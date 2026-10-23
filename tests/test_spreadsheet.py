import os
import shutil
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook, load_workbook

import support  # noqa: F401
from teladoc_bot.azure import Comment, WorkItem
from teladoc_bot.azure_link import parse_work_item_link
from teladoc_bot.config import ColumnMap, ConfigError
from teladoc_bot.prompting import build_prompt
from teladoc_bot.spreadsheet import load_rows, mark_documented

COLUMNS = ColumnMap(
    screen_name="Nome da tela",
    documentation="Documentação",
    status="Status",
    azure_link="Link Azure",
    notes="Observações",
)
LINK = "https://dev.azure.com/metanetsistema/Metanet/_workitems/edit/{id}"


class SpreadsheetTests(unittest.TestCase):
    def test_selection_uses_fixed_columns_and_ignores_andamento(self) -> None:
        previous = {key: os.environ.get(key) for key in ("AZURE_ORGANIZATION", "AZURE_PROJECT")}
        os.environ.pop("AZURE_ORGANIZATION", None)
        os.environ.pop("AZURE_PROJECT", None)
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "copia.xlsx"
                self._write_layout(path)
                rows = load_rows(path, "TELAS DE CADASTRO", 1, COLUMNS)
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        by_name = {row.screen_name: row for row in rows}
        placas = by_name["Placas"]
        self.assertIsNone(placas.skip_reason)
        self.assertEqual(placas.work_item.id if placas.work_item else None, 30057)
        self.assertEqual(placas.notes, "manter o filtro")
        self.assertEqual(by_name["Descontos"].skip_reason, "status HARD CRUD não é processado nesta versão")
        self.assertEqual(by_name["Andamento CRUD"].skip_reason, "status diferente de CRUD")
        self.assertEqual(by_name["Pronta"].skip_reason, 'documentação diferente de "NÃO"')
        self.assertEqual(by_name["Sem cache"].skip_reason, "link calculado ausente")
        self.assertEqual(by_name["Link ruim"].skip_reason, "link inválido de work item do Azure DevOps")
        self.assertEqual(by_name["ID divergente"].skip_reason, "divergência entre o ID da US e o link Azure")
        self.assertNotIn("STATUS", [row.screen_name for row in rows])

    def test_notes_go_into_the_screen_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "copia.xlsx"
            self._write_layout(path)
            placas = next(row for row in load_rows(path, "telas de cadastro", 1, COLUMNS) if row.screen_name == "Placas")
        prompt = build_prompt(
            "teladoc-prompt-version: 1\nBase.",
            "1",
            placas,
            WorkItem(30057, "Placas", "User Story", "New", "", "", [], ""),
            [Comment("Ana", "2026-01-01", "comentario")],
            Path("/clone/RetaguardaWeb"),
        )
        self.assertIn("manter o filtro", prompt)
        self.assertIn("Observações da planilha", prompt)

    def test_mark_changes_only_documentation_and_keeps_formulas(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "copia.xlsx"
            self._write_layout(path)
            formula = '=IF(D2<>"",CONCATENATE("https://dev.azure.com/metanetsistema/Metanet/_workitems/edit/",D2),"")'
            prepared = load_workbook(path)
            prepared["TELAS DE CADASTRO"]["H2"] = formula
            prepared.save(path)
            prepared.close()
            original = path.read_bytes()
            ref = parse_work_item_link(LINK.format(id=30057))
            other = parse_work_item_link(LINK.format(id=99))
            assert ref is not None and other is not None
            with self.assertRaises(ConfigError):
                mark_documented(path, "TELAS DE CADASTRO", 1, COLUMNS, 2, other)
            self.assertEqual(path.read_bytes(), original)
            mark_documented(path, "TELAS DE CADASTRO", 1, COLUMNS, 2, ref)
            workbook = load_workbook(path, data_only=False)
            worksheet = workbook["TELAS DE CADASTRO"]
            self.assertEqual(worksheet["G2"].value, "SIM")
            self.assertEqual(worksheet["H2"].value, formula)
            self.assertEqual(worksheet["A2"].value, "Placas")
            self.assertEqual(worksheet["D2"].value, 30057)
            self.assertEqual(worksheet["E2"].value, "IDEAS")
            self.assertEqual(worksheet["F2"].value, " crud ")
            self.assertEqual(worksheet["I2"].value, "manter o filtro")
            self.assertEqual(worksheet["B2"].value, "não alterar")
            self.assertEqual(worksheet["G3"].value, "NÃO")
            self.assertEqual(worksheet["H3"].value, LINK.format(id=30055))
            workbook.close()

    def test_reload_after_mark_keeps_other_rows_eligible_by_id(self) -> None:
        previous = {key: os.environ.get(key) for key in ("AZURE_ORGANIZATION", "AZURE_PROJECT")}
        os.environ["AZURE_ORGANIZATION"] = "https://dev.azure.com/metanetsistema"
        os.environ["AZURE_PROJECT"] = "Metanet"
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "copia.xlsx"
                formula = '=IF(D{row}<>"",CONCATENATE("https://dev.azure.com/metanetsistema/Metanet/_workitems/edit/",D{row}),"")'
                workbook = Workbook()
                worksheet = workbook.active
                worksheet.title = "TELAS DE CADASTRO"
                rows = [
                    (2, "Categorias", 30092, "NÃO"),
                    (3, "Placas", 30057, "NÃO"),
                    (4, "Horários", 30093, "NÃO"),
                ]
                for row, name, us_id, documentation in rows:
                    worksheet.cell(row, 1).value = name
                    worksheet.cell(row, 4).value = us_id
                    worksheet.cell(row, 6).value = "CRUD"
                    worksheet.cell(row, 7).value = documentation
                    worksheet.cell(row, 8).value = formula.format(row=row)
                workbook.save(path)
                workbook.close()

                before = {row.screen_name: row for row in load_rows(path, "TELAS DE CADASTRO", 1, COLUMNS)}
                self.assertIsNone(before["Categorias"].skip_reason)
                self.assertIsNone(before["Placas"].skip_reason)
                self.assertEqual(before["Placas"].work_item.id if before["Placas"].work_item else None, 30057)

                ref = parse_work_item_link(LINK.format(id=30092))
                assert ref is not None
                mark_documented(path, "TELAS DE CADASTRO", 1, COLUMNS, 2, ref)

                stored = load_workbook(path, data_only=False)
                sheet = stored["TELAS DE CADASTRO"]
                self.assertEqual(sheet["G2"].value, "SIM")
                self.assertEqual(sheet["H2"].value, formula.format(row=2))
                self.assertEqual(sheet["H3"].value, formula.format(row=3))
                self.assertEqual(sheet["H4"].value, formula.format(row=4))
                stored.close()
                cached = load_workbook(path, data_only=True)
                self.assertIsNone(cached["TELAS DE CADASTRO"]["H3"].value)
                cached.close()

                after = {row.screen_name: row for row in load_rows(path, "TELAS DE CADASTRO", 1, COLUMNS)}
                self.assertEqual(after["Categorias"].skip_reason, 'documentação diferente de "NÃO"')
                self.assertIsNone(after["Placas"].skip_reason)
                self.assertIsNone(after["Horários"].skip_reason)
                self.assertEqual(after["Placas"].azure_link, LINK.format(id=30057))
                self.assertEqual(after["Horários"].work_item.id if after["Horários"].work_item else None, 30093)
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_real_workbook_copy_keeps_formulas_after_mark(self) -> None:
        source = Path(__file__).resolve().parents[1] / "Componentização - telas de cadastro.xlsx"
        if not source.is_file():
            self.skipTest("planilha real ausente")
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / source.name
            shutil.copy2(source, copy)
            before = load_workbook(copy, data_only=False)
            sheet_before = before["TELAS DE CADASTRO"]
            formula = sheet_before["H11"].value
            untouched = {
                coordinate: sheet_before[coordinate].value
                for coordinate in ("A11", "D11", "E11", "F11", "I11", "G12", "H12", "A2", "H2")
            }
            before.close()
            ref = parse_work_item_link(LINK.format(id=30057))
            assert ref is not None
            mark_documented(copy, "TELAS DE CADASTRO", 1, COLUMNS, 11, ref)
            after = load_workbook(copy, data_only=False)
            sheet = after["TELAS DE CADASTRO"]
            self.assertEqual(sheet["G11"].value, "SIM")
            self.assertEqual(sheet["H11"].value, formula)
            for coordinate, value in untouched.items():
                self.assertEqual(sheet[coordinate].value, value, coordinate)
            after.close()
            original = load_workbook(source, data_only=False)
            self.assertEqual(original["TELAS DE CADASTRO"]["G11"].value, "NÃO")
            self.assertEqual(original["TELAS DE CADASTRO"]["H11"].value, formula)
            original.close()

    def _write_layout(self, path: Path) -> None:
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "TELAS DE CADASTRO"
        worksheet["A1"] = "Nome da Tela"
        worksheet["E1"] = "STATUS"
        worksheet["G1"] = "Documentação"
        worksheet["I1"] = "Observações"
        rows = [
            (2, "Placas", 30057, "IDEAS", " crud ", " não ", LINK.format(id=30057), "manter o filtro"),
            (3, "Descontos", 30055.0, "IDEAS", "HÁRD CRUD", "NÃO", LINK.format(id=30055), "BUG 27847"),
            (4, "Andamento CRUD", 1, "CRUD", None, "NÃO", None, None),
            (5, "Pronta", 12, "TEST", "CRUD", "SIM", LINK.format(id=12), None),
            (6, "Sem cache", 13, "IDEAS", "CRUD", "NÃO", f'=IF(D6<>"",CONCATENATE("{LINK.format(id=13)}"),"")', None),
            (7, "Link ruim", 14, "IDEAS", "CRUD", "Nao", "https://example.com/item", None),
            (8, "ID divergente", 10, "IDEAS", "CRUD", "NÃO", LINK.format(id=11), None),
        ]
        for row, name, us_id, andamento, kind, documentation, link, notes in rows:
            worksheet.cell(row, 1).value = name
            worksheet.cell(row, 2).value = "não alterar" if row == 2 else None
            worksheet.cell(row, 4).value = us_id
            worksheet.cell(row, 5).value = andamento
            worksheet.cell(row, 6).value = kind
            worksheet.cell(row, 7).value = documentation
            worksheet.cell(row, 8).value = link
            worksheet.cell(row, 9).value = notes
        workbook.save(path)
        workbook.close()


if __name__ == "__main__":
    unittest.main()
