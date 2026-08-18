"""Reading facts out of a PDF: page count, whether it has text, a thumbnail.

Uses pypdfium2 (Apache-2.0/BSD) rather than PyMuPDF, which is AGPL — see
docs/phases/02-google-drive.md D2. Everything here treats the file as hostile:
a PDF arriving from someone's Drive may be truncated, encrypted, or not a PDF
at all, and none of those may take down an import (PRD §35).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

logger = logging.getLogger("lumaindex.documents")

# Sampled rather than exhaustive: a 900-page scan should not be fully text
# extracted just to answer "is there a text layer?".
TEXT_PROBE_PAGES = 8
# Below this many characters across the sample, treat the document as scanned.
# Scanned PDFs often carry a few stray characters from a cover or a stamp.
TEXT_PROBE_MIN_CHARS = 40

THUMBNAIL_WIDTH = 400
THUMBNAIL_QUALITY = 80


class DocumentError(Exception):
    """The file could not be read as a PDF."""


class DocumentEncrypted(DocumentError):
    """Password-protected. PRD §35 lists this as a case to handle, not crash on."""


@dataclass(frozen=True)
class DocumentInfo:
    page_count: int
    has_text_layer: bool


def _open(path: Path) -> pdfium.PdfDocument:
    try:
        document = pdfium.PdfDocument(str(path))
        len(document)  # forces parsing; a truncated file fails here, not later
    except pdfium.PdfiumError as exc:
        message = str(exc).lower()
        if "password" in message or "encrypted" in message:
            raise DocumentEncrypted("The PDF is password-protected.") from exc
        raise DocumentError(f"Unreadable PDF: {exc}") from exc
    except Exception as exc:  # pypdfium2 can surface OSError on a bad file
        raise DocumentError(f"Unreadable PDF: {type(exc).__name__}") from exc
    return document


def _sample_pages(total: int, limit: int = TEXT_PROBE_PAGES) -> list[int]:
    """Spread the sample through the document.

    Front matter is often typeset even in an otherwise scanned book, so probing
    only the first pages would call a scan searchable.
    """
    if total <= limit:
        return list(range(total))
    step = total / limit
    return sorted({min(total - 1, int(i * step)) for i in range(limit)})


def probe(path: Path) -> DocumentInfo:
    """Page count and whether a usable text layer exists."""
    document = _open(path)
    try:
        page_count = len(document)
        characters = 0

        for index in _sample_pages(page_count):
            try:
                page = document[index]
                textpage = page.get_textpage()
                characters += len(textpage.get_text_bounded().strip())
                textpage.close()
                page.close()
            except Exception as exc:
                # One unreadable page should not decide the whole document, but
                # a run of them explains a surprising has_text_layer result.
                logger.debug("text probe skipped a page",
                             extra={"event": "documents.probe.page_skipped",
                                    "page": index, "reason": type(exc).__name__})
                continue
            if characters >= TEXT_PROBE_MIN_CHARS:
                break

        return DocumentInfo(page_count=page_count,
                            has_text_layer=characters >= TEXT_PROBE_MIN_CHARS)
    finally:
        document.close()


def render_thumbnail(path: Path, destination: Path, *, width: int = THUMBNAIL_WIDTH) -> Path:
    """Render page 1 to a WebP thumbnail. Returns the written path."""
    document = _open(path)
    try:
        if len(document) == 0:
            raise DocumentError("PDF has no pages.")

        page = document[0]
        # Scale from the page's own width so the output is a predictable size
        # whether the source is A4, Letter, or a phone-sized scan.
        page_width = page.get_width() or width
        scale = max(0.1, min(4.0, width / page_width))

        bitmap = page.render(scale=scale)
        image = bitmap.to_pil().convert("RGB")

        # pypdfium2 rounds the scaled dimensions, so a requested 400 can come
        # back 401. Grid layouts want an exact width, so normalise it here.
        if image.width != width:
            height = max(1, round(image.height * width / image.width))
            image = image.resize((width, height), Image.LANCZOS)

        destination.parent.mkdir(parents=True, exist_ok=True)
        # Write beside the target and rename, so a crash mid-render cannot
        # leave a half-written thumbnail that later looks like a valid one.
        staging = destination.with_suffix(destination.suffix + ".tmp")
        image.save(staging, "WEBP", quality=THUMBNAIL_QUALITY, method=4)
        staging.replace(destination)

        page.close()
        return destination
    except DocumentError:
        raise
    except Exception as exc:
        raise DocumentError(f"Could not render thumbnail: {type(exc).__name__}: {exc}") from exc
    finally:
        document.close()


def thumbnail_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size
