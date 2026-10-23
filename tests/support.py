"""Helpers de teste do loop e da planilha."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import json

from openpyxl import Workbook

from teladoc_bot.config import Config
from teladoc_bot.sections import REQUIRED_HEADINGS

REPO = Path(__file__).resolve().parents[1]
LINK = "https://dev.azure.com/imex/Retaguarda%20Web/_workitems/edit/{id}"


def write_workbook(path: Path, rows: list[list[object]], headers: list[str] | None = None, sheet: str = "Telas") -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet
    worksheet.append(headers or ["Nome da tela", "Documentação", "Status", "Link Azure", "Observações"])
    for row in rows:
        worksheet.append(row)
    workbook.save(path)
    workbook.close()


def seed_clone(root: Path) -> list[str]:
    relative = ["src/app/cliente.component.ts", "src/app/cliente.component.html"]
    typescript = root / relative[0]
    template = root / relative[1]
    typescript.parent.mkdir(parents=True, exist_ok=True)
    typescript.write_text(
        "export const fields = [{ key: 'nomeCliente', uniqueIdField: 'idRegistro' }];\n",
        encoding="utf-8",
    )
    template.write_text("<app-base-table></app-base-table>\n", encoding="utf-8")
    return relative


def documentation(paths: list[str], criterion: str = "O usuário consulta a lista e grava o cadastro pelo drawer.") -> str:
    blocks = []
    for heading in REQUIRED_HEADINGS:
        blocks.append(heading)
        blocks.append("Conteúdo confirmado no código da tela.")
        if heading.startswith("## 7."):
            blocks.extend(f"- {path}" for path in paths)
        elif heading.startswith("## 8."):
            blocks.extend(
                [
                    "| Componente atual | Substituir por | Onde |",
                    "| --- | --- | --- |",
                    "| app-base-table | app-base-table | listagem |",
                ]
            )
        elif heading.startswith("## 9."):
            blocks.extend(["tableId: clientes-teladoc", "uniqueIdField: idRegistro"])
        elif heading.startswith("## 12."):
            blocks.extend(
                [
                    "| Campo | Key | Obrigatório | Validação | Default | Somente leitura |",
                    "| --- | --- | --- | --- | --- | --- |",
                    "| Nome | nomeCliente | sim | obrigatório | vazio | não |",
                ]
            )
        elif heading.startswith("## 13."):
            blocks.append("Não adicionar FormlyModule.forRoot() no módulo da tela.")
            blocks.append("Os campos atuais migram para cliente.fields.ts.")
        elif heading.startswith("## 14."):
            blocks.append(f"- {criterion}")
        blocks.append("")
    return "\n".join(blocks)


def ready_payload(paths: list[str], criterion: str = "O usuário consulta a lista e grava o cadastro pelo drawer.") -> dict:
    return {
        "status": "ready",
        "screen_name": "Clientes",
        "documentation_markdown": documentation(paths, criterion),
        "acceptance_criteria": [criterion],
        "files_consulted": paths,
        "pending_reason": "",
        "needs_review_reason": "",
        "evidence_notes": "Template, componente, key nomeCliente e uniqueIdField idRegistro confirmados.",
    }


def write_config(directory: Path, spreadsheet: Path, retaguarda: Path, output: Path) -> Config:
    payload = {
        "spreadsheet": {
            "path": str(spreadsheet),
            "sheet": "Telas",
            "header_row": 1,
            "columns": {
                "screen_name": "Nome da tela",
                "documentation": "Documentação",
                "status": "Status",
                "azure_link": "Link Azure",
                "notes": "Observações",
            },
        },
        "retaguarda_path": str(retaguarda),
        "prompt_path": str(REPO / "prompts" / "documentacao_tela.md"),
        "schema_path": str(REPO / "schema" / "resposta_analise.json"),
        "output_dir": str(output),
        "publish": False,
        "azure": {"pat_env": "AZURE_DEVOPS_PAT"},
        "agent": {"executor": "codex", "codex_bin": str(directory / "codex-ausente"), "timeout_seconds": 30},
    }
    path = directory / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return Config.load(path)
