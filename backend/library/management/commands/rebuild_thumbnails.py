"""Re-render book covers.

Needed whenever THUMBNAIL_WIDTH changes: existing files keep their old size,
and nothing else would notice. Clears the recorded path so the ingest worker
picks each book up again on its next pass.

    ./deploy/deploy.sh manage rebuild_thumbnails
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from library.models import Book
from library.services import process_pending_documents


class Command(BaseCommand):
    help = "Re-render every book cover."

    def add_arguments(self, parser):
        parser.add_argument("--now", action="store_true",
                            help="Render immediately instead of leaving it to the worker.")

    def handle(self, *args, **options):
        count = Book.objects.exclude(thumbnail_path="").update(thumbnail_path="")
        self.stdout.write(f"queued {count} cover(s) for re-rendering")

        if not options["now"]:
            self.stdout.write("the ingest worker will pick them up")
            return

        while True:
            result = process_pending_documents()
            self.stdout.write(f"  {result}")
            if not result["remaining"] or not (result["processed"] or result["failed"]):
                break
