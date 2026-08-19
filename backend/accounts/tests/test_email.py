"""Sending mail for real, and what happens when it cannot be sent.

The interesting behaviour is not the happy path — `test_auth.py` already pins
that. It is the failure: a relay that refuses must not turn this endpoint into
a way to find out which addresses have accounts.
"""

from __future__ import annotations

import smtplib

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client

from .test_auth import _request_reset


@pytest.fixture
def user(db):
    """Local rather than imported: pytest treats a fixture pulled in by name
    as a redefinition of the one already in scope, and `conftest.py` has a
    different address for the whole project."""
    return get_user_model().objects.create_user(
        email="alice@example.com", password="correct-horse-battery-staple",
    )

# -- a broken relay must not become an oracle ----------------------------------- #

@pytest.mark.django_db
def test_a_failed_send_still_answers_204(client: Client, user, monkeypatch):
    """The whole reason the endpoint always answers 204 is that any other
    answer says "this address exists". A 500 from a refused SMTP handshake says
    it just as loudly, and says it only for the addresses that do."""
    def refuse(*args, **kwargs):
        raise smtplib.SMTPRecipientsRefused({"alice@example.com": (550, b"nope")})

    monkeypatch.setattr("accounts.views.send_mail", refuse)

    assert _request_reset(client, "alice@example.com").status_code == 204


@pytest.mark.django_db
def test_a_broken_relay_looks_the_same_as_an_unknown_address(client: Client, user,
                                                             monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr("accounts.views.send_mail", refuse)

    known = _request_reset(client, "alice@example.com")
    unknown = _request_reset(Client(), "nobody@example.com")

    assert known.status_code == unknown.status_code == 204


@pytest.mark.django_db
def test_a_failed_send_is_logged_without_naming_the_address(client: Client, user,
                                                            monkeypatch, caplog):
    """Invisible from outside is the point; invisible from the logs would just
    be a broken instance nobody could diagnose. But SMTP errors quote the
    recipient back, so only the exception type is recorded."""
    def refuse(*args, **kwargs):
        raise smtplib.SMTPRecipientsRefused({"alice@example.com": (550, b"nope")})

    monkeypatch.setattr("accounts.views.send_mail", refuse)

    with caplog.at_level("ERROR"):
        _request_reset(client, "alice@example.com")

    records = [r for r in caplog.records if getattr(r, "event", "") == "auth.reset.send_failed"]
    assert len(records) == 1
    assert records[0].reason == "SMTPRecipientsRefused"
    assert "alice@example.com" not in caplog.text


@pytest.mark.django_db
def test_the_reset_link_points_at_the_public_origin(client: Client, user, mailoutbox,
                                                    settings):
    """The link is built from configuration, not the request's Host header —
    which an attacker controls, and which would otherwise let them send a
    victim a working token pointing at their own server."""
    settings.PUBLIC_ORIGIN = "https://books.example.ts.net"

    _request_reset(client, "alice@example.com")

    assert "https://books.example.ts.net/reset/" in mailoutbox[0].body


@pytest.mark.django_db
def test_the_token_never_reaches_the_log(client: Client, user, mailoutbox, caplog):
    with caplog.at_level("INFO"):
        _request_reset(client, "alice@example.com")

    body = mailoutbox[0].body
    token = body.split("/reset/")[1].split()[0]
    assert token, "the email should carry a token"
    assert token not in caplog.text


# -- the configuration check ------------------------------------------------------ #

@pytest.mark.django_db
def test_check_email_reports_the_backend_in_use(capsys, settings):
    settings.EMAIL_MODE = "console"

    call_command("check_email", "--show-config")

    out = capsys.readouterr().out
    assert "backend:" in out
    assert "console" in out


@pytest.mark.django_db
def test_check_email_never_prints_the_password(capsys, settings):
    """This output gets pasted into issues and chat windows."""
    settings.EMAIL_MODE = "smtp"
    settings.EMAIL_HOST = "smtp.example.com"
    settings.EMAIL_PORT = 587
    settings.EMAIL_HOST_USER = "luma"
    settings.EMAIL_HOST_PASSWORD = "hunter2-do-not-print"
    settings.EMAIL_USE_TLS = True
    settings.EMAIL_USE_SSL = False
    settings.EMAIL_TIMEOUT = 10

    call_command("check_email", "--show-config")

    out = capsys.readouterr().out
    assert "hunter2-do-not-print" not in out
    assert "password:     set" in out


@pytest.mark.django_db
def test_check_email_warns_about_the_placeholder_sender(capsys, settings):
    settings.EMAIL_MODE = "smtp"
    settings.EMAIL_HOST = "smtp.example.com"
    settings.EMAIL_PORT = 587
    settings.EMAIL_HOST_USER = ""
    settings.EMAIL_HOST_PASSWORD = ""
    settings.EMAIL_USE_TLS = True
    settings.EMAIL_USE_SSL = False
    settings.EMAIL_TIMEOUT = 10
    settings.DEFAULT_FROM_EMAIL = "lumaindex@localhost"

    call_command("check_email", "--show-config")

    assert "Most relays reject it" in capsys.readouterr().out


@pytest.mark.django_db
def test_check_email_warns_when_nothing_is_encrypted(capsys, settings):
    settings.EMAIL_MODE = "smtp"
    settings.EMAIL_HOST = "smtp.example.com"
    settings.EMAIL_PORT = 25
    settings.EMAIL_HOST_USER = "luma"
    settings.EMAIL_HOST_PASSWORD = "x"
    settings.EMAIL_USE_TLS = False
    settings.EMAIL_USE_SSL = False
    settings.EMAIL_TIMEOUT = 10

    call_command("check_email", "--show-config")

    assert "in the clear" in capsys.readouterr().out


@pytest.mark.django_db
def test_check_email_needs_an_address_to_send_to(settings):
    settings.EMAIL_MODE = "console"

    with pytest.raises(CommandError, match="--show-config"):
        call_command("check_email")


@pytest.mark.django_db
def test_check_email_sends_when_given_an_address(mailoutbox, settings):
    settings.EMAIL_MODE = "console"

    call_command("check_email", "someone@example.com")

    assert [m.to for m in mailoutbox] == [["someone@example.com"]]


@pytest.mark.django_db
def test_check_email_turns_a_refused_connection_into_advice(settings, monkeypatch):
    settings.EMAIL_MODE = "smtp"
    settings.EMAIL_HOST = "smtp.example.com"
    settings.EMAIL_PORT = 587

    def refuse(*args, **kwargs):
        raise ConnectionRefusedError(111, "Connection refused")

    monkeypatch.setattr("accounts.management.commands.check_email.send_mail", refuse)

    with pytest.raises(CommandError, match="Check the host and port"):
        call_command("check_email", "someone@example.com")


@pytest.mark.django_db
def test_check_email_explains_an_auth_extension_refusal(settings, monkeypatch):
    """A relay that takes mail without credentials refuses to be given them,
    and the connection was fine — so blaming host and port sends people to
    check the one thing that already worked."""
    settings.EMAIL_MODE = "smtp"
    settings.EMAIL_HOST = "smtp.example.com"
    settings.EMAIL_PORT = 25

    def refuse(*args, **kwargs):
        raise smtplib.SMTPNotSupportedError("SMTP AUTH extension not supported by server.")

    monkeypatch.setattr("accounts.management.commands.check_email.send_mail", refuse)

    with pytest.raises(CommandError, match="clear EMAIL_HOST_USER"):
        call_command("check_email", "someone@example.com")
