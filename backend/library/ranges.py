"""HTTP Range responses for stored files.

Django's FileResponse advertises nothing about ranges and serves the whole file
whatever the request asked for. That matters here for one specific reason: PDF.js
fetches a byte range to read a PDF's trailer and cross-reference table, then
pulls only the pages it needs. Without `206 Partial Content` it gives up and
downloads the entire file before rendering page one, so a 300 MB book takes
minutes to open instead of seconds.

Single ranges only. `multipart/byteranges` exists but no PDF reader needs it,
and a half-correct implementation is worse than an honest 200.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.http import FileResponse, HttpResponse

RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
CHUNK = 1024 * 256


class _Slice:
    """Reads a bounded window of a file, so a range never over-reads."""

    def __init__(self, path: Path, start: int, length: int):
        self._handle = path.open("rb")
        self._handle.seek(start)
        self._remaining = length

    def __iter__(self):
        return self

    def __next__(self) -> bytes:
        if self._remaining <= 0:
            self._handle.close()
            raise StopIteration
        chunk = self._handle.read(min(CHUNK, self._remaining))
        if not chunk:
            self._handle.close()
            raise StopIteration
        self._remaining -= len(chunk)
        return chunk

    def close(self) -> None:
        self._handle.close()


def parse_range(header: str, size: int) -> tuple[int, int] | None | str:
    """Return (start, end) inclusive, None if there is no range, or "invalid".

    "invalid" means the header was a range we cannot satisfy, which is a 416 —
    distinct from no range at all, which is a plain 200.
    """
    if not header:
        return None

    match = RANGE_RE.match(header.strip())
    if not match:
        # A syntactically odd or multi-range header: ignore it and send the
        # whole file, which the spec permits and every client handles.
        return None

    raw_start, raw_end = match.group(1), match.group(2)

    if raw_start == "" and raw_end == "":
        return None
    if raw_start == "":
        # A suffix range: the last N bytes.
        length = int(raw_end)
        if length == 0:
            return "invalid"
        start = max(0, size - length)
        return start, size - 1

    start = int(raw_start)
    if start >= size:
        return "invalid"
    end = int(raw_end) if raw_end else size - 1
    return start, min(end, size - 1)


def serve_file(path: Path, *, content_type: str, filename: str,
               range_header: str = "", etag: str = "",
               if_none_match: str = "", if_range: str = "",
               max_age: int = 0) -> HttpResponse:
    """Serve a file, honouring a single byte range when one is asked for.

    With an `etag`, the same file asked for twice costs a 304 instead of the
    whole book. That matters more than it sounds: a reader re-opened over a
    slow link was re-downloading every byte it had already seen, because
    nothing here said the bytes were worth keeping.

    Content addressing makes the tag free and exact — the storage key is the
    SHA-256 of the contents, so it cannot say "unchanged" about a file that
    changed. It is a strong validator for the same reason, which is what lets
    `If-Range` resume a partial download rather than start again.
    """
    size = path.stat().st_size

    quoted = f'"{etag}"' if etag else ""
    if quoted and _matches(if_none_match, quoted):
        # 304 carries the validators and nothing else, by definition.
        not_modified = HttpResponse(status=304)
        not_modified["ETag"] = quoted
        not_modified["Accept-Ranges"] = "bytes"
        if max_age:
            not_modified["Cache-Control"] = f"private, max-age={max_age}, must-revalidate"
        return not_modified

    # A range conditional on a version we no longer have has to be answered in
    # full, or the client stitches new bytes onto an old prefix.
    if range_header and if_range and quoted and not _matches(if_range, quoted):
        range_header = ""

    requested = parse_range(range_header, size)

    if requested == "invalid":
        response = HttpResponse(status=416)
        response["Content-Range"] = f"bytes */{size}"
        response["Accept-Ranges"] = "bytes"
        return response

    if requested is None:
        response = FileResponse(path.open("rb"), content_type=content_type)
        response["Content-Length"] = str(size)
    else:
        start, end = requested
        length = end - start + 1
        response = FileResponse(_Slice(path, start, length), content_type=content_type,
                                status=206)
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
        response["Content-Length"] = str(length)

    response["Accept-Ranges"] = "bytes"
    if quoted:
        response["ETag"] = quoted
    if max_age:
        # `private` because Django authorised this and a shared cache must not
        # hand it to the next reader. `must-revalidate` because a replaced
        # source keeps the same URL, and a stale book is worse than a 304.
        response["Cache-Control"] = f"private, max-age={max_age}, must-revalidate"
    # Quoted and escaped: a filename containing a quote would otherwise break
    # the header, and titles come from whatever the user uploaded.
    safe = filename.replace("\\", "").replace('"', "")
    response["Content-Disposition"] = f'inline; filename="{safe}"'
    return response


def _matches(header: str, quoted_etag: str) -> bool:
    """Whether an If-None-Match / If-Range header covers this entity tag."""
    value = (header or "").strip()
    if not value:
        return False
    if value == "*":
        return True
    # Weak comparison is not used here: ranges need a strong validator, and the
    # tag is a content hash, so W/ prefixes are stripped only to be forgiving
    # about what a client sends back.
    candidates = [part.strip().removeprefix("W/") for part in value.split(",")]
    return quoted_etag in candidates
