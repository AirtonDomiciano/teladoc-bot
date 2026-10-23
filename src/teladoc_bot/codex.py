"""Executor do Codex CLI para uma sessão nova e somente leitura por tela."""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from teladoc_bot.config import Config

_SECRET_ENV = {"AZURE_DEVOPS_PAT", "AZURE_DEVOPS_EXT_PAT", "ADO_PAT", "AZURE_DEVOPS_TOKEN"}
_DIRECT_CANDIDATES = (
    Path(".local/bin/codex"),
    Path(".npm-global/bin/codex"),
    Path(".cargo/bin/codex"),
)
_EXTENSION_ROOTS = (
    Path(".vscode/extensions"),
    Path(".cursor/extensions"),
    Path(".vscode-server/extensions"),
    Path(".cursor-server/extensions"),
)


class CodexUnavailable(RuntimeError):
    """O Codex CLI não está instalado ou não respondeu a --version."""


DEPENDENCY_MESSAGE = (
    "Dependência ausente: Codex CLI.\n"
    "O executor \"codex\" não encontrou um executável utilizável.\n"
    "Informe agent.codex_bin, exporte CODEX_BIN ou instale o Codex CLI no PATH.\n"
    "Nenhuma análise foi executada."
)


@dataclass(frozen=True)
class AgentExecution:
    command: list[str]
    returncode: int | None
    last_message: str
    error: str | None


