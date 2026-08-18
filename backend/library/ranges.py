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
               range_header: str = "") -> HttpResponse:
    """Serve a file, honouring a single byte range when one is asked for."""
    size = path.stat().st_size
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
    # Quoted and escaped: a filename containing a quote would otherwise break
    # the header, and titles come from whatever the user uploaded.
    safe = filename.replace("\\", "").replace('"', "")
    response["Content-Disposition"] = f'inline; filename="{safe}"'
    return response
