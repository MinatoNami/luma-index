"""Index the text of books that were uploaded before there was an index.

The worker indexes on ingest, which does nothing for a library that already
exists. This walks it once.

    manage.py index_text            # only books with no pages indexed
    manage.py index_text --all      # re-index everything, after a config change
    manage.py index_text --dry-run  # say what would be read, read nothing
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from library.fulltext import index_book
from library.models import Book, BookPage
from library.storage import LibraryStorage


class Command(BaseCommand):
    help = "Extract and index the page text of books that have a text layer."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true",
                            help="Re-index books that already have pages indexed.")
        parser.add_argument("--dry-run", action="store_true",
                            help="List what would be indexed without opening a file.")
        parser.add_argument("--limit", type=int, default=0,
                            help="Stop after this many books (0 means no limit).")

    def handle(self, *args, **options):
        # A scan has nothing to index; has_text_layer is what says so, and it is
        # null until the worker has probed the book at all.
        books = (Book.objects.filter(has_text_layer=True, deleted_at__isnull=True)
                 .select_related("source").order_by("pk"))

        if not options["all"]:
            books = books.exclude(pk__in=BookPage.objects.values("book_id"))
        if options["limit"]:
            books = books[:options["limit"]]

        books = list(books)
        if not books:
            self.stdout.write("Nothing to index.")
            return

        storage = LibraryStorage()
        indexed = pages = skipped = 0

        for book in books:
            # A one-to-one, so this raises rather than returning None when a
            # book somehow has no file behind it.
            source = getattr(book, "source", None)
            if source is None:
                skipped += 1
                continue
            path = storage.path_for(source.storage_key)
            if not path.exists():
                # The row says the file is there and it is not. Someone else's
                # problem to fix; this command's job is not to hide it.
                self.stderr.write(self.style.WARNING(
                    f"  missing file for {book.pk}: {book.title[:60]}"))
                skipped += 1
                continue

            if options["dry_run"]:
                self.stdout.write(f"  would index {book.pk}: {book.title[:60]}")
                indexed += 1
                continue

            try:
                count = index_book(book, path)
            except Exception as exc:
                # One unreadable book must not stop the walk.
                self.stderr.write(self.style.WARNING(
                    f"  failed on {book.pk} ({type(exc).__name__}): {book.title[:50]}"))
                skipped += 1
                continue

            indexed += 1
            pages += count
            self.stdout.write(f"  {book.pk}: {count} page(s) — {book.title[:50]}")

        verb = "would index" if options["dry_run"] else "indexed"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {indexed} book(s), {pages} page(s); {skipped} skipped."))
