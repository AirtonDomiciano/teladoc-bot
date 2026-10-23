"""Seleção das linhas da planilha e marcação de Documentação = Sim."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from teladoc_bot.azure_link import WorkItemRef, parse_work_item_link
from teladoc_bot.config import ColumnMap, ConfigError
from teladoc_bot.textutil import normalize

DOCUMENTED_VALUE = "Sim"
_EMPTY = ""
_NAO = "nao"
_CRUD = "crud"
_HARD_CRUD = "hard crud"


@dataclass(frozen=True)
class SheetRow:
    excel_row: int
    screen_name: str
    documentation: str
    status: str
    azure_link: str
    notes: str
    work_item: WorkItemRef | None
    skip_reason: str | None


def load_rows(path: Path, sheet_name: str | None, header_row: int, columns: ColumnMap) -> list[SheetRow]:
    if not path.is_file():
        raise ConfigError(f"Planilha não encontrada: {path}")
    workbook = load_workbook(path, data_only=False, keep_vba=path.suffix.lower() == ".xlsm")
    try:
        worksheet = _resolve_sheet(workbook, sheet_name)
        indexes = _column_indexes(worksheet, header_row, columns)
        rows: list[SheetRow] = []
        for excel_row in range(header_row + 1, worksheet.max_row + 1):
            item = _read_row(worksheet, excel_row, indexes)
            if item is None:
                continue
            rows.append(item)
        return rows
    finally:
        workbook.close()


def mark_documented(
    path: Path,
    sheet_name: str | None,
    header_row: int,
    columns: ColumnMap,
    excel_row: int,
    expected: WorkItemRef,
) -> None:
    workbook = load_workbook(path, data_only=False, keep_vba=path.suffix.lower() == ".xlsm")
    try:
        worksheet = _resolve_sheet(workbook, sheet_name)
        indexes = _column_indexes(worksheet, header_row, columns)
        link = _cell_link(worksheet.cell(excel_row, indexes["azure_link"]))
        parsed = parse_work_item_link(link)
        if parsed is None or parsed.key != expected.key:
            raise ConfigError(
                "A linha da planilha mudou antes da marcação. "
                "A US pode já ter sido atualizada, e Documentação permanece Não."
            )
        worksheet.cell(excel_row, indexes["documentation"]).value = DOCUMENTED_VALUE
        temporary = path.with_suffix(path.suffix + ".tmp")
        workbook.save(temporary)
    finally:
        workbook.close()
    temporary.replace(path)


def _resolve_sheet(workbook, sheet_name: str | None) -> Worksheet:
    if not sheet_name:
        return workbook.active
    if sheet_name in workbook.sheetnames:
        return workbook[sheet_name]
    wanted = normalize(sheet_name)
    matches = [name for name in workbook.sheetnames if normalize(name) == wanted]
    if len(matches) == 1:
        return workbook[matches[0]]
    available = ", ".join(workbook.sheetnames)
    raise ConfigError(f"Aba '{sheet_name}' não encontrada. Abas disponíveis: {available}")


def _column_indexes(worksheet: Worksheet, header_row: int, columns: ColumnMap) -> dict[str, int]:
    found: dict[str, int] = {}
    seen: dict[str, str] = {}
    for cell in worksheet[header_row]:
        header = "" if cell.value is None else str(cell.value)
        key = normalize(header)
        if not key:
            continue
        if key in seen:
            raise ConfigError(f"Cabeçalho duplicado na planilha: '{header}'.")
        seen[key] = header
    expected = {
        "screen_name": columns.screen_name,
        "documentation": columns.documentation,
        "status": columns.status,
        "azure_link": columns.azure_link,
        "notes": columns.notes,
    }
    missing = []
    for field_name, header in expected.items():
        key = normalize(header)
        if key not in seen:
            missing.append(header)
            continue
        for cell in worksheet[header_row]:
            if normalize("" if cell.value is None else str(cell.value)) == key:
                found[field_name] = cell.column
                break
    if missing:
        raise ConfigError("Colunas não encontradas na planilha: " + ", ".join(missing))
    return found


def _read_row(worksheet: Worksheet, excel_row: int, indexes: dict[str, int]) -> SheetRow | None:
    screen_name = _text(worksheet.cell(excel_row, indexes["screen_name"]).value)
    documentation = _text(worksheet.cell(excel_row, indexes["documentation"]).value)
    status = _text(worksheet.cell(excel_row, indexes["status"]).value)
    notes = _notes(worksheet.cell(excel_row, indexes["notes"]).value)
    azure_link = _cell_link(worksheet.cell(excel_row, indexes["azure_link"]))
    if not any((screen_name, documentation, status, notes, azure_link)):
        return None
    work_item = parse_work_item_link(azure_link)
    return SheetRow(
        excel_row=excel_row,
        screen_name=screen_name,
        documentation=documentation,
        status=status,
        azure_link=azure_link,
        notes=notes,
        work_item=work_item,
        skip_reason=_skip_reason(screen_name, documentation, status, azure_link, work_item),
    )


def _skip_reason(
    screen_name: str,
    documentation: str,
    status: str,
    azure_link: str,
    work_item: WorkItemRef | None,
) -> str | None:
    if normalize(documentation) != _NAO:
        return 'documentação diferente de "Não"'
    normalized_status = normalize(status)
    if normalized_status == _HARD_CRUD:
        return "status HARD CRUD não é processado nesta versão"
    if normalized_status != _CRUD:
        return "status diferente de CRUD"
    if not azure_link.strip():
        return "sem link"
    if work_item is None:
        return "link inválido de work item do Azure DevOps"
    if not screen_name.strip():
        return "nome da tela vazio"
    return None


def _text(value: object) -> str:
    if value is None:
        return _EMPTY
    return str(value).replace("\xa0", " ").strip()


def _notes(value: object) -> str:
    if value is None:
        return _EMPTY
    return str(value).replace("\xa0", " ").strip()


def _cell_link(cell) -> str:
    candidates: list[str] = []
    hyperlink = getattr(cell, "hyperlink", None)
    if hyperlink is not None and getattr(hyperlink, "target", None):
        candidates.append(str(hyperlink.target).strip())
    if isinstance(cell.value, str):
        formula = _hyperlink_formula(cell.value)
        if formula:
            candidates.append(formula)
        candidates.append(cell.value.strip())
    elif cell.value is not None:
        candidates.append(str(cell.value).strip())
    for candidate in candidates:
        if parse_work_item_link(candidate):
            return candidate
    return candidates[0] if candidates else _EMPTY


def _hyperlink_formula(value: str) -> str | None:
    if not value.startswith("=") or "HYPERLINK" not in value.upper():
        return None
    match = re.search(r'HYPERLINK\(\s*"([^"]+)"', value, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return None
