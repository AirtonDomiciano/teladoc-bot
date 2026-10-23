"""Fonte opcional de Google Sheets, com o mesmo recorte da planilha Excel."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from teladoc_bot.azure_link import WorkItemRef
from teladoc_bot.config import ConfigError
from teladoc_bot.spreadsheet import DOCUMENTED_VALUE, SheetRow, _read_row, _sheet_id, _text
from teladoc_bot.textutil import normalize

_SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)
_RENDER = "UNFORMATTED_VALUE"


def google_requested() -> bool:
    return bool(os.environ.get("GOOGLE_SPREADSHEET_ID", "").strip())


def load_google_rows(sheet_name: str | None, header_row: int, service=None) -> list[SheetRow]:
    sheet = _sheet_name(sheet_name)
    api = service or sheets_service()
    quoted = _quote_sheet(sheet)
    try:
        response = (
            api.spreadsheets()
            .values()
            .get(
                spreadsheetId=_spreadsheet_id(),
                range=f"{quoted}!A:I",
                valueRenderOption=_RENDER,
            )
            .execute()
        )
    except ConfigError:
        raise
    except Exception as exc:
        raise ConfigError("Falha ao ler o Google Sheets.") from exc
    values = response.get("values") or []
    origin = _range_origin(str(response.get("range") or "A1"))
    grid = _ValueGrid({origin + offset: row for offset, row in enumerate(values)})
    rows: list[SheetRow] = []
    for offset in range(len(values)):
        excel_row = origin + offset
        if excel_row <= header_row:
            continue
        item = _read_row(grid, excel_row)
        if item is not None:
            rows.append(item)
    return rows


def mark_google_documented(sheet_name: str | None, excel_row: int, expected: WorkItemRef, service=None) -> None:
    sheet = _sheet_name(sheet_name)
    api = service or sheets_service()
    quoted = _quote_sheet(sheet)
    current = _read_cells(api, f"{quoted}!D{excel_row}:G{excel_row}", 4)
    sheet_id = _sheet_id(current[0])
    if sheet_id != expected.id:
        raise ConfigError(
            "A linha da planilha mudou antes da marcação. "
            "A US pode já ter sido atualizada, e Documentação permanece NÃO."
        )
    previous = _text(current[3])
    target = f"{quoted}!G{excel_row}"
    _write_cell(api, target, DOCUMENTED_VALUE)
    try:
        confirmed = _read_cells(api, target, 1)
    except ConfigError:
        _restore_cell(api, target, previous)
        raise ConfigError("A releitura da documentação no Google Sheets não confirmou SIM.") from None
    if normalize(confirmed[0]) != normalize(DOCUMENTED_VALUE):
        _restore_cell(api, target, previous)
        raise ConfigError("A releitura da documentação no Google Sheets não confirmou SIM.")


def sheets_service():
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise ConfigError(
            "Instale google-api-python-client e google-auth-oauthlib para usar o Google Sheets."
        ) from exc
    return build("sheets", "v4", credentials=authorize(), cache_discovery=False)


def authorize(credentials_path: Path | None = None, token_path: Path | None = None):
    credentials_path = credentials_path or _env_path("GOOGLE_CREDENTIALS_PATH", "credentials.json")
    token_path = token_path or _env_path("GOOGLE_TOKEN_PATH", "token.json")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise ConfigError(
            "Instale google-api-python-client e google-auth-oauthlib para usar o Google Sheets."
        ) from exc

    def load(path: Path):
        try:
            return Credentials.from_authorized_user_file(str(path), list(_SCOPES))
        except Exception as exc:
            raise ConfigError(f"Não foi possível ler o token OAuth em {path.name}.") from exc

    def refresh(creds) -> None:
        try:
            creds.refresh(Request())
        except Exception as exc:
            raise ConfigError("Não foi possível renovar o token OAuth do Google Sheets.") from exc

    def browser(path: Path):
        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(path), list(_SCOPES))
            return flow.run_local_server(port=0, open_browser=True, prompt="consent")
        except Exception as exc:
            raise ConfigError("Não foi possível autorizar o Google Sheets no navegador.") from exc

    def store(path: Path, creds) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(creds.to_json(), encoding="utf-8")
        path.chmod(0o600)

    return prepare_credentials(
        credentials_path,
        token_path,
        load=load,
        refresh=refresh,
        authorize_browser=browser,
        store=store,
    )


def prepare_credentials(
    credentials_path: Path,
    token_path: Path,
    *,
    load: Callable,
    refresh: Callable,
    authorize_browser: Callable,
    store: Callable,
):
    """Reutiliza o token salvo. Na ausência ou na expiração sem renovação, abre o navegador."""
    creds = load(token_path) if token_path.is_file() else None
    if creds is not None and getattr(creds, "expired", False) and getattr(creds, "refresh_token", None):
        refresh(creds)
        store(token_path, creds)
        return creds
    if creds is not None and getattr(creds, "valid", False):
        return creds
    if not credentials_path.is_file():
        raise ConfigError(f"Credenciais OAuth não encontradas: {credentials_path}")
    creds = authorize_browser(credentials_path)
    store(token_path, creds)
    return creds


def _read_cells(api, cell_range: str, width: int) -> list[object]:
    try:
        response = (
            api.spreadsheets()
            .values()
            .get(spreadsheetId=_spreadsheet_id(), range=cell_range, valueRenderOption=_RENDER)
            .execute()
        )
    except ConfigError:
        raise
    except Exception as exc:
        raise ConfigError("Falha ao reler a linha no Google Sheets.") from exc
    values = response.get("values") or []
    row = list(values[0] if values else [])
    row.extend([None] * width)
    return row[:width]


def _write_cell(api, cell_range: str, value: str) -> None:
    try:
        (
            api.spreadsheets()
            .values()
            .update(
                spreadsheetId=_spreadsheet_id(),
                range=cell_range,
                valueInputOption="RAW",
                body={"values": [[value]]},
            )
            .execute()
        )
    except ConfigError:
        raise
    except Exception as exc:
        raise ConfigError("Falha ao atualizar a célula de documentação no Google Sheets.") from exc


def _restore_cell(api, cell_range: str, previous: str) -> None:
    try:
        _write_cell(api, cell_range, previous)
    except ConfigError:
        return


def _spreadsheet_id() -> str:
    spreadsheet_id = os.environ.get("GOOGLE_SPREADSHEET_ID", "").strip()
    if not spreadsheet_id:
        raise ConfigError("Defina GOOGLE_SPREADSHEET_ID para usar o Google Sheets.")
    return spreadsheet_id


def _sheet_name(fallback: str | None) -> str:
    name = os.environ.get("GOOGLE_SHEET_NAME", "").strip() or (fallback or "").strip()
    if not name:
        raise ConfigError("Defina GOOGLE_SHEET_NAME com a aba do Google Sheets.")
    return name


def _env_path(name: str, default: str) -> Path:
    raw = os.environ.get(name, "").strip() or default
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _quote_sheet(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def _range_origin(a1: str) -> int:
    cells = a1.split("!")[-1]
    start = cells.split(":")[0]
    number = "".join(character for character in start if character.isdigit())
    return int(number) if number else 1


class _Value:
    def __init__(self, value: object) -> None:
        self.value = value


class _ValueGrid:
    def __init__(self, rows: dict[int, list]) -> None:
        self._rows = rows

    def cell(self, excel_row: int, column: int) -> _Value:
        row = self._rows.get(excel_row) or []
        if column < 1 or column > len(row):
            return _Value(None)
        return _Value(row[column - 1])
