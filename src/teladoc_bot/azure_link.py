"""Leitura de links de work item do Azure DevOps."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote

_DEV_AZURE = re.compile(
    r"""https?://dev\.azure\.com/
    (?P<org>[^/?#\s]+)/
    (?P<project>[^/?#\s]+)
    /(?:_workitems/edit/|_apis/wit/workitems/)
    (?P<id>\d+)
    (?=$|[/?#])""",
    re.IGNORECASE | re.VERBOSE,
)
_DEV_AZURE_COLLECTION = re.compile(
    r"""https?://dev\.azure\.com/
    (?P<org>[^/?#\s]+)/
    [Dd]efault[Cc]ollection/
    (?P<project>[^/?#\s]+)
    /(?:_workitems/edit/|_apis/wit/workitems/)
    (?P<id>\d+)
    (?=$|[/?#])""",
    re.IGNORECASE | re.VERBOSE,
)
_VISUAL_STUDIO = re.compile(
    r"""https?://(?P<org>[^./?#\s]+)\.visualstudio\.com/
    (?P<project>[^/?#\s]+)
    /(?:_workitems/edit/|_apis/wit/workitems/)
    (?P<id>\d+)
    (?=$|[/?#])""",
    re.IGNORECASE | re.VERBOSE,
)
_VISUAL_STUDIO_COLLECTION = re.compile(
    r"""https?://(?P<org>[^./?#\s]+)\.visualstudio\.com/
    [Dd]efault[Cc]ollection/
    (?P<project>[^/?#\s]+)
    /(?:_workitems/edit/|_apis/wit/workitems/)
    (?P<id>\d+)
    (?=$|[/?#])""",
    re.IGNORECASE | re.VERBOSE,
)
_PATTERNS = (_DEV_AZURE, _DEV_AZURE_COLLECTION, _VISUAL_STUDIO, _VISUAL_STUDIO_COLLECTION)


@dataclass(frozen=True)
class WorkItemRef:
    organization: str
    project: str
    id: int
    url: str

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.organization.casefold(), self.project.casefold(), self.id)


def parse_work_item_link(value: object) -> WorkItemRef | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for pattern in _PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        work_item_id = int(match.group("id"))
        if work_item_id <= 0:
            return None
        return WorkItemRef(
            organization=unquote(match.group("org")),
            project=unquote(match.group("project")),
            id=work_item_id,
            url=match.group(0),
        )
    return None
