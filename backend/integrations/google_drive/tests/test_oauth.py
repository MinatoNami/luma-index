"""OAuth flow, including the checks that are load-bearing for account safety."""

from __future__ import annotations

import httpx
import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from integrations.google_drive import oauth
from integrations.google_drive.errors import DriveAuthError, DriveUnavailable
from integrations.google_drive.models import DriveConnection
from library.models import Book, BookSource

User = get_user_model()

PASSWORD = "a-long-enough-password-42"
SETTINGS = dict(
    GOOGLE_OAUTH_CLIENT_ID="client-id",
    GOOGLE_OAUTH_CLIENT_SECRET="client-secret",  # noqa: S106
    GOOGLE_OAUTH_REDIRECT_URI="https://luma.test/api/drive/oauth/callback",
    GOOGLE_DRIVE_CONFIGURED=True,
    PUBLIC_ORIGIN="https://luma.test",
)


@pytest.fixture(autouse=True)
def oauth_settings(settings):
    for key, value in SETTINGS.items():
        setattr(settings, key, value)
    return settings


@pytest.fixture
def user(db):
    return User.objects.create_user(email="alice@example.com", password=PASSWORD)


@pytest.fixture
def auth_client(user):
    client = Client()
    client.force_login(user)
    client.get(reverse("accounts:csrf"))
    return client


def csrf(client) -> dict:
    return {"x-csrftoken": client.cookies["lumaindex_csrftoken"].value}


def token_endpoint(payload: dict, status_code: int = 200) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(status_code, json=payload)
    ))


# -- authorization URL -------------------------------------------------------- #

def test_authorization_url_requests_offline_access_and_forces_consent():
    """Without both, the connection cannot refresh and dies within the hour."""
    url = oauth.build_authorization_url("state-value")
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "client_id=client-id" in url
    assert "state=state-value" in url


# -- state -------------------------------------------------------------------- #

def test_state_round_trips():
    session = {}
    state = oauth.issue_state(_FakeSession(session))
    assert oauth.consume_state(_FakeSession(session), state) is True


def test_state_is_single_use():
    store = {}
    session = _FakeSession(store)
    state = oauth.issue_state(session)
    assert oauth.consume_state(session, state) is True
    assert oauth.consume_state(session, state) is False


def test_state_from_another_session_is_rejected():
    """The attack: complete the flow in a victim's browser to attach your Drive."""
    attacker_state = oauth.issue_state(_FakeSession({}))
    victim_session = _FakeSession({})
    oauth.issue_state(victim_session)
    assert oauth.consume_state(victim_session, attacker_state) is False


def test_tampered_state_is_rejected():
    store = {}
    session = _FakeSession(store)
    state = oauth.issue_state(session)
    assert oauth.consume_state(_FakeSession(store), state[:-3] + "aaa") is False


class _FakeSession(dict):
    def __init__(self, backing: dict):
        super().__init__(backing)
        self._backing = backing
        self.modified = False

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._backing[key] = value

    def pop(self, key, default=None):
        self._backing.pop(key, None)
        return super().pop(key, default)


# -- ID token ----------------------------------------------------------------- #

def test_unverified_email_is_refused():
    """Gap #2: the rule that stops account takeover once Google sign-in exists."""
    with pytest.raises(DriveAuthError, match="not verified"):
        oauth.verify_id_token("t", verifier=lambda _: {
            "sub": "google-sub-1", "email": "victim@example.com", "email_verified": False,
        })


def test_verified_email_is_accepted():
    claims = oauth.verify_id_token("t", verifier=lambda _: {
        "sub": "google-sub-1", "email": "alice@gmail.com", "email_verified": True,
    })
    assert claims["sub"] == "google-sub-1"


def test_token_without_a_subject_is_refused():
    with pytest.raises(DriveAuthError):
        oauth.verify_id_token("t", verifier=lambda _: {"email_verified": True})


