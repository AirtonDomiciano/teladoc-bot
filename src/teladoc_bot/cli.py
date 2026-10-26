"""Interface de terminal do TelaDoc Bot."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from teladoc_bot.azure import AzureError
from teladoc_bot.codex import CodexUnavailable, create_executor
from teladoc_bot.config import Config, ConfigError, apply_environment, load_dotenv
from teladoc_bot.handoff import collect_screens, import_screens, publish_screens, review_screens
from teladoc_bot.prompting import PromptError, read_base_prompt
from teladoc_bot.runner import _require_schema, azure_from_config, execute, require_pat
from teladoc_bot.spreadsheet import load_rows


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        config_path = Path(args.config)
        load_dotenv(config_path.expanduser().resolve().parent / ".env")
        config = apply_overrides(apply_environment(Config.load(config_path)), args)
        if args.command == "check":
            return check(config)
        if args.command == "collect":
            _package, code = collect_screens(
                config,
                azure_from_config(config),
                limit=_limit(args),
                only_id=getattr(args, "only_id", None),
                screen_dir=getattr(args, "screen_dir", None),
            )
            return code
        if args.command == "import":
            return import_screens(config, _path_arg(args.package), _path_arg(args.source))
        if args.command == "review":
            return review_screens(config, _path_arg(args.package))
        if args.command == "publish":
            return publish_screens(config, _path_arg(args.package), azure_from_config(config))
        publish = config.publish
        limit = _limit(args)
        executor = create_executor(config)
        azure = azure_from_config(config)
        report = execute(
            config,
            executor=executor,
            azure=azure,
            publish=publish,
            limit=limit,
            only_id=args.only_id,
            screen_dir=getattr(args, "screen_dir", None),
        )
    except (ConfigError, PromptError, CodexUnavailable, AzureError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Resumo: {report.run_dir / 'resumo.txt'}")
    return report.exit_code


def check(config: Config) -> int:
    problems: list[str] = []
    try:
        version = create_executor(config).ensure_available()
        print(f"Codex CLI: {version}")
    except (CodexUnavailable, ConfigError) as exc:
        problems.append(str(exc))
    try:
        _require_schema(config.schema_path)
        _, prompt_version = read_base_prompt(config.prompt_path)
        print(f"Prompt base: versão {prompt_version} ({config.prompt_path})")
    except PromptError as exc:
        problems.append(str(exc))
    if not config.retaguarda_path.is_dir():
        problems.append(f"Clone do RetaguardaWeb não encontrado: {config.retaguarda_path}")
    else:
        print(f"RetaguardaWeb: {config.retaguarda_path}")
    try:
        require_pat(config)
        print("PAT disponível.")
    except PromptError as exc:
        problems.append(str(exc))
    try:
        rows = load_rows(config.spreadsheet_path, config.sheet, config.header_row, config.columns)
    except ConfigError as exc:
        problems.append(str(exc))
        rows = []
    eligible = [row for row in rows if row.skip_reason is None]
    ignored = [row for row in rows if row.skip_reason]
    print(f"Linhas com conteúdo: {len(rows)}. Elegíveis: {len(eligible)}. Ignoradas: {len(ignored)}.")
    for row in eligible:
        assert row.work_item is not None
        print(f"elegível | linha {row.excel_row} | {row.screen_name} | US {row.work_item.id}")
    for row in ignored:
        print(f"ignorada | linha {row.excel_row} | {row.screen_name or '(sem nome)'} | {row.skip_reason}")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print("Publicação habilitada." if config.publish else "Publicação desabilitada.")
    return 0


def apply_overrides(config: Config, args: argparse.Namespace) -> Config:
    updates: dict = {}
    if getattr(args, "spreadsheet", None):
        updates["spreadsheet_path"] = Path(args.spreadsheet).expanduser().resolve()
    if getattr(args, "sheet", None):
        updates["sheet"] = args.sheet
    if getattr(args, "retaguarda", None):
        updates["retaguarda_path"] = Path(args.retaguarda).expanduser().resolve()
    if getattr(args, "codex_bin", None):
        updates["codex_bin"] = args.codex_bin
    if getattr(args, "output_dir", None):
        updates["output_dir"] = Path(args.output_dir).expanduser().resolve()
    publish = getattr(args, "publish", False)
    no_publish = getattr(args, "no_publish", False)
    if publish and no_publish:
        raise ConfigError("Use apenas uma das opções --publish ou --no-publish.")
    if publish:
        updates["publish"] = True
    if no_publish:
        updates["publish"] = False
    return replace(config, **updates) if updates else config


def _limit(args: argparse.Namespace) -> int | None:
    limit = getattr(args, "limit", None)
    if limit is not None and limit <= 0:
        raise ConfigError("--limit precisa ser um inteiro positivo.")
    return limit


def _path_arg(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="teladoc-bot",
        description="Documenta telas CRUD da planilha com o clone local do RetaguardaWeb e a US no Azure DevOps.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", required=True, help="Caminho do JSON de configuração.")
    check_parser = subcommands.add_parser("check", parents=[common], help="Confere Codex, planilha, prompt e PAT.")
    check_parser.add_argument("--spreadsheet", help="Substitui o caminho da planilha.")
    check_parser.add_argument("--sheet", help="Substitui a aba da planilha.")
    check_parser.add_argument("--retaguarda", help="Substitui o caminho do clone.")
    check_parser.add_argument("--codex-bin", help="Substitui o executável do Codex CLI.")
    run_parser = subcommands.add_parser("run", parents=[common], help="Processa as linhas elegíveis, uma sessão por tela.")
    run_parser.add_argument("--spreadsheet", help="Substitui o caminho da planilha.")
    run_parser.add_argument("--sheet", help="Substitui a aba da planilha.")
    run_parser.add_argument("--retaguarda", help="Substitui o caminho do clone.")
    run_parser.add_argument("--codex-bin", help="Substitui o executável do Codex CLI.")
    run_parser.add_argument("--output-dir", help="Substitui o diretório de evidências.")
    run_parser.add_argument("--publish", action="store_true", help="Atualiza a US e marca a planilha depois da confirmação.")
    run_parser.add_argument("--no-publish", action="store_true", help="Mantém a publicação desligada nesta execução.")
    run_parser.add_argument("--limit", type=int, help="Quantidade máxima de telas analisadas nesta execução.")
    run_parser.add_argument("--only-id", type=int, help="Analisa somente a US com este ID.")
    run_parser.add_argument(
        "--screen-dir",
        help="Diretório da tela relativo ao clone, já confirmado. Vale para uma única US.",
    )
    collect_parser = subcommands.add_parser(
        "collect",
        parents=[common],
        help="Exporta o pacote Markdown das telas elegíveis, sem chamar IA.",
    )
    collect_parser.add_argument("--spreadsheet", help="Substitui o caminho da planilha.")
    collect_parser.add_argument("--sheet", help="Substitui a aba da planilha.")
    collect_parser.add_argument("--retaguarda", help="Substitui o caminho do clone.")
    collect_parser.add_argument("--output-dir", help="Substitui o diretório de evidências.")
    collect_parser.add_argument("--limit", type=int, help="Quantidade máxima de telas exportadas nesta coleta.")
    collect_parser.add_argument("--only-id", type=int, help="Exporta somente a US com este ID.")
    collect_parser.add_argument(
        "--screen-dir",
        help="Diretório da tela relativo ao clone. As evidências saem desse diretório.",
    )
    import_parser = subcommands.add_parser(
        "import",
        parents=[common],
        help="Importa o conteúdo elaborado e valida cada tela, sem publicar.",
    )
    import_parser.add_argument("--package", required=True, help="Diretório do pacote gerado por collect.")
    import_parser.add_argument("--from", dest="source", required=True, help="Diretório com o JSON, ou Markdown contendo o JSON, de cada US.")
    import_parser.add_argument("--retaguarda", help="Substitui o caminho do clone.")
    review_parser = subcommands.add_parser(
        "review",
        parents=[common],
        help="Confere o conteúdo importado, sem publicar e sem alterar a planilha.",
    )
    review_parser.add_argument("--package", required=True, help="Diretório do pacote gerado por collect.")
    review_parser.add_argument("--spreadsheet", help="Substitui o caminho da planilha.")
    review_parser.add_argument("--sheet", help="Substitui a aba da planilha.")
    review_parser.add_argument("--retaguarda", help="Substitui o caminho do clone.")
    publish_parser = subcommands.add_parser(
        "publish",
        parents=[common],
        help="Publica as telas aprovadas e marca SIM somente depois da confirmação.",
    )
    publish_parser.add_argument("--package", required=True, help="Diretório do pacote gerado por collect.")
    publish_parser.add_argument("--spreadsheet", help="Substitui o caminho da planilha.")
    publish_parser.add_argument("--sheet", help="Substitui a aba da planilha.")
    publish_parser.add_argument("--retaguarda", help="Substitui o caminho do clone.")
    return parser
