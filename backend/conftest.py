"""Shared test fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_storage(settings, tmp_path):
    """Point library storage at a per-test directory.

    Without this, tests would write into the configured library directory —
    which in a container is the real one — and leak files between runs.
    """
    settings.LIBRARY_DIR = tmp_path / "library"
    settings.THUMBNAIL_DIR = tmp_path / "thumbnails"
    settings.UPLOAD_STAGING_DIR = tmp_path / "staging"
    for path in (settings.LIBRARY_DIR, settings.THUMBNAIL_DIR, settings.UPLOAD_STAGING_DIR):
        path.mkdir(parents=True, exist_ok=True)
    return settings


@pytest.fixture
def user(db, django_user_model):
    return django_user_model.objects.create_user(
        email="owner@example.com", password="a-long-enough-password-42",
    )


@pytest.fixture
def other_user(db, django_user_model):
    return django_user_model.objects.create_user(
        email="mallory@example.com", password="a-long-enough-password-42",
    )


@pytest.fixture
def api(user):
    """A signed-in client with a CSRF token ready."""
    from django.test import Client
    from django.urls import reverse

    client = Client()
    client.force_login(user)
    client.get(reverse("accounts:csrf"))
    client.csrf = client.cookies["lumaindex_csrftoken"].value
    client.headers = {"x-csrftoken": client.csrf}
    return client
