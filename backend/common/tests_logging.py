"""The redaction filter is a security control, so it gets tests."""

from __future__ import annotations

from common.logging import scrub


def test_sensitive_keys_are_redacted():
    scrubbed = scrub({"refresh_token": "1//abcdefghijklmnop", "email": "a@b.com"})
    assert scrubbed["refresh_token"] == "[redacted]"
    assert scrubbed["email"] == "a@b.com"


def test_nested_structures_are_redacted():
    scrubbed = scrub({"outer": [{"client_secret": "shhh"}]})
    assert scrubbed["outer"][0]["client_secret"] == "[redacted]"


def test_inline_google_refresh_token_is_redacted():
    assert "1//0gabcdefghijk" not in scrub("failed for token 1//0gabcdefghijk")


def test_inline_bearer_header_is_redacted():
    assert "ya29.a0Af" not in scrub("Authorization: Bearer ya29.a0AfExample")


def test_inline_key_value_is_redacted():
    assert "hunter2" not in scrub("password=hunter2 for user")
