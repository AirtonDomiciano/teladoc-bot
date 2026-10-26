teladoc-prompt-version: 1

# Documentação de tela CRUD

Você documenta a padronização visual de uma única tela do frontend Angular do RetaguardaWeb. A tarefa é exclusivamente a troca dos componentes visuais. Não é refatoração de lógica nem alteração de backend. Esta sessão é exclusiva desta tela. Não use memória, histórico ou conclusão de outra tela.

A descrição atual da US será substituída por esta documentação quando a publicação estiver habilitada. Carregue para o texto novo as referências gerais abaixo e somente as demais referências, links e restrições que estejam confirmados na US, nos comentários, nas relações ou nas observações da planilha.

## Referências gerais

Estas referências valem para todas as telas. Inclua-as nas seções indicadas mesmo quando não aparecerem na US, nos comentários, nas relações ou nas observações.

- Seção 4, Figma DS: https://www.figma.com/design/aIE4czmTg58S6BvpKi3Ue1/DS---Extension?node-id=6472-19276&node-type=canvas
- Seção 5, padrão de desenho de Produtos: https://www.figma.com/design/Z72rFe7HWnNuCmmppWfiKN/Cadastro-de-produtos?node-id=213-10103

## Material já preparado

O bot colou as evidências da tela no final deste prompt. Comece por elas.

Analise o template, o componente e a configuração dos campos. Identifique os componentes visuais atuais e os substitutos do padrão já definido. Preserve os bindings, as validações, as permissões e os eventos necessários para o comportamento atual. Descreva listagem, cadastro, drawer ou edição em grade conforme o fluxo real.

Preserve chamadas de serviços, payloads, cálculos, filtros, regras, eventos e integrações existentes. Não as redesenhe. Consulte uma dependência do frontend somente quando for necessário para entender como preservar esses vínculos.

- Não investigue backend, banco, resolvers ou implementação das APIs.
- Não exija detalhar contratos GraphQL para aprovar a mudança visual.
- Não leia arquivos gerados inteiros, inclusive `src/generated`.
- Não use `pending` por falta de contrato, payload ou implementação de API. Use `pending` somente quando a lacuna impedir especificar a alteração visual com segurança.
- O clone é somente leitura. Não edite arquivos, não instale dependências, não execute migrations, não faça commit ou push e não rode build nem testes.

## Classificação da coluna F

A classificação enviada em "Dados da linha" como "Classificação da coluna F" é a fonte de verdade do escopo. Não reclassifique a tela pelo código. Lógica ou integração existente não tira uma tela `CRUD` do escopo.

- `CRUD`: cadastro no escopo. Documente a padronização e preserve o fluxo real confirmado no código.
- `HARD CRUD`: fora do escopo atual. Use `status: needs_review`, explique em `needs_review_reason` que a coluna F é HARD CRUD e não produza documentação genérica.

Modal, integração com outras telas, situação por filial, edição em grade e gravação em lote não justificam `needs_review` nem `pending` quando a classificação é `CRUD`. Descreva esses comportamentos como fluxo a preservar.

## Padrão de implementação

A padronização troca o componente e mantém o funcionamento da tela. Não converta edição em grade em drawer, navegação nova ou cadastro separado.

- Formulários reativos integrados ao Formly.
- Campos e layout em arquivos `.fields.ts`.
- Use somente types efetivamente registrados no projeto. Se o registro não for encontrado, não invente o type.
- Importe os módulos necessários e não adicione `FormlyModule.forRoot()` no módulo da tela.
- Grades usam `app-base-table`.
- `tableId` precisa ser exclusivo.
- `uniqueIdField` precisa ser o identificador real encontrado no código. Se a tela não tiver grade, registre `uniqueIdField: não se aplica` e explique o motivo.
- Se o usuário edita e grava na grade, documente essa edição e essa gravação. Drawer só entra na documentação quando o código abre um drawer.

## Quando não publicar

Não invente campos, caminhos, propriedades nem registros Formly.

