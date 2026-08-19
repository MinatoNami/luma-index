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
from django.core.mail import send_mail
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
    AccountDeleteSerializer,
    LoginSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    ProfileSerializer,
    RegisterSerializer,
    UserSerializer,
    UserSettingsSerializer,
    build_reset_token,
)
from .settings_models import UserSettings

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
        # Every other session is already dead at this point: Django derives the
        # session auth hash from the password hash and verifies it on each
        # request, so changing the password signs out every other device. This
        # call re-stamps the *current* session so the user who just changed it
        # is not signed out too.
        update_session_auth_hash(request, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


@csrf_required
class PasswordResetRequestView(APIView):
    """Start a password reset.

    Always answers 204, whether or not the address has an account, and whether
    or not the mail actually went out. Anything else turns this endpoint into a
    way to enumerate the instance's users — a 500 from a refused SMTP handshake
    says "this address exists" exactly as loudly as a 404 would, and it says it
    only for the addresses that do.

    The cost is that a misconfigured relay is invisible from the outside, so it
    is logged at ERROR and `manage.py check_email` exists to check the
    configuration directly rather than by locking yourself out.
    """

    permission_classes = [AllowAny]
    throttle_scope = "auth"

    @extend_schema(
        summary="Request a password reset",
        request=PasswordResetRequestSerializer,
        responses={204: OpenApiResponse(
            description="Accepted. Sent only if the address has an active account.")},
    )
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.get_user()
        if user is not None:
            uid, token = build_reset_token(user)
            reset_url = f"{settings.PUBLIC_ORIGIN.rstrip('/')}/reset/{uid}/{token}"
            hours = settings.PASSWORD_RESET_TIMEOUT // 3600
            try:
                send_mail(
                    subject="Reset your LumaIndex password",
                    message=(
                        "Someone asked to reset the LumaIndex password for this "
                        "address.\n\n"
                        f"{reset_url}\n\n"
                        f"The link is valid for {hours} hour(s) and stops working "
                        "once it is used.\n\n"
                        "If this was not you, no action is needed — your password "
                        "has not changed."
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    fail_silently=False,
                )
            except Exception as exc:
                # Swallowed on purpose: see the class docstring. The type is
                # logged, never the message — SMTP errors quote the recipient
                # back, and the whole point is not to say who exists.
                logger.error("password reset email failed to send",
                             extra={"event": "auth.reset.send_failed",
                                    "user_id": user.pk,
                                    "reason": type(exc).__name__})
            else:
                # The URL carries the token, so it must never reach the log.
                logger.info("password reset requested",
                            extra={"event": "auth.reset.requested", "user_id": user.pk})
        else:
            logger.info("password reset requested for unknown address",
                        extra={"event": "auth.reset.unknown"})

        return Response(status=status.HTTP_204_NO_CONTENT)


@csrf_required
class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth"

    @extend_schema(
        summary="Complete a password reset",
        request=PasswordResetConfirmSerializer,
        responses={204: OpenApiResponse(description="Password changed")},
    )
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        logger.info("password reset completed",
                    extra={"event": "auth.reset.completed", "user_id": user.pk})
        # No automatic sign-in: whoever holds the link is not yet proven to be
        # the account owner beyond controlling the mailbox.
        return Response(status=status.HTTP_204_NO_CONTENT)


@csrf_required
class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Your profile", responses={200: ProfileSerializer})
    def get(self, request):
        return Response(ProfileSerializer(request.user).data)

    @extend_schema(summary="Update your profile", request=ProfileSerializer,
                   responses={200: ProfileSerializer})
    def patch(self, request):
        serializer = ProfileSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


@csrf_required
class UserSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Your preferences", responses={200: UserSettingsSerializer})
    def get(self, request):
        return Response(UserSettingsSerializer(UserSettings.for_user(request.user)).data)

    @extend_schema(summary="Update your preferences", request=UserSettingsSerializer,
                   responses={200: UserSettingsSerializer})
    def patch(self, request):
        serializer = UserSettingsSerializer(
            UserSettings.for_user(request.user), data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


@csrf_required
class AccountDeleteView(APIView):
    """PRD §33: a user must be able to delete their application account."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "auth"

    @extend_schema(
        summary="Delete your account",
        request=AccountDeleteSerializer,
        responses={204: OpenApiResponse(description="Account and files deleted")},
    )
    def post(self, request):
        serializer = AccountDeleteSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        user = request.user
        user_id = user.pk

        # Collect the storage keys before the rows go: once the books are
        # deleted there is nothing left pointing at the files, and they would
        # sit on disk forever.
        from library.models import BookSource
        from library.storage import LibraryStorage

        keys = list(
            BookSource.objects.filter(book__owner=user).values_list("storage_key", flat=True)
        )

        logout(request)
        user.delete()

        storage = LibraryStorage()
        removed = 0
        for key in set(keys):
            # Another account may hold the same bytes; the check keeps their
            # copy intact.
            removed += bool(storage.delete_if_unreferenced(key))

        logger.warning("account deleted",
                       extra={"event": "auth.account.deleted", "user_id": user_id,
                              "files_removed": removed})
        return Response(status=status.HTTP_204_NO_CONTENT)
