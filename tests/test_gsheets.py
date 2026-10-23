import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import support  # noqa: F401
from teladoc_bot.azure_link import parse_work_item_link
from teladoc_bot.config import ColumnMap, ConfigError
from teladoc_bot.gsheets import load_google_rows, mark_google_documented, prepare_credentials
from teladoc_bot.spreadsheet import load_rows, mark_documented

COLUMNS = ColumnMap("Nome da tela", "Documentação", "Status", "Link Azure", "Observações")
LINK = "https://dev.azure.com/metanetsistema/Metanet/_workitems/edit/{id}"
SHEET = "TELAS DE CADASTRO"
_ENV = (
    "GOOGLE_SPREADSHEET_ID",
    "GOOGLE_SHEET_NAME",
    "GOOGLE_CREDENTIALS_PATH",
    "GOOGLE_TOKEN_PATH",
    "AZURE_ORGANIZATION",
    "AZURE_PROJECT",
)


class FakeSheets:
    def __init__(self, rows: dict[int, list]) -> None:
        self.rows = {number: list(values) for number, values in rows.items()}
        self.calls: list[tuple[str, dict]] = []
        self.fail_update = False
        self.confirm_as: str | None = None

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, **kwargs):
        self.calls.append(("get", kwargs))
        start_column, start_row, end_column, end_row = _parse_range(kwargs["range"])
        if start_row is None:
            numbers = sorted(self.rows)
            origin = numbers[0] if numbers else 1
            last = numbers[-1] if numbers else origin
            values = [self._slice(number, start_column, end_column) for number in range(origin, last + 1)]
            rendered = f"'{SHEET}'!A{origin}:I{last}"
        else:
            values = [self._slice(start_row, start_column, end_column)]
            if self.confirm_as is not None and start_column == end_column == 7:
                values = [[self.confirm_as]]
            rendered = kwargs["range"]
        return _Done({"range": rendered, "values": values})

    def update(self, **kwargs):
        self.calls.append(("update", kwargs))
        if self.fail_update:
            raise RuntimeError("ya29.token-super-secreto")
        column, row, end_column, end_row = _parse_range(kwargs["range"])
        if row is None or row != end_row or column != end_column:
            raise AssertionError(kwargs["range"])
        sent = kwargs["body"]["values"]
        if len(sent) != 1 or len(sent[0]) != 1:
            raise AssertionError(sent)
        stored = self.rows.setdefault(row, [])
        while len(stored) < column:
            stored.append(None)
        stored[column - 1] = sent[0][0]
        return _Done({"updatedCells": 1})

    def _slice(self, row: int, start: int, end: int) -> list:
        stored = list(self.rows.get(row) or [])
        stored.extend([None] * end)
        return stored[start - 1 : end]


class _Done:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def execute(self) -> dict:
        return self.payload


class GoogleSheetsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous = {key: os.environ.get(key) for key in _ENV}
        os.environ["GOOGLE_SPREADSHEET_ID"] = "planilha-de-teste"
        os.environ["GOOGLE_SHEET_NAME"] = SHEET
        os.environ.pop("AZURE_ORGANIZATION", None)
        os.environ.pop("AZURE_PROJECT", None)

    def tearDown(self) -> None:
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_selection_uses_calculated_link_and_crud_filter(self) -> None:
        sheets = FakeSheets(
            {
                1: ["Nome da Tela", None, None, "WB", "STATUS", None, "Documentação", "Link", "Observações"],
                2: ["Categorias", None, None, 30092, "IDEAS", "CRUD", "NÃO", LINK.format(id=30092), ""],
                3: ["Descontos", None, None, 30055, "IDEAS", "HARD CRUD", "NÃO", LINK.format(id=30055), ""],
                4: ["Pronta", None, None, 12, "TEST", "CRUD", "SIM", LINK.format(id=12), ""],
                5: ["Link ruim", None, None, 14, "IDEAS", "CRUD", "NÃO", "https://example.com/item", ""],
                6: ["Divergente", None, None, 10, "IDEAS", "CRUD", "NÃO", LINK.format(id=11), ""],
            }
        )
        rows = {row.screen_name: row for row in load_google_rows(SHEET, 1, sheets)}
        categorias = rows["Categorias"]
        self.assertIsNone(categorias.skip_reason)
        self.assertEqual(categorias.excel_row, 2)
        self.assertEqual(categorias.work_item.id if categorias.work_item else None, 30092)
        self.assertEqual(categorias.azure_link, LINK.format(id=30092))
        self.assertEqual(rows["Descontos"].skip_reason, "status HARD CRUD não é processado nesta versão")
        self.assertEqual(rows["Pronta"].skip_reason, 'documentação diferente de "NÃO"')
        self.assertEqual(rows["Link ruim"].skip_reason, "link inválido de work item do Azure DevOps")
        self.assertEqual(rows["Divergente"].skip_reason, "divergência entre o ID da US e o link Azure")
        self.assertEqual(sheets.calls[0][1]["valueRenderOption"], "UNFORMATTED_VALUE")
        self.assertNotIn("formula", str(sheets.calls).casefold())

    def test_mark_rewrites_only_documentation_after_reread(self) -> None:
        sheets = self._category_sheet()
        ref = parse_work_item_link(LINK.format(id=30092))
        assert ref is not None
        mark_google_documented(SHEET, 45, ref, sheets)
        updates = [call for kind, call in sheets.calls if kind == "update"]
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["range"], f"'{SHEET}'!G45")
        self.assertEqual(updates[0]["valueInputOption"], "RAW")
        self.assertEqual(updates[0]["body"], {"values": [["SIM"]]})
        self.assertEqual(sheets.rows[45][3], 30092)
        self.assertEqual(sheets.rows[45][6], "SIM")
        self.assertEqual(sheets.rows[45][7], '=IF(D45<>"",CONCATENATE("https://exemplo"),"")')
        gets = [call["range"] for kind, call in sheets.calls if kind == "get"]
        self.assertEqual(gets, [f"'{SHEET}'!D45:G45", f"'{SHEET}'!G45"])

    def test_id_mismatch_does_not_write(self) -> None:
        sheets = self._category_sheet()
        other = parse_work_item_link(LINK.format(id=99))
        assert other is not None
        with self.assertRaises(ConfigError):
            mark_google_documented(SHEET, 45, other, sheets)
        self.assertFalse(any(kind == "update" for kind, _call in sheets.calls))
        self.assertEqual(sheets.rows[45][6], "NÃO")

    def test_update_error_does_not_mark_sim_or_expose_the_token(self) -> None:
        sheets = self._category_sheet()
        sheets.fail_update = True
        ref = parse_work_item_link(LINK.format(id=30092))
        assert ref is not None
        with self.assertRaises(ConfigError) as caught:
            mark_google_documented(SHEET, 45, ref, sheets)
        self.assertNotIn("token-super-secreto", str(caught.exception))
        self.assertEqual(sheets.rows[45][6], "NÃO")

    def test_failed_confirmation_restores_the_cell(self) -> None:
        sheets = self._category_sheet()
        sheets.confirm_as = "NÃO"
        ref = parse_work_item_link(LINK.format(id=30092))
        assert ref is not None
        with self.assertRaises(ConfigError):
            mark_google_documented(SHEET, 45, ref, sheets)
        self.assertEqual(sheets.rows[45][6], "NÃO")
        self.assertEqual([call["body"]["values"][0][0] for kind, call in sheets.calls if kind == "update"], ["SIM", "NÃO"])

    def test_excel_loader_delegates_without_opening_the_workbook(self) -> None:
        sheets = self._category_sheet()
        missing = Path("/tmp/teladoc-planilha-inexistente.xlsx")
        ref = parse_work_item_link(LINK.format(id=30092))
        assert ref is not None
        from teladoc_bot import gsheets

        original = gsheets.sheets_service
        gsheets.sheets_service = lambda: sheets
        try:
            selected = load_rows(missing, SHEET, 1, COLUMNS)
            self.assertEqual(selected[0].screen_name, "Categorias")
            mark_documented(missing, SHEET, 1, COLUMNS, 45, ref)
        finally:
            gsheets.sheets_service = original
        self.assertFalse(missing.exists())
        self.assertEqual(sheets.rows[45][6], "SIM")
        self.assertTrue(str(sheets.rows[45][7]).startswith("=IF("))

    def test_saved_token_is_reused_and_first_run_opens_the_browser(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            credentials = root / "credentials.json"
            token = root / "token.json"
            credentials.write_text("{}", encoding="utf-8")
            token.write_text("ja-existe", encoding="utf-8")
            stored: list[str] = []

            def store(path: Path, creds) -> None:
                stored.append(creds.secret)
                path.write_text("salvo", encoding="utf-8")

            reused = prepare_credentials(
                credentials,
                token,
                load=lambda _path: SimpleNamespace(valid=True, expired=False, refresh_token="nao-usar", secret="nao-exibir"),
                refresh=lambda _creds: self.fail("renovação inesperada"),
                authorize_browser=lambda _path: self.fail("navegador inesperado"),
                store=store,
            )
            self.assertEqual(reused.secret, "nao-exibir")
            self.assertEqual(stored, [])
            token.unlink()
            created = prepare_credentials(
                credentials,
                token,
                load=lambda _path: None,
                refresh=lambda _creds: None,
                authorize_browser=lambda path: SimpleNamespace(secret="token-novo", path=path),
                store=store,
            )
            self.assertEqual(created.secret, "token-novo")
            self.assertEqual(token.read_text(encoding="utf-8"), "salvo")
            self.assertEqual(stored, ["token-novo"])

    def test_expired_token_refreshes_without_opening_the_browser(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / "token.json"
            token.write_text("antigo", encoding="utf-8")
            refreshed: list[str] = []

            def refresh(creds) -> None:
                creds.expired = False
                creds.valid = True
                refreshed.append("ok")

            creds = SimpleNamespace(valid=False, expired=True, refresh_token="ref", secret="segredo")
            prepare_credentials(
                Path(directory) / "ausente.json",
                token,
                load=lambda _path: creds,
                refresh=refresh,
                authorize_browser=lambda _path: self.fail("navegador inesperado"),
                store=lambda path, item: path.write_text(item.secret, encoding="utf-8"),
            )
            self.assertEqual(refreshed, ["ok"])
            self.assertEqual(token.read_text(encoding="utf-8"), "segredo")

    def _category_sheet(self) -> FakeSheets:
        return FakeSheets(
            {
                45: [
                    "Categorias",
                    None,
                    None,
                    30092,
                    "IDEAS",
                    "CRUD",
                    "NÃO",
                    '=IF(D45<>"",CONCATENATE("https://exemplo"),"")',
                    "",
                ]
            }
        )


def _parse_range(a1: str) -> tuple[int, int | None, int, int | None]:
    _sheet, _sep, cells = a1.rpartition("!")
    if ":" in cells:
        start, end = cells.split(":")
    else:
        start = end = cells
    start_column, start_row = _parse_cell(start)
    end_column, end_row = _parse_cell(end)
    return start_column, start_row, end_column, end_row


def _parse_cell(token: str) -> tuple[int, int | None]:
    letters = "".join(character for character in token if character.isalpha())
    digits = "".join(character for character in token if character.isdigit())
    column = 0
    for character in letters.upper():
        column = column * 26 + (ord(character) - 64)
    return column, int(digits) if digits else None


if __name__ == "__main__":
    unittest.main()