def test_invalid_signature_is_refused():
    def explode(_):
        raise ValueError("bad signature")

    with pytest.raises(DriveAuthError):
        oauth.verify_id_token("t", verifier=explode)


# -- refresh ------------------------------------------------------------------ #

@pytest.mark.django_db
def test_refresh_returns_an_access_token(user):
    connection = DriveConnection.objects.create(user=user, provider_account_id="sub-1",
                                                refresh_token="refresh-1")
    token = oauth.get_access_token(
        connection, http=token_endpoint({"access_token": "at-1", "expires_in": 3600})
    )
    assert token == "at-1"


@pytest.mark.django_db
def test_access_token_is_cached_between_calls(user):
    connection = DriveConnection.objects.create(user=user, provider_account_id="sub-1",
                                                refresh_token="refresh-1")
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})

    http = httpx.Client(transport=httpx.MockTransport(transport))
    oauth.get_access_token(connection, http=http)
    oauth.get_access_token(connection, http=http)
    assert len(calls) == 1


@pytest.mark.django_db
def test_invalid_grant_marks_the_connection_expired_and_keeps_the_library(user):
    """Testing mode expires refresh tokens weekly; it must cost nothing."""
    connection = DriveConnection.objects.create(user=user, provider_account_id="sub-1",
                                                refresh_token="refresh-1")
    book = Book.objects.create(owner=user, title="DDIA")
    BookSource.objects.create(book=book, drive_connection=connection,
                              provider_file_id="f1", filename="DDIA.pdf")

    with pytest.raises(DriveAuthError):
        oauth.get_access_token(
            connection, http=token_endpoint({"error": "invalid_grant"}, 400)
        )

    connection.refresh_from_db()
    assert connection.status == DriveConnection.Status.EXPIRED
    assert Book.objects.filter(pk=book.pk).exists()
    assert BookSource.objects.filter(book=book).exists()


@pytest.mark.django_db
def test_a_server_error_does_not_mark_the_connection_expired(user):
    """A Google outage is not a lost grant, and must not look like one."""
    connection = DriveConnection.objects.create(user=user, provider_account_id="sub-1",
                                                refresh_token="refresh-1")
    with pytest.raises(DriveUnavailable):
        oauth.get_access_token(connection, http=token_endpoint({"error": "backend_error"}, 503))

    connection.refresh_from_db()
    assert connection.status == DriveConnection.Status.ACTIVE


@pytest.mark.django_db
def test_a_successful_refresh_clears_a_previous_expiry(user):
    connection = DriveConnection.objects.create(
        user=user, provider_account_id="sub-1", refresh_token="refresh-1",
        status=DriveConnection.Status.EXPIRED, status_detail="was expired",
    )
    oauth.get_access_token(connection,
                           http=token_endpoint({"access_token": "at", "expires_in": 3600}))
    connection.refresh_from_db()
    assert connection.status == DriveConnection.Status.ACTIVE
    assert connection.status_detail == ""


# -- endpoints ---------------------------------------------------------------- #

@pytest.mark.django_db
def test_status_requires_authentication():
    assert Client().get(reverse("drive:status")).status_code == 403


@pytest.mark.django_db
def test_status_reports_no_connection(auth_client):
    body = auth_client.get(reverse("drive:status")).json()
    assert body["configured"] is True
    assert body["connection"] is None


@pytest.mark.django_db
def test_status_never_exposes_the_refresh_token(auth_client, user):
    DriveConnection.objects.create(user=user, provider_account_id="sub-1",
                                   refresh_token="1//super-secret", provider_email="a@gmail.com")
    raw = auth_client.get(reverse("drive:status")).content.decode()
    assert "1//super-secret" not in raw
    assert "refresh_token" not in raw


@pytest.mark.django_db
def test_connect_returns_an_authorization_url(auth_client):
    response = auth_client.post(reverse("drive:connect"), headers=csrf(auth_client))
    assert response.status_code == 200
    assert response.json()["authorization_url"].startswith(
        "https://accounts.google.com/o/oauth2/v2/auth?"
    )


