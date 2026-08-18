"""A PDF's table of contents.

PRD §20 asks for the outline "where available", which most books have and most
scans do not. Extraction is not free — it opens the document — so the result is
cached: an outline only changes when the file does, and the storage key already
encodes that.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pypdfium2 as pdfium
from django.core.cache import cache

logger = logging.getLogger("lumaindex.outline")

MAX_DEPTH = 6
MAX_ITEMS = 2000
CACHE_SECONDS = 60 * 60 * 24


def _extract(path: Path) -> list[dict]:
    document = pdfium.PdfDocument(str(path))
    try:
        items: list[dict] = []
        for entry in document.get_toc(max_depth=MAX_DEPTH):
            if len(items) >= MAX_ITEMS:
                # A pathological outline should not become a megabyte of JSON
                # on every reader open.
                logger.info("outline truncated", extra={"event": "outline.truncated"})
                break
            title = (entry.title or "").strip()
            if not title:
                continue
            items.append({
                "title": title[:300],
                "page": entry.page_index if entry.page_index is not None else None,
                "level": entry.level,
            })
        return items
    finally:
        document.close()


def outline_for(path: Path, storage_key: str) -> list[dict]:
    """Cached outline for a stored file, or an empty list if it has none."""
    key = f"outline:{storage_key}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    try:
        items = _extract(path)
    except Exception as exc:
        # A missing or unreadable outline is not an error worth failing the
        # reader over; the sidebar simply has nothing to show.
        logger.info("no outline extracted",
                    extra={"event": "outline.unavailable", "reason": type(exc).__name__})
        items = []

    cache.set(key, items, CACHE_SECONDS)
    return items
