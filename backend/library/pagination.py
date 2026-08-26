"""Bounded list responses.

Phase 3 wrote the rule down and the code never kept it: "an unpaginated library
endpoint works fine for the developer with 12 books and falls over on a real
import." Every library list returned its whole queryset, so a search across a
few thousand books serialised all of them, thumbnails and progress included.

The shape is `{"count": N, "results": [...]}` rather than a bare array. A cap on
its own is worse than no cap: the client cannot tell a full page from the end of
the list, so silently returning the first hundred of four hundred looks exactly
like a library with a hundred books in it. `count` is what makes the truncation
visible, and `limit`/`offset` are what let a client do something about it.
"""

from __future__ import annotations

from typing import Any

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


def _int(raw: str | None, fallback: int) -> int:
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def page_params(request, *, default: int = DEFAULT_LIMIT) -> tuple[int, int]:
    """`limit` and `offset`, clamped. Nonsense falls back rather than 400s —
    a bad page size is not worth failing a library listing over."""
    limit = max(1, min(_int(request.GET.get("limit"), default), MAX_LIMIT))
    offset = max(0, _int(request.GET.get("offset"), 0))
    return limit, offset


def paginate(queryset, request, *, default: int = DEFAULT_LIMIT) -> tuple[Any, dict]:
    """Slice `queryset`, and return it with the metadata for the envelope.

    `count` is taken before slicing, and is the whole point: it is how a client
    knows there is more.
    """
    limit, offset = page_params(request, default=default)
    total = queryset.count()
    return queryset[offset:offset + limit], {
        "count": total, "limit": limit, "offset": offset,
    }


def envelope(data, meta: dict) -> dict:
    return {**meta, "results": data}
