"""Cliente da REST API de work items do Azure DevOps."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import quote, urlencode, urlparse

from teladoc_bot.azure_link import WorkItemRef


class AzureError(RuntimeError):
    """Falha ao consultar ou atualizar o Azure DevOps."""


@dataclass(frozen=True)
class Relation:
    rel: str
    url: str
    name: str


@dataclass
class WorkItem:
    id: int
    title: str
    work_item_type: str
    state: str
    description_html: str
    acceptance_html: str
    relations: list[Relation] = field(default_factory=list)
    url: str = ""


@dataclass(frozen=True)
class Comment:
    author: str
    created: str
    text: str


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None = None


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes


class HttpTransport(Protocol):
    def send(self, request: HttpRequest) -> HttpResponse: ...


class _AzureRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = (urlparse(newurl).hostname or "").lower()
        if host != "dev.azure.com" and not host.endswith(".visualstudio.com"):
            raise AzureError(f"Redirecionamento do Azure DevOps recusado para {host}.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UrllibTransport:
    def __init__(self, timeout_seconds: int = 60) -> None:
        self._timeout = timeout_seconds
        self._opener = urllib.request.build_opener(_AzureRedirectHandler)

    def send(self, request: HttpRequest) -> HttpResponse:
        outgoing = urllib.request.Request(request.url, data=request.body, method=request.method)
        for key, value in request.headers.items():
            outgoing.add_header(key, value)
        try:
            with self._opener.open(outgoing, timeout=self._timeout) as response:
                return HttpResponse(status=response.status, body=response.read())
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            raise AzureHttpStatus(exc.code, payload, request.url) from exc
        except urllib.error.URLError as exc:
            raise AzureError(f"Falha de rede ao chamar Azure DevOps: {exc.reason}") from exc


class AzureHttpStatus(AzureError):
    def __init__(self, status: int, body: bytes, url: str) -> None:
        snippet = body.decode("utf-8", errors="replace")[:1500]
        super().__init__(f"Azure DevOps respondeu HTTP {status} para {url}: {snippet}")
        self.status = status


def _path_segment(value: str) -> str:
    return quote(value, safe="")


def _pointer(field_name: str) -> str:
    escaped = field_name.replace("~", "~0").replace("/", "~1")
    return f"/fields/{escaped}"


class AzureDevOpsClient:
    def __init__(
        self,
        pat: str,
        *,
        api_version: str = "7.1",
        comments_api_version: str = "7.1-preview.4",
        description_field: str = "System.Description",
        acceptance_field: str = "Microsoft.VSTS.Common.AcceptanceCriteria",
        transport: HttpTransport | None = None,
        timeout_seconds: int = 60,
    ) -> None:
        if not pat or not pat.strip():
            raise AzureError("O Personal Access Token do Azure DevOps está vazio.")
        self._pat = pat.strip()
        self.api_version = api_version
        self.comments_api_version = comments_api_version
        self.description_field = description_field
        self.acceptance_field = acceptance_field
        self._transport = transport or UrllibTransport(timeout_seconds)

    def get_work_item(self, ref: WorkItemRef) -> WorkItem:
        fields = [
            "System.Id",
            "System.Title",
            "System.WorkItemType",
            "System.State",
            self.description_field,
            self.acceptance_field,
        ]
        query = urlencode(
            {
                "api-version": self.api_version,
                "$expand": "relations",
                "fields": ",".join(dict.fromkeys(fields)),
            }
        )
        payload = self._get_json(f"{self._work_item_url(ref)}?{query}")
        if "fields" not in payload:
            raise AzureError("A resposta da US não trouxe os campos do work item.")
        values = payload.get("fields") or {}
        relations = []
        for item in payload.get("relations") or []:
            attributes = item.get("attributes") or {}
            relations.append(
                Relation(
                    rel=str(item.get("rel") or ""),
                    url=str(item.get("url") or ""),
                    name=str(attributes.get("name") or ""),
                )
            )
        return WorkItem(
            id=int(payload.get("id") or ref.id),
            title=str(values.get("System.Title") or ""),
            work_item_type=str(values.get("System.WorkItemType") or ""),
            state=str(values.get("System.State") or ""),
            description_html=str(values.get(self.description_field) or ""),
            acceptance_html=str(values.get(self.acceptance_field) or ""),
            relations=relations,
            url=str(payload.get("url") or ref.url),
        )

    def get_comments(self, ref: WorkItemRef) -> list[Comment]:
        comments: list[Comment] = []
        query = urlencode({"api-version": self.comments_api_version})
        url = f"{self._work_item_url(ref)}/comments?{query}"
        for _page in range(20):
            payload = self._get_json(url)
            if "comments" not in payload:
                raise AzureError("A resposta de comentários da US não trouxe a lista comments.")
            for item in payload.get("comments") or []:
                author = item.get("createdBy") or {}
                text = item.get("text") or item.get("renderedText") or ""
                comments.append(
                    Comment(
                        author=str(author.get("displayName") or ""),
                        created=str(item.get("createdDate") or ""),
                        text=str(text),
                    )
                )
            token = payload.get("continuationToken")
            if not token:
                break
            query = urlencode(
                {
                    "api-version": self.comments_api_version,
                    "continuationToken": token,
                }
            )
            url = f"{self._work_item_url(ref)}/comments?{query}"
        else:
            comments.append(Comment("", "", "[a paginação de comentários foi interrompida nesta consulta]"))
        return comments

    def update_documentation(self, ref: WorkItemRef, description_html: str, acceptance_html: str) -> None:
        operations = [
            {"op": "add", "path": _pointer(self.description_field), "value": description_html},
            {"op": "add", "path": _pointer(self.acceptance_field), "value": acceptance_html},
        ]
        query = urlencode({"api-version": self.api_version})
        body = json.dumps(operations, ensure_ascii=False).encode("utf-8")
        self._request(
            "PATCH",
            f"{self._work_item_url(ref)}?{query}",
            body=body,
            content_type="application/json-patch+json",
        )

    def _work_item_url(self, ref: WorkItemRef) -> str:
        org = _path_segment(ref.organization)
        project = _path_segment(ref.project)
        return f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{ref.id}"

    def _get_json(self, url: str) -> dict:
        raw = self._request("GET", url)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise AzureError("Azure DevOps devolveu um corpo que não é JSON.") from exc
        if not isinstance(payload, dict):
            raise AzureError("Azure DevOps devolveu um JSON que não é um objeto.")
        return payload

    def _request(self, method: str, url: str, body: bytes | None = None, content_type: str | None = None) -> bytes:
        token = base64.b64encode(f":{self._pat}".encode("utf-8")).decode("ascii")
        headers = {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "User-Agent": "teladoc-bot/0.1",
        }
        if content_type:
            headers["Content-Type"] = content_type
        try:
            response = self._transport.send(HttpRequest(method=method, url=url, headers=headers, body=body))
        except AzureError:
            raise
        except Exception as exc:
            raise AzureError(f"Falha ao chamar Azure DevOps: {exc}") from exc
        if response.status >= 400:
            raise AzureHttpStatus(response.status, response.body, url)
        return response.body
