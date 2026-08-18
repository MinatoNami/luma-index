"""Session-cookie authentication endpoints for the Nuxt frontend.

The flow the frontend follows:

    GET  /api/auth/csrf/      -> sets the CSRF cookie
    POST /api/auth/login/     -> sets the session cookie
    GET  /api/auth/session/   -> who am I (204 when anonymous)
    POST /api/auth/logout/    -> clears the session

No tokens are handed to JavaScript: the session cookie is HttpOnly, per PRD §7.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import login, logout, update_session_auth_hash
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from common.net import client_ip_for_log
from common.throttling import TargetedAccountThrottle

from .serializers import (
    LoginSerializer,
    PasswordChangeSerializer,
    RegisterSerializer,
    UserSerializer,
)

logger = logging.getLogger("lumaindex.accounts")

# DRF marks every APIView csrf_exempt and leaves CSRF enforcement to
# SessionAuthentication — which only runs once a request is already
# authenticated. That leaves anonymous POSTs (login, register) unprotected, so
# a third-party site could sign a visitor into an account it controls and
# harvest whatever they then read or annotate. These views opt back in.
csrf_required = method_decorator(csrf_protect, name="dispatch")


class CsrfView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        summary="Issue a CSRF cookie",
        responses={204: OpenApiResponse(description="CSRF cookie set")},
    )
    def get(self, request):
        get_token(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SessionView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        summary="Current session",
        responses={200: UserSerializer, 204: OpenApiResponse(description="Not signed in")},
    )
    def get(self, request):
        if not request.user.is_authenticated:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(UserSerializer(request.user).data)


@csrf_required
class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth"
    throttle_classes = [ScopedRateThrottle, TargetedAccountThrottle]

    @extend_schema(summary="Sign in", request=LoginSerializer, responses={200: UserSerializer})
    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            logger.warning(
                "authentication failed",
                extra={"event": "auth.login.failed",
                       "client_ip": client_ip_for_log(request),
                       "email_domain": str(request.data.get("email", "")).rsplit("@", 1)[-1]},
            )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = serializer.validated_data["user"]
        login(request, user)
        logger.info("authenticated", extra={"event": "auth.login.ok", "user_id": user.pk})
        return Response(UserSerializer(user).data)


@csrf_required
class LogoutView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(summary="Sign out", request=None,
                   responses={204: OpenApiResponse(description="Signed out")})
    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


@csrf_required
class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth"

    @extend_schema(
        summary="Create an account",
        request=RegisterSerializer,
        responses={201: UserSerializer,
                   403: OpenApiResponse(description="Registration is disabled")},
    )
    def post(self, request):
        if not settings.REGISTRATION_ENABLED:
            return Response(
                {"detail": "Registration is disabled on this instance."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        login(request, user)
        logger.info("account created", extra={"event": "auth.register", "user_id": user.pk})
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


@csrf_required
class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "auth"

    @extend_schema(
        summary="Change password",
        request=PasswordChangeSerializer,
        responses={204: OpenApiResponse(description="Password changed")},
    )
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password", "updated_at"])
        # Keeps this device signed in; other sessions keep working until they
        # expire. Tighten to a full session flush if you want change-password
        # to sign out every other device.
        update_session_auth_hash(request, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
