import json
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401
from openpyxl import load_workbook
from support import LINK, ready_payload, seed_clone, write_config, write_workbook
from teladoc_bot.azure import AzureError, Comment, Relation, WorkItem
from teladoc_bot.codex import AgentExecution, CodexUnavailable
from teladoc_bot.runner import execute


class FakeAzure:
    def __init__(self, work_item: WorkItem, comments: list[Comment], *, mismatch: bool = False, fail_update: bool = False, fail_reread: bool = False) -> None:
        self.work_item = work_item
        self.comments = comments
        self.mismatch = mismatch
        self.fail_update = fail_update
        self.fail_reread = fail_reread
        self.updates: list[tuple[str, str]] = []

    def get_work_item(self, ref) -> WorkItem:
        if self.fail_reread and self.updates:
            raise AzureError("releitura falhou")
        self.work_item.id = ref.id
        return self.work_item

    def get_comments(self, ref) -> list[Comment]:
        return self.comments

    def update_documentation(self, ref, description_html: str, acceptance_html: str) -> None:
        if self.fail_update:
            raise AzureError("patch falhou")
        self.updates.append((description_html, acceptance_html))
        if self.mismatch:
            self.work_item.description_html = "<p>conteúdo diferente</p>"
            self.work_item.acceptance_html = "<p>conteúdo diferente</p>"
            return
        self.work_item.description_html = f"<div>{description_html}</div>"
        self.work_item.acceptance_html = f"<div>{acceptance_html}</div>"


class FakeExecutor:
    def __init__(self, payloads: list[object]) -> None:
        self.payloads = list(payloads)
        self.prompts: list[str] = []

    def ensure_available(self) -> str:
        return "codex-cli test"

    def run(self, *, prompt: str, workspace: Path, schema_path: Path, artifact_dir: Path) -> AgentExecution:
        self.prompts.append(prompt)
        item = self.payloads.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, AgentExecution):
            return item
        return AgentExecution(
            command=["codex", "exec", "-"],
            returncode=0,
            last_message=json.dumps(item, ensure_ascii=False),
            error=None,
        )


