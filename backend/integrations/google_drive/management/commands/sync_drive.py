"""One-shot sync, for an operator at a terminal.

    ./deploy/deploy.sh manage sync_drive --email someone@example.com
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from integrations.google_drive.models import DriveConnection
from integrations.google_drive.sync import SyncBusy, process_pending_documents, sync_connection


class Command(BaseCommand):
    help = "Synchronise Drive connections now."

    def add_arguments(self, parser):
        parser.add_argument("--email", help="Limit to one user's connections.")
        parser.add_argument("--skip-documents", action="store_true",
                            help="Metadata only; do not download or thumbnail.")

    def handle(self, *args, **options):
        connections = DriveConnection.objects.all()
        if options["email"]:
            connections = connections.filter(user__email=options["email"].lower())
        if not connections.exists():
            raise CommandError("No matching Drive connections.")

        for drive in connections:
            self.stdout.write(f"syncing {drive} …")
            try:
                run = sync_connection(drive)
            except SyncBusy:
                self.stdout.write(self.style.WARNING("  already running elsewhere; skipped"))
                continue
            self.stdout.write(f"  {run.status}: {run.counts}")
            if run.error_summary:
                self.stdout.write(self.style.WARNING(f"  {run.error_summary[:500]}"))

            if options["skip_documents"]:
                continue
            while True:
                result = process_pending_documents(drive)
                self.stdout.write(f"  documents: {result}")
                if not result["remaining"] or not (result["processed"] or result["failed"]):
                    break
