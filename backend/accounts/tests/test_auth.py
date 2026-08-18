"""Authentication and authorization-default tests.

PRD §29 requires server-side authorization. The `test_api_denies_anonymous_by_default`
case is the regression guard for that: if someone changes DRF's default
permission class, this fails.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

User = get_user_model()

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def user(db):
    return User.objects.create_user(email="alice@example.com", password=PASSWORD,
                                    display_name="Alice")


@pytest.mark.django_db
def test_email_is_lowercased_on_create():
    user = User.objects.create_user(email="Alice@Example.COM", password=PASSWORD)
    assert user.email == "alice@example.com"


@pytest.mark.django_db
def test_user_defaults_to_non_admin(user):
    assert user.role == User.Role.USER
    assert not user.is_staff
    assert not user.is_superuser
    assert user.is_active


@pytest.mark.django_db
def test_superuser_gets_admin_role():
    admin = User.objects.create_superuser(email="root@example.com", password=PASSWORD)
    assert admin.is_admin and admin.is_staff and admin.is_superuser


@pytest.mark.django_db
def test_login_sets_session_cookie(client: Client, user):
    response = client.post(reverse("accounts:login"),
                           {"email": "alice@example.com", "password": PASSWORD},
                           content_type="application/json")
    assert response.status_code == 200
    assert response.json()["email"] == "alice@example.com"
    assert "lumaindex_session" in response.cookies


@pytest.mark.django_db
def test_login_is_case_insensitive(client: Client, user):
    response = client.post(reverse("accounts:login"),
                           {"email": "ALICE@example.com", "password": PASSWORD},
                           content_type="application/json")
    assert response.status_code == 200


@pytest.mark.django_db
def test_login_rejects_bad_password(client: Client, user):
    response = client.post(reverse("accounts:login"),
                           {"email": "alice@example.com", "password": "wrong"},
                           content_type="application/json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_disabled_account_cannot_log_in(client: Client, user):
    user.is_active = False
    user.save(update_fields=["is_active"])
    response = client.post(reverse("accounts:login"),
                           {"email": "alice@example.com", "password": PASSWORD},
                           content_type="application/json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_session_returns_204_when_anonymous(client: Client):
    assert client.get(reverse("accounts:session")).status_code == 204


@pytest.mark.django_db
def test_logout_clears_session(client: Client, user):
    client.force_login(user)
    assert client.get(reverse("accounts:session")).status_code == 200
    assert client.post(reverse("accounts:logout")).status_code == 204
    assert client.get(reverse("accounts:session")).status_code == 204


@pytest.mark.django_db
@override_settings(REGISTRATION_ENABLED=False)
def test_registration_disabled_by_default(client: Client):
    response = client.post(reverse("accounts:register"),
                           {"email": "bob@example.com", "password": PASSWORD},
                           content_type="application/json")
    assert response.status_code == 403
    assert not User.objects.filter(email="bob@example.com").exists()


@pytest.mark.django_db
@override_settings(REGISTRATION_ENABLED=True)
def test_registration_enforces_password_strength(client: Client):
    response = client.post(reverse("accounts:register"),
                           {"email": "bob@example.com", "password": "short"},
                           content_type="application/json")
    assert response.status_code == 400


@pytest.mark.django_db
@override_settings(REGISTRATION_ENABLED=True)
def test_registration_rejects_duplicate_email_case_insensitively(client: Client, user):
    response = client.post(reverse("accounts:register"),
                           {"email": "ALICE@example.com", "password": PASSWORD},
                           content_type="application/json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_password_change_requires_current_password(client: Client, user):
    client.force_login(user)
    response = client.post(reverse("accounts:password-change"),
                           {"current_password": "nope", "new_password": "another-long-one-99"},
                           content_type="application/json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_api_denies_anonymous_by_default(client: Client):
    """DRF's default permission must stay deny-by-default."""
    from rest_framework.permissions import IsAuthenticated
    from rest_framework.settings import api_settings

    assert IsAuthenticated in api_settings.DEFAULT_PERMISSION_CLASSES


# --- CSRF ------------------------------------------------------------------- #
# DRF's APIViews are csrf_exempt and SessionAuthentication only enforces CSRF
# once a request is authenticated, so anonymous POSTs need explicit protection.
# These tests are the guard against that protection being removed.

@pytest.fixture
def csrf_client():
    return Client(enforce_csrf_checks=True)


