"""Cookies left at "/" by a release that predates the path prefix.

A browser that held them sends every cookie name twice, and the two ends of
the CSRF handshake then disagree about which one counts — so this is a lockout,
not an inconvenience, and it gets tests.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

CSRF = "lumaindex_csrftoken"
SESSION = "lumaindex_session"

# Django rotates a CSRF cookie it cannot parse, and a response that sets the
# cookie is one this middleware deliberately leaves alone — so the values here
# have to be the 32 alphanumerics a real token is.
PREFIXED = "prefixedprefixedprefixedprefixed"
STALE = "stalestalestalestalestalestalest"


def _get(path="/api/health/", cookie=None):
    client = Client()
    if cookie is None:
        return client.get(path)
    return client.get(path, headers={"cookie": cookie})


@pytest.fixture
def prefixed(settings):
    settings.BASE_PATH = "/luma-index"
    return settings


def test_duplicate_cookie_is_expired_at_the_root_path(prefixed):
    response = _get(cookie=f"{CSRF}={PREFIXED}; {CSRF}={STALE}")
    morsel = response.cookies[CSRF]
    assert morsel.value == ""
    assert morsel["path"] == "/"
    assert morsel["max-age"] == 0


def test_the_session_cookie_is_expired_the_same_way(prefixed):
    response = _get(cookie=f"{SESSION}={PREFIXED}; {SESSION}={STALE}")
    assert response.cookies[SESSION]["path"] == "/"


def test_only_the_duplicated_name_is_touched(prefixed):
    response = _get(cookie=f"{CSRF}={PREFIXED}; {CSRF}={STALE}; {SESSION}={PREFIXED}")
    assert CSRF in response.cookies
    assert SESSION not in response.cookies


def test_a_single_cookie_is_left_alone(prefixed):
    """Self-terminating: with the stale cookie gone there is nothing to send."""
    response = _get(cookie=f"{CSRF}={PREFIXED}; {SESSION}={PREFIXED}")
    assert CSRF not in response.cookies
    assert SESSION not in response.cookies


def test_a_cookie_whose_name_merely_ends_in_ours_is_not_a_duplicate(prefixed):
    response = _get(cookie=f"{CSRF}={PREFIXED}; other_{CSRF}={STALE}")
    assert CSRF not in response.cookies


def test_an_instance_on_its_own_origin_never_deletes_anything(settings):
    """There "/" is where the cookies belong, so a duplicate is not ours to judge."""
    settings.BASE_PATH = ""
    response = _get(cookie=f"{CSRF}={PREFIXED}; {CSRF}={STALE}")
    assert CSRF not in response.cookies


@pytest.mark.django_db
def test_an_unsafe_request_echoing_the_last_cookie_passes_csrf(prefixed, user):
    """Django validates against the last occurrence, so that is the one to echo.

    The regression this whole middleware exists for: echoing the *first* is
    what the SPA used to do, and it failed every unsafe request.
    """
    # enforce_csrf_checks, or the test client waves the check through and the
    # assertions below would hold whatever the middleware did.
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    client.get(reverse("accounts:csrf"))
    prefixed_token = client.cookies[CSRF].value
    session = client.cookies[SESSION].value

    # What the browser sends: the prefixed cookie first, because its path is
    # longer, and the one left at "/" last.
    duplicated = f"{SESSION}={session}; {CSRF}={prefixed_token}; {CSRF}={STALE}"

    def create(name, echoed):
        return client.post(
            reverse("library:folders"), {"name": name}, content_type="application/json",
            headers={"cookie": duplicated, "x-csrftoken": echoed},
        )

    assert create("nope", prefixed_token).status_code == 403
    echoing_the_last = create("yes", STALE)
    assert echoing_the_last.status_code == 201
    # And the round trip that finally works is the one that clears the stale
    # cookie, so the next request is unambiguous.
    assert echoing_the_last.cookies[CSRF]["max-age"] == 0
