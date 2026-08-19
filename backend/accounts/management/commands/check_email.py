"""Prove the mail configuration works, without locking anyone out to do it.

Password reset deliberately answers 204 whether or not the mail went out — a
500 from a refused SMTP handshake would say "this address exists" only for the
addresses that do. That leaves an operator with no way to tell a working relay
from a broken one by using the app, which is what this is for.

Django ships `sendtestemail`, which sends and then reports the same traceback
smtplib raised. This one prints the configuration it is about to use and turns
the usual first-time failures — wrong port for the TLS mode, a From address the
relay will not accept, an account password where an app password was needed —
into the sentence that says what to change.

    python manage.py check_email you@example.com
    python manage.py check_email --show-config
"""

from __future__ import annotations

import smtplib

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send a test email, and report exactly what configuration was used."

    def add_arguments(self, parser):
        parser.add_argument("recipient", nargs="?",
                            help="Where to send it. Omit with --show-config.")
        parser.add_argument("--show-config", action="store_true",
                            help="Print the resolved settings and send nothing.")

    def handle(self, *args, **options):
        self.report_config()

        if options["show_config"]:
            return

        recipient = options["recipient"]
        if not recipient:
            raise CommandError("Give an address to send to, or pass --show-config.")

        mode = getattr(settings, "EMAIL_MODE", "console")
        if mode != "smtp":
            self.stdout.write(self.style.WARNING(
                f"\nLUMA_EMAIL_BACKEND is '{mode}', so nothing will reach {recipient}."
                "\nSet it to 'smtp' to send for real."))

        self.stdout.write(f"\nSending to {recipient}…")
        try:
            sent = send_mail(
                subject="LumaIndex test email",
                message=(
                    "If you are reading this, LumaIndex can send mail.\n\n"
                    "That means password reset links will reach people instead "
                    "of only reaching the server log.\n"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                fail_silently=False,
            )
        except smtplib.SMTPAuthenticationError as exc:
            raise CommandError(f"The relay rejected the credentials: {exc}\n"
                               "Check EMAIL_HOST_USER and EMAIL_HOST_PASSWORD. Many "
                               "providers need an app password rather than the "
                               "account password.") from exc
        except smtplib.SMTPSenderRefused as exc:
            raise CommandError(f"The relay refused the sender address: {exc}\n"
                               f"DEFAULT_FROM_EMAIL is {settings.DEFAULT_FROM_EMAIL!r}. "
                               "Most relays only accept addresses on a domain they "
                               "know about.") from exc
        except smtplib.SMTPRecipientsRefused as exc:
            raise CommandError(f"The relay refused the recipient: {exc}") from exc
        except smtplib.SMTPNotSupportedError as exc:
            # The connection was fine; blaming host and port here sends people
            # to check the one thing that already worked.
            raise CommandError(
                f"Connected, but the relay does not support what was asked of it: {exc}\n"
                "If that is AUTH, clear EMAIL_HOST_USER and EMAIL_HOST_PASSWORD — "
                "a relay that accepts mail without credentials refuses to be given "
                "them. If it is STARTTLS, that server wants EMAIL_USE_TLS off."
            ) from exc
        except (smtplib.SMTPException, OSError) as exc:
            # OSError covers connection refused, DNS failure and TLS problems,
            # which is most of what goes wrong the first time.
            raise CommandError(
                f"Could not send: {type(exc).__name__}: {exc}\n"
                f"Reaching {getattr(settings, 'EMAIL_HOST', '?')}:"
                f"{getattr(settings, 'EMAIL_PORT', '?')} failed. Check the host and "
                "port, whether TLS or SSL is right for that port, and that the "
                "server can reach it outbound."
            ) from exc

        if sent:
            self.stdout.write(self.style.SUCCESS(f"Sent 1 message to {recipient}."))
            self.stdout.write("If it does not arrive, check the spam folder and the "
                              "relay's own logs — it left here successfully.")
        else:
            self.stdout.write(self.style.WARNING(
                "The backend reported 0 messages sent."))

    def report_config(self):
        mode = getattr(settings, "EMAIL_MODE", "console")
        self.stdout.write("Mail configuration")
        self.stdout.write(f"  backend:      {mode} ({settings.EMAIL_BACKEND})")
        self.stdout.write(f"  from:         {settings.DEFAULT_FROM_EMAIL}")

        if mode != "smtp":
            return

        self.stdout.write(f"  host:         {settings.EMAIL_HOST}:{settings.EMAIL_PORT}")
        self.stdout.write(f"  username:     {settings.EMAIL_HOST_USER or '(none)'}")
        # Whether one is set, never which. This output ends up pasted into
        # issues and chat windows.
        self.stdout.write(f"  password:     {'set' if settings.EMAIL_HOST_PASSWORD else '(none)'}")
        self.stdout.write(f"  TLS / SSL:    {settings.EMAIL_USE_TLS} / {settings.EMAIL_USE_SSL}")
        self.stdout.write(f"  timeout:      {settings.EMAIL_TIMEOUT}s")

        if settings.DEFAULT_FROM_EMAIL.endswith("@localhost"):
            self.stdout.write(self.style.WARNING(
                "  ! DEFAULT_FROM_EMAIL is still the placeholder. Most relays "
                "reject it."))
        if not settings.EMAIL_USE_TLS and not settings.EMAIL_USE_SSL:
            self.stdout.write(self.style.WARNING(
                "  ! Neither TLS nor SSL is on — the password crosses the "
                "network in the clear."))