@pytest.mark.django_db
def test_login_without_csrf_token_is_rejected(csrf_client: Client, user):
    response = csrf_client.post(reverse("accounts:login"),
                                {"email": "alice@example.com", "password": PASSWORD},
                                content_type="application/json")
    assert response.status_code == 403


@pytest.mark.django_db
def test_login_with_csrf_token_succeeds(csrf_client: Client, user):
    csrf_client.get(reverse("accounts:csrf"))
    token = csrf_client.cookies["lumaindex_csrftoken"].value
    response = csrf_client.post(reverse("accounts:login"),
                                {"email": "alice@example.com", "password": PASSWORD},
                                content_type="application/json",
                                headers={"x-csrftoken": token})
    assert response.status_code == 200


@pytest.mark.django_db
@override_settings(REGISTRATION_ENABLED=True)
def test_register_without_csrf_token_is_rejected(csrf_client: Client):
    response = csrf_client.post(reverse("accounts:register"),
                                {"email": "bob@example.com", "password": PASSWORD},
                                content_type="application/json")
    assert response.status_code == 403


@pytest.mark.django_db
def test_logout_without_csrf_token_is_rejected(csrf_client: Client, user):
    csrf_client.force_login(user)
    assert csrf_client.post(reverse("accounts:logout")).status_code == 403


@pytest.mark.django_db
def test_csrf_endpoint_itself_needs_no_token(csrf_client: Client):
    assert csrf_client.get(reverse("accounts:csrf")).status_code == 204


# --- Rate limiting ----------------------------------------------------------- #
# These guard two bugs that made PRD §32's "rate limit authentication"
# decorative: a per-process cache (each gunicorn worker counted separately) and
# DRF's default NUM_PROXIES=None (the throttle key was the caller's own
# X-Forwarded-For header, so varying it gave unlimited fresh buckets).

@pytest.fixture
def throttle_cache():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


def _attempt(client: Client, token: str, email: str = "alice@example.com", **headers):
    return client.post(reverse("accounts:login"),
                       {"email": email, "password": "definitely-wrong"},
                       content_type="application/json",
                       headers={"x-csrftoken": token, **headers})


@pytest.mark.django_db
@override_settings(REST_FRAMEWORK={
    **__import__("django.conf", fromlist=["settings"]).settings.REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {"auth": "3/min", "login_email": "100/min"},
})
def test_repeated_failures_from_one_address_are_throttled(throttle_cache, user):
    client = Client(enforce_csrf_checks=True)
    client.get(reverse("accounts:csrf"))
    token = client.cookies["lumaindex_csrftoken"].value

    codes = [_attempt(client, token).status_code for _ in range(6)]
    assert 429 in codes, f"never throttled: {codes}"


@pytest.mark.django_db
@override_settings(REST_FRAMEWORK={
    **__import__("django.conf", fromlist=["settings"]).settings.REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {"auth": "3/min", "login_email": "100/min"},
})
def test_spoofed_forwarded_for_cannot_reset_the_throttle(throttle_cache, user):
    """The attack that made the limit useless: a new X-Forwarded-For per request."""
    client = Client(enforce_csrf_checks=True)
    client.get(reverse("accounts:csrf"))
    token = client.cookies["lumaindex_csrftoken"].value

    codes = [
        _attempt(client, token, **{"x-forwarded-for": f"10.0.0.{i}"}).status_code
        for i in range(1, 8)
    ]
    assert 429 in codes, f"forged X-Forwarded-For bypassed the throttle: {codes}"


@pytest.mark.django_db
@override_settings(REST_FRAMEWORK={
    **__import__("django.conf", fromlist=["settings"]).settings.REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {"auth": "1000/min", "login_email": "3/min"},
})
def test_one_account_is_protected_across_addresses(throttle_cache, user):
    """Distributed stuffing against a single account is capped by the email key."""
    codes = []
    for i in range(1, 8):
        client = Client(enforce_csrf_checks=True)
        client.get(reverse("accounts:csrf"))
        token = client.cookies["lumaindex_csrftoken"].value
        codes.append(_attempt(client, token, **{"x-forwarded-for": f"10.0.0.{i}"}).status_code)
    assert 429 in codes, f"account-targeted throttle never fired: {codes}"


