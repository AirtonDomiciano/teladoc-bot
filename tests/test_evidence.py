import tempfile
import unittest
from pathlib import Path

from teladoc_bot.evidence import prepare_writing_evidence, render_evidence, resolve_screen_directory
from teladoc_bot.prompting import PromptError


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

    def test_screen_dir_quotes_that_directory_and_the_route_that_references_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(
                root,
                {
                    "src/app/pages/clientes/clientes.component.ts": "@Component({ selector: 'app-clientes' })\n",
                    "src/app/pages/clientes/clientes.component.html": "<form></form>\n",
                    "src/app/pages/clientes-extra/clientes-extra.component.html": "<p>extra</p>\n",
                    "src/app/app.routing.ts": "loadChildren: () =>\nimport('src/app/pages/clientes/clientes.module')\n",
                    "src/app/app.routing-telas.ts": "loadChildren: () =>\nimport('src/app/pages/clientes/clientes.module')\n",
                },
            )
            screen_dir = resolve_screen_directory(root, "src/app/pages/clientes")
            text = render_evidence(root, "Clientes", screen_dir=screen_dir)
        self.assertEqual(screen_dir, "src/app/pages/clientes")
        self.assertIn("Diretório informado: `src/app/pages/clientes`", text)
        self.assertIn("selector: 'app-clientes'", text)
        self.assertIn("<form></form>", text)
        self.assertIn("src/app/app.routing.ts", text)
        self.assertIn("src/app/app.routing-telas.ts", text)
        self.assertIn("loadChildren: () =>", text)
        self.assertIn("src/app/pages/clientes/clientes.module", text)
        self.assertNotIn("<p>extra</p>", text)
        self.assertNotIn("Há mais de um diretório", text)

    def test_writing_evidence_includes_the_whole_screen_file_and_skips_codex_when_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(
                root,
                {
                    "src/app/pages/clientes/clientes.component.ts": "@Component({ selector: 'app-clientes' })\nexport class ClientesComponent { campo = 'inteiro'; }\n",
                    "src/app/pages/clientes/clientes.module.ts": "export class ClientesModule {}\n",
                    "src/app/pages/clientes-extra/clientes-extra.component.html": "<p>extra</p>\n",
                },
            )
            ready, text = prepare_writing_evidence(root, "Clientes")
        self.assertFalse(ready)
        self.assertIn("Há mais de um diretório compatível", text)
        self.assertNotIn("campo = 'inteiro'", text)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(
                root,
                {
                    "src/app/pages/clientes/clientes.component.ts": "@Component({ selector: 'app-clientes' })\nexport class ClientesComponent { campo = 'inteiro'; }\n",
                    "src/app/pages/clientes/clientes.module.ts": "export class ClientesModule {}\n",
                },
            )
            ready, text = prepare_writing_evidence(root, "Clientes")
        self.assertTrue(ready)
        self.assertIn("1: @Component({ selector: 'app-clientes' })", text)
        self.assertIn("campo = 'inteiro'", text)
        self.assertIn("clientes.module.ts", text)
        self.assertIn("Não execute comandos", text)

    def test_screen_dir_must_stay_inside_the_clone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            with self.assertRaises(PromptError):
                resolve_screen_directory(root, "../")
            with self.assertRaises(PromptError):
                resolve_screen_directory(root, "/tmp")
            with self.assertRaises(PromptError):
                resolve_screen_directory(root, "src/ausente")
            (root / "src" / "arquivo.ts").write_text("export const v = 1;\n", encoding="utf-8")
            with self.assertRaises(PromptError):
                resolve_screen_directory(root, "src/arquivo.ts")

    def _write(self, root: Path, files: dict[str, str]) -> None:
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
