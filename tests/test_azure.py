import json
import unittest
from urllib.parse import parse_qs, unquote, urlsplit

import support  # noqa: F401

from teladoc_bot.azure import AzureDevOpsClient, AzureError, AzureHttpStatus, HttpRequest, HttpResponse
from teladoc_bot.azure_link import WorkItemRef


class FakeTransport:
    def __init__(self) -> None:
        self.requests: list[HttpRequest] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        if request.method == "PATCH":
            return HttpResponse(200, b"{}")
        if "/comments" in request.url and "continuationToken" not in request.url:
            body = {
                "comments": [{"text": "<p>preservar o atalho</p>", "createdBy": {"displayName": "Ana"}, "createdDate": "2026-01-01"}],
                "continuationToken": "proxima",
            }
            return HttpResponse(200, json.dumps(body).encode())
        if "/comments" in request.url:
            body = {"comments": [{"text": "segunda nota", "createdBy": {"displayName": "Bia"}, "createdDate": "2026-01-02"}]}
            return HttpResponse(200, json.dumps(body).encode())
        body = {
            "id": 15,
            "url": request.url,
            "fields": {
                "System.Title": "Clientes",
                "System.WorkItemType": "User Story",
                "System.State": "New",
                "System.Description": "<p>Descrição <a href=\"https://figma.example/us\">Figma</a></p>",
                "Microsoft.VSTS.Common.AcceptanceCriteria": "<ul><li>salva</li></ul>",
            },
            "relations": [
                {
                    "rel": "System.LinkTypes.Related",
                    "url": "https://dev.azure.com/org/Meu%20Projeto/_apis/wit/workItems/2",
                    "attributes": {"name": "Related"},
                }
            ],
        }
        return HttpResponse(200, json.dumps(body).encode())


class AzureClientTests(unittest.TestCase):
    def test_reads_and_patches_without_exposing_the_token(self) -> None:
        transport = FakeTransport()
        client = AzureDevOpsClient("segredo-pat", transport=transport)
        ref = WorkItemRef("org", "Meu Projeto", 15, "https://dev.azure.com/org/Meu%20Projeto/_workitems/edit/15")
        work_item = client.get_work_item(ref)
        comments = client.get_comments(ref)
        client.update_documentation(ref, "<p>nova</p>", "<ul><li>salva</li></ul>")

        self.assertEqual(work_item.title, "Clientes")
        self.assertEqual(work_item.relations[0].name, "Related")
        self.assertEqual([comment.author for comment in comments], ["Ana", "Bia"])
        self.assertTrue(any("Meu%20Projeto" in request.url for request in transport.requests))
        patch = transport.requests[-1]
        self.assertEqual(patch.method, "PATCH")
        self.assertEqual(patch.headers["Content-Type"], "application/json-patch+json")
        operations = json.loads(patch.body or b"{}")
        self.assertEqual(operations[0]["path"], "/fields/System.Description")
        self.assertEqual(operations[1]["path"], "/fields/Microsoft.VSTS.Common.AcceptanceCriteria")
        self.assertNotIn("segredo-pat", patch.url)
        self.assertNotIn("segredo-pat", patch.body.decode())
        self.assertIn("expand=relations", unquote(transport.requests[0].url))
        get_query = parse_qs(urlsplit(transport.requests[0].url).query)
        self.assertEqual(get_query.get("api-version"), ["7.1"])
        self.assertEqual(get_query.get("$expand"), ["relations"])
        self.assertNotIn("fields", get_query)

    def test_http_error_omits_the_token(self) -> None:
        class Denied:
            def send(self, request: HttpRequest) -> HttpResponse:
                return HttpResponse(401, b"acesso negado")

        client = AzureDevOpsClient("segredo-pat", transport=Denied())
        ref = WorkItemRef("org", "proj", 4, "https://dev.azure.com/org/proj/_workitems/edit/4")
        with self.assertRaises(AzureError) as caught:
            client.get_work_item(ref)
        self.assertNotIn("segredo-pat", str(caught.exception))
        self.assertIsInstance(caught.exception, AzureHttpStatus)


if __name__ == "__main__":
    unittest.main()
