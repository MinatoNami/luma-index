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
    from rest_framework.settings import api_settings

    from rest_framework.permissions import IsAuthenticated

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
