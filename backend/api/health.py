"""Health endpoints.

Deliberately two of them. A single health check that touches the database will
restart the backend every time Postgres hiccups, which turns a brief database
blip into a full outage. Liveness answers "is this process wedged", readiness
answers "can it serve traffic".
"""

from __future__ import annotations

import logging
import os

from django.conf import settings
from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger("lumaindex.health")


class LivenessView(APIView):
    """Process is up. No dependencies — this is what the container healthcheck hits."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(summary="Liveness probe", responses={200: dict})
    def get(self, request):
        return Response({"status": "ok"})


class ReadinessView(APIView):
    """Dependencies are usable. This is what the deploy script gates on."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(summary="Readiness probe", responses={200: dict, 503: dict})
    def get(self, request):
        checks: dict[str, str] = {}
        healthy = True

        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            checks["database"] = "ok"
        except Exception as exc:
            healthy = False
            checks["database"] = "error"
            logger.error("database health check failed", exc_info=exc)

        for label, path in (("pdf_cache", settings.PDF_CACHE_DIR),
                            ("thumbnails", settings.THUMBNAIL_DIR)):
            try:
                path.mkdir(parents=True, exist_ok=True)
                if not os.access(path, os.W_OK):
                    raise PermissionError(f"{path} is not writable")
                checks[label] = "ok"
            except Exception as exc:
                healthy = False
                checks[label] = "error"
                logger.error("storage health check failed",
                             extra={"path": str(path)}, exc_info=exc)

        return Response(
            {"status": "ok" if healthy else "degraded", "checks": checks},
            status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        )
