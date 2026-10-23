import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import support  # noqa: F401
from openpyxl import load_workbook
from support import LINK, write_config, write_workbook
from teladoc_bot.cli import main


class CliTests(unittest.TestCase):
    def test_run_stops_when_codex_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clone = root / "retaguarda"
            clone.mkdir()
            sheet = root / "planilha.xlsx"
            write_workbook(sheet, [["Clientes", "Não", "CRUD", LINK.format(id=10), ""]])
            write_config(root, sheet, clone, root / "output")
            stderr = StringIO()
            with redirect_stderr(stderr):
                code = main(["run", "--config", str(root / "config.json"), "--codex-bin", str(root / "codex-ausente")])
            workbook = load_workbook(sheet)
            documentation = workbook.active["G2"].value
            workbook.close()
        self.assertEqual(code, 1)
        self.assertEqual(documentation, "Não")
        self.assertIn("Nenhuma análise foi executada.", stderr.getvalue())
        self.assertNotIn("publicada", stderr.getvalue())

    def test_check_lists_rows_and_does_not_print_the_pat(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clone = root / "retaguarda"
            clone.mkdir()
            sheet = root / "planilha.xlsx"
            write_workbook(
                sheet,
                [
                    ["Clientes", "Não", "CRUD", LINK.format(id=10), ""],
                    ["Sem link", "Não", "CRUD", "", ""],
                ],
            )
            write_config(root, sheet, clone, root / "output")
            binary = root / "codex"
            binary.write_text("#!/usr/bin/env python3\nimport sys\nprint('codex-cli test')\nraise SystemExit(0 if '--version' in sys.argv else 1)\n", encoding="utf-8")
            binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
            previous = os.environ.get("AZURE_DEVOPS_PAT")
            os.environ["AZURE_DEVOPS_PAT"] = "token-super-secreto"
            stdout = StringIO()
            stderr = StringIO()
            try:
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main(["check", "--config", str(root / "config.json"), "--codex-bin", str(binary)])
            finally:
                if previous is None:
                    os.environ.pop("AZURE_DEVOPS_PAT", None)
                else:
                    os.environ["AZURE_DEVOPS_PAT"] = previous
        self.assertEqual(code, 0, stderr.getvalue())
        text = stdout.getvalue()
        self.assertIn("codex-cli test", text)
        self.assertIn("elegível | linha 2 | Clientes | US 10", text)
        self.assertIn("link calculado ausente", text)
        self.assertNotIn("token-super-secreto", text)
        self.assertNotIn("token-super-secreto", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
