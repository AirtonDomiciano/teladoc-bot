import json
import os
import stat
import tempfile
import textwrap
import unittest
from pathlib import Path

import support  # noqa: F401
from teladoc_bot.codex import DEPENDENCY_MESSAGE, CodexExecutor, CodexUnavailable, resolve_codex_bin


def write_executable(path: Path, source: str) -> None:
    path.write_text(textwrap.dedent(source).lstrip("\n"), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class CodexExecutorTests(unittest.TestCase):
    def test_missing_binary_does_not_invent_a_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "codex"
            with self.assertRaises(CodexUnavailable) as caught:
                CodexExecutor(
                    configured_bin=str(missing),
                    model=None,
                    timeout_seconds=5,
                    disable_features=(),
                    ignore_user_config=False,
                )
        self.assertIn("Nenhuma análise foi executada.", str(caught.exception))
        self.assertIn("Nenhuma análise foi executada.", DEPENDENCY_MESSAGE)

    def test_discovery_finds_an_extension_binary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            binary = home / ".vscode/extensions/openai.chatgpt-9/bin/linux-x86_64/codex"
            binary.parent.mkdir(parents=True)
            write_executable(binary, "#!/bin/sh\necho codex-cli test\n")
            found = resolve_codex_bin(None, environ={}, which=lambda _name: None, home=home)
            self.assertEqual(found, binary)

    def test_command_is_a_new_read_only_session_and_hides_the_pat(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = root / "record.json"
            binary = root / "codex"
            write_executable(
                binary,
                """
                #!/usr/bin/env python3
                import json, os, sys
                from pathlib import Path
                if "--version" in sys.argv:
                    print("codex-cli test")
                    raise SystemExit(0)
                output = Path(sys.argv[sys.argv.index("-o") + 1])
                output.write_text('{"status":"pending"}\\n', encoding="utf-8")
                Path(os.environ["TELADOC_RECORD"]).write_text(json.dumps({
                    "argv": sys.argv,
                    "stdin": sys.stdin.read(),
                    "pat": os.environ.get("AZURE_DEVOPS_PAT"),
                    "azure_pat": os.environ.get("AZURE_PAT"),
                }), encoding="utf-8")
                """,
            )
            schema = root / "schema.json"
            schema.write_text("{}", encoding="utf-8")
            workspace = root / "repo"
            workspace.mkdir()
            previous = os.environ.get("AZURE_DEVOPS_PAT")
            previous_azure = os.environ.get("AZURE_PAT")
            os.environ["AZURE_DEVOPS_PAT"] = "segredo-pat"
            os.environ["AZURE_PAT"] = "outro-segredo"
            os.environ["TELADOC_RECORD"] = str(record)
            try:
                executor = CodexExecutor(
                    configured_bin=str(binary),
                    model=None,
                    timeout_seconds=30,
                    disable_features=("memories", "multi_agent"),
                    ignore_user_config=False,
                    secret_env_names=("AZURE_DEVOPS_PAT",),
                )
                self.assertIn("codex-cli", executor.ensure_available())
                result = executor.run(
                    prompt="analise somente esta tela",
                    workspace=workspace,
                    schema_path=schema,
                    artifact_dir=root / "artifacts",
                )
            finally:
                if previous is None:
                    os.environ.pop("AZURE_DEVOPS_PAT", None)
                else:
                    os.environ["AZURE_DEVOPS_PAT"] = previous
                if previous_azure is None:
                    os.environ.pop("AZURE_PAT", None)
                else:
                    os.environ["AZURE_PAT"] = previous_azure
                os.environ.pop("TELADOC_RECORD", None)
            recorded = json.loads(record.read_text(encoding="utf-8"))
            argv = recorded["argv"][1:]
            self.assertEqual(argv[0], "exec")
            self.assertEqual(argv[-1], "-")
            self.assertIn("--sandbox", argv)
            self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
            for flag in ("--ephemeral", "--json", "--output-schema", "--skip-git-repo-check", "-C", "-o"):
                self.assertIn(flag, argv)
            self.assertEqual(argv[argv.index("--disable") + 1], "memories")
            self.assertNotIn("resume", argv)
            self.assertNotIn("fork", argv)
            self.assertNotIn("workspace-write", argv)
            self.assertNotIn("dangerously-bypass-approvals-and-sandbox", argv)
            self.assertEqual(recorded["stdin"], "analise somente esta tela")
            self.assertIsNone(recorded["pat"])
            self.assertIsNone(recorded["azure_pat"])
            self.assertIsNone(result.error)
            self.assertEqual(result.last_message, '{"status":"pending"}')

    def test_timeout_is_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "codex"
            write_executable(
                binary,
                """
                #!/usr/bin/env python3
                import sys, time
                if "--version" in sys.argv:
                    print("codex-cli test")
                    raise SystemExit(0)
                time.sleep(30)
                """,
            )
            executor = CodexExecutor(
                configured_bin=str(binary),
                model=None,
                timeout_seconds=1,
                disable_features=(),
                ignore_user_config=False,
            )
            executor.ensure_available()
            result = executor.run(
                prompt="demorado",
                workspace=root,
                schema_path=root / "schema.json",
                artifact_dir=root / "artifacts",
            )
            self.assertIsNotNone(result.error)
            self.assertIn("Tempo esgotado", result.error or "")
            self.assertEqual(result.last_message, "")


if __name__ == "__main__":
    unittest.main()
