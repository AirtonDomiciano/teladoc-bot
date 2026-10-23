import json
import tempfile
import unittest
from pathlib import Path

import support
from support import REPO
from teladoc_bot.azure_link import parse_work_item_link
from teladoc_bot.config import Config, ConfigError
from teladoc_bot.prompting import read_base_prompt
from teladoc_bot.sections import REQUIRED_HEADINGS, RESPONSE_FIELDS
from teladoc_bot.textutil import canonical_text, normalize


class TextAndLinkTests(unittest.TestCase):
    def test_normalize_ignores_case_spaces_and_accents(self) -> None:
        self.assertEqual(normalize("  NÃO \u00a0 "), "nao")
        self.assertEqual(normalize("Crúd"), "crud")
        self.assertEqual(normalize("HÁRD   CRUD"), "hard crud")
        self.assertNotEqual(normalize("HARD CRUD"), normalize("CRUD"))

    def test_canonical_text_ignores_html_wrapper(self) -> None:
        sent = "<h2>Nome</h2><p>Campo obrigatório</p>"
        remote = "<div>\n<h2>Nome</h2>\n<p>Campo   obrigatório</p>\n</div>"
        self.assertEqual(canonical_text(sent), canonical_text(remote))

    def test_work_item_links(self) -> None:
        parsed = parse_work_item_link("https://dev.azure.com/imex/Retaguarda%20Web/_workitems/edit/321?src=WorkItem")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual((parsed.organization, parsed.project, parsed.id), ("imex", "Retaguarda Web", 321))

        visual = parse_work_item_link("https://imex.visualstudio.com/DefaultCollection/Projeto/_workitems/edit/7")
        self.assertIsNotNone(visual)
        assert visual is not None
        self.assertEqual((visual.organization, visual.project, visual.id), ("imex", "Projeto", 7))

        api = parse_work_item_link("https://dev.azure.com/org/proj/_apis/wit/workitems/15")
        self.assertIsNotNone(api)
        self.assertIsNone(parse_work_item_link(""))
        self.assertIsNone(parse_work_item_link("12345"))
        self.assertIsNone(parse_work_item_link("https://dev.azure.com/org/proj/_boards/board/t/time?workitem=9"))
        self.assertIsNone(parse_work_item_link("https://example.com/workitems/edit/4"))


class ContractTests(unittest.TestCase):
    def test_prompt_and_schema_share_the_contract(self) -> None:
        prompt, version = read_base_prompt(REPO / "prompts" / "documentacao_tela.md")
        self.assertEqual(version, "1")
        for heading in REQUIRED_HEADINGS:
            self.assertIn(heading, prompt)
        schema = json.loads((REPO / "schema" / "resposta_analise.json").read_text(encoding="utf-8"))
        self.assertTrue(set(RESPONSE_FIELDS).issubset(schema["required"]))
        self.assertFalse(schema["additionalProperties"])

    def test_example_config_starts_without_publishing(self) -> None:
        config = Config.load(REPO / "config.example.json")
        self.assertFalse(config.publish)
        self.assertEqual(config.executor, "codex")
        self.assertEqual(config.columns.status, "Status")
        self.assertIn("memories", config.disable_features)

    def test_environment_overrides_paths_without_replacing_existing_variables(self) -> None:
        import os
        import tempfile

        from teladoc_bot.config import apply_environment, load_dotenv
        from teladoc_bot.runner import require_pat

        config = Config.load(REPO / "config.example.json")
        saved = {key: os.environ.get(key) for key in ("PLANILHA_PATH", "PLANILHA_ABA", "RETAGUARDA_PATH", "AZURE_DEVOPS_PAT", "AZURE_PAT")}
        os.environ.pop("AZURE_DEVOPS_PAT", None)
        os.environ["AZURE_PAT"] = "token-do-teste"
        os.environ["PLANILHA_PATH"] = "/tmp/teladoc-planilha.xlsx"
        os.environ["PLANILHA_ABA"] = "Telas"
        os.environ["RETAGUARDA_PATH"] = "/tmp/teladoc-retaguarda"
        try:
            updated = apply_environment(config)
            self.assertEqual(updated.sheet, "Telas")
            self.assertEqual(updated.spreadsheet_path, Path("/tmp/teladoc-planilha.xlsx"))
            self.assertEqual(updated.retaguarda_path, Path("/tmp/teladoc-retaguarda"))
            self.assertEqual(require_pat(updated), "token-do-teste")
            with tempfile.TemporaryDirectory() as directory:
                env_file = Path(directory) / ".env"
                env_file.write_text("PLANILHA_ABA=Outra\nAZURE_PAT=nao-usar\n", encoding="utf-8")
                load_dotenv(env_file)
            self.assertEqual(os.environ["PLANILHA_ABA"], "Telas")
            self.assertEqual(os.environ["AZURE_PAT"], "token-do-teste")
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_config_rejects_embedded_secret(self) -> None:
        path = REPO / "config.example.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["azure"]["pat"] = "nao-gravar"
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory) / "config.json"
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ConfigError):
                Config.load(temporary)


if __name__ == "__main__":
    unittest.main()
