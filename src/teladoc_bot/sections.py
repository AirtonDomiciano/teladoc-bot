"""Contrato das seções da documentação publicada."""

REQUIRED_HEADINGS: tuple[str, ...] = (
    "## 1. Nome da tela — como implementar no padrão novo",
    "## 2. Menu e objetivo",
    "## 3. Referências do levantamento e da iniciativa",
    "## 4. Figma DS",
    "## 5. Figma para seguir o padrão de desenho",
    "## 6. O que o usuário faz",
    "## 7. Arquivos e contratos analisados",
    "## 8. Componentes atuais e substituições",
    "## 9. Fluxo da listagem",
    "## 10. Fluxo do cadastro/drawer",
    "## 11. Gravação e tratamento de erros",
    "## 12. Campos e regras a preservar",
    "## 13. Cuidados específicos",
    "## 14. Critérios de aceite verificáveis",
)

RESPONSE_FIELDS: tuple[str, ...] = (
    "status",
    "screen_name",
    "documentation_markdown",
    "acceptance_criteria",
    "files_consulted",
    "pending_reason",
    "needs_review_reason",
    "evidence_notes",
)
