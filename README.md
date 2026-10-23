# TelaDoc Bot

Bot de terminal que separa a coleta, a elaboração e a publicação da documentação das telas CRUD. A coleta exporta um pacote Markdown com a identificação da tela, as fontes e o contexto da US. A elaboração desse pacote acontece fora do bot. A importação valida o conteúdo pronto, a conferência mostra o resultado e a publicação grava na User Story somente o que a validação aprovar.

A publicação não altera a planilha até o comando `publish`. `Documentação` só vira `Sim` depois que a US é atualizada e a releitura confirma o texto enviado, ou quando a releitura mostra que o conteúdo esperado já está presente.

## Requisitos

- Python 3.11 ou superior.
- Planilha `.xlsx`, ou a planilha do Google Sheets quando `GOOGLE_SPREADSHEET_ID` está definido.
- PAT do Azure DevOps com permissão de ler e editar work items. Ele fica fora dos arquivos exportados.
- Clone local do RetaguardaWeb, usado somente para leitura e para validar caminhos, keys e seletores.

Este fluxo não chama o Codex CLI nem outra IA ou API. O comando `run` permanece no programa e ainda inicia uma sessão do Codex por tela; ele não faz parte da coleta, da importação, da conferência nem da publicação.

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
.venv/bin/python -m teladoc_bot collect --config config.json
.venv/bin/python -m teladoc_bot collect --config config.json --only-id 30092
.venv/bin/python -m teladoc_bot collect --config config.json --only-id 30057 --screen-dir src/app/pages/cadastros/clientes/placas/gerenciamento/placas
.venv/bin/python -m teladoc_bot import --config config.json --package output/<execução>/pacote --from respostas/
.venv/bin/python -m teladoc_bot review --config config.json --package output/<execução>/pacote
.venv/bin/python -m teladoc_bot publish --config config.json --package output/<execução>/pacote
```

`collect` lê as linhas elegíveis, a US e o clone local, e grava o pacote em `output/<execução>/pacote`. `--limit` limita a quantidade exportada. `--only-id` exporta uma US. `--screen-dir` indica o diretório da tela, relativo ao clone: o caminho precisa existir dentro do RetaguardaWeb, e as evidências saem desse diretório e das rotas que o referenciam. Sem essa opção, a coleta continua buscando pelo nome e não inclui trechos quando há mais de um diretório compatível. O diretório informado vale para uma única US. O pacote traz a identificação, o caminho do clone, as observações, as referências Figma do prompt e as evidências encontradas no RetaguardaWeb: caminhos e trechos literais de rotas, componentes, templates, formulários e serviços. Se a tela não for localizada com segurança, o pacote registra essa limitação e não inventa comportamento. Credenciais não entram nos arquivos.

`import` lê o diretório indicado por `--from`. Cada resposta é um JSON, ou um Markdown com um objeto JSON, e precisa trazer `work_item_id` e o `screen_name` da tela. A validação existente confere o schema prático, os caminhos reais, as keys e os seletores. Conteúdo ausente, inválido ou associado a outro ID fica bloqueado e não segue para publicação.

`review` relê a planilha, mostra o resultado de cada tela e não publica nem altera `Documentação`.

`publish` localiza de novo a linha pelo ID da US, publica somente o que estiver aprovado e marca `Documentação = Sim` depois da releitura. Se a US já contiver o texto esperado, a marcação acontece sem um novo envio. Uma falha mantém `Não`, registra o motivo e segue para a próxima tela.

## Seleção

Entra na fila a linha com documentação igual a `Não`, status igual a `CRUD` e link de work item do Azure DevOps. `HARD CRUD` fica de fora. Linha sem link, com link inválido ou com outro status é registrada no resumo e a execução segue.

O link aceito aponta para `/_workitems/edit/{id}` ou `/_apis/wit/workitems/{id}` em `dev.azure.com` ou `visualstudio.com`.

## Fluxo

1. `collect` lê a próxima linha elegível, consulta a US, busca a tela no clone e exporta o Markdown de contexto com os trechos encontrados.
2. A elaboração da descrição e dos critérios é feita fora do bot, a partir desse pacote.
3. `import` amarra o conteúdo à tela, à linha e ao work item e aplica a validação já existente.
4. `review` permite conferir o resultado antes de qualquer gravação no Azure ou na planilha.
5. `publish` envia a descrição e os critérios, ou confirma que eles já estão na US, e só então altera a coluna de documentação.

Uma falha, uma pendência ou `needs_review` mantém `Não`, grava o motivo e passa para a próxima linha. A mesma US não entra duas vezes no mesmo pacote.

O clone não recebe edição, instalação, migration, build, teste, commit ou push. A análise insuficiente volta como pendência e não é publicada.

## Código de saída

- `0`: as telas elegíveis foram concluídas ou ignoradas conforme as regras.
- `1`: configuração, dependência ou falha que impediu o início.
- `2`: ao menos uma tela ficou pendente, em revisão ou sem confirmação da planilha.

No fluxo separado, o código 2 indica tela bloqueada, pendente, em revisão ou sem confirmação da planilha. A conferência não altera `Documentação`. O comando `run`, quando a publicação está desligada, continua registrando `documentada_local` e mantém `Não`.
