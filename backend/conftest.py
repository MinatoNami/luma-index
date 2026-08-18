"""Shared test fixtures."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

# Generated per run rather than hard-coded, so nothing in the repo looks like a
# real key and nothing depends on a particular one.
TEST_ENCRYPTION_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def encryption_key(settings):
    """Give every test a working field-encryption key.

    Without this, any test touching an EncryptedTextField fails on
    configuration rather than on the behaviour it is checking.
    """
    from common.encryption import _cipher

    settings.FIELD_ENCRYPTION_KEY = TEST_ENCRYPTION_KEY
    settings.FIELD_ENCRYPTION_KEYS_LEGACY = []
    _cipher.cache_clear()
    yield
    _cipher.cache_clear()
