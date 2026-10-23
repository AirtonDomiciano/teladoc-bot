"""Normalização de texto usada na seleção da planilha e na confirmação."""

from __future__ import annotations

import html
import re
import unicodedata

_WS = re.compile(r"\s+")


def normalize(value: object) -> str:
    """Remove acentos, compacta espaços e ignora maiúsculas."""
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ").strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = _WS.sub(" ", text)
    return text.casefold()


def collapse_whitespace(value: str) -> str:
    return _WS.sub(" ", (value or "").replace("\xa0", " ")).strip()


def strip_html(value: str) -> str:
    text = value or ""
    text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", text)
    text = re.sub(r"(?i)</\s*(p|div|li|tr|h[1-6]|table)\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(text)


def canonical_text(value: str) -> str:
    """Texto comparável depois de HTML, entidades e espaços."""
    return collapse_whitespace(strip_html(value)).casefold()


def extract_hrefs(value: str) -> list[str]:
    return re.findall(r"""href\s*=\s*["']([^"']+)["']""", value or "", flags=re.IGNORECASE)


def slugify(value: str, max_len: int = 48) -> str:
    text = normalize(value)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return (text[:max_len].strip("-") or "tela")
