"""Destroy trashed items past their retention period.

The worker does this on a timer; this is the same sweep with a handle on it,
for a first run after turning retention on and for seeing what would go before
it goes.

    python manage.py empty_trash --dry-run
    python manage.py empty_trash
    python manage.py empty_trash --days 30 --limit 1000
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from library.models import Book, Folder
from library.retention import SWEEP_LIMIT, cutoff, purge_expired, retention_days


class Command(BaseCommand):
    help = "Permanently delete trashed items older than the retention period."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="List what would go, and delete nothing.")
        parser.add_argument("--days", type=int, default=None,
                            help="Override LUMA_TRASH_RETENTION_DAYS for this run.")
        parser.add_argument("--limit", type=int, default=SWEEP_LIMIT)

    def handle(self, *args, **options):
        if options["days"] is not None:
            from django.conf import settings
            settings.TRASH_RETENTION_DAYS = options["days"]

        days = retention_days()
        if not days:
            self.stdout.write(self.style.WARNING(
                "Trash retention is off — nothing is ever swept. "
                "Set LUMA_TRASH_RETENTION_DAYS, or pass --days for this run."))
            return

        due = cutoff()
        self.stdout.write(f"Retention: {days} days (anything trashed before "
                          f"{timezone.localtime(due):%Y-%m-%d %H:%M} is due).")

        if options["dry_run"]:
            folders = Folder.objects.filter(deleted_at__isnull=False, deleted_at__lt=due)
            books = Book.objects.filter(deleted_at__isnull=False, deleted_at__lt=due)
            self.stdout.write(f"Would delete {folders.count()} folder(s) "
                              f"and {books.count()} book(s):")
            for folder in folders.order_by("deleted_at")[:50]:
                self.stdout.write(f"  folder  {folder.path}")
            for book in books.order_by("deleted_at")[:50]:
                self.stdout.write(f"  book    {book.title}")
            return

        result = purge_expired(limit=options["limit"])
        self.stdout.write(self.style.SUCCESS(
            f"Deleted {result['folders']} folder(s), {result['books']} book(s), "
            f"and {result['files']} file(s) from disk."))
        if result["skipped"]:
            self.stdout.write(self.style.WARNING(
                f"{result['skipped']} folder(s) skipped — they still hold live items. "
                "See the log for which."))
