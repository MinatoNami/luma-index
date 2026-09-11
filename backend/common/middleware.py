"""Response middleware."""

from __future__ import annotations

from django.conf import settings

# The cookies we own, with the SameSite each is set with so the deletion
# carries it too. A cookie at "/" under one of these names was set by an
# earlier release of this instance, never by a neighbour behind the gateway.
_OUR_COOKIES = (
    (settings.SESSION_COOKIE_NAME, settings.SESSION_COOKIE_SAMESITE),
    (settings.CSRF_COOKIE_NAME, settings.CSRF_COOKIE_SAMESITE),
)


def _duplicated(header: str) -> set[str]:
    """Names of our cookies the browser sent more than once.

    Read from the raw header because request.COOKIES has already collapsed the
    duplicate — keeping the last occurrence, which is the crux of the bug this
    middleware exists for.
    """
    sent = [chunk.split("=", 1)[0].strip() for chunk in header.split(";")]
    return {name for name, _ in _OUR_COOKIES if sent.count(name) > 1}


class ExpireRootPathCookies:
    """Delete our cookies left at "/" by a release that predates BASE_PATH.

    Both cookies are scoped to the path prefix now (see SESSION_COOKIE_PATH). A
    browser holding the old ones ends up with both: same name, different path,
    so the new cookie does not replace the old one — it joins it. Every request
    then carries the name twice and the two ends of the CSRF handshake disagree
    about which one counts. `document.cookie` puts the longer path first, so the
    SPA echoes the prefixed token; Django's cookie parser keeps the last
    occurrence, so it validates against the one at "/". Every unsafe request
    fails with "CSRF token from the 'X-CSRFToken' HTTP header incorrect" —
    including the login that would otherwise be the way out.

    Deleting at "/" leaves the cookie at the prefix alone, because a different
    path is a different cookie. So this ends the ambiguity rather than the
    session — unless the session was the one at "/", in which case signing in
    again is the point: that cookie was being handed to every other application
    behind the gateway, which is what scoping it to the prefix was for.

    Self-terminating: once the browser has dropped the old cookie there is no
    duplicate to detect and no deletion to send.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        # Nothing to do for an instance that owns its origin: "/" is exactly
        # where its cookies belong.
        self.enabled = bool(settings.BASE_PATH)

    def __call__(self, request):
        response = self.get_response(request)
        if not self.enabled:
            return response
        duplicated = _duplicated(request.META.get("HTTP_COOKIE", ""))
        for name, samesite in _OUR_COOKIES:
            # One Set-Cookie per name is all a response can carry, so a name
            # this response is already setting is left for the next one. The
            # duplicate is still there to find, and clobbering a rotated token
            # with a deletion for a different path would be the worse trade.
            if name in duplicated and name not in response.cookies:
                response.delete_cookie(name, path="/", samesite=samesite)
        return response
