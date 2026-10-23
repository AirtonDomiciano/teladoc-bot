# TelaDoc Bot

Bot de terminal que percorre uma planilha de telas, analisa o clone local do RetaguardaWeb e grava a documentação na User Story do Azure DevOps. Cada tela recebe um prompt novo e uma sessão nova do Codex CLI.

A publicação fica desligada por padrão. `Documentação` só vira `Sim` depois que a US é atualizada e a releitura confirma o texto enviado.

## Requisitos

- Python 3.11 ou superior.
- Planilha `.xlsx`.
- PAT do Azure DevOps com permissão de ler e editar work items.
- Clone local do RetaguardaWeb, usado somente para leitura.
- Codex CLI. O comando conferido nesta versão é o `codex exec` do codex-cli 0.155, com `--sandbox read-only`, `--ephemeral`, `--json`, `--output-schema`, `-o`, `-C` e o prompt em stdin (`-`).

O executável pode estar fora do `PATH`. A resolução usa, nesta ordem, `agent.codex_bin`, a variável `CODEX_BIN`, o `PATH` e instalações locais conhecidas do Codex nas extensões do VS Code e do Cursor. Se nenhum executável responder a `codex --version`, o bot para e informa a dependência. Ele não simula uma análise bem-sucedida.

## Instalação

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

Copie `config.example.json` para `config.json` e ajuste a planilha, a aba, os nomes das colunas e o caminho do clone. Caminhos relativos do JSON são resolvidos a partir da pasta do próprio arquivo. O mapeamento das colunas é configurável. A comparação ignora espaços, maiúsculas e acentos.

O PAT fica fora do JSON. O bot lê `AZURE_DEVOPS_PAT` ou `AZURE_PAT`. Um arquivo `.env` ao lado do `config.json` também vale: `PLANILHA_PATH`, `PLANILHA_ABA` e `RETAGUARDA_PATH` substituem os caminhos do JSON, e os argumentos da linha de comando substituem os dois. O modelo em `.env.example` mostra os nomes. Organização e projeto vêm do link da US.

## Uso

```bash
.venv/bin/python -m teladoc_bot check --config config.json
.venv/bin/python -m teladoc_bot run --config config.json
.venv/bin/python -m teladoc_bot run --config config.json --limit 1
.venv/bin/python -m teladoc_bot run --config config.json --publish
```

`--publish` atualiza a descrição e os critérios de aceite. `--no-publish` mantém a execução local mesmo quando o JSON habilita publicação. `--only-id` restringe a US. `--limit` limita a quantidade de telas analisadas.

## Seleção

Entra na fila a linha com documentação igual a `Não`, status igual a `CRUD` e link de work item do Azure DevOps. `HARD CRUD` fica de fora. Linha sem link, com link inválido ou com outro status é registrada no resumo e a execução segue.

O link aceito aponta para `/_workitems/edit/{id}` ou `/_apis/wit/workitems/{id}` em `dev.azure.com` ou `visualstudio.com`.

## Fluxo de cada tela

1. Lê a próxima linha elegível e extrai o ID da US.
2. Consulta título, descrição, critérios, relações e comentários.
3. Monta o prompt com `prompts/documentacao_tela.md`, os dados da linha, a US e o caminho do clone.
4. Inicia `codex exec` em sessão efêmera, no sandbox somente leitura, com memórias e multissessão desligadas.
5. Valida o JSON, os caminhos reais, as keys e os seletores citados.
6. Salva a documentação e as evidências em `output/<execução>/`.
7. Com `--publish`, envia a descrição e os critérios, lê a US de novo e compara o conteúdo.
8. Marca `Documentação = Sim` somente depois dessa confirmação.

Uma falha, uma pendência ou `needs_review` mantém `Não`, grava o motivo e passa para a próxima linha. A mesma US não é analisada duas vezes na mesma execução.

O clone não recebe edição, instalação, migration, build, teste, commit ou push. A análise insuficiente volta como pendência e não é publicada.

## Código de saída

- `0`: as telas elegíveis foram concluídas ou ignoradas conforme as regras.
- `1`: configuração, dependência ou falha que impediu o início.
- `2`: ao menos uma tela ficou pendente, em revisão ou sem confirmação da planilha.

Uma análise pronta com publicação desligada termina como `documentada_local` e mantém a planilha em `Não`.
