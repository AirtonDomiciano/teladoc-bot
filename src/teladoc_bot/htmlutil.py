"""Conversão mínima de Markdown para o HTML aceito pelo Azure DevOps."""

from __future__ import annotations

import html
import re


def _inline(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def _is_table_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def markdown_to_html(markdown: str) -> str:
    lines = (markdown or "").replace("\r\n", "\n").split("\n")
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        if stripped.startswith("```"):
            fence: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                fence.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            blocks.append(f"<pre><code>{html.escape(chr(10).join(fence))}</code></pre>")
            continue
        if stripped.startswith("|") and index + 1 < len(lines) and _is_table_separator(lines[index + 1]):
            rows = [stripped]
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(lines[index].strip())
                index += 1
            blocks.append(_table(rows))
            continue
        if stripped.startswith("#"):
            level = min(len(stripped) - len(stripped.lstrip("#")), 6)
            content = stripped[level:].strip()
            blocks.append(f"<h{level}>{_inline(content)}</h{level}>")
            index += 1
            continue
        if stripped.startswith("- "):
            items: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("- "):
                items.append(lines[index].strip()[2:].strip())
                index += 1
            body = "".join(f"<li>{_inline(item)}</li>" for item in items)
            blocks.append(f"<ul>{body}</ul>")
            continue
        paragraph: list[str] = [stripped]
        index += 1
        while index < len(lines) and lines[index].strip() and not _starts_block(lines[index]):
            paragraph.append(lines[index].strip())
            index += 1
        blocks.append(f"<p>{_inline(' '.join(paragraph))}</p>")
    return "\n".join(blocks)


def _starts_block(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("#") or stripped.startswith("- ") or stripped.startswith("|") or stripped.startswith("```")


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _table(rows: list[str]) -> str:
    header = _split_row(rows[0])
    body = [_split_row(row) for row in rows[1:]]
    head_html = "".join(f"<th>{_inline(cell)}</th>" for cell in header)
    body_html = []
    for row in body:
        cells = "".join(f"<td>{_inline(cell)}</td>" for cell in row)
        body_html.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head_html}</tr></thead><tbody>{''.join(body_html)}</tbody></table>"


def acceptance_criteria_html(criteria: list[str]) -> str:
    items = []
    for criterion in criteria:
        text = collapse_line(criterion)
        if text:
            items.append(f"<li>{html.escape(text)}</li>")
    return "<ul>" + "".join(items) + "</ul>"


def collapse_line(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())
