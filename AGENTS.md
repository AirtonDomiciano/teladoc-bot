# Operação do TelaDoc Bot

Pedidos simples de documentação usam o fluxo automático já implementado. Comandos, seleção de linhas, códigos de saída e o fluxo manual (`collect`, `import`, `review`, `publish`) estão no [README](README.md). As regras de conteúdo ficam só em [prompts/documentacao_tela.md](prompts/documentacao_tela.md).

## Documentar e publicar uma US

Quando o usuário pedir «Faça a documentação da US &lt;ID&gt; e publique no Azure», execute o fluxo automático existente, uma vez por ID solicitado:

```bash
PYTHONPATH=src .venv/bin/python -m teladoc_bot run --config config.json --only-id <ID> --publish
```

### Antes de executar

- Leia este arquivo, o README e confira a configuração necessária (`config.json` e `.env`).
- Use as configurações locais e as credenciais existentes. Não as exiba.
- Não altere o código do bot para atender a um pedido de documentação.

### Durante a execução

- Use o executor e o prompt padrão já implementados.
- Preserve as validações existentes.
- Publique somente se a análise for aprovada. Marque `SIM` na planilha apenas depois de confirmar o conteúdo no Azure.
- Se houver bloqueio, informe o motivo. Não contorne a validação.
- Processe somente as USs solicitadas.

### Ao terminar

- Informe o resultado e o link da US.
- A conferência humana acontece diretamente no Azure.
- Não faça commit nem push sem solicitação.