def sample_work_item() -> tuple[WorkItem, list[Comment]]:
    work_item = WorkItem(
        id=10,
        title="Cadastro de clientes",
        work_item_type="User Story",
        state="New",
        description_html='<p>Objetivo <a href="https://figma.example/ds">DS</a></p>',
        acceptance_html="<p>critério antigo</p>",
        relations=[Relation("System.LinkTypes.Related", "https://dev.azure.com/org/proj/_apis/wit/workItems/2", "Related")],
        url=LINK.format(id=10),
    )
    return work_item, [Comment("Ana", "2026-01-01", "preservar o atalho")]


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.clone = self.root / "retaguarda"
        self.paths = seed_clone(self.clone)
        self.output = self.root / "output"
        self.sheet = self.root / "planilha.xlsx"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_publish_marks_sim_only_after_confirmation(self) -> None:
        self._sheet([["Clientes", "Não", "CRUD", LINK.format(id=10), "manter o filtro de situação"]])
        config = write_config(self.root, self.sheet, self.clone, self.output)
        work_item, comments = sample_work_item()
        azure = FakeAzure(work_item, comments)
        executor = FakeExecutor([ready_payload(self.paths)])
        report = execute(config, executor=executor, azure=azure, publish=True, limit=None, only_id=None, log=lambda _m: None)
        self.assertEqual(report.exit_code, 0)
        self.assertEqual(report.results[-1].outcome, "publicada")
        self.assertTrue(report.results[-1].marked)
        self.assertEqual(len(azure.updates), 1)
        self.assertEqual(self._cell("B2"), "Sim")
        self.assertEqual(self._cell("E2"), "manter o filtro de situação")
        prompt = executor.prompts[0]
        self.assertIn("manter o filtro de situação", prompt)
        self.assertIn("Cadastro de clientes", prompt)
        self.assertIn("preservar o atalho", prompt)
        self.assertIn("https://figma.example/ds", prompt)
        self.assertIn(str(self.clone), prompt)
        self.assertIn("teladoc-prompt-version: 1", prompt)
        self.assertIn("AGENTS.md", prompt)
        document = next((self.output.rglob("documentacao.md")))
        self.assertIn("nomeCliente", document.read_text(encoding="utf-8"))

    def test_confirmation_mismatch_keeps_nao(self) -> None:
        self._sheet([["Clientes", "Não", "CRUD", LINK.format(id=10), ""]])
        config = write_config(self.root, self.sheet, self.clone, self.output)
        work_item, comments = sample_work_item()
        azure = FakeAzure(work_item, comments, mismatch=True)
        report = execute(
            config,
            executor=FakeExecutor([ready_payload(self.paths)]),
            azure=azure,
            publish=True,
            limit=None,
            only_id=None,
            log=lambda _m: None,
        )
        self.assertEqual(report.exit_code, 2)
        self.assertEqual(report.results[0].outcome, "falha_confirmacao")
        self.assertEqual(self._cell("B2"), "Não")
        self.assertEqual(len(azure.updates), 1)

    def test_local_analysis_does_not_touch_azure_or_the_sheet(self) -> None:
        self._sheet(
            [
                ["Clientes", "Não", "CRUD", LINK.format(id=10), ""],
                ["Árduo", "Não", "HARD CRUD", LINK.format(id=11), ""],
                ["Sem link", "Não", "CRUD", "", ""],
            ]
        )
        config = write_config(self.root, self.sheet, self.clone, self.output)
        work_item, comments = sample_work_item()
        azure = FakeAzure(work_item, comments)
        report = execute(
            config,
            executor=FakeExecutor([ready_payload(self.paths)]),
            azure=azure,
            publish=False,
            limit=None,
            only_id=None,
            log=lambda _m: None,
        )
        self.assertEqual(report.exit_code, 0)
        self.assertEqual(azure.updates, [])
        self.assertEqual(self._cell("B2"), "Não")
        self.assertEqual(self._cell("B3"), "Não")
        outcomes = {result.screen_name: result.outcome for result in report.results}
        self.assertEqual(outcomes["Clientes"], "documentada_local")
        self.assertEqual(outcomes["Árduo"], "ignorada")
        self.assertEqual(outcomes["Sem link"], "ignorada")
        self.assertIn("sem link", report.results[-1].reason)

    def test_failure_continues_and_review_does_not_mark_sim(self) -> None:
        self._sheet(
            [
                ["Primeira", "Não", "CRUD", LINK.format(id=10), ""],
                ["Segunda", "Não", "CRUD", LINK.format(id=20), ""],
                ["Terceira", "Não", "CRUD", LINK.format(id=30), ""],
            ]
        )
        config = write_config(self.root, self.sheet, self.clone, self.output)
        review = ready_payload(self.paths)
        review["status"] = "needs_review"
        review["needs_review_reason"] = "A tela controla um wizard de três etapas."
        work_item, comments = sample_work_item()
        azure = FakeAzure(work_item, comments)
        executor = FakeExecutor([RuntimeError("agente indisponível"), review, ready_payload(self.paths)])
        report = execute(config, executor=executor, azure=azure, publish=True, limit=None, only_id=None, log=lambda _m: None)
        self.assertEqual(report.exit_code, 2)
        self.assertEqual([item.outcome for item in report.results], ["pendente", "revisao", "publicada"])
        self.assertEqual(self._cell("B2"), "Não")
        self.assertEqual(self._cell("B3"), "Não")
        self.assertEqual(self._cell("B4"), "Sim")
        self.assertEqual(len(azure.updates), 1)
        self.assertEqual(len(executor.prompts), 3)

    def test_same_work_item_is_not_retried(self) -> None:
        link = LINK.format(id=10)
        self._sheet(
            [
                ["Clientes", "Não", "CRUD", link, ""],
                ["Clientes de novo", "Não", "CRUD", link, ""],
            ]
        )
        config = write_config(self.root, self.sheet, self.clone, self.output)
        work_item, comments = sample_work_item()
        executor = FakeExecutor([ready_payload(self.paths), ready_payload(self.paths)])
        report = execute(
            config,
            executor=executor,
            azure=FakeAzure(work_item, comments),
            publish=True,
            limit=None,
            only_id=None,
            log=lambda _m: None,
        )
        self.assertEqual(len(executor.prompts), 1)
        self.assertEqual(report.results[1].reason, "work item já processado nesta execução")
        self.assertEqual(self._cell("B2"), "Sim")
        self.assertEqual(self._cell("B3"), "Não")

    def test_codex_disappearance_stops_the_loop(self) -> None:
        self._sheet(
            [
                ["Primeira", "Não", "CRUD", LINK.format(id=10), ""],
                ["Segunda", "Não", "CRUD", LINK.format(id=20), ""],
            ]
        )
        config = write_config(self.root, self.sheet, self.clone, self.output)
        work_item, comments = sample_work_item()
        with self.assertRaises(CodexUnavailable):
            execute(
                config,
                executor=FakeExecutor([CodexUnavailable("Codex CLI sumiu no meio da execução.")]),
                azure=FakeAzure(work_item, comments),
                publish=True,
                limit=None,
                only_id=None,
                log=lambda _m: None,
            )
        self.assertEqual(self._cell("B2"), "Não")
        self.assertEqual(self._cell("B3"), "Não")
        summary = json.loads(next(self.output.rglob("resumo.json")).read_text(encoding="utf-8"))
        self.assertEqual(summary["results"][0]["outcome"], "pendente")
        self.assertEqual(len(summary["results"]), 1)

    def _sheet(self, rows: list[list[object]]) -> None:
        write_workbook(self.sheet, rows)

    def _cell(self, coordinate: str) -> object:
        workbook = load_workbook(self.sheet)
        try:
            return workbook.active[coordinate].value
        finally:
            workbook.close()


if __name__ == "__main__":
    unittest.main()
