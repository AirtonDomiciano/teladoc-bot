"""Validação da resposta estruturada do agente."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from teladoc_bot.sections import REQUIRED_HEADINGS, RESPONSE_FIELDS
from teladoc_bot.textutil import canonical_text, normalize

_CODE_SUFFIXES = {".ts", ".html", ".tsx", ".js"}
_SKIP_VALUES = {
    "",
    "-",
    "nao",
    "nao confirmado",
    "nao confirmada",
    "nao se aplica",
    "n/a",
    "na",
    "nenhum",
    "nenhuma",
}
_APP_SELECTOR = re.compile(r"\bapp-[a-z0-9-]+\b", re.IGNORECASE)


@dataclass
class Analysis:
    publishable: bool
    outcome: str
    reasons: list[str] = field(default_factory=list)
    screen_name: str = ""
    documentation_markdown: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    files_consulted: list[str] = field(default_factory=list)
    evidence_notes: str = ""


def parse_json_object(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("A resposta do agente está vazia.")
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"A resposta do agente não é JSON válido: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("A resposta do agente não é um objeto JSON.")
    return payload


def validate_analysis(payload: dict, workspace: Path) -> Analysis:
    missing = [name for name in RESPONSE_FIELDS if name not in payload]
    if missing:
        return Analysis(False, "pendente", [f"Resposta sem os campos: {', '.join(missing)}"])
    status = payload.get("status")
    if status not in {"ready", "pending", "needs_review"}:
        return Analysis(False, "pendente", ["O status da resposta não é ready, pending ou needs_review."])
    documentation = _string(payload.get("documentation_markdown"))
    criteria = _string_list(payload.get("acceptance_criteria"))
    files = _string_list(payload.get("files_consulted"))
    pending_reason = _string(payload.get("pending_reason"))
    review_reason = _string(payload.get("needs_review_reason"))
    evidence = _string(payload.get("evidence_notes"))
    screen_name = _string(payload.get("screen_name"))
    base = Analysis(
        publishable=False,
        outcome="pendente",
        screen_name=screen_name,
        documentation_markdown=documentation,
        acceptance_criteria=criteria,
        files_consulted=files,
        evidence_notes=evidence,
    )
    if status == "pending":
        base.reasons = [pending_reason or "O agente marcou pending sem explicar o motivo."]
        return base
    if status == "needs_review":
        base.outcome = "revisao"
        base.reasons = [review_reason or "O agente marcou needs_review sem explicar o motivo."]
        return base
    reasons = _ready_reasons(
        documentation=documentation,
        criteria=criteria,
        files=files,
        pending_reason=pending_reason,
        review_reason=review_reason,
        evidence=evidence,
        screen_name=screen_name,
        workspace=workspace,
    )
    if reasons:
        base.reasons = reasons
        return base
    base.publishable = True
    base.outcome = "ready"
    return base


def _ready_reasons(
    *,
    documentation: str,
    criteria: list[str],
    files: list[str],
    pending_reason: str,
    review_reason: str,
    evidence: str,
    screen_name: str,
    workspace: Path,
) -> list[str]:
    reasons: list[str] = []
    if not screen_name:
        reasons.append("screen_name vazio.")
    if pending_reason:
        reasons.append("status ready com pending_reason preenchido.")
    if review_reason:
        reasons.append("status ready com needs_review_reason preenchido.")
    if not evidence:
        reasons.append("evidence_notes vazio.")
    for heading in REQUIRED_HEADINGS:
        if heading not in documentation:
            reasons.append(f"Seção ausente: {heading}")
    if "tableId" not in documentation or "uniqueIdField" not in documentation:
        reasons.append("A documentação não informa tableId e uniqueIdField.")
    if "fields.ts" not in documentation:
        reasons.append("A documentação não aborda .fields.ts.")
    if "FormlyModule.forRoot" not in documentation:
        reasons.append("A documentação não registra o cuidado com FormlyModule.forRoot.")
    if not criteria:
        reasons.append("Nenhum critério de aceite foi informado.")
    document_compare = canonical_text(documentation)
    for criterion in criteria:
        if not criterion.strip():
            reasons.append("Critério de aceite vazio.")
            continue
        if canonical_text(criterion) not in document_compare:
            reasons.append(f"Critério ausente na documentação: {criterion}")
    resolved, path_errors = _resolve_files(files, workspace)
    reasons.extend(path_errors)
    if resolved and not any(path.suffix.lower() in _CODE_SUFFIXES for path in resolved):
        reasons.append("Nenhum arquivo .ts, .html, .tsx ou .js foi confirmado.")
    corpus = _read_corpus(resolved)
    relative_paths = []
    for path in resolved:
        relative = path.relative_to(workspace.resolve()).as_posix()
        relative_paths.append(relative)
        if relative not in documentation and str(path) not in documentation:
            reasons.append(f"Caminho consultado ausente na documentação: {relative}")
    reasons.extend(_key_reasons(documentation, corpus))
    reasons.extend(_selector_reasons(documentation, corpus))
    reasons.extend(_unique_id_reasons(documentation, corpus))
    return reasons


def _resolve_files(files: list[str], workspace: Path) -> tuple[list[Path], list[str]]:
    root = workspace.resolve()
    resolved: list[Path] = []
    errors: list[str] = []
    if not files:
        return [], ["files_consulted vazio."]
    for raw in files:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            candidate = candidate.resolve()
            candidate.relative_to(root)
        except (ValueError, OSError):
            errors.append(f"Caminho fora do clone: {raw}")
            continue
        if candidate == root or not candidate.exists():
            errors.append(f"Caminho inexistente no clone: {raw}")
            continue
        if not candidate.is_file():
            errors.append(f"Caminho não é um arquivo do clone: {raw}")
            continue
        resolved.append(candidate)
    return resolved, errors


def _read_corpus(paths: list[Path]) -> str:
    chunks: list[str] = []
    for path in paths:
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def _markdown_tables(markdown: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if cells and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
                continue
            current.append(cells)
            continue
        if current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    return tables


def _key_reasons(documentation: str, corpus: str) -> list[str]:
    keys: list[str] = []
    found_column = False
    for table in _markdown_tables(documentation):
        if not table:
            continue
        headers = [normalize(cell) for cell in table[0]]
        indexes = [index for index, header in enumerate(headers) if header in {"key", "chave"}]
        if not indexes:
            continue
        found_column = True
        for row in table[1:]:
            for index in indexes:
                if index >= len(row):
                    continue
                cell = _clean_cell(row[index])
                if normalize(cell) in _SKIP_VALUES:
                    continue
                if any(char.isspace() for char in cell):
                    return [f"Key com texto livre, que não pode ser confirmada: {cell}"]
                keys.append(cell)
    if not found_column:
        return ["A documentação não tem uma tabela com a coluna Key."]
    if not keys:
        return ["Nenhuma key real foi informada na tabela de campos."]
    return [f"Key não encontrada nos arquivos consultados: {key}" for key in keys if not _token_in_corpus(key, corpus)]


def _unique_id_reasons(documentation: str, corpus: str) -> list[str]:
    reasons = []
    pattern = re.compile(r"uniqueIdField\s*[:=]\s*`?([A-Za-z_][A-Za-z0-9_.]*)`?")
    for match in pattern.finditer(documentation):
        token = match.group(1)
        if not _token_in_corpus(token, corpus):
            reasons.append(f"uniqueIdField não encontrado nos arquivos consultados: {token}")
    return reasons


def _selector_reasons(documentation: str, corpus: str) -> list[str]:
    missing = []
    seen = set()
    for selector in _APP_SELECTOR.findall(documentation):
        if selector in seen:
            continue
        seen.add(selector)
        if not _token_in_corpus(selector, corpus):
            missing.append(f"Seletor não encontrado nos arquivos consultados: {selector}")
    return missing


def _token_in_corpus(token: str, corpus: str) -> bool:
    pattern = re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(token)}(?![A-Za-z0-9_-])")
    return pattern.search(corpus) is not None


def _clean_cell(value: str) -> str:
    return value.replace("`", "").replace("**", "").strip()


def _string(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        return ""
    return value


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str)]
