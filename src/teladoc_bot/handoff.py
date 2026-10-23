"""Coleta, importação, conferência e publicação sem chamada de IA."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from teladoc_bot.azure import AzureDevOpsClient, AzureError
from teladoc_bot.config import Config
from teladoc_bot.evidence import index_sources, render_evidence
from teladoc_bot.prompting import PromptError, build_prompt, read_base_prompt
from teladoc_bot.runner import _allocate_run_dir, _publish, _write_json
from teladoc_bot.spreadsheet import SheetRow, load_rows
from teladoc_bot.textutil import normalize, slugify
from teladoc_bot.validation import Analysis, validate_analysis

_SECRET_NAMES = {
    "AZURE_DEVOPS_PAT",
    "AZURE_DEVOPS_EXT_PAT",
    "AZURE_DEVOPS_TOKEN",
    "AZURE_PAT",
    "ADO_PAT",
}
_SECRET_PARTS = ("PAT", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "API_KEY")
_NAME_ID = re.compile(r"(?:^|-)(\d+)$")


@dataclass(frozen=True)
class ScreenRecord:
    work_item_id: int
    excel_row: int
    screen_name: str
    organization: str
    project: str
    source: str

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.organization.casefold(), self.project.casefold(), self.work_item_id)


@dataclass
class HandoffItem:
    excel_row: int
    screen_name: str
    work_item_id: int | None
    outcome: str
    reason: str
    marked: bool = False


def collect_screens(
    config: Config,
    azure: AzureDevOpsClient,
    *,
    limit: int | None,
    only_id: int | None,
    log=print,
) -> tuple[Path, int]:
    """Exporta o pacote Markdown das telas elegíveis. Não chama IA nem publica."""
    _require_clone(config)
    base_prompt, prompt_version = read_base_prompt(config.prompt_path)
    rows = load_rows(config.spreadsheet_path, config.sheet, config.header_row, config.columns)
    sources = index_sources(config.retaguarda_path)
    run_dir = _allocate_run_dir(config.output_dir)
    package = run_dir / "pacote"
    package.mkdir(parents=True)
    results: list[HandoffItem] = []
    screens: list[ScreenRecord] = []
    seen: set[tuple[str, str, int]] = set()
    exported = 0
    for row in rows:
        if row.skip_reason:
            results.append(_item(row, None, "ignorada", row.skip_reason))
            continue
        assert row.work_item is not None
        if only_id is not None and row.work_item.id != only_id:
            continue
        if row.work_item.key in seen:
            results.append(_item(row, row.work_item.id, "ignorada", "work item já exportado neste pacote"))
            continue
        if limit is not None and exported >= limit:
            results.append(_item(row, row.work_item.id, "ignorada", "limite da coleta atingido"))
            continue
        seen.add(row.work_item.key)
        try:
            work_item = azure.get_work_item(row.work_item)
            comments = azure.get_comments(row.work_item)
        except AzureError as exc:
            results.append(_item(row, row.work_item.id, "pendente", f"Falha ao ler a US. {_public(exc)}"))
            continue
        filename = _screen_filename(package, row.work_item.id)
        document = _screen_document(
            build_prompt(base_prompt, prompt_version, row, work_item, comments, config.retaguarda_path),
            row.work_item.id,
        )
        document = document.rstrip() + "\n\n" + render_evidence(config.retaguarda_path, row.screen_name, sources)
        _write_text(package / filename, document)
        screens.append(
            ScreenRecord(
                work_item.id,
                row.excel_row,
                row.screen_name,
                row.work_item.organization,
                row.work_item.project,
                filename,
            )
        )
        exported += 1
        results.append(_item(row, row.work_item.id, "exportada", filename))
    _write_json(
        package / "pacote.json",
        {
            "prompt_version": prompt_version,
            "screens": [
                {
                    "work_item_id": screen.work_item_id,
                    "excel_row": screen.excel_row,
                    "screen_name": screen.screen_name,
                    "organization": screen.organization,
                    "project": screen.project,
                    "source": screen.source,
                }
                for screen in screens
            ],
        },
    )
    _write_text(package / "indice.md", _index(screens, prompt_version))
    _write_summary(run_dir, results)
    log(f"Pacote: {package}")
    for result in results:
        log(_format(result))
    return package, _exit_code(results)


def import_screens(config: Config, package: Path, source: Path, log=print) -> int:
    """Valida o conteúdo elaborado e grava a conferência local, sem publicar."""
    _require_clone(config)
    records = _load_package(package)
    responses = _load_responses(source)
    results = [_assess(config, record, responses) for record in records]
    _store_assessments(package, results)
    _write_summary(package, results, "importacao.txt")
    for result in results:
        log(_format(result))
    return _exit_code(results)


def review_screens(config: Config, package: Path, log=print) -> int:
    """Mostra a conferência já importada, sem ler o Azure para gravar e sem alterar a planilha."""
    _require_clone(config)
    records = _load_package(package)
    stored = _stored_responses(package)
    results: list[HandoffItem] = []
    for record in records:
        item = _assess(config, record, stored)
        if item.outcome == "ausente":
            saved = _saved_outcome(package, record.work_item_id)
            if saved is not None and saved.outcome != "pronta":
                item = saved
        error, info = _binding_note(config, record)
        if error and item.outcome == "pronta":
            item.outcome = "id_divergente"
            item.reason = error
        elif info and item.outcome == "pronta":
            item.reason = f"{item.reason} {info}".strip()
        results.append(item)
    for result in results:
        log(_format(result))
    log("Nenhuma US foi publicada e a planilha não foi alterada.")
    return _exit_code(results)


def publish_screens(config: Config, package: Path, azure: AzureDevOpsClient, log=print) -> int:
    """Publica somente telas aprovadas e marca SIM depois da confirmação no Azure."""
    _require_clone(config)
    records = _load_package(package)
    stored = _stored_responses(package)
    rows = load_rows(config.spreadsheet_path, config.sheet, config.header_row, config.columns)
    results: list[HandoffItem] = []
    for record in records:
        item = _assess(config, record, stored)
        if item.outcome == "ausente":
            saved = _saved_outcome(package, record.work_item_id)
            if saved is not None and saved.outcome != "pronta":
                item = saved
        if item.outcome != "pronta":
            results.append(item)
            log(_format(item))
            continue
        located = _locate(rows, record)
        if isinstance(located, str):
            blocked = _item_record(record, "id_divergente", located)
            results.append(blocked)
            log(_format(blocked))
            continue
        if located.skip_reason:
            blocked = _item(located, record.work_item_id, "pendente", f"A linha não pode ser marcada. {located.skip_reason}")
            results.append(blocked)
            log(_format(blocked))
            continue
        assert item.analysis is not None
        folder = package / "publicacao" / f"us-{record.work_item_id}"
        published = _publish(config, folder, located, azure, item.analysis)
        outcome = HandoffItem(
            published.excel_row,
            published.screen_name,
            published.work_item_id,
            published.outcome,
            _public(published.reason),
            published.marked,
        )
        results.append(outcome)
        log(_format(outcome))
    _write_summary(package, results, "publicacao.txt")
    return _exit_code(results)


@dataclass
class _Assessment(HandoffItem):
    analysis: Analysis | None = None
    payload: dict | None = None


def _assess(config: Config, record: ScreenRecord, responses: dict[int, dict]) -> _Assessment:
    payload = responses.get(record.work_item_id)
    if payload is None:
        return _Assessment(record.excel_row, record.screen_name, record.work_item_id, "ausente", "Conteúdo pronto não encontrado para esta US.", analysis=None)
    if payload.get("_conflict"):
        return _Assessment(
            record.excel_row,
            record.screen_name,
            record.work_item_id,
            "id_divergente",
            "O conteúdo desta US está ausente, ambíguo ou associado a outro work item e não será publicado.",
            analysis=None,
        )
    payload = _redact_payload(payload)
    found_id = _payload_id(payload)
    if found_id is None:
        return _Assessment(
            record.excel_row,
            record.screen_name,
            record.work_item_id,
            "id_divergente",
            "O conteúdo não informa o work_item_id desta US e não será publicado.",
            analysis=None,
            payload=payload,
        )
    if found_id != record.work_item_id:
        return _Assessment(
            record.excel_row,
            record.screen_name,
            record.work_item_id,
            "id_divergente",
            "O conteúdo está associado a outro work item e não será publicado.",
            analysis=None,
        )
    if normalize(str(payload.get("screen_name") or "")) != normalize(record.screen_name):
        return _Assessment(
            record.excel_row,
            record.screen_name,
            record.work_item_id,
            "id_divergente",
            "O nome da tela no conteúdo não confere com a tela do pacote.",
            analysis=None,
            payload=payload,
        )
    analysis = validate_analysis(payload, config.retaguarda_path)
    if not analysis.publishable:
        outcome = "revisao" if analysis.outcome == "revisao" else "invalida"
        reason = " ".join(analysis.reasons) or "O conteúdo não passou na validação."
        return _Assessment(record.excel_row, record.screen_name, record.work_item_id, outcome, reason, analysis=analysis, payload=payload)
    return _Assessment(
        record.excel_row,
        record.screen_name,
        record.work_item_id,
        "pronta",
        "Validação aprovada. Ainda não publicada.",
        analysis=analysis,
        payload=payload,
    )


def _store_assessments(package: Path, results: list[_Assessment]) -> None:
    destination = package / "respostas"
    destination.mkdir(parents=True, exist_ok=True)
    for item in results:
        if item.work_item_id is None:
            continue
        stored = destination / f"us-{item.work_item_id}.json"
        preview = destination / f"us-{item.work_item_id}.documentacao.md"
        if item.payload is not None and not item.payload.get("_conflict"):
            _write_json(stored, item.payload)
        elif stored.exists():
            stored.unlink()
        if item.analysis is not None and item.analysis.documentation_markdown:
            _write_text(preview, item.analysis.documentation_markdown)
        elif preview.exists():
            preview.unlink()
        _write_json(
            destination / f"us-{item.work_item_id}.validacao.json",
            {
                "work_item_id": item.work_item_id,
                "excel_row": item.excel_row,
                "screen_name": item.screen_name,
                "outcome": item.outcome,
                "publishable": item.outcome == "pronta",
                "reason": item.reason,
            },
        )


def _stored_responses(package: Path) -> dict[int, dict]:
    directory = package / "respostas"
    found: dict[int, dict] = {}
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("us-*.json")):
        if path.name.endswith(".validacao.json"):
            continue
        work_item_id = _filename_id(path)
        if work_item_id is None:
            continue
        try:
            payload = _read_payload(path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            found[work_item_id] = {"work_item_id": work_item_id, "_conflict": True}
            continue
        if not isinstance(payload, dict):
            found[work_item_id] = {"work_item_id": work_item_id, "_conflict": True}
            continue
        found[work_item_id] = payload
    return found


def _saved_outcome(package: Path, work_item_id: int) -> HandoffItem | None:
    path = package / "respostas" / f"us-{work_item_id}.validacao.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    return HandoffItem(
        int(raw.get("excel_row") or 0),
        str(raw.get("screen_name") or ""),
        work_item_id,
        str(raw.get("outcome") or "ausente"),
        str(raw.get("reason") or "Conteúdo pronto não encontrado para esta US."),
    )


def _load_responses(source: Path) -> dict[int, dict]:
    if not source.is_dir():
        raise PromptError(f"Diretório de respostas não encontrado: {source}")
    found: dict[int, dict] = {}
    blocked: set[int] = set()
    for path in sorted(source.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".json", ".md"}:
            continue
        if path.name in {"pacote.json", "indice.md"} or path.name.endswith(".validacao.json"):
            continue
        try:
            payload = _read_payload(path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            continue
        if not isinstance(payload, dict) or "documentation_markdown" not in payload and "status" not in payload:
            continue
        filename_id = _filename_id(path)
        payload_id = _payload_id(payload)
        if filename_id is not None and payload_id is not None and filename_id != payload_id:
            blocked.add(filename_id)
            found.pop(filename_id, None)
            continue
        work_item_id = filename_id if filename_id is not None else payload_id
        if work_item_id is None:
            continue
        if work_item_id in found or work_item_id in blocked:
            blocked.add(work_item_id)
            found.pop(work_item_id, None)
            continue
        found[work_item_id] = payload
    for work_item_id in blocked:
        found[work_item_id] = {"work_item_id": work_item_id, "_conflict": True}
    return found


def _read_payload(path: Path) -> dict:
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            raise
        payload, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(payload, dict):
        raise ValueError("A resposta não é um objeto JSON.")
    return payload


def _load_package(package: Path) -> list[ScreenRecord]:
    path = package / "pacote.json"
    if not path.is_file():
        raise PromptError(f"Pacote não encontrado: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PromptError(f"pacote.json inválido: {exc}") from exc
    screens = raw.get("screens") if isinstance(raw, dict) else None
    if not isinstance(screens, list):
        raise PromptError("pacote.json não contém a lista de telas.")
    records: list[ScreenRecord] = []
    for item in screens:
        if not isinstance(item, dict):
            raise PromptError("Uma entrada do pacote não é um objeto.")
        work_item_id = _payload_id(item)
        excel_row = item.get("excel_row")
        screen_name = str(item.get("screen_name") or "").strip()
        organization = str(item.get("organization") or "").strip()
        project = str(item.get("project") or "").strip()
        source = str(item.get("source") or "").strip()
        if work_item_id is None or not isinstance(excel_row, int) or excel_row <= 0 or not screen_name or not organization or not project:
            raise PromptError("Uma entrada do pacote está sem identificação da tela, da linha ou do work item.")
        records.append(ScreenRecord(work_item_id, excel_row, screen_name, organization, project, source))
    return records


def _locate(rows: list[SheetRow], record: ScreenRecord) -> SheetRow | str:
    matches = [row for row in rows if row.work_item is not None and row.work_item.key == record.key]
    if len(matches) != 1:
        return "A coluna D não tem exatamente uma linha para este work item. A tela não foi publicada."
    row = matches[0]
    if normalize(row.screen_name) != normalize(record.screen_name):
        return "A linha localizada pelo ID não é a tela deste pacote. A tela não foi publicada."
    return row


def _binding_note(config: Config, record: ScreenRecord) -> tuple[str, str]:
    try:
        rows = load_rows(config.spreadsheet_path, config.sheet, config.header_row, config.columns)
    except Exception as exc:
        return f"Não foi possível reler a planilha. {_public(exc)}", ""
    located = _locate(rows, record)
    if isinstance(located, str):
        return located, ""
    if located.excel_row != record.excel_row:
        return "", f"A US está na linha {located.excel_row} da planilha."
    return "", ""


def _screen_document(prompt: str, work_item_id: int) -> str:
    extra = (
        "\n\n## Resposta esperada\n"
        "Elabore a documentação fora deste bot e devolva um único objeto JSON.\n"
        f'Inclua `"work_item_id": {work_item_id}`.\n'
        "O `screen_name` deve ser o nome da tela deste arquivo.\n"
        "Não inclua credenciais, PAT, tokens ou segredos.\n"
    )
    return _public(prompt.strip() + extra)


def _index(screens: list[ScreenRecord], prompt_version: str) -> str:
    lines = [
        "# Pacote de coleta",
        "",
        f"Versão do prompt: {prompt_version}",
        "",
        "Este pacote reúne identificação, fontes e contexto de cada tela.",
        "A elaboração é feita fora do bot. Este arquivo não contém credenciais.",
        "",
        "| US | Linha | Tela | Arquivo |",
        "| --- | --- | --- | --- |",
    ]
    if not screens:
        lines.append("| — | — | nenhuma tela exportada | — |")
    for screen in screens:
        lines.append(
            f"| {screen.work_item_id} | {screen.excel_row} | {screen.screen_name} | {screen.source} |"
        )
    return "\n".join(lines) + "\n"


def _screen_filename(package: Path, work_item_id: int) -> str:
    filename = f"us-{work_item_id}.md"
    if (package / filename).exists():
        filename = f"us-{work_item_id}-{slugify(str(work_item_id))}.md"
    return filename


def _payload_id(payload: dict) -> int | None:
    value = payload.get("work_item_id")
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
        return number if number > 0 else None
    return None


def _filename_id(path: Path) -> int | None:
    match = _NAME_ID.search(path.stem)
    if match is None:
        return None
    number = int(match.group(1))
    return number if number > 0 else None


def _require_clone(config: Config) -> None:
    if not config.retaguarda_path.is_dir():
        raise PromptError(f"Clone do RetaguardaWeb não encontrado: {config.retaguarda_path}")


def _secret_values() -> list[str]:
    values: list[str] = []
    for name, raw in os.environ.items():
        upper = name.upper()
        if upper not in _SECRET_NAMES and not any(part in upper for part in _SECRET_PARTS):
            continue
        value = raw.strip()
        if len(value) >= 12:
            values.append(value)
    values.sort(key=len, reverse=True)
    return values


def _public(value: object) -> str:
    text = str(value)
    for secret in _secret_values():
        text = text.replace(secret, "[redigido]")
    text = re.sub(r"(?i)(authorization:\s*basic\s+)\S+", r"\1[redigido]", text)
    text = re.sub(r"(?i)(bearer\s+)\S+", r"\1[redigido]", text)
    return text


def _redact_payload(value: object) -> object:
    if isinstance(value, str):
        return _public(value)
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _redact_payload(item) for key, item in value.items()}
    return value


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = _public(text)
    if not cleaned.endswith("\n"):
        cleaned += "\n"
    path.write_text(cleaned, encoding="utf-8")
    written = path.read_text(encoding="utf-8")
    for secret in _secret_values():
        if secret in written:
            path.unlink(missing_ok=True)
            raise PromptError(f"O arquivo {path.name} conteria uma credencial e não foi gravado.")


def _write_summary(directory: Path, results: list[HandoffItem], name: str = "resumo.txt") -> None:
    lines = [_format(item) for item in results]
    _write_text(directory / name, "\n".join(lines) + ("\n" if lines else ""))


def _item(row: SheetRow, work_item_id: int | None, outcome: str, reason: str) -> HandoffItem:
    return HandoffItem(row.excel_row, row.screen_name, work_item_id, outcome, _public(reason))


def _item_record(record: ScreenRecord, outcome: str, reason: str) -> HandoffItem:
    return HandoffItem(record.excel_row, record.screen_name, record.work_item_id, outcome, _public(reason))


def _format(result: HandoffItem) -> str:
    name = result.screen_name or "(sem nome)"
    work_item = "" if result.work_item_id is None else f" | US {result.work_item_id}"
    return f"linha {result.excel_row} | {name}{work_item} | {result.outcome} | {result.reason}"


def _exit_code(results: list[HandoffItem]) -> int:
    for item in results:
        if item.outcome in {"exportada", "pronta", "ignorada"}:
            continue
        if item.outcome == "publicada" and item.marked:
            continue
        return 2
    return 0
