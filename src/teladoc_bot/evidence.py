"""Evidências literais do clone, sem inferir comportamento."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from teladoc_bot.textutil import normalize, slugify

_STOP = {
    "de",
    "da",
    "do",
    "das",
    "dos",
    "e",
    "por",
    "para",
    "a",
    "o",
    "as",
    "os",
    "em",
    "no",
    "na",
    "nos",
    "nas",
    "um",
    "uma",
}
_SKIP_DIRS = {"node_modules", "dist", ".git", "coverage", ".angular", "tmp", "out-tsc"}
_KINDS = ("rota", "componente", "template", "formulario", "servico")
_TITLES = {
    "rota": "Rotas",
    "componente": "Componentes",
    "template": "Templates",
    "formulario": "Formulários",
    "servico": "Serviços",
}
_LINE = {
    "rota": re.compile(r"\bpath\s*:|component\s*:|loadChildren|canActivate|RouterModule"),
    "componente": re.compile(r"@Component|selector\s*:|templateUrl\s*:|styleUrls\s*:|export class |\bkey\s*:"),
    "template": re.compile(r"<"),
    "formulario": re.compile(r"\bkey\s*:|formly|Formly|export const |validators"),
    "servico": re.compile(r"@Injectable|export class |\bgql\b|\bquery\b|\bmutation\b"),
}
_SUFFIXES = (
    ".component.html",
    ".component.ts",
    ".service.ts",
    ".fields.ts",
    ".routing.ts",
    ".routes.ts",
    ".html",
    ".ts",
)


@dataclass(frozen=True)
class SourceFile:
    relative: str
    kind: str


def index_sources(root: Path) -> tuple[SourceFile, ...]:
    found: list[SourceFile] = []
    if not root.is_dir():
        return ()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in _SKIP_DIRS for part in relative.parts):
            continue
        kind = _kind(relative.as_posix())
        if kind is not None:
            found.append(SourceFile(relative.as_posix(), kind))
    return tuple(found)


def render_evidence(root: Path, screen_name: str, sources: tuple[SourceFile, ...] | None = None) -> str:
    indexed = index_sources(root) if sources is None else sources
    tokens = _tokens(screen_name)
    lines = ["## Evidências locais do RetaguardaWeb", ""]
    if not tokens:
        lines.append(
            "A implementação não foi localizada com segurança: o nome da tela não fornece um termo buscável. "
            "Nenhum componente, comportamento ou regra foi inferido."
        )
        return "\n".join(lines) + "\n"
    anchors = _anchors(indexed, tokens)
    located = [anchor for anchor in anchors if _has_screen_file(anchors[anchor])]
    if len(located) != 1:
        lines.extend(_limitation(screen_name, located or list(anchors)))
        return "\n".join(lines) + "\n"
    anchor = located[0]
    selected = _files_for_anchor(anchor, anchors[anchor], tokens)
    selected.extend(_external_routes(root, anchor, indexed, directory_match=_directory_matches(Path(anchor).name, tokens)))
    lines.append("Arquivos localizados pelo nome da tela. Os trechos abaixo são citações literais do clone.")
    lines.append("O que não aparece aqui não foi confirmado e não deve ser tratado como regra da tela.")
    lines.append("")
    for source in selected:
        lines.append(f"- `{source.relative}`")
    lines.append("")
    for kind in _KINDS:
        group = [source for source in selected if source.kind == kind]
        lines.append(f"### {_TITLES[kind]}")
        lines.append("")
        if not group:
            lines.append("Não encontrado no clone para esta tela.")
            lines.append("")
            continue
        for source in group:
            needle = ""
            if source.kind == "rota" and source_is_outside(source.relative, anchor):
                needle = _route_needle(anchor)
            excerpt = _excerpt(root, source.relative, kind, needle)
            lines.append(f"`{source.relative}`")
            lines.append("")
            if excerpt:
                lines.extend(f"    {line}" for line in excerpt)
            else:
                lines.append("    [sem trecho classificado; o conteúdo não foi reproduzido]")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _anchors(sources: tuple[SourceFile, ...], tokens: list[str]) -> dict[str, list[SourceFile]]:
    grouped: dict[str, list[SourceFile]] = {}
    for source in sources:
        anchor = _anchor(source.relative, tokens)
        if anchor is None:
            continue
        grouped.setdefault(anchor, []).append(source)
    return grouped


def _anchor(relative: str, tokens: list[str]) -> str | None:
    path = Path(relative)
    for parent in path.parents:
        if str(parent) == ".":
            break
        if _directory_matches(parent.name, tokens):
            return parent.as_posix()
    if _file_matches(path.name, tokens):
        parent = path.parent.as_posix()
        return "" if parent == "." else parent
    return None


def _files_for_anchor(anchor: str, sources: list[SourceFile], tokens: list[str]) -> list[SourceFile]:
    if _directory_matches(Path(anchor).name, tokens):
        selected = list(sources)
    else:
        selected = [source for source in sources if _file_matches(Path(source.relative).name, tokens)]
    selected.sort(key=lambda source: source.relative)
    return selected


def _has_screen_file(sources: list[SourceFile]) -> bool:
    return any(source.kind in {"componente", "template"} for source in sources)


def _external_routes(root: Path, anchor: str, sources: tuple[SourceFile, ...], *, directory_match: bool) -> list[SourceFile]:
    if not directory_match:
        return []
    needle = _route_needle(anchor)
    extra: list[SourceFile] = []
    for source in sources:
        if source.kind != "rota" or source.relative.startswith(anchor + "/"):
            continue
        text = _read(root / source.relative)
        if needle and needle in text:
            extra.append(source)
    return extra


def _route_needle(anchor: str) -> str:
    parts = Path(anchor).parts
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    return parts[-1] if parts else ""


def _excerpt(root: Path, relative: str, kind: str, needle: str) -> list[str]:
    path = root / relative
    try:
        if path.stat().st_size > 1_500_000:
            return ["[arquivo grande demais; trecho não reproduzido]"]
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ["[arquivo não pôde ser lido]"]
    pattern = _LINE[kind]
    chosen: list[str] = []
    for number, line in enumerate(content.splitlines(), start=1):
        if needle and needle not in line:
            continue
        if pattern.search(line):
            chosen.append(f"{number}: {line.strip()[:200]}")
        if len(chosen) >= 30:
            break
    return chosen


def source_is_outside(relative: str, anchor: str) -> bool:
    return not relative.startswith(anchor + "/")


def _limitation(screen_name: str, anchors: list[str]) -> list[str]:
    lines = [
        f'A implementação de "{screen_name}" não foi localizada com segurança no clone.',
        "Nenhum componente, comportamento ou regra foi inferido.",
    ]
    if not anchors:
        lines.append("Nenhum arquivo de rota, componente, template, formulário ou serviço correspondeu ao nome da tela.")
        return lines
    if len(anchors) == 1:
        lines.append("A correspondência não inclui componente ou template:")
    else:
        lines.append("Há mais de um diretório compatível; os trechos não foram incluídos:")
    for anchor in anchors[:12]:
        lines.append(f"- `{anchor}`")
    return lines


def _tokens(screen_name: str) -> list[str]:
    return [part for part in slugify(screen_name).split("-") if part not in _STOP and len(part) > 1]


def _directory_matches(name: str, tokens: list[str]) -> bool:
    segments = _segments(name)
    return bool(segments) and all(any(_same_token(segment, token) for segment in segments) for token in tokens)


def _file_matches(name: str, tokens: list[str]) -> bool:
    segments = _segments(_stem(name))
    return bool(segments) and all(any(_same_token(segment, token) for segment in segments) for token in tokens)


def _segments(value: str) -> list[str]:
    return [normalize(part) for part in re.split(r"[^0-9A-Za-z]+", value) if part]


def _stem(name: str) -> str:
    for suffix in _SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem


def _same_token(segment: str, token: str) -> bool:
    if segment == token:
        return True
    if len(segment) > 4 and segment.endswith("s") and segment[:-1] == token:
        return True
    if len(token) > 4 and token.endswith("s") and token[:-1] == segment:
        return True
    return False


def _kind(relative: str) -> str | None:
    name = relative.casefold()
    if name.endswith(".component.html"):
        return "template"
    if name.endswith(".html"):
        return "template"
    if not name.endswith(".ts"):
        return None
    if ".routing." in name or name.endswith(".routing.ts") or name.endswith(".routes.ts") or "/menu/" in name:
        return "rota"
    if name.endswith(".component.ts"):
        return "componente"
    if name.endswith(".fields.ts"):
        return "formulario"
    if name.endswith(".service.ts"):
        return "servico"
    return None


def _read(path: Path) -> str:
    try:
        if path.stat().st_size > 1_500_000:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
