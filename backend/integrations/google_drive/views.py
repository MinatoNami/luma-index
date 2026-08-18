"""Drive connection endpoints."""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from django.conf import settings
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from library.models import Book

from . import oauth
from .client import DriveClient
from .errors import DriveAuthError, DriveError
from .models import DriveConnection, DriveRoot
from .serializers import (
    AddRootSerializer,
    DisconnectSerializer,
    DriveConnectionSerializer,
    DriveFolderSerializer,
    DriveRootSerializer,
)

logger = logging.getLogger("lumaindex.drive")

csrf_required = method_decorator(csrf_protect, name="dispatch")


def _connection_for(user) -> DriveConnection | None:
    return DriveConnection.objects.filter(user=user).order_by("-created_at").first()


class DriveStatusView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Drive connection status", responses={200: dict})
    def get(self, request):
        connection = _connection_for(request.user)
        return Response({
            "configured": settings.GOOGLE_DRIVE_CONFIGURED,
            "connection": (DriveConnectionSerializer(connection).data if connection else None),
        })


@csrf_required
class DriveConnectView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Begin the Drive OAuth flow", request=None, responses={200: dict})
    def post(self, request):
        if not settings.GOOGLE_DRIVE_CONFIGURED:
            return Response(
                {"detail": "Google Drive is not configured on this instance."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        state = oauth.issue_state(request.session)
        return Response({"authorization_url": oauth.build_authorization_url(state)})


class DriveCallbackView(APIView):
    """Where Google sends the browser back.

    A top-level GET navigation, so the SameSite=Lax session cookie is sent and
    the user is still identified. Returns a redirect rather than JSON because
    the browser lands here directly.
    """

    permission_classes = [IsAuthenticated]

    def _back(self, **params) -> HttpResponseRedirect:
        # urlencode, not f-string concatenation: `error` is whatever Google put
        # in the query string, and interpolating it raw would let a crafted
        # value add parameters to this redirect.
        query = urlencode({k: str(v)[:200] for k, v in params.items()})
        return redirect(f"{settings.PUBLIC_ORIGIN.rstrip('/')}/settings/drive?{query}")

    @extend_schema(summary="Google OAuth callback", responses={302: OpenApiResponse()})
    def get(self, request):
        if error := request.GET.get("error"):
            # User pressed Cancel, most often.
            return self._back(error=error)

        # Burn the state before anything else. Without this check an attacker
        # can complete the flow in the victim's browser and attach their own
        # Drive to the victim's account.
        if not oauth.consume_state(request.session, request.GET.get("state", "")):
            logger.warning("drive oauth state rejected",
                           extra={"event": "drive.oauth.bad_state", "user_id": request.user.pk})
            return self._back(error="invalid_state")

        code = request.GET.get("code", "")
        if not code:
            return self._back(error="missing_code")

        try:
            token = oauth.exchange_code(code)
            claims = oauth.verify_id_token(token.id_token) if token.id_token else {}
        except DriveError as exc:
            logger.warning("drive oauth exchange failed",
                           extra={"event": "drive.oauth.failed", "user_id": request.user.pk,
                                  "reason": type(exc).__name__})
            return self._back(error="exchange_failed")

        if not token.refresh_token:
            # Without one the connection cannot outlive the first access token.
            # Usually means a prior grant was reused; prompt=consent should
            # prevent it, so surface it rather than storing a doomed connection.
            return self._back(error="no_refresh_token")

        account_id = claims.get("sub") or ""
        if not account_id:
            return self._back(error="no_identity")

        connection, _ = DriveConnection.objects.update_or_create(
            user=request.user,
            provider_account_id=account_id,
            defaults={
                "provider_email": claims.get("email", ""),
                "refresh_token": token.refresh_token,
                "scopes_granted": token.scope,
                "status": DriveConnection.Status.ACTIVE,
                "status_detail": "",
            },
        )
        oauth.forget_access_token(connection)

        logger.info("drive connected", extra={"event": "drive.connected",
                                              "user_id": request.user.pk,
                                              "connection_id": connection.pk})
        return self._back(connected="1")


@csrf_required
class DriveDisconnectView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Disconnect Drive", request=DisconnectSerializer,
                   responses={204: OpenApiResponse(description="Disconnected")})
    def post(self, request):
        connection = _connection_for(request.user)
        if connection is None:
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = DisconnectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        delete_library = serializer.validated_data["delete_library"]

        token = connection.refresh_token
        with transaction.atomic():
            if delete_library:
                # Explicitly requested. Books cascade to their sources; PRD §33
                # requires this to be a deliberate act, never a side effect.
                Book.objects.filter(owner=request.user, source__drive_connection=connection
                                    ).delete()
            oauth.forget_access_token(connection)
            connection.delete()   # sources keep their rows via SET_NULL

        if token:
            oauth.revoke(token)   # best effort; local state is already gone

        logger.info("drive disconnected",
                    extra={"event": "drive.disconnected", "user_id": request.user.pk,
                           "deleted_library": delete_library})
        return Response(status=status.HTTP_204_NO_CONTENT)


class DriveFolderListView(APIView):
    """Browse Drive folders for the root picker."""

    permission_classes = [IsAuthenticated]

    @extend_schema(summary="List Drive folders", responses={200: DriveFolderSerializer(many=True)})
    def get(self, request):
        connection = _connection_for(request.user)
        if connection is None:
            return Response({"detail": "No Drive connection."}, status=status.HTTP_404_NOT_FOUND)

        parent = request.GET.get("parent") or "root"
        try:
            token = oauth.get_access_token(connection)
            client = DriveClient(token)
            folders = [
                {"id": f.id, "name": f.name}
                for f in client.list_children(parent, only_folders=True)
            ]
        except DriveAuthError:
            return Response({"detail": "Drive authorization expired. Reconnect to continue.",
                             "code": "reauthorization_required"},
                            status=status.HTTP_409_CONFLICT)
        except DriveError as exc:
            return Response({"detail": f"Drive is unavailable ({type(exc).__name__})."},
                            status=status.HTTP_502_BAD_GATEWAY)

        return Response(DriveFolderSerializer(folders, many=True).data)


@csrf_required
class DriveRootListView(APIView):
    permission_classes = [IsAuthenticated]

    def _connection_or_404(self, request):
        connection = _connection_for(request.user)
        if connection is None:
            return None, Response({"detail": "No Drive connection."},
                                  status=status.HTTP_404_NOT_FOUND)
        return connection, None

    @extend_schema(summary="Selected root folders", responses={200: DriveRootSerializer(many=True)})
    def get(self, request):
        connection, error = self._connection_or_404(request)
        if error:
            return error
        return Response(DriveRootSerializer(connection.roots.all(), many=True).data)

    @extend_schema(summary="Add a root folder", request=AddRootSerializer,
                   responses={201: DriveRootSerializer})
    def post(self, request):
        connection, error = self._connection_or_404(request)
        if error:
            return error

        serializer = AddRootSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        root, created = DriveRoot.objects.get_or_create(
            drive_connection=connection,
            provider_folder_id=serializer.validated_data["provider_folder_id"],
            defaults={"name": serializer.validated_data["name"],
                      "original_path": serializer.validated_data.get("original_path", "")},
        )
        return Response(DriveRootSerializer(root).data,
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@csrf_required
class DriveRootDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Remove a root folder",
                   responses={204: OpenApiResponse(description="Removed")})
    def delete(self, request, root_id: int):
        root = DriveRoot.objects.filter(
            pk=root_id, drive_connection__user=request.user
        ).first()
        if root is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        # Removing a root stops future syncing. It does not delete books —
        # doing so would take annotations with them for a settings change.
        root.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
