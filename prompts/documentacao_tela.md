teladoc-prompt-version: 1

# Documentação de tela CRUD

Você analisa uma única tela do clone local do RetaguardaWeb e devolve a documentação para a User Story correspondente. Esta sessão é exclusiva desta tela. Não use memória, histórico ou conclusão de outra tela.

A descrição atual da US será substituída por esta documentação quando a publicação estiver habilitada. Por isso, carregue para o texto novo somente referências, links e restrições que estejam confirmados na US, nos comentários, nas relações ou nas observações da planilha.

## Leitura obrigatória

- Leia as instruções aplicáveis do repositório, inclusive `AGENTS.md` na raiz e nos subprojetos, quando esses arquivos existirem.
- Localize a tela pelas rotas, pelos menus e pelos componentes. Use o nome da planilha, o título da US e os termos das observações.
- Confirme a implementação no código antes de descrevê-la.
- O clone é somente leitura. Não edite arquivos, não instale dependências, não execute migrations, não faça commit ou push e não rode build nem testes da aplicação.
- Pode usar apenas comandos de leitura e busca. Não grave arquivos no clone. A resposta estruturada é o único resultado.

## O que analisar

Conforme a tela exigir, abra e use como evidência:

- templates HTML;
- componentes TypeScript;
- módulos;
- arquivos Formly e `.fields.ts`;
- services;
- models e contratos;
- componentes padrão já usados em telas migradas;
- consumidores de rotas, modais e eventos de retorno.

A documentação precisa cobrir, quando existirem no código:

- caminhos reais dos arquivos consultados;
- componentes atuais e os componentes que devem substituí-los;
- campos e keys reais;
- validações, obrigatoriedade, limites e defaults;
- permissões e somente leitura;
- consultas, filtros e paginação;
- identificadores e payload de gravação;
- dependências e comportamentos que devem ser preservados.

## Padrão de implementação

- Formulários reativos integrados ao Formly.
- Campos e layout em arquivos `.fields.ts`.
- Use somente types efetivamente registrados no projeto. Se o registro não for encontrado, não invente o type.
- Importe os módulos necessários e não adicione `FormlyModule.forRoot()` no módulo da tela.
- Grades usam `app-base-table`.
- `tableId` precisa ser exclusivo.
- `uniqueIdField` precisa ser o identificador real encontrado no código. Se a tela não tiver grade, registre `uniqueIdField: não se aplica` e explique o motivo.

## Quando não publicar

Não invente campos, caminhos, propriedades, registros Formly ou contratos.

- Se faltar confirmação de arquivo, key, validação, payload, filtro ou permissão essencial, use `status: pending` e explique a lacuna em `pending_reason`.
- Se o código mostrar complexidade incompatível com CRUD simples, como wizard, várias entidades, orquestração entre telas ou regra que não cabe em listagem e drawer, use `status: needs_review`, explique em `needs_review_reason` e mantenha a tela fora de uma documentação genérica.
- As observações da planilha são restrições da tela. Se elas impedirem uma documentação CRUD confiável, respeite a restrição com `pending` ou `needs_review`.
- Figma, links e referências de levantamento só entram se aparecerem na US, em comentário, relação ou observação. Caso contrário, escreva na seção correspondente: "Não confirmado na US." Isso, sozinho, não impede `ready` quando a implementação foi confirmada no código.

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

Adapte o conteúdo ao fluxo real. Não troque os títulos.

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
