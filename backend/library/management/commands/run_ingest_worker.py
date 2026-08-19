"""Long-running ingest worker.

Extracting a ZIP of a few hundred books, probing each PDF, and rendering
thumbnails takes minutes — far too long for a request. PRD §36 rules out Celery
for now and permits a lightweight mechanism; this is a loop that claims work
with a PostgreSQL advisory lock. No broker, and the same functions become
Celery tasks later without the domain code changing.

    python manage.py run_ingest_worker
    python manage.py run_ingest_worker --once
"""

from __future__ import annotations

import logging
import os
import signal
import time
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection as db_connection

from common.db import advisory_lock
from library.models import UploadBatch
from library.retention import purge_expired, retention_days
from library.services import process_pending_documents, process_zip_batch

logger = logging.getLogger("lumaindex.ingest.worker")

HEARTBEAT_PATH = Path(os.environ.get("LUMA_WORKER_HEARTBEAT",
                                     "/tmp/lumaindex-ingest-worker.heartbeat"))  # noqa: S108

POLL_SECONDS = 5
DOCUMENT_PASSES = 4

# Retention is measured in days, so sweeping more than hourly buys nothing and
# costs a query on every one of the worker's five-second passes.
TRASH_SWEEP_SECONDS = 3600


class Command(BaseCommand):
    help = "Process queued uploads, then probe and thumbnail new books."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run one pass and exit.")
        parser.add_argument("--poll-seconds", type=int, default=POLL_SECONDS)

    def handle(self, *args, **options):
        self._running = True

        def stop(signum, frame):
            # Finish the batch in flight instead of abandoning an extraction
            # and leaving an UploadBatch stuck in 'running'.
            logger.info("shutdown requested", extra={"event": "ingest.worker.stopping"})
            self._running = False

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        self.beat()
        # None, not zero, for "has not swept yet". Zero only reads as "long ago"
        # if the clock's origin is long ago, and time.monotonic() counts from
        # boot on Linux — so on a machine up for less than TRASH_SWEEP_SECONDS
        # the subtraction stayed under the interval and the sweep never ran at
        # all. A freshly rebooted server would skip the trash for its first
        # hour, which is exactly the case this was written to handle.
        self._last_sweep: float | None = None
        logger.info("ingest worker started", extra={"event": "ingest.worker.started"})

        while self._running:
            try:
                worked = self.pass_once()
            except Exception as exc:
                # A crash here stops ingestion for every user until someone
                # notices, so the loop absorbs and reports instead.
                logger.exception("ingest worker pass failed",
                                 extra={"event": "ingest.worker.error",
                                        "reason": type(exc).__name__})
                worked = False
            finally:
                db_connection.close_if_unusable_or_obsolete()
                self.beat()

            if options["once"]:
                return
            if not self._running:
                break

            slept = 0.0
            poll = 0 if worked else options["poll_seconds"]
            while self._running and slept < poll:
                time.sleep(0.5)
                slept += 0.5

        logger.info("ingest worker stopped", extra={"event": "ingest.worker.stopped"})

    # ------------------------------------------------------------------ #

    def beat(self) -> None:
        try:
            HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
            HEARTBEAT_PATH.touch()
        except OSError:
            logger.warning("could not write worker heartbeat",
                           extra={"event": "ingest.worker.heartbeat_failed"})

    def pass_once(self) -> bool:
        worked = self.process_batches()
        self.sweep_trash()
        for _ in range(DOCUMENT_PASSES):
            if not self._running:
                break
            result = process_pending_documents()
            if result["processed"] or result["failed"]:
                worked = True
                logger.info("documents processed",
                            extra={"event": "ingest.worker.documents", **result})
            if not result["remaining"]:
                break
        return worked

    def sweep_trash(self) -> None:
        """Destroy trashed items past their retention, at most hourly.

        Under an advisory lock like everything else here, so a second worker —
        or somebody running `manage.py empty_trash` — cannot sweep the same
        rows at the same time.
        """
        if not retention_days():
            return
        now = time.monotonic()
        if self._last_sweep is not None and now - self._last_sweep < TRASH_SWEEP_SECONDS:
            return
        self._last_sweep = now

        with advisory_lock("lumaindex.trash_sweep", blocking=False) as acquired:
            if not acquired:
                return
            purge_expired()

    def process_batches(self) -> bool:
        worked = False
        pending = UploadBatch.objects.filter(status=UploadBatch.Status.PENDING).order_by("pk")

        for batch in pending:
            if not self._running:
                break
            # One worker per batch; the lock is what makes a second worker
            # process (or a manual command) safe to run alongside this one.
            with advisory_lock(f"lumaindex.upload_batch:{batch.pk}", blocking=False) as acquired:
                if not acquired:
                    continue
                batch.refresh_from_db()
                if batch.status != UploadBatch.Status.PENDING:
                    continue
                worked = True
                process_zip_batch(batch)
                logger.info("batch processed",
                            extra={"event": "ingest.worker.batch", "batch_id": batch.pk,
                                   "status": batch.status, **batch.counts})
        return worked
