"""An in-memory Drive that speaks the v3 REST API.

Lets every path in client.py — pagination, retries, shortcut resolution, cycle
detection, Shared Drive parameters — run against real request/response handling
without a Google account. Tests that mock the client itself would prove nothing
about the part most likely to be wrong.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import httpx

FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
PDF_MIME = "application/pdf"


@dataclass
class FakeFile:
    id: str
    name: str
    mime_type: str = PDF_MIME
    parents: list[str] = field(default_factory=list)
    size: int | None = 1024
    modified: str = "2026-01-01T00:00:00.000Z"
    checksum: str = ""
    trashed: bool = False
    target_id: str | None = None
    content: bytes = b"%PDF-1.4 fake"

    def to_payload(self) -> dict:
        payload = {
            "id": self.id,
            "name": self.name,
            "mimeType": self.mime_type,
            "parents": self.parents,
            "modifiedTime": self.modified,
            "trashed": self.trashed,
        }
        if self.size is not None and self.mime_type != FOLDER_MIME:
            payload["size"] = str(self.size)
        if self.checksum:
            payload["md5Checksum"] = self.checksum
        if self.target_id:
            payload["shortcutDetails"] = {"targetId": self.target_id,
                                          "targetMimeType": PDF_MIME}
        return payload


class FakeDrive:
    """Builds an httpx.MockTransport that behaves like Drive v3."""

    def __init__(self, page_size: int = 200):
        self.files: dict[str, FakeFile] = {}
        self.page_size = page_size
        self.requests: list[httpx.Request] = []
        # Queue of statuses to return before succeeding, for retry tests.
        self.failures: list[int] = []
        self.forbidden_folders: set[str] = set()
        self.missing_files: set[str] = set()

    # -- fixture building --------------------------------------------------- #

    def folder(self, file_id: str, name: str, parent: str | None = None) -> FakeFile:
        return self.add(FakeFile(id=file_id, name=name, mime_type=FOLDER_MIME,
                                 parents=[parent] if parent else [], size=None))

    def pdf(self, file_id: str, name: str, parent: str, **kwargs) -> FakeFile:
        return self.add(FakeFile(id=file_id, name=name, mime_type=PDF_MIME,
                                 parents=[parent], **kwargs))

    def other(self, file_id: str, name: str, parent: str, mime: str) -> FakeFile:
        return self.add(FakeFile(id=file_id, name=name, mime_type=mime, parents=[parent]))

    def shortcut(self, file_id: str, name: str, parent: str, target: str) -> FakeFile:
        return self.add(FakeFile(id=file_id, name=name, mime_type=SHORTCUT_MIME,
                                 parents=[parent], target_id=target, size=None))

    def add(self, file: FakeFile) -> FakeFile:
        self.files[file.id] = file
        return file

    # -- transport ---------------------------------------------------------- #

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=self.transport())

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)

        if self.failures:
            status = self.failures.pop(0)
            body = {"error": {"errors": [{"reason": "rateLimitExceeded"}]}} \
                if status == 403 else {"error": {"message": "boom"}}
            return httpx.Response(status, json=body)

        path = request.url.path
        if path.endswith("/about"):
            return httpx.Response(200, json={"user": {"emailAddress": "owner@gmail.com",
                                                      "displayName": "Owner",
                                                      "permissionId": "perm-1"}})
        if path.endswith("/changes/startPageToken"):
            return httpx.Response(200, json={"startPageToken": "token-1"})
        if path.endswith("/files"):
            return self._list(request)

        match = re.search(r"/files/([^/]+)$", path)
        if match:
            return self._file(request, match.group(1))

        return httpx.Response(404, json={"error": {"message": "no route"}})

    def _list(self, request: httpx.Request) -> httpx.Response:
        query = request.url.params.get("q", "")
        parent_match = re.search(r"'([^']+)' in parents", query)
        parent = parent_match.group(1) if parent_match else None

        if parent in self.forbidden_folders:
            return httpx.Response(403, json={"error": {"errors": [{"reason": "forbidden"}]}})

        matches = [
            f for f in self.files.values()
            if parent in f.parents and not f.trashed
            and (FOLDER_MIME not in query or f.mime_type == FOLDER_MIME)
        ]
        matches.sort(key=lambda f: (f.mime_type != FOLDER_MIME, f.name))

        start = int(request.url.params.get("pageToken", "0") or 0)
        page_size = min(int(request.url.params.get("pageSize", self.page_size)), self.page_size)
        window = matches[start:start + page_size]

        body: dict = {"files": [f.to_payload() for f in window]}
        if start + page_size < len(matches):
            body["nextPageToken"] = str(start + page_size)
        return httpx.Response(200, json=body)

    def _file(self, request: httpx.Request, file_id: str) -> httpx.Response:
        if file_id in self.missing_files or file_id not in self.files:
            return httpx.Response(404, json={"error": {"errors": [{"reason": "notFound"}]}})

        file = self.files[file_id]
        if request.url.params.get("alt") == "media":
            return httpx.Response(200, content=file.content)
        return httpx.Response(200, json=file.to_payload())


def request_params(drive: FakeDrive, needle: str) -> list[str]:
    """Every value of a query parameter across the recorded requests."""
    return [json.dumps(dict(r.url.params)) for r in drive.requests if needle in str(r.url)]
