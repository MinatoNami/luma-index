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

from drf_spectacular.utils import OpenApiParameter, inline_serializer
from rest_framework import serializers

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


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
#
# Declared rather than assumed, because the alternative was tried: the six
# endpoints below kept `responses={200: XSerializer(many=True)}` for exactly as
# long as it took someone to read the schema and believe it. PRD §45 lists a
# published OpenAPI schema as a criterion, which makes a wrong one worse than
# none. `test_schema.py` checks these against real responses.

PAGE_PARAMS = [
    OpenApiParameter("limit", int, description=(
        f"How many to return. Default {DEFAULT_LIMIT}, capped at {MAX_LIMIT}.")),
    OpenApiParameter("offset", int, description="How many to skip."),
]


def paginated(child, name: str):
    """The envelope `child` comes back in, for `responses={200: ...}`."""
    return inline_serializer(name=name, fields={
        "count": serializers.IntegerField(
            help_text="How many there are in total, not how many arrived."),
        "limit": serializers.IntegerField(),
        "offset": serializers.IntegerField(),
        "results": child(many=True),
    })
