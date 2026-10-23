import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import support  # noqa: F401
from openpyxl import load_workbook
from support import LINK, ready_payload, seed_clone, write_config, write_workbook
from teladoc_bot.azure import Comment, Relation, WorkItem
from teladoc_bot.cli import main
from teladoc_bot.handoff import collect_screens, import_screens, publish_screens, review_screens
from teladoc_bot.prompting import PromptError
from teladoc_bot.htmlutil import acceptance_criteria_html, markdown_to_html
from teladoc_bot.validation import validate_analysis

SECRET = "token-super-secreto"


class FakeAzure:
    def __init__(self, work_item: WorkItem, comments: list[Comment]) -> None:
        self.work_item = work_item
        self.comments = comments
        self.updates: list[tuple[str, str]] = []

    def get_work_item(self, ref) -> WorkItem:
        self.work_item.id = ref.id
        return self.work_item

    def get_comments(self, ref) -> list[Comment]:
        return self.comments

    def update_documentation(self, ref, description_html: str, acceptance_html: str) -> None:
        self.updates.append((description_html, acceptance_html))
        self.work_item.description_html = f"<div>{description_html}</div>"
        self.work_item.acceptance_html = f"<div>{acceptance_html}</div>"


class HandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.clone = self.root / "retaguarda"
        self.paths = seed_clone(self.clone)
        self.output = self.root / "output"
        self.sheet = self.root / "planilha.xlsx"
        self._saved_env = {
            key: os.environ.get(key)
            for key in (
                "PLANILHA_PATH",
                "PLANILHA_ABA",
                "RETAGUARDA_PATH",
                "GOOGLE_SPREADSHEET_ID",
                "GOOGLE_SHEET_NAME",
                "AZURE_DEVOPS_PAT",
                "AZURE_PAT",
            )
        }
        for key in self._saved_env:
            os.environ.pop(key, None)
        os.environ["AZURE_DEVOPS_PAT"] = SECRET
        write_workbook(
            self.sheet,
            [["Clientes", "Não", "CRUD", LINK.format(id=10), f"observação {SECRET}"]],
        )
        self.config = write_config(self.root, self.sheet, self.clone, self.output)
        self.azure = FakeAzure(*self._work_item())

    def tearDown(self) -> None:
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temporary.cleanup()

    def test_collect_exports_context_without_secrets_or_writes(self) -> None:
        package, code = collect_screens(self.config, self.azure, limit=None, only_id=None, log=lambda _m: None)
        text = (package / "us-10.md").read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertEqual(self.azure.updates, [])
        self.assertEqual(self._cell("G2"), "Não")
        self.assertIn("ID da US: 10", text)
        self.assertIn("observação [redigido]", text)
        self.assertIn("## Evidências locais do RetaguardaWeb", text)
        self.assertIn("src/app/cliente.component.ts", text)
        self.assertIn("src/app/cliente.component.html", text)
        self.assertIn("nomeCliente", text)
        self.assertIn("Não encontrado no clone para esta tela.", text)
        self.assertIn(str(self.clone), text)
        self.assertIn("figma.com/design", text)
        self.assertIn("## 8. Componentes atuais e substituições", text)
        self.assertNotIn(SECRET, text)
        self.assertNotIn(SECRET, (package / "pacote.json").read_text(encoding="utf-8"))
        self.assertNotIn(SECRET, (package / "indice.md").read_text(encoding="utf-8"))

    def test_screen_dir_collects_only_that_directory(self) -> None:
        screen = self.clone / "src/app/pages/clientes"
        screen.mkdir(parents=True)
        (screen / "clientes.component.ts").write_text("@Component({ selector: 'app-clientes' })\n", encoding="utf-8")
        (screen / "clientes.component.html").write_text("<form></form>\n", encoding="utf-8")
        package, code = collect_screens(
            self.config,
            self.azure,
            limit=None,
            only_id=10,
            screen_dir="src/app/pages/clientes",
            log=lambda _m: None,
        )
        text = (package / "us-10.md").read_text(encoding="utf-8")
        payload = json.loads((package / "pacote.json").read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(self.azure.updates, [])
        self.assertEqual(self._cell("G2"), "Não")
        self.assertIn("Diretório informado: `src/app/pages/clientes`", text)
        self.assertIn("selector: 'app-clientes'", text)
        self.assertNotIn("nomeCliente", text)
        self.assertEqual(payload["screens"][0]["screen_directory"], "src/app/pages/clientes")
        self.assertNotIn(SECRET, text)

    def test_screen_dir_rejects_a_directory_for_several_screens(self) -> None:
        write_workbook(
            self.sheet,
            [
                ["Clientes", "Não", "CRUD", LINK.format(id=10), ""],
                ["Placas", "Não", "CRUD", LINK.format(id=11), ""],
            ],
        )
        with self.assertRaises(PromptError):
            collect_screens(
                self.config,
                self.azure,
                limit=None,
                only_id=None,
                screen_dir="src/app",
                log=lambda _m: None,
            )
        self.assertEqual(self.azure.updates, [])
        self.assertEqual(self._cell("G2"), "Não")

    def test_invalid_missing_and_wrong_id_block_publication(self) -> None:
        package, _code = collect_screens(self.config, self.azure, limit=None, only_id=None, log=lambda _m: None)
        source = self.root / "respostas"
        source.mkdir()
        wrong = ready_payload(self.paths)
        wrong["work_item_id"] = 99
        (source / "us-10.json").write_text(json.dumps(wrong), encoding="utf-8")
        self.assertEqual(import_screens(self.config, package, source, log=lambda _m: None), 2)
        self.assertEqual(publish_screens(self.config, package, self.azure, log=lambda _m: None), 2)
        self.assertEqual(self.azure.updates, [])
        self.assertEqual(self._cell("G2"), "Não")

        pending = ready_payload(self.paths)
        pending["work_item_id"] = 10
        pending["status"] = "pending"
        pending["pending_reason"] = "Falta confirmar o payload."
        (source / "us-10.json").write_text(json.dumps(pending), encoding="utf-8")
        self.assertEqual(import_screens(self.config, package, source, log=lambda _m: None), 2)
        self.assertEqual(publish_screens(self.config, package, self.azure, log=lambda _m: None), 2)
        self.assertEqual(self.azure.updates, [])
        self.assertEqual(self._cell("G2"), "Não")

        source.joinpath("us-10.json").unlink()
        self.assertEqual(import_screens(self.config, package, source, log=lambda _m: None), 2)
        self.assertIn("ausente", (package / "importacao.txt").read_text(encoding="utf-8"))
        self.assertEqual(self._cell("G2"), "Não")

    def test_publish_confirms_azure_before_marking_and_skips_when_already_present(self) -> None:
        package = self._imported_ready()
        code = publish_screens(self.config, package, self.azure, log=lambda _m: None)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.azure.updates), 1)
        self.assertNotIn(SECRET, self.azure.updates[0][0])
        self.assertEqual(self._cell("G2"), "SIM")
        self.assertEqual(self._cell("I2"), f"observação {SECRET}")

    def test_existing_azure_content_marks_without_a_second_write(self) -> None:
        package = self._imported_ready()
        payload = json.loads((package / "respostas" / "us-10.json").read_text(encoding="utf-8"))
        analysis = validate_analysis(payload, self.clone)
        self.azure.work_item.description_html = markdown_to_html(analysis.documentation_markdown)
        self.azure.work_item.acceptance_html = acceptance_criteria_html(analysis.acceptance_criteria)
        code = publish_screens(self.config, package, self.azure, log=lambda _m: None)
        self.assertEqual(code, 0)
        self.assertEqual(self.azure.updates, [])
        self.assertEqual(self._cell("G2"), "SIM")

    def test_moved_or_foreign_row_is_not_marked(self) -> None:
        package = self._imported_ready()
        write_workbook(self.sheet, [["Outra", "Não", "CRUD", LINK.format(id=99), ""]])
        code = publish_screens(self.config, package, self.azure, log=lambda _m: None)
        self.assertEqual(code, 2)
        self.assertEqual(self.azure.updates, [])
        self.assertEqual(self._cell("G2"), "Não")

    def test_review_command_does_not_publish_or_print_the_secret(self) -> None:
        package = self._imported_ready()
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = main(["review", "--config", str(self.root / "config.json"), "--package", str(package)])
        text = stdout.getvalue()
        self.assertEqual(code, 0, text)
        self.assertIn("pronta", text)
        self.assertIn("Nenhuma US foi publicada", text)
        self.assertNotIn(SECRET, text)
        self.assertEqual(self.azure.updates, [])
        self.assertEqual(self._cell("G2"), "Não")

    def _imported_ready(self) -> Path:
        package, _code = collect_screens(self.config, self.azure, limit=None, only_id=None, log=lambda _m: None)
        payload = ready_payload(self.paths)
        payload["work_item_id"] = 10
        payload["documentation_markdown"] += f"\n{SECRET}\n"
        source = self.root / "respostas"
        source.mkdir()
        (source / "clientes.md").write_text("```json\n" + json.dumps(payload) + "\n```\n", encoding="utf-8")
        self.assertEqual(import_screens(self.config, package, source, log=lambda _m: None), 0)
        stored = (package / "respostas" / "us-10.documentacao.md").read_text(encoding="utf-8")
        self.assertNotIn(SECRET, stored)
        self.assertEqual(self._cell("G2"), "Não")
        return package

    def _work_item(self) -> tuple[WorkItem, list[Comment]]:
        work_item = WorkItem(
            id=10,
            title="Cadastro de clientes",
            work_item_type="User Story",
            state="New",
            description_html="<p>Objetivo</p>",
            acceptance_html="<p>critério antigo</p>",
            relations=[Relation("System.LinkTypes.Related", "https://dev.azure.com/org/proj/_apis/wit/workItems/2", "Related")],
            url=LINK.format(id=10),
        )
        return work_item, [Comment("Ana", "2026-01-01", "preservar o atalho")]

    def _cell(self, coordinate: str) -> object:
        workbook = load_workbook(self.sheet)
        try:
            return workbook.active[coordinate].value
        finally:
            workbook.close()


if __name__ == "__main__":
    unittest.main()
