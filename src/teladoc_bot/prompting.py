"""Monta o prompt exclusivo de cada tela."""

from __future__ import annotations

import re
from pathlib import Path

from teladoc_bot.azure import Comment, WorkItem
from teladoc_bot.spreadsheet import SheetRow
from teladoc_bot.textutil import extract_hrefs, strip_html

_VERSION = re.compile(r"teladoc-prompt-version:\s*([A-Za-z0-9._-]+)")
_MAX_COMMENTS = 100
_MAX_COMMENT_CHARS = 8000


class PromptError(ValueError):
    """Prompt base ausente ou sem versão."""


def read_base_prompt(path: Path) -> tuple[str, str]:
    if not path.is_file():
        raise PromptError(f"Prompt base não encontrado: {path}")
    text = path.read_text(encoding="utf-8")
    match = _VERSION.search(text)
    if match is None:
        raise PromptError("O prompt base não contém teladoc-prompt-version.")
    return text.strip(), match.group(1)


def build_prompt(
    base_prompt: str,
    prompt_version: str,
    row: SheetRow,
    work_item: WorkItem,
    comments: list[Comment],
    retaguarda_path: Path,
) -> str:
    if row.work_item is None:
        raise PromptError("A linha não tem work item para montar o prompt.")
    truncated = len(comments) > _MAX_COMMENTS
    visible = comments[:_MAX_COMMENTS]
    parts = [
        base_prompt.strip(),
        "",
        "## Sessão",
        f"Versão do prompt base: {prompt_version}",
        "Esta sessão analisa somente a tela abaixo. Não reutilize histórico, memória ou conclusão de outra tela.",
        "",
        "## Dados da linha",
        f"- Linha da planilha: {row.excel_row}",
        f"- Nome da tela: {_or_empty(row.screen_name)}",
        f"- Documentação: {_or_empty(row.documentation)}",
        f"- Status: {_or_empty(row.status)}",
        f"- Link Azure: {_or_empty(row.azure_link)}",
        f"- ID da US: {row.work_item.id}",
        f"- Organização: {row.work_item.organization}",
        f"- Projeto: {row.work_item.project}",
        "- Observações da planilha (contexto e restrições específicas desta tela):",
        _or_empty(row.notes),
        "",
        "## Work item",
        f"- Tipo: {_or_empty(work_item.work_item_type)}",
        f"- Estado: {_or_empty(work_item.state)}",
        f"- Título: {_or_empty(work_item.title)}",
        "",
        "### Descrição atual",
        _plain(work_item.description_html),
        "",
        "### Links encontrados na descrição",
        _lines(extract_hrefs(work_item.description_html)),
        "",
        "### Critérios de aceite atuais",
        _plain(work_item.acceptance_html),
        "",
        "### Links encontrados nos critérios de aceite",
        _lines(extract_hrefs(work_item.acceptance_html)),
        "",
        "### Relações",
        _relations(work_item),
        "",
        "### Comentários",
        _comments(visible, truncated),
        "",
        "## Clone local do RetaguardaWeb",
        str(retaguarda_path),
        "Esse diretório é a raiz de leitura desta sessão. Consulte AGENTS.md quando existir.",
        "Não edite o clone e não grave arquivos nele. A resposta estruturada é o único resultado esperado.",
    ]
    return "\n".join(parts).strip() + "\n"


def _plain(value: str) -> str:
    text = strip_html(value).strip()
    return text or "(vazio)"


def _or_empty(value: str) -> str:
    return value.strip() if value and value.strip() else "(vazio)"


def _lines(values: list[str]) -> str:
    if not values:
        return "(nenhum)"
    return "\n".join(f"- {item}" for item in values)


def _relations(work_item: WorkItem) -> str:
    if not work_item.relations:
        return "(nenhuma)"
    lines = []
    for relation in work_item.relations:
        label = relation.name or relation.rel or "relação"
        lines.append(f"- {label}: {relation.url}")
    return "\n".join(lines)


def _comments(comments: list[Comment], truncated: bool) -> str:
    if not comments:
        return "(nenhum)"
    blocks = []
    for comment in comments:
        text = comment.text.strip()
        if len(text) > _MAX_COMMENT_CHARS:
            text = text[:_MAX_COMMENT_CHARS] + "\n[comentário truncado]"
        blocks.append(f"- {comment.author or 'autor não informado'} ({comment.created or 'data não informada'}):\n{text}")
    if truncated:
        blocks.append("[a lista de comentários foi truncada nos 100 primeiros]")
    return "\n".join(blocks)