class CodexExecutor:
    def __init__(
        self,
        *,
        configured_bin: str | None,
        model: str | None,
        timeout_seconds: int,
        disable_features: tuple[str, ...],
        ignore_user_config: bool,
        secret_env_names: tuple[str, ...] = (),
        bin_path: Path | None = None,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.disable_features = disable_features
        self.ignore_user_config = ignore_user_config
        self.secret_env_names = secret_env_names
        self.bin_path = bin_path or resolve_codex_bin(configured_bin)
        self.version: str | None = None

    def ensure_available(self) -> str:
        try:
            completed = subprocess.run(
                [str(self.bin_path), "--version"],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CodexUnavailable(f"Não foi possível executar {self.bin_path}: {exc}\n{DEPENDENCY_MESSAGE}") from exc
        text = (completed.stdout or completed.stderr).strip()
        if completed.returncode != 0 or "codex" not in text.casefold():
            raise CodexUnavailable(
                f"O executável {self.bin_path} não se identificou como Codex CLI.\n{text}\n{DEPENDENCY_MESSAGE}"
            )
        self.version = text.splitlines()[0]
        return self.version

    def build_command(self, *, workspace: Path, schema_path: Path, last_message_path: Path) -> list[str]:
        command = [
            str(self.bin_path),
            "exec",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--skip-git-repo-check",
            "--ephemeral",
            "--json",
            "--output-schema",
            str(schema_path),
            "-o",
            str(last_message_path),
            "-C",
            str(workspace),
        ]
        for feature in self.disable_features:
            command.extend(["--disable", feature])
        if self.model:
            command.extend(["-m", self.model])
        if self.ignore_user_config:
            command.append("--ignore-user-config")
        command.append("-")
        forbidden = {"resume", "fork", "dangerously-bypass-approvals-and-sandbox", "workspace-write"}
        if forbidden.intersection(command):
            raise CodexUnavailable("O comando do Codex incluía uma opção incompatível com a análise somente leitura.")
        return command

    def run(self, *, prompt: str, workspace: Path, schema_path: Path, artifact_dir: Path) -> AgentExecution:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        last_message_path = artifact_dir / "codex.last_message.txt"
        command = self.build_command(
            workspace=workspace,
            schema_path=schema_path,
            last_message_path=last_message_path,
        )
        (artifact_dir / "codex.command.txt").write_text(shlex.join(command) + "\n", encoding="utf-8")
        try:
            completed, error = _run_process(
                command,
                prompt=prompt,
                workspace=workspace,
                timeout_seconds=self.timeout_seconds,
                env=_scrub_env(self.secret_env_names),
            )
        except OSError as exc:
            error = f"Falha ao iniciar o Codex CLI: {exc}"
            completed = subprocess.CompletedProcess(command, returncode=None, stdout="", stderr="")
        (artifact_dir / "codex.stdout.jsonl").write_text(completed.stdout or "", encoding="utf-8")
        (artifact_dir / "codex.stderr.txt").write_text(completed.stderr or "", encoding="utf-8")
        last_message = ""
        if error is None and last_message_path.is_file():
            last_message = last_message_path.read_text(encoding="utf-8", errors="replace").strip()
        if error is None and completed.returncode not in (0, None):
            tail = (completed.stderr or completed.stdout or "").strip()
            error = f"Codex CLI encerrou com código {completed.returncode}."
            if tail:
                error = f"{error} {tail[-2000:]}"
        if error is None and not last_message:
            error = "Codex CLI encerrou sem a mensagem final."
        return AgentExecution(
            command=command,
            returncode=completed.returncode,
            last_message=last_message if error is None else "",
            error=error,
        )


def create_executor(config: Config) -> CodexExecutor:
    if config.executor != "codex":
        raise CodexUnavailable(
            f"Executor '{config.executor}' não está implementado. "
            "Nenhuma análise foi simulada. Executor disponível: codex."
        )
    return CodexExecutor(
        configured_bin=config.codex_bin,
        model=config.model,
        timeout_seconds=config.timeout_seconds,
        disable_features=config.disable_features,
        ignore_user_config=config.ignore_user_config,
        secret_env_names=(config.pat_env,),
    )


def resolve_codex_bin(
    explicit: str | None,
    *,
    environ: dict[str, str] | None = None,
    which=shutil.which,
    home: Path | None = None,
) -> Path:
    environment = os.environ if environ is None else environ
    if explicit:
        return _existing_executable(Path(explicit).expanduser(), explicit)
    env_bin = environment.get("CODEX_BIN")
    if env_bin:
        return _existing_executable(Path(env_bin).expanduser(), env_bin)
    found = which("codex")
    if found:
        return _existing_executable(Path(found), found)
    discovered = _discover(Path.home() if home is None else home)
    if discovered is not None:
        return discovered
    raise CodexUnavailable(DEPENDENCY_MESSAGE)


def _existing_executable(path: Path, label: str) -> Path:
    if path.is_file() and os.access(path, os.X_OK):
        return path
    raise CodexUnavailable(f"Codex CLI configurado em '{label}' não é um executável.\n{DEPENDENCY_MESSAGE}")


def _discover(home: Path) -> Path | None:
    candidates: list[Path] = []
    for relative in _DIRECT_CANDIDATES:
        candidates.append(home / relative)
    for root in _EXTENSION_ROOTS:
        base = home / root
        if not base.is_dir():
            continue
        candidates.extend(base.glob("openai.chatgpt-*/bin/*/codex"))
        candidates.extend(base.glob("openai.chatgpt-*/bin/codex"))
    executables = [path for path in candidates if path.is_file() and os.access(path, os.X_OK)]
    if not executables:
        return None
    executables.sort(key=lambda path: path.as_posix())
    return executables[-1]


def _scrub_env(extra_names: tuple[str, ...]) -> dict[str, str]:
    blocked = {name.upper() for name in extra_names}
    blocked.update(_SECRET_ENV)
    return {key: value for key, value in os.environ.items() if key.upper() not in blocked}


def _run_process(
    command: list[str],
    *,
    prompt: str,
    workspace: Path,
    timeout_seconds: int,
    env: dict[str, str],
) -> tuple[subprocess.CompletedProcess[str], str | None]:
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(workspace),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(input=prompt, timeout=timeout_seconds)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr), None
    except subprocess.TimeoutExpired:
        _terminate(process)
        stdout, stderr = process.communicate()
        completed = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        return completed, f"Tempo esgotado após {timeout_seconds}s. A tela não foi publicada."


def _terminate(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        process.kill()
