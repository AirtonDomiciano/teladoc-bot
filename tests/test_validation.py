import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401
from support import documentation, ready_payload, seed_clone
from teladoc_bot.htmlutil import markdown_to_html
from teladoc_bot.textutil import canonical_text
from teladoc_bot.validation import parse_json_object, validate_analysis


class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.paths = seed_clone(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_ready_response_is_publishable(self) -> None:
        analysis = validate_analysis(ready_payload(self.paths), self.root)
        self.assertTrue(analysis.publishable)
        self.assertEqual(analysis.outcome, "ready")

    def test_missing_file_key_or_heading_blocks_publication(self) -> None:
        missing_file = ready_payload(self.paths)
        missing_file["files_consulted"] = ["src/app/nao-existe.component.ts"]
        self.assertFalse(validate_analysis(missing_file, self.root).publishable)

        outside = ready_payload(["../segredo.ts"])
        self.assertFalse(validate_analysis(outside, self.root).publishable)

        invented_key = ready_payload(self.paths)
        invented_key["documentation_markdown"] = documentation(self.paths).replace("nomeCliente", "campoInventado")
        analysis = validate_analysis(invented_key, self.root)
        self.assertFalse(analysis.publishable)
        self.assertTrue(any("campoInventado" in reason for reason in analysis.reasons))

        partial_key = ready_payload(self.paths)
        partial_key["documentation_markdown"] = documentation(self.paths).replace("| nomeCliente |", "| nome |")
        self.assertFalse(validate_analysis(partial_key, self.root).publishable)

        missing_heading = ready_payload(self.paths)
        missing_heading["documentation_markdown"] = missing_heading["documentation_markdown"].replace("## 4. Figma DS\n", "")
        self.assertFalse(validate_analysis(missing_heading, self.root).publishable)

    def test_pending_and_review_are_not_published(self) -> None:
        pending = ready_payload(self.paths)
        pending["status"] = "pending"
        pending["pending_reason"] = "O payload de gravação não foi encontrado."
        analysis = validate_analysis(pending, self.root)
        self.assertFalse(analysis.publishable)
        self.assertEqual(analysis.outcome, "pendente")

        review = ready_payload(self.paths)
        review["status"] = "needs_review"
        review["needs_review_reason"] = "A tela orquestra três entidades."
        analysis = validate_analysis(review, self.root)
        self.assertFalse(analysis.publishable)
        self.assertEqual(analysis.outcome, "revisao")

    def test_markdown_conversion_keeps_confirmed_text(self) -> None:
        plain = canonical_text(markdown_to_html(documentation(self.paths)))
        self.assertIn("nomecliente", plain)
        self.assertIn("idregistro", plain)
        self.assertIn("app-base-table", plain)
        self.assertIn("formlymodule.forroot", plain)

    def test_invalid_json_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_json_object("sem json")
        self.assertEqual(parse_json_object('```json\n{"status": "pending"}\n```')["status"], "pending")


if __name__ == "__main__":
    unittest.main()