@pytest.mark.django_db
def test_connect_reports_when_drive_is_not_configured(auth_client, settings):
    settings.GOOGLE_DRIVE_CONFIGURED = False
    response = auth_client.post(reverse("drive:connect"), headers=csrf(auth_client))
    assert response.status_code == 503


@pytest.mark.django_db
def test_callback_rejects_a_forged_state(auth_client):
    response = auth_client.get(reverse("drive:callback"), {"code": "c", "state": "forged"})
    assert response.status_code == 302
    assert "error=invalid_state" in response.url
    assert not DriveConnection.objects.exists()


@pytest.mark.django_db
def test_callback_passes_through_a_user_cancellation(auth_client):
    response = auth_client.get(reverse("drive:callback"), {"error": "access_denied"})
    assert "error=access_denied" in response.url
    assert not DriveConnection.objects.exists()


@pytest.mark.django_db
def test_callback_requires_authentication():
    assert Client().get(reverse("drive:callback"), {"code": "c"}).status_code == 403


@pytest.mark.django_db
def test_disconnect_keeps_the_library_by_default(auth_client, user):
    connection = DriveConnection.objects.create(user=user, provider_account_id="sub-1",
                                                refresh_token="")
    book = Book.objects.create(owner=user, title="Dune")
    BookSource.objects.create(book=book, drive_connection=connection,
                              provider_file_id="f1", filename="Dune.pdf")

    response = auth_client.post(reverse("drive:disconnect"), {},
                                content_type="application/json", headers=csrf(auth_client))

    assert response.status_code == 204
    assert not DriveConnection.objects.exists()
    assert Book.objects.filter(pk=book.pk).exists()
    assert BookSource.objects.get(book=book).drive_connection is None


@pytest.mark.django_db
def test_disconnect_can_delete_the_library_when_asked(auth_client, user):
    connection = DriveConnection.objects.create(user=user, provider_account_id="sub-1",
                                                refresh_token="")
    book = Book.objects.create(owner=user, title="Dune")
    BookSource.objects.create(book=book, drive_connection=connection,
                              provider_file_id="f1", filename="Dune.pdf")

    auth_client.post(reverse("drive:disconnect"), {"delete_library": True},
                     content_type="application/json", headers=csrf(auth_client))

    assert not Book.objects.filter(pk=book.pk).exists()


@pytest.mark.django_db
def test_removing_a_root_does_not_delete_books(auth_client, user):
    from integrations.google_drive.models import DriveRoot

    connection = DriveConnection.objects.create(user=user, provider_account_id="sub-1")
    root = DriveRoot.objects.create(drive_connection=connection,
                                    provider_folder_id="folder-1", name="Books")
    book = Book.objects.create(owner=user, title="Dune")
    BookSource.objects.create(book=book, drive_connection=connection,
                              provider_file_id="f1", filename="Dune.pdf")

    response = auth_client.delete(
        reverse("drive:root-detail", args=[root.pk]), headers=csrf(auth_client)
    )
    assert response.status_code == 204
    assert Book.objects.filter(pk=book.pk).exists()


@pytest.mark.django_db
def test_a_user_cannot_remove_another_users_root(auth_client, user):
    from integrations.google_drive.models import DriveRoot

    other = User.objects.create_user(email="mallory@example.com", password=PASSWORD)
    connection = DriveConnection.objects.create(user=other, provider_account_id="sub-2")
    root = DriveRoot.objects.create(drive_connection=connection,
                                    provider_folder_id="f", name="Theirs")

    response = auth_client.delete(
        reverse("drive:root-detail", args=[root.pk]), headers=csrf(auth_client)
    )
    assert response.status_code == 404
    assert DriveRoot.objects.filter(pk=root.pk).exists()
