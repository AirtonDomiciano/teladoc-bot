"""Carrega a configuração do bot a partir de um arquivo JSON."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path


class ConfigError(ValueError):
    """Configuração ausente ou inválida."""


@dataclass(frozen=True)
class ColumnMap:
    screen_name: str
    documentation: str
    status: str
    azure_link: str
    notes: str


@dataclass(frozen=True)
class Config:
    spreadsheet_path: Path
    sheet: str | None
    header_row: int
    columns: ColumnMap
    retaguarda_path: Path
    prompt_path: Path
    schema_path: Path
    output_dir: Path
    publish: bool
    pat_env: str
    api_version: str
    comments_api_version: str
    description_field: str
    acceptance_field: str
    azure_timeout_seconds: int
    executor: str
    codex_bin: str | None
    model: str | None
    timeout_seconds: int
    disable_features: tuple[str, ...]
    ignore_user_config: bool

    @staticmethod
    def load(path: Path) -> Config:
        path = path.expanduser().resolve()
        if not path.is_file():
            raise ConfigError(f"Arquivo de configuração não encontrado: {path}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"JSON inválido em {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigError("A configuração precisa ser um objeto JSON.")
        base = path.parent
        spreadsheet = _object(raw, "spreadsheet")
        columns = _object(spreadsheet, "columns")
        azure = raw.get("azure") or {}
        agent = raw.get("agent") or {}
        if not isinstance(azure, dict) or not isinstance(agent, dict):
            raise ConfigError("As seções azure e agent precisam ser objetos.")
        if any(str(key).casefold() in {"pat", "token", "password", "secret"} for key in azure):
            raise ConfigError("Não grave segredos no JSON. Use a variável indicada em azure.pat_env.")
        column_map = ColumnMap(
            screen_name=_required_str(columns, "screen_name"),
            documentation=_required_str(columns, "documentation"),
            status=_required_str(columns, "status"),
            azure_link=_required_str(columns, "azure_link"),
            notes=_required_str(columns, "notes"),
        )
        features = agent.get("disable_features", ["memories", "multi_agent", "browser_use", "computer_use"])
        if not isinstance(features, list) or not all(isinstance(item, str) and item.strip() for item in features):
            raise ConfigError("agent.disable_features precisa ser uma lista de nomes de feature.")
        return Config(
            spreadsheet_path=_resolve(base, _required_str(spreadsheet, "path")),
            sheet=_optional_str(spreadsheet.get("sheet")),
            header_row=_positive_int(spreadsheet.get("header_row", 1), "spreadsheet.header_row"),
            columns=column_map,
            retaguarda_path=_resolve(base, _required_str(raw, "retaguarda_path")),
            prompt_path=_resolve(base, str(raw.get("prompt_path") or "prompts/documentacao_tela.md")),
            schema_path=_resolve(base, str(raw.get("schema_path") or "schema/resposta_analise.json")),
            output_dir=_resolve(base, str(raw.get("output_dir") or "output")),
            publish=bool(raw.get("publish", False)),
            pat_env=str(azure.get("pat_env") or "AZURE_DEVOPS_PAT"),
            api_version=str(azure.get("api_version") or "7.1"),
            comments_api_version=str(azure.get("comments_api_version") or "7.1-preview.4"),
            description_field=str(azure.get("description_field") or "System.Description"),
            acceptance_field=str(
                azure.get("acceptance_criteria_field") or "Microsoft.VSTS.Common.AcceptanceCriteria"
            ),
            azure_timeout_seconds=_positive_int(azure.get("timeout_seconds", 60), "azure.timeout_seconds"),
            executor=str(agent.get("executor") or "codex"),
            codex_bin=_optional_str(agent.get("codex_bin")),
            model=_optional_str(agent.get("model")),
            timeout_seconds=_positive_int(agent.get("timeout_seconds", 1800), "agent.timeout_seconds"),
            disable_features=tuple(item.strip() for item in features),
            ignore_user_config=bool(agent.get("ignore_user_config", False)),
        )


def _object(payload: dict, key: str) -> dict:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"A configuração precisa do objeto '{key}'.")
    return value


def _required_str(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"O campo '{key}' é obrigatório.")
    return value.strip()


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError("Um campo opcional de texto recebeu outro tipo.")
    stripped = value.strip()
    return stripped or None


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{label} precisa ser um inteiro positivo.")
    return value


def _resolve(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def load_dotenv(path: Path) -> None:
    """Carrega um .env sem substituir variáveis que já existem no processo."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def apply_environment(config: Config) -> Config:
    """Planilha, aba e clone podem vir do ambiente e prevalecem sobre o JSON."""
    updates: dict = {}
    spreadsheet = os.environ.get("PLANILHA_PATH", "").strip()
    sheet = os.environ.get("PLANILHA_ABA", "").strip()
    retaguarda = os.environ.get("RETAGUARDA_PATH", "").strip()
    if spreadsheet:
        updates["spreadsheet_path"] = Path(spreadsheet).expanduser().resolve()
    if sheet:
        updates["sheet"] = sheet
    if retaguarda:
        updates["retaguarda_path"] = Path(retaguarda).expanduser().resolve()
    return replace(config, **updates) if updates else config
