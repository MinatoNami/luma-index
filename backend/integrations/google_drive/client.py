"""A thin client over the Google Drive v3 REST API.

Written directly against the REST endpoints rather than through
google-api-python-client so that field projections, retry behaviour, and
pagination stay explicit — those are exactly the parts that decide whether a
large library sync stays inside quota.

The HTTP transport is injectable, so every path here (retries, pagination,
shortcut resolution, cycle detection) is exercised in tests without a Google
account. See tests/test_client.py.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from django.utils.dateparse import parse_datetime

from .errors import (
    DriveAuthError,
    DriveForbidden,
    DriveNotFound,
    DriveRateLimited,
    DriveUnavailable,
)

logger = logging.getLogger("lumaindex.drive")

DRIVE_API = "https://www.googleapis.com/drive/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 — an endpoint, not a secret
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"

PDF_MIME = "application/pdf"
FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"

# Ask only for what is used. Drive bills list calls partly by payload, and the
# default projection returns considerably more than this.
FILE_FIELDS = (
    "id,name,mimeType,size,modifiedTime,md5Checksum,parents,trashed,"
    "shortcutDetails(targetId,targetMimeType)"
)
LIST_FIELDS = f"nextPageToken,files({FILE_FIELDS})"

MAX_ATTEMPTS = 5
PAGE_SIZE = 200


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime_type: str
    size: int | None = None
    modified_at: datetime | None = None
    checksum: str = ""
    parent_id: str = ""
    path: str = ""
    shortcut_target_id: str = ""

    @property
    def is_folder(self) -> bool:
        return self.mime_type == FOLDER_MIME

    @property
    def is_pdf(self) -> bool:
        return self.mime_type == PDF_MIME


@dataclass
class WalkStats:
    folders_visited: int = 0
    files_seen: int = 0
    pdfs_found: int = 0
    shortcuts_resolved: int = 0
    cycles_skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _parse_file(payload: dict[str, Any], *, path: str = "") -> DriveFile:
    size = payload.get("size")
    return DriveFile(
        id=payload["id"],
        name=payload.get("name", ""),
        mime_type=payload.get("mimeType", ""),
        size=int(size) if size is not None else None,
        modified_at=(parse_datetime(payload["modifiedTime"])
                     if payload.get("modifiedTime") else None),
        checksum=payload.get("md5Checksum", "") or "",
        parent_id=(payload.get("parents") or [""])[0],
        path=path,
        shortcut_target_id=(payload.get("shortcutDetails") or {}).get("targetId", "") or "",
    )


class DriveClient:
    """Drive calls for one connection's access token."""

    def __init__(
        self,
        access_token: str,
        *,
        http: httpx.Client | None = None,
        sleep=None,
    ):
        self._token = access_token
        self._http = http or httpx.Client(timeout=httpx.Timeout(30.0, read=300.0))
        # Injectable so retry tests do not spend real seconds sleeping.
        self._sleep = sleep or __import__("time").sleep

    # -- plumbing ----------------------------------------------------------- #

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """One Drive call, with backoff on the retriable failures."""
        headers = {"Authorization": f"Bearer {self._token}", **kwargs.pop("headers", {})}
        delay = 1.0

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self._http.request(method, url, headers=headers, **kwargs)
            except httpx.RequestError as exc:
                if attempt == MAX_ATTEMPTS:
                    raise DriveUnavailable(f"Drive unreachable: {type(exc).__name__}") from exc
                self._sleep(delay)
                delay *= 2
                continue

            if response.status_code < 400:
                return response

            retriable = self._classify(response)
            if retriable is None or attempt == MAX_ATTEMPTS:
                self._raise_for(response)

            retry_after = self._retry_after(response) or delay
            logger.info("drive call retrying",
                        extra={"event": "drive.retry", "status": response.status_code,
                               "attempt": attempt, "delay": retry_after})
            self._sleep(retry_after)
            delay *= 2

        raise DriveUnavailable("Exhausted retries")  # pragma: no cover — loop always returns

    @staticmethod
    def _reason(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return ""
        errors = payload.get("error", {})
        if isinstance(errors, str):
            return errors
        details = errors.get("errors") or []
        return (details[0].get("reason", "") if details else "") or errors.get("status", "")

    def _classify(self, response: httpx.Response) -> str | None:
        """Return a reason string when the failure is worth retrying, else None."""
        if response.status_code in (429, 500, 502, 503, 504):
            return "transient"
        # Drive reports quota exhaustion as 403 with a specific reason, which is
        # retriable — unlike every other 403, which is not.
        if response.status_code == 403 and self._reason(response) in {
            "rateLimitExceeded", "userRateLimitExceeded", "sharingRateLimitExceeded",
        }:
            return "quota"
        return None

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        try:
            return float(value) if value else None
        except ValueError:
            return None

    def _raise_for(self, response: httpx.Response) -> None:
        reason = self._reason(response)
        status = response.status_code

        if status == 401:
            raise DriveAuthError(f"Drive rejected the access token ({reason or 'unauthorized'})")
        if status == 403:
            if reason in {"rateLimitExceeded", "userRateLimitExceeded"}:
                raise DriveRateLimited("Drive quota exceeded", self._retry_after(response))
            raise DriveForbidden(f"Access denied by Drive ({reason or 'forbidden'})")
        if status == 404:
            raise DriveNotFound(f"Not found in Drive ({reason or 'notFound'})")
        if status >= 500:
            raise DriveUnavailable(f"Drive returned {status}")
        raise DriveUnavailable(f"Unexpected Drive response {status} ({reason})")

    # -- reads -------------------------------------------------------------- #

    def get_account(self) -> dict[str, Any]:
        response = self._request("GET", f"{DRIVE_API}/about",
                                 params={"fields": "user(displayName,emailAddress,permissionId)"})
        return response.json().get("user", {})

    def get_file(self, file_id: str) -> DriveFile:
        response = self._request("GET", f"{DRIVE_API}/files/{file_id}",
                                 params={"fields": FILE_FIELDS, "supportsAllDrives": "true"})
        return _parse_file(response.json())

    def get_start_page_token(self) -> str:
        """Bookmark for incremental sync later. Cheap now, impossible to backfill."""
        response = self._request("GET", f"{DRIVE_API}/changes/startPageToken",
                                 params={"supportsAllDrives": "true"})
        return response.json().get("startPageToken", "")

    def list_children(self, folder_id: str, *, only_folders: bool = False) -> Iterator[DriveFile]:
        """Every non-trashed child of a folder, following pagination."""
        query = f"'{folder_id}' in parents and trashed = false"
        if only_folders:
            query += f" and mimeType = '{FOLDER_MIME}'"

        page_token = ""
        while True:
            params = {
                "q": query,
                "fields": LIST_FIELDS,
                "pageSize": str(PAGE_SIZE),
                "orderBy": "folder,name",
                # Without both of these, files in Shared Drives are invisible —
                # a silent, confusing partial import.
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }
            if page_token:
                params["pageToken"] = page_token

            payload = self._request("GET", f"{DRIVE_API}/files", params=params).json()
            for item in payload.get("files", []):
                yield _parse_file(item)

            page_token = payload.get("nextPageToken", "")
            if not page_token:
                return

    def walk_pdfs(self, root_id: str, *, root_name: str = "",
                  stats: WalkStats | None = None) -> Iterator[DriveFile]:
        """Every PDF under a folder, depth-first, with its Drive path.

        Handles the three things that quietly break a naive recursive walk:
        shortcuts that need resolving, Google-native files that are not really
        PDFs, and folder shortcuts that point back up the tree and would
        otherwise loop forever.
        """
        stats = stats if stats is not None else WalkStats()
        visited: set[str] = set()
        pending: list[tuple[str, str]] = [(root_id, root_name or "")]

        while pending:
            folder_id, prefix = pending.pop()
            if folder_id in visited:
                stats.cycles_skipped += 1
                logger.info("skipping already-visited folder",
                            extra={"event": "drive.walk.cycle", "folder_id": folder_id})
                continue
            visited.add(folder_id)
            stats.folders_visited += 1

            try:
                children = list(self.list_children(folder_id))
            except (DriveForbidden, DriveNotFound) as exc:
                # One unreadable subfolder must not abandon the whole import.
                stats.errors.append(f"{prefix or folder_id}: {exc}")
                logger.warning("skipping unreadable folder",
                               extra={"event": "drive.walk.skip", "folder_id": folder_id})
                continue

            for child in children:
                stats.files_seen += 1
                path = f"{prefix}/{child.name}" if prefix else child.name

                if child.mime_type == SHORTCUT_MIME:
                    resolved = self._resolve_shortcut(child, path, stats)
                    if resolved is None:
                        continue
                    child = resolved

                if child.is_folder:
                    pending.append((child.id, path))
                elif child.is_pdf:
                    stats.pdfs_found += 1
                    yield DriveFile(
                        id=child.id, name=child.name, mime_type=child.mime_type,
                        size=child.size, modified_at=child.modified_at,
                        checksum=child.checksum, parent_id=folder_id, path=path,
                    )
                # Everything else — Google Docs, images, epubs — is ignored.
                # PRD §42 keeps the MVP to PDFs.

    def _resolve_shortcut(self, shortcut: DriveFile, path: str,
                          stats: WalkStats) -> DriveFile | None:
        """Follow a shortcut to the file it points at.

        Without this, a library organised with shortcuts imports as zero books.

        The target id already arrived in the listing (it is part of FILE_FIELDS),
        so this costs one call to read the target's size and checksum — not
        three. On a shortcut-heavy library that difference is quota.
        """
        if not shortcut.shortcut_target_id:
            stats.errors.append(f"{path}: shortcut with no target")
            return None

        try:
            target = self.get_file(shortcut.shortcut_target_id)
        except (DriveNotFound, DriveForbidden) as exc:
            stats.errors.append(f"{path}: broken shortcut ({exc})")
            return None

        stats.shortcuts_resolved += 1
        # Keep the shortcut's name and path: that is what the user sees in Drive.
        return DriveFile(id=target.id, name=shortcut.name, mime_type=target.mime_type,
                         size=target.size, modified_at=target.modified_at,
                         checksum=target.checksum, parent_id=shortcut.parent_id, path=path)

    def download(self, file_id: str, destination) -> int:
        """Stream a file to an open binary handle. Returns bytes written."""
        written = 0
        headers = {"Authorization": f"Bearer {self._token}"}
        with self._http.stream("GET", f"{DRIVE_API}/files/{file_id}",
                               params={"alt": "media", "supportsAllDrives": "true"},
                               headers=headers) as response:
            if response.status_code >= 400:
                response.read()
                self._raise_for(response)
            for chunk in response.iter_bytes(chunk_size=1024 * 256):
                destination.write(chunk)
                written += len(chunk)
        return written
