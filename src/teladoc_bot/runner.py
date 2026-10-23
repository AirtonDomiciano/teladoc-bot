"""Loop sequencial: uma tela, um prompt, uma sessão."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from teladoc_bot.azure import AzureDevOpsClient, AzureError, Comment, WorkItem
from teladoc_bot.codex import CodexExecutor, CodexUnavailable
from teladoc_bot.config import Config
from teladoc_bot.htmlutil import acceptance_criteria_html, markdown_to_html
from teladoc_bot.prompting import PromptError, build_prompt, read_base_prompt
from teladoc_bot.spreadsheet import SheetRow, load_rows, mark_documented
from teladoc_bot.textutil import canonical_text, slugify
from teladoc_bot.validation import Analysis, parse_json_object, validate_analysis

_INCOMPLETE = {"pendente", "revisao", "falha_confirmacao", "falha_planilha"}


@dataclass
class ItemResult:
    excel_row: int
    screen_name: str
    work_item_id: int | None
    outcome: str
    reason: str
    marked: bool
    artifact_dir: str | None = None


@dataclass
class RunReport:
    run_dir: Path
    results: list[ItemResult]
    exit_code: int
    codex_version: str


def execute(
    config: Config,
    *,
    executor: CodexExecutor,
    azure: AzureDevOpsClient | None,
    publish: bool,
    limit: int | None,
    only_id: int | None,
    log=print,
) -> RunReport:
    if not config.retaguarda_path.is_dir():
        raise PromptError(f"Clone do RetaguardaWeb não encontrado: {config.retaguarda_path}")
    base_prompt, prompt_version = read_base_prompt(config.prompt_path)
    _require_schema(config.schema_path)
    version = executor.ensure_available()
    rows = load_rows(config.spreadsheet_path, config.sheet, config.header_row, config.columns)
    if publish and azure is None:
        raise PromptError("A publicação foi habilitada sem um cliente do Azure DevOps.")
    if any(row.skip_reason is None for row in rows) and azure is None:
        raise PromptError("A consulta da US precisa do cliente do Azure DevOps.")
    run_dir = _allocate_run_dir(config.output_dir)
    results: list[ItemResult] = []
    seen: set[tuple[str, str, int]] = set()
    processed = 0
    log(f"Execução em {run_dir}")
    log(f"Codex CLI: {version}")
    log("Publicação habilitada." if publish else "Publicação desabilitada. A planilha só muda depois de uma confirmação no Azure.")
    try:
        for row in rows:
            if row.skip_reason:
                result = _ignored(row)
                results.append(result)
                log(_format(result))
                continue
            assert row.work_item is not None
            if only_id is not None and row.work_item.id != only_id:
                continue
            if row.work_item.key in seen:
                result = ItemResult(
                    row.excel_row,
                    row.screen_name,
                    row.work_item.id,
                    "ignorada",
                    "work item já processado nesta execução",
                    False,
                )
                results.append(result)
                log(_format(result))
                continue
            if limit is not None and processed >= limit:
                result = ItemResult(
                    row.excel_row,
                    row.screen_name,
                    row.work_item.id,
                    "ignorada",
                    "limite da execução atingido",
                    False,
                )
                results.append(result)
                log(_format(result))
                continue
            seen.add(row.work_item.key)
            processed += 1
            try:
                result = _process_row(
                    config,
                    row=row,
                    run_dir=run_dir,
                    executor=executor,
                    azure=azure,
                    publish=publish,
                    base_prompt=base_prompt,
                    prompt_version=prompt_version,
                )
            except CodexUnavailable as exc:
                result = ItemResult(row.excel_row, row.screen_name, row.work_item.id, "pendente", str(exc), False)
                results.append(result)
                log(_format(result))
                raise
            except Exception as exc:
                result = ItemResult(row.excel_row, row.screen_name, row.work_item.id, "pendente", str(exc), False)
            results.append(result)
            log(_format(result))
    finally:
        exit_code = 2 if any(item.outcome in _INCOMPLETE for item in results) else 0
        _write_json(
            run_dir / "resumo.json",
            {
                "codex_version": version,
                "prompt_version": prompt_version,
                "publish": publish,
                "exit_code": exit_code,
                "results": [asdict(item) for item in results],
            },
        )
        (run_dir / "resumo.txt").write_text(
            "\n".join(_format(item) for item in results) + ("\n" if results else ""),
            encoding="utf-8",
        )
    return RunReport(run_dir=run_dir, results=results, exit_code=exit_code, codex_version=version)


def _process_row(
    config: Config,
    *,
    row: SheetRow,
    run_dir: Path,
    executor: CodexExecutor,
    azure: AzureDevOpsClient | None,
    publish: bool,
    base_prompt: str,
    prompt_version: str,
) -> ItemResult:
    assert row.work_item is not None and azure is not None
    folder = run_dir / f"linha-{row.excel_row:04d}-wi-{row.work_item.id}-{slugify(row.screen_name)}"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        work_item = azure.get_work_item(row.work_item)
        comments = azure.get_comments(row.work_item)
    except AzureError as exc:
        return _finish(folder, row, "pendente", str(exc), False)
    prompt = build_prompt(base_prompt, prompt_version, row, work_item, comments, config.retaguarda_path)
    (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
    _write_json(folder / "work_item.json", _work_item_payload(work_item, comments))
    execution = executor.run(
        prompt=prompt,
        workspace=config.retaguarda_path,
        schema_path=config.schema_path,
        artifact_dir=folder,
    )
    _write_json(
        folder / "codex.resultado.json",
        {
            "returncode": execution.returncode,
            "error": execution.error,
            "command": execution.command,
        },
    )
    if execution.error:
        return _finish(folder, row, "pendente", execution.error, False)
    try:
        payload = parse_json_object(execution.last_message)
    except ValueError as exc:
        (folder / "resposta.bruta.txt").write_text(execution.last_message, encoding="utf-8")
        return _finish(folder, row, "pendente", str(exc), False)
    _write_json(folder / "resposta.json", payload)
    analysis = validate_analysis(payload, config.retaguarda_path)
    _write_analysis(folder, analysis)
    if not analysis.publishable:
        outcome = "revisao" if analysis.outcome == "revisao" else "pendente"
        return _finish(folder, row, outcome, " ".join(analysis.reasons), False)
    if not publish:
        return _finish(
            folder,
            row,
            "documentada_local",
            "Documentação salva localmente. Publicação desabilitada, então a planilha permanece Não.",
            False,
        )
    return _publish(config, folder, row, azure, analysis)


def _publish(
    config: Config,
    folder: Path,
    row: SheetRow,
    azure: AzureDevOpsClient,
    analysis: Analysis,
) -> ItemResult:
    assert row.work_item is not None
    description_html = markdown_to_html(analysis.documentation_markdown)
    acceptance_html = acceptance_criteria_html(analysis.acceptance_criteria)
    (folder / "documentacao.html").write_text(description_html, encoding="utf-8")
    (folder / "criterios.html").write_text(acceptance_html, encoding="utf-8")
    try:
        azure.update_documentation(row.work_item, description_html, acceptance_html)
    except AzureError as exc:
        return _finish(folder, row, "pendente", f"Falha ao atualizar a US. A planilha não foi alterada. {exc}", False)
    try:
        remote = azure.get_work_item(row.work_item)
    except AzureError as exc:
        return _finish(
            folder,
            row,
            "falha_confirmacao",
            f"A atualização foi enviada, mas a releitura da US falhou. A planilha não foi alterada. {exc}",
            False,
        )
    description_ok = canonical_text(description_html) == canonical_text(remote.description_html)
    acceptance_ok = canonical_text(acceptance_html) == canonical_text(remote.acceptance_html)
    _write_json(
        folder / "confirmacao.json",
        {
            "description_ok": description_ok,
            "acceptance_ok": acceptance_ok,
            "sent_description": canonical_text(description_html),
            "remote_description": canonical_text(remote.description_html),
            "sent_acceptance": canonical_text(acceptance_html),
            "remote_acceptance": canonical_text(remote.acceptance_html),
        },
    )
    if not description_ok or not acceptance_ok:
        return _finish(
            folder,
            row,
            "falha_confirmacao",
            "A US foi atualizada, mas o conteúdo relido difere do enviado. Documentação permanece Não.",
            False,
        )
    try:
        mark_documented(
            config.spreadsheet_path,
            config.sheet,
            config.header_row,
            config.columns,
            row.excel_row,
            row.work_item,
        )
    except Exception as exc:
        return _finish(
            folder,
            row,
            "falha_planilha",
            f"A US foi confirmada, mas a planilha não foi marcada como Sim. {exc}",
            False,
        )
    return _finish(folder, row, "publicada", "Descrição, critérios de aceite e planilha confirmados.", True)


def _write_analysis(folder: Path, analysis: Analysis) -> None:
    _write_json(
        folder / "validacao.json",
        {
            "publishable": analysis.publishable,
            "outcome": analysis.outcome,
            "reasons": analysis.reasons,
            "files_consulted": analysis.files_consulted,
            "evidence_notes": analysis.evidence_notes,
        },
    )
    if analysis.documentation_markdown:
        (folder / "documentacao.md").write_text(analysis.documentation_markdown, encoding="utf-8")
    if analysis.acceptance_criteria:
        lines = "\n".join(f"- {item}" for item in analysis.acceptance_criteria)
        (folder / "criterios.md").write_text(lines + "\n", encoding="utf-8")


def _finish(folder: Path, row: SheetRow, outcome: str, reason: str, marked: bool) -> ItemResult:
    result = ItemResult(
        excel_row=row.excel_row,
        screen_name=row.screen_name,
        work_item_id=None if row.work_item is None else row.work_item.id,
        outcome=outcome,
        reason=reason,
        marked=marked,
        artifact_dir=str(folder),
    )
    _write_json(folder / "resultado.json", asdict(result))
    return result


def _ignored(row: SheetRow) -> ItemResult:
    return ItemResult(
        excel_row=row.excel_row,
        screen_name=row.screen_name,
        work_item_id=None if row.work_item is None else row.work_item.id,
        outcome="ignorada",
        reason=row.skip_reason or "ignorada",
        marked=False,
    )


def _format(result: ItemResult) -> str:
    name = result.screen_name or "(sem nome)"
    work_item = "" if result.work_item_id is None else f" | US {result.work_item_id}"
    return f"linha {result.excel_row} | {name}{work_item} | {result.outcome} | {result.reason}"


def _work_item_payload(work_item: WorkItem, comments: list[Comment]) -> dict:
    return {
        "id": work_item.id,
        "title": work_item.title,
        "work_item_type": work_item.work_item_type,
        "state": work_item.state,
        "description_html": work_item.description_html,
        "acceptance_html": work_item.acceptance_html,
        "url": work_item.url,
        "relations": [asdict(item) for item in work_item.relations],
        "comments": [asdict(item) for item in comments],
    }


def _require_schema(path: Path) -> None:
    if not path.is_file():
        raise PromptError(f"Schema da resposta não encontrado: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PromptError(f"Schema da resposta não é JSON válido: {exc}") from exc
    required = payload.get("required") if isinstance(payload, dict) else None
    expected = {
        "status",
        "screen_name",
        "documentation_markdown",
        "acceptance_criteria",
        "files_consulted",
        "pending_reason",
        "needs_review_reason",
        "evidence_notes",
    }
    if not isinstance(required, list) or not expected.issubset(required):
        raise PromptError("O schema da resposta não exige o contrato completo do agente.")


def _allocate_run_dir(output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    candidate = output / stamp
    suffix = 2
    while candidate.exists():
        candidate = output / f"{stamp}-{suffix}"
        suffix += 1
    candidate.mkdir()
    return candidate


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require_pat(config: Config) -> str:
    import os

    names: list[str] = []
    for name in (config.pat_env, "AZURE_DEVOPS_PAT", "AZURE_PAT"):
        if name not in names:
            names.append(name)
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    raise PromptError(
        "Defina " + " ou ".join(names) + " com um PAT do Azure DevOps. Nenhuma análise foi executada."
    )


def azure_from_config(config: Config) -> AzureDevOpsClient:
    return AzureDevOpsClient(
        require_pat(config),
        api_version=config.api_version,
        comments_api_version=config.comments_api_version,
        description_field=config.description_field,
        acceptance_field=config.acceptance_field,
        timeout_seconds=config.azure_timeout_seconds,
    )