@pytest.mark.django_db
@override_settings(REST_FRAMEWORK={
    **__import__("django.conf", fromlist=["settings"]).settings.REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {"auth": "1000/min", "login_email": "3/min"},
})
def test_throttling_one_account_does_not_block_another(throttle_cache, user):
    """The per-account limit must not become a denial-of-service against a user."""
    User.objects.create_user(email="bob@example.com", password=PASSWORD)
    client = Client(enforce_csrf_checks=True)
    client.get(reverse("accounts:csrf"))
    token = client.cookies["lumaindex_csrftoken"].value

    for _ in range(6):
        _attempt(client, token, email="alice@example.com")

    assert _attempt(client, token, email="bob@example.com").status_code == 400


@pytest.mark.django_db
def test_client_ip_trusts_only_configured_proxy_hops(settings):
    from django.test import RequestFactory

    from common.net import client_ip

    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}
    from rest_framework.settings import api_settings
    api_settings.reload()

    request = RequestFactory().get("/")
    request.META["REMOTE_ADDR"] = "172.18.0.5"
    request.META["HTTP_X_FORWARDED_FOR"] = "1.2.3.4, 203.0.113.9"
    # One proxy: trust only the hop it appended, never the forged prefix.
    assert client_ip(request) == "203.0.113.9"
    api_settings.reload()


# --- Password reset ---------------------------------------------------------- #

def _request_reset(client: Client, email: str):
    client.get(reverse("accounts:csrf"))
    token = client.cookies["lumaindex_csrftoken"].value
    return client.post(reverse("accounts:password-reset"), {"email": email},
                       content_type="application/json", headers={"x-csrftoken": token})


def _reset_link_parts(mail_body: str) -> tuple[str, str]:
    import re
    match = re.search(r"/reset/([^/\s]+)/([^\s]+)", mail_body)
    assert match, f"no reset link in email:\n{mail_body}"
    return match.group(1), match.group(2)


@pytest.mark.django_db
def test_reset_request_sends_a_link(client: Client, user, mailoutbox):
    assert _request_reset(client, "alice@example.com").status_code == 204
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == ["alice@example.com"]


@pytest.mark.django_db
def test_reset_request_does_not_reveal_whether_an_account_exists(client: Client, user,
                                                                 mailoutbox):
    """Same status for a known and an unknown address, and no mail for the latter."""
    known = _request_reset(client, "alice@example.com")
    unknown = _request_reset(Client(), "nobody@example.com")
    assert known.status_code == unknown.status_code == 204
    assert [m.to for m in mailoutbox] == [["alice@example.com"]]


@pytest.mark.django_db
def test_reset_request_is_silent_for_disabled_accounts(client: Client, user, mailoutbox):
    user.is_active = False
    user.save(update_fields=["is_active"])
    assert _request_reset(client, "alice@example.com").status_code == 204
    assert mailoutbox == []


@pytest.mark.django_db
def test_full_reset_flow_changes_the_password(client: Client, user, mailoutbox):
    _request_reset(client, "alice@example.com")
    uid, token = _reset_link_parts(mailoutbox[0].body)

    new_password = "a-brand-new-passphrase-42"
    confirm = Client()
    confirm.get(reverse("accounts:csrf"))
    csrf = confirm.cookies["lumaindex_csrftoken"].value
    response = confirm.post(reverse("accounts:password-reset-confirm"),
                            {"uid": uid, "token": token, "new_password": new_password},
                            content_type="application/json", headers={"x-csrftoken": csrf})
    assert response.status_code == 204

    user.refresh_from_db()
    assert user.check_password(new_password)
    assert not user.check_password(PASSWORD)


@pytest.mark.django_db
def test_reset_token_is_single_use(client: Client, user, mailoutbox):
    _request_reset(client, "alice@example.com")
    uid, token = _reset_link_parts(mailoutbox[0].body)

    def attempt(password):
        c = Client()
        c.get(reverse("accounts:csrf"))
        csrf = c.cookies["lumaindex_csrftoken"].value
        return c.post(reverse("accounts:password-reset-confirm"),
                      {"uid": uid, "token": token, "new_password": password},
                      content_type="application/json", headers={"x-csrftoken": csrf})

    assert attempt("first-new-passphrase-42").status_code == 204
    assert attempt("second-new-passphrase-42").status_code == 400


@pytest.mark.django_db
def test_reset_rejects_a_tampered_token(client: Client, user, mailoutbox):
    _request_reset(client, "alice@example.com")
    uid, token = _reset_link_parts(mailoutbox[0].body)

    c = Client()
    c.get(reverse("accounts:csrf"))
    csrf = c.cookies["lumaindex_csrftoken"].value
    response = c.post(reverse("accounts:password-reset-confirm"),
                      {"uid": uid, "token": token[:-2] + "xy",
                       "new_password": "another-long-passphrase-42"},
                      content_type="application/json", headers={"x-csrftoken": csrf})
    assert response.status_code == 400
    user.refresh_from_db()
    assert user.check_password(PASSWORD)