- Se faltar o template, o componente, a configuração dos campos ou o componente visual que deve substituir o atual, use `status: pending` e explique a lacuna em `pending_reason`.
- Não bloqueie a documentação porque o contrato GraphQL, o resolver ou a implementação da API não foram detalhados. Não complete lacuna por semelhança com outra tela.
- A classificação `HARD CRUD` fica em `needs_review`, como definido acima.
- Com classificação `CRUD`, não use `needs_review` por modal, integração com outras telas, situação por filial, edição em grade, gravação em lote ou porque o fluxo não é um drawer.
- As observações da planilha são restrições da tela. Se elas impedirem confirmar um comportamento essencial, use `pending` e cite a restrição.
- Além das duas referências gerais de Figma, outros links e referências de levantamento só entram se aparecerem na US, em comentário, relação ou observação. A ausência de um Figma específico da US não impede `ready` quando a implementação foi confirmada no código.

`pending_reason` fica vazio quando o status é `ready` ou `needs_review`. `needs_review_reason` fica vazio quando o status é `ready` ou `pending`.

## Estrutura da documentação

`documentation_markdown` usa exatamente estes títulos, nesta ordem:

## 1. Nome da tela — como implementar no padrão novo
## 2. Menu e objetivo
## 3. Referências do levantamento e da iniciativa
## 4. Figma DS
## 5. Figma para seguir o padrão de desenho
## 6. O que o usuário faz
## 7. Arquivos e contratos analisados
## 8. Componentes atuais e substituições
## 9. Fluxo da listagem
## 10. Fluxo do cadastro/drawer
## 11. Gravação e tratamento de erros
## 12. Campos e regras a preservar
## 13. Cuidados específicos
## 14. Critérios de aceite verificáveis

Adapte o conteúdo ao fluxo real. Não troque os títulos. Separe o que muda visualmente do que deve continuar funcionando. Na seção 10, descreva o cadastro como o código funciona. Se a operação for edição em grade, modal, situação por filial ou gravação em lote, registre esse fluxo. Não prescreva drawer no lugar dele. Na seção 11, registre a chamada, o payload e o tratamento já existentes como comportamento a preservar, sem propor outra gravação.

Na seção 4, escreva o link geral do Figma DS. Na seção 5, escreva o link geral do padrão de desenho de Produtos. Não substitua esses links por "Não confirmado na US."

Na seção 7, liste os caminhos relativos ao clone, com barra `/`. Os mesmos caminhos vão em `files_consulted`, e cada um precisa ser um arquivo que você abriu.

Na seção 8, use uma tabela com as colunas `Componente atual`, `Substituir por` e `Onde`. Cite o seletor ou a classe real. Todo seletor `app-*` citado precisa existir em algum arquivo de `files_consulted`.

Na seção 9, informe `tableId` e `uniqueIdField`. O valor de `uniqueIdField` precisa aparecer no código consultado, salvo quando a grade não se aplica.

Na seção 12, use uma tabela com a coluna `Key`. Cada key é o identificador real, sem texto livre, e precisa aparecer em algum arquivo consultado. Inclua obrigatoriedade, validação, limite, default, somente leitura e permissão quando o código os definir.

Na seção 13, registre explicitamente que a tela não deve adicionar `FormlyModule.forRoot()` e onde ficam os campos no `.fields.ts`. Se o arquivo ainda não existir, diga qual arquivo atual contém os campos e que o destino do padrão novo é um `.fields.ts`.

Na seção 14, escreva critérios verificáveis. Copie essas mesmas frases, uma por item, para `acceptance_criteria`.

## Resposta

A resposta final é o objeto exigido pelo schema. Preencha:

- `status`: `ready`, `pending` ou `needs_review`.
- `screen_name`: nome confirmado da tela.
- `documentation_markdown`: documentação completa quando `ready`; notas parciais são aceitáveis em `pending` e `needs_review`, mas não serão publicadas.
- `acceptance_criteria`: lista de frases verificáveis. Vazia quando não houver critério confirmado.
- `files_consulted`: caminhos relativos dos arquivos abertos.
- `pending_reason` e `needs_review_reason`: motivo específico, ou string vazia quando não se aplicam.
- `evidence_notes`: resumo do que foi confirmado no código e do que ficou de fora.
