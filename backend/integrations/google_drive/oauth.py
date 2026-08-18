"""Google OAuth: authorization URL, code exchange, token refresh, revocation.

Written against the token endpoint directly (it is one POST) rather than
pulling in google-auth-oauthlib. `google-auth` is still used for the one thing
worth not hand-rolling: verifying the ID token's signature.

See docs/google-oauth.md for why the scope in settings is a decision and not a
default, and why refresh tokens may expire weekly.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from django.conf import settings
from django.core import signing
from django.core.cache import cache

from .client import AUTH_URL, REVOKE_URL, TOKEN_URL
from .errors import DriveAuthError, DriveUnavailable

logger = logging.getLogger("lumaindex.drive.oauth")

STATE_SALT = "lumaindex.drive.oauth.state"
STATE_MAX_AGE = 600  # ten minutes to complete the consent screen
SESSION_STATE_KEY = "drive_oauth_nonce"

# Refresh a little before expiry so an in-flight sync does not trip over it.
ACCESS_TOKEN_SKEW = 120


@dataclass(frozen=True)
class TokenResponse:
    access_token: str
    expires_in: int
    scope: str = ""
    refresh_token: str | None = None
    id_token: str | None = None


def _http() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(20.0))


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #

def issue_state(session) -> str:
    """A signed, single-use, session-bound `state`.

    All three properties matter. Without the session binding an attacker can
    complete the flow in a victim's browser and attach *their* Drive to the
    victim's account — the OAuth equivalent of login CSRF.
    """
    nonce = secrets.token_urlsafe(24)
    session[SESSION_STATE_KEY] = nonce
    session.modified = True
    return signing.dumps({"nonce": nonce}, salt=STATE_SALT)


def consume_state(session, state: str) -> bool:
    """Validate and burn the state. False means do not proceed."""
    expected = session.pop(SESSION_STATE_KEY, None)
    session.modified = True
    if not expected or not state:
        return False
    try:
        payload = signing.loads(state, salt=STATE_SALT, max_age=STATE_MAX_AGE)
    except signing.BadSignature:
        return False
    return secrets.compare_digest(str(payload.get("nonce", "")), str(expected))


# --------------------------------------------------------------------------- #
# Flow
# --------------------------------------------------------------------------- #

def build_authorization_url(state: str) -> str:
    params = {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(settings.GOOGLE_DRIVE_SCOPES),
        "state": state,
        # Without offline access there is no refresh token, and the connection
        # dies the moment the first access token expires.
        "access_type": "offline",
        # Google withholds a refresh token on re-consent unless forced. Skipping
        # this produces a connection that works once and then cannot refresh.
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _token_request(data: dict, *, http: httpx.Client | None = None) -> TokenResponse:
    client = http or _http()
    try:
        response = client.post(TOKEN_URL, data=data)
    except httpx.RequestError as exc:
        raise DriveUnavailable(f"Could not reach Google: {type(exc).__name__}") from exc

    if response.status_code >= 400:
        payload = {}
        try:
            payload = response.json()
        except ValueError:
            pass
        error = payload.get("error", "")
        # The grant is gone: revoked by the user, expired under Testing mode's
        # 7-day rule, or the client credentials changed.
        if error in {"invalid_grant", "unauthorized_client", "invalid_client"}:
            raise DriveAuthError(f"Google rejected the grant ({error})")
        raise DriveUnavailable(f"Token endpoint returned {response.status_code} ({error})")

    payload = response.json()
    return TokenResponse(
        access_token=payload.get("access_token", ""),
        expires_in=int(payload.get("expires_in", 3600)),
        scope=payload.get("scope", ""),
        refresh_token=payload.get("refresh_token"),
        id_token=payload.get("id_token"),
    )


def exchange_code(code: str, *, http: httpx.Client | None = None) -> TokenResponse:
    return _token_request(
        {
            "code": code,
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        http=http,
    )


def verify_id_token(id_token: str, *, verifier=None) -> dict:
    """Verify the ID token and return its claims.

    Enforces `email_verified`. Google normally only issues verified addresses,
    but the check is what stops the account-takeover path if "Sign in with
    Google" is ever added and links accounts by matching email: an unverified
    claim would let anyone who can obtain one take over the matching account.
    Enforcing it here means the rule is already in place when that arrives.
    """
    if verifier is None:  # pragma: no cover — exercised via injection in tests
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token

        def verifier(token):
            return google_id_token.verify_oauth2_token(
                token, google_requests.Request(), settings.GOOGLE_OAUTH_CLIENT_ID
            )

    try:
        claims = verifier(id_token)
    except Exception as exc:
        raise DriveAuthError(f"Could not verify Google identity: {type(exc).__name__}") from exc

    if not claims.get("sub"):
        raise DriveAuthError("Google identity token carried no subject.")
    if claims.get("email") and not claims.get("email_verified"):
        raise DriveAuthError("This Google account's email address is not verified.")
    return claims


# --------------------------------------------------------------------------- #
# Access tokens
# --------------------------------------------------------------------------- #

def _cache_key(connection) -> str:
    return f"drive:access_token:{connection.pk}"


def get_access_token(connection, *, http: httpx.Client | None = None, force: bool = False) -> str:
    """A usable access token, refreshing only when needed.

    Cached because a sync makes many calls and Google's token endpoint is rate
    limited too. The cache is the shared database cache, so gunicorn workers and
    the sync worker do not each refresh separately.
    """
    if not force:
        cached = cache.get(_cache_key(connection))
        if cached:
            return cached

    if not connection.refresh_token:
        connection.mark_expired("No refresh token stored.")
        raise DriveAuthError("This Drive connection has no refresh token; reconnect required.")

    try:
        token = _token_request(
            {
                "refresh_token": connection.refresh_token,
                "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                "grant_type": "refresh_token",
            },
            http=http,
        )
    except DriveAuthError as exc:
        # The single most common cause is Testing mode's 7-day expiry. Record it
        # and stop; deleting anything here would lose the user's library over a
        # routine, expected event (PRD §13, §35).
        connection.mark_expired(str(exc))
        logger.warning("drive authorization lost",
                       extra={"event": "drive.auth.expired", "connection_id": connection.pk})
        raise

    cache.set(_cache_key(connection), token.access_token,
              max(60, token.expires_in - ACCESS_TOKEN_SKEW))

    if connection.status != connection.Status.ACTIVE:
        connection.status = connection.Status.ACTIVE
        connection.status_detail = ""
        connection.save(update_fields=["status", "status_detail", "updated_at"])

    return token.access_token


def forget_access_token(connection) -> None:
    cache.delete(_cache_key(connection))


def revoke(token: str, *, http: httpx.Client | None = None) -> bool:
    """Best-effort revocation at Google. Never blocks disconnecting locally."""
    client = http or _http()
    try:
        response = client.post(REVOKE_URL, data={"token": token})
        return response.status_code < 400
    except httpx.RequestError:
        return False