@pytest.mark.django_db
def test_expired_reset_token_is_rejected(client: Client, user, mailoutbox, monkeypatch):
    _request_reset(client, "alice@example.com")
    uid, token = _reset_link_parts(mailoutbox[0].body)

    # Move the generator's clock past PASSWORD_RESET_TIMEOUT rather than setting
    # the timeout to zero — Django compares `elapsed > timeout`, so a zero
    # timeout with zero elapsed time still passes and the test proves nothing.
    from datetime import datetime, timedelta

    from django.contrib.auth.tokens import default_token_generator

    monkeypatch.setattr(default_token_generator, "_now",
                        lambda: datetime.now() + timedelta(seconds=7200))

    c = Client()
    c.get(reverse("accounts:csrf"))
    csrf = c.cookies["lumaindex_csrftoken"].value
    response = c.post(reverse("accounts:password-reset-confirm"),
                      {"uid": uid, "token": token, "new_password": "another-long-one-42"},
                      content_type="application/json", headers={"x-csrftoken": csrf})
    assert response.status_code == 400


@pytest.mark.django_db
def test_reset_enforces_password_strength(client: Client, user, mailoutbox):
    _request_reset(client, "alice@example.com")
    uid, token = _reset_link_parts(mailoutbox[0].body)

    c = Client()
    c.get(reverse("accounts:csrf"))
    csrf = c.cookies["lumaindex_csrftoken"].value
    response = c.post(reverse("accounts:password-reset-confirm"),
                      {"uid": uid, "token": token, "new_password": "short"},
                      content_type="application/json", headers={"x-csrftoken": csrf})
    assert response.status_code == 400


@pytest.mark.django_db
def test_reset_requires_csrf(user):
    c = Client(enforce_csrf_checks=True)
    assert c.post(reverse("accounts:password-reset"), {"email": "alice@example.com"},
                  content_type="application/json").status_code == 403


# --- Profile, settings, account deletion -------------------------------------- #

@pytest.mark.django_db
def test_password_change_signs_out_other_devices(user):
    """Django derives the session auth hash from the password hash and checks it
    on every request, so a password change invalidates every other session.
    The comment in the view used to claim the opposite."""
    laptop = Client()
    laptop.force_login(user)
    phone = Client()
    phone.force_login(user)
    assert phone.get(reverse("accounts:session")).status_code == 200

    laptop.get(reverse("accounts:csrf"))
    response = laptop.post(
        reverse("accounts:password-change"),
        {"current_password": PASSWORD, "new_password": "a-brand-new-passphrase-42"},
        content_type="application/json",
        headers={"x-csrftoken": laptop.cookies["lumaindex_csrftoken"].value},
    )
    assert response.status_code == 204

    assert laptop.get(reverse("accounts:session")).status_code == 200, \
        "signed out the device that changed the password"
    assert phone.get(reverse("accounts:session")).status_code == 204, \
        "the other device stayed signed in"


@pytest.mark.django_db
def test_display_name_can_be_changed(client: Client, user):
    client.force_login(user)
    client.get(reverse("accounts:csrf"))
    response = client.patch(reverse("accounts:profile"), {"display_name": "  Alice A.  "},
                            content_type="application/json",
                            headers={"x-csrftoken": client.cookies["lumaindex_csrftoken"].value})
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.display_name == "Alice A."


@pytest.mark.django_db
def test_email_and_role_are_not_editable_through_the_profile(client: Client, user):
    """Email is an identity change needing verification; role is a privilege."""
    client.force_login(user)
    client.get(reverse("accounts:csrf"))
    client.patch(reverse("accounts:profile"),
                 {"email": "someone-else@example.com", "role": "admin", "is_staff": True},
                 content_type="application/json",
                 headers={"x-csrftoken": client.cookies["lumaindex_csrftoken"].value})
    user.refresh_from_db()
    assert user.email == "alice@example.com"
    assert user.role == User.Role.USER
    assert user.is_staff is False


@pytest.mark.django_db
def test_settings_are_created_on_first_read(client: Client, user):
    client.force_login(user)
    body = client.get(reverse("accounts:settings")).json()
    assert body["theme"] == "system"
    assert body["library_view"] == "list"


