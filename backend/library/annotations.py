"""Validation for highlight anchors.

`position_data` arrives from the browser, so it is validated rather than
trusted: a highlight is stored once and read back for years, and a malformed
one would break the reader every time that page is opened.

The format is versioned from the very first write. Adding a version later means
guessing what unversioned rows meant.
"""

from __future__ import annotations

from rest_framework import serializers

CURRENT_VERSION = 1
MAX_QUADS = 400
# PDF user space is points at 72/inch. A 200x200 inch page would be absurd, and
# a coordinate outside this range is a bug or an attempt at one.
COORD_LIMIT = 20000


def validate_position_data(value) -> dict:
    if not isinstance(value, dict):
        raise serializers.ValidationError("position_data must be an object.")

    version = value.get("v", CURRENT_VERSION)
    if version != CURRENT_VERSION:
        raise serializers.ValidationError(
            f"Unsupported position_data version {version!r}; this server writes v{CURRENT_VERSION}."
        )

    quads = value.get("quads")
    if not isinstance(quads, list) or not quads:
        raise serializers.ValidationError("position_data.quads must be a non-empty list.")
    if len(quads) > MAX_QUADS:
        raise serializers.ValidationError(
            f"A highlight may span at most {MAX_QUADS} rectangles."
        )

    cleaned = []
    for quad in quads:
        if not isinstance(quad, dict):
            raise serializers.ValidationError("Each quad must be an object.")
        point = {}
        for key in ("x1", "y1", "x2", "y2"):
            raw = quad.get(key)
            if not isinstance(raw, (int, float)) or isinstance(raw, bool):
                raise serializers.ValidationError(f"quad.{key} must be a number.")
            if not (-COORD_LIMIT <= raw <= COORD_LIMIT):
                raise serializers.ValidationError(f"quad.{key} is out of range.")
            point[key] = float(raw)
        cleaned.append(point)

    result: dict = {"v": CURRENT_VERSION, "quads": cleaned}

    offsets = value.get("text_offsets")
    if isinstance(offsets, dict):
        start, end = offsets.get("start"), offsets.get("end")
        if isinstance(start, int) and isinstance(end, int) and 0 <= start <= end:
            # A secondary anchor: if a file is replaced by a re-scan with
            # slightly different geometry, offsets can often re-locate the
            # selection when coordinates cannot.
            result["text_offsets"] = {"start": start, "end": end}

    return result
