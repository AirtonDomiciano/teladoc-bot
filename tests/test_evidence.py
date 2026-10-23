import tempfile
import unittest
from pathlib import Path

from teladoc_bot.evidence import render_evidence


class EvidenceTests(unittest.TestCase):
    def test_quotes_routes_components_templates_forms_and_services(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(
                root,
                {
                    "src/app/pages/clientes/clientes.component.ts": "@Component({ selector: 'app-clientes', templateUrl: './clientes.component.html' })\nexport class ClientesComponent {}\n",
                    "src/app/pages/clientes/clientes.component.html": "<form></form>\n",
                    "src/app/pages/clientes/clientes.fields.ts": "export const fields = [{ key: 'codigo' }];\n",
                    "src/app/pages/clientes/clientes.service.ts": "@Injectable()\nexport class ClientesService {}\n",
                    "src/app/pages/clientes/clientes.routing.ts": "path: 'clientes',\n",
                    "src/app/app.routing.ts": "loadChildren: () => import('./pages/clientes/clientes.module')\n",
                    "src/app/pages/produtos/produtos.component.ts": "@Component({ selector: 'app-produtos' })\n",
                },
            )
            text = render_evidence(root, "Clientes")
        self.assertIn("src/app/pages/clientes/clientes.component.ts", text)
        self.assertIn("src/app/pages/clientes/clientes.component.html", text)
        self.assertIn("src/app/pages/clientes/clientes.fields.ts", text)
        self.assertIn("src/app/pages/clientes/clientes.service.ts", text)
        self.assertIn("src/app/pages/clientes/clientes.routing.ts", text)
        self.assertIn("src/app/app.routing.ts", text)
        self.assertIn("selector: 'app-clientes'", text)
        self.assertIn("<form></form>", text)
        self.assertIn("key: 'codigo'", text)
        self.assertIn("export class ClientesService", text)
        self.assertIn("path: 'clientes'", text)
        self.assertIn("pages/clientes/clientes.module", text)
        self.assertNotIn("app-produtos", text)

    def test_missing_screen_records_the_limitation_without_inventing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(root, {"src/app/pages/produtos/produtos.component.ts": "@Component({ selector: 'app-produtos' })\n"})
            text = render_evidence(root, "Zzzinexistente")
        self.assertIn("não foi localizada com segurança", text)
        self.assertIn("Nenhum componente, comportamento ou regra foi inferido.", text)
        self.assertNotIn("app-produtos", text)
        self.assertNotIn("selector:", text)

    def test_ambiguous_directories_do_not_include_excerpts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(
                root,
                {
                    "src/app/pages/clientes/clientes.component.html": "<p>lista</p>\n",
                    "src/app/pages/clientes-extra/clientes-extra.component.html": "<p>extra</p>\n",
                },
            )
            text = render_evidence(root, "Clientes")
        self.assertIn("Há mais de um diretório compatível", text)
        self.assertIn("src/app/pages/clientes", text)
        self.assertIn("src/app/pages/clientes-extra", text)
        self.assertNotIn("<p>lista</p>", text)
        self.assertNotIn("<p>extra</p>", text)
        self.assertIn("Nenhum componente, comportamento ou regra foi inferido.", text)

    def _write(self, root: Path, files: dict[str, str]) -> None:
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