@pytest.mark.django_db
def test_settings_persist_so_they_follow_a_device(client: Client, user):
    client.force_login(user)
    client.get(reverse("accounts:csrf"))
    client.patch(reverse("accounts:settings"), {"theme": "dark", "library_view": "large"},
                 content_type="application/json",
                 headers={"x-csrftoken": client.cookies["lumaindex_csrftoken"].value})

    elsewhere = Client()
    elsewhere.force_login(user)
    body = elsewhere.get(reverse("accounts:settings")).json()
    assert body["theme"] == "dark"
    assert body["library_view"] == "large"


@pytest.mark.django_db
def test_settings_reject_an_unknown_value(client: Client, user):
    client.force_login(user)
    client.get(reverse("accounts:csrf"))
    response = client.patch(reverse("accounts:settings"), {"theme": "neon"},
                            content_type="application/json",
                            headers={"x-csrftoken": client.cookies["lumaindex_csrftoken"].value})
    assert response.status_code == 400


@pytest.mark.django_db
def test_another_users_settings_are_untouchable(client: Client, user):
    """There is no id in the URL — the endpoint only ever serves the caller."""
    other = User.objects.create_user(email="bob@example.com", password=PASSWORD)
    client.force_login(user)
    client.get(reverse("accounts:csrf"))
    client.patch(reverse("accounts:settings"), {"theme": "dark"},
                 content_type="application/json",
                 headers={"x-csrftoken": client.cookies["lumaindex_csrftoken"].value})

    from accounts.settings_models import UserSettings
    assert UserSettings.for_user(other).theme == "system"


def _delete_account(client, **payload):
    client.get(reverse("accounts:csrf"))
    return client.post(reverse("accounts:account-delete"), payload,
                       content_type="application/json",
                       headers={"x-csrftoken": client.cookies["lumaindex_csrftoken"].value})


@pytest.mark.django_db
def test_account_deletion_needs_the_password(client: Client, user):
    client.force_login(user)
    response = _delete_account(client, password="wrong", confirm="delete")
    assert response.status_code == 400
    assert User.objects.filter(pk=user.pk).exists()


@pytest.mark.django_db
def test_account_deletion_needs_the_typed_confirmation(client: Client, user):
    client.force_login(user)
    response = _delete_account(client, password=PASSWORD, confirm="yes")
    assert response.status_code == 400
    assert User.objects.filter(pk=user.pk).exists()


@pytest.mark.django_db
def test_account_deletion_removes_the_user_and_their_files(client: Client, user, settings):
    from library.models import Book, BookSource
    from library.storage import LibraryStorage

    storage = LibraryStorage()
    blob = storage.store_stream(iter([b"%PDF-1.4 mine"]))
    book = Book.objects.create(owner=user, title="Mine")
    BookSource.objects.create(book=book, storage_key=blob.storage_key,
                              original_filename="Mine.pdf", file_size=blob.size)

    client.force_login(user)
    assert _delete_account(client, password=PASSWORD, confirm="delete").status_code == 204

    assert not User.objects.filter(pk=user.pk).exists()
    assert not Book.objects.filter(pk=book.pk).exists()
    assert not storage.exists(blob.storage_key), "the uploaded file was left on disk"


@pytest.mark.django_db
def test_account_deletion_keeps_a_file_another_user_still_has(client: Client, user, settings):
    """Content addressing means two accounts can share one blob."""
    from library.models import Book, BookSource
    from library.storage import LibraryStorage

    storage = LibraryStorage()
    blob = storage.store_stream(iter([b"%PDF-1.4 shared"]))
    other = User.objects.create_user(email="bob@example.com", password=PASSWORD)
    for owner in (user, other):
        book = Book.objects.create(owner=owner, title="Shared")
        BookSource.objects.create(book=book, storage_key=blob.storage_key,
                                  original_filename="Shared.pdf", file_size=blob.size)

    client.force_login(user)
    _delete_account(client, password=PASSWORD, confirm="delete")

    assert storage.exists(blob.storage_key), "deleted the other account's only copy"
    assert Book.objects.filter(owner=other).exists()


@pytest.mark.django_db
def test_account_deletion_signs_the_user_out(client: Client, user):
    client.force_login(user)
    _delete_account(client, password=PASSWORD, confirm="delete")
    assert client.get(reverse("accounts:session")).status_code == 204


@pytest.mark.django_db
def test_settings_endpoints_require_authentication():
    anon = Client()
    for name in ("accounts:profile", "accounts:settings"):
        assert anon.get(reverse(name)).status_code == 403
    assert anon.post(reverse("accounts:account-delete")).status_code == 403
