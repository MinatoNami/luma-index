"""Long-running sync worker.

PRD §36 says not to introduce Celery until an async workload justifies it, and
permits "lightweight application mechanisms". This is that mechanism: a loop
that claims due work with a database advisory lock. No broker, no Redis, and it
becomes a Celery task later without the domain code changing.

    python manage.py run_sync_worker            # loop until SIGTERM
    python manage.py run_sync_worker --once     # a single pass, for cron or tests
"""

from __future__ import annotations

import logging
import os
import signal
import time
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection as db_connection
from django.utils import timezone

from integrations.google_drive.errors import DriveAuthError, DriveError
from integrations.google_drive.models import DriveConnection
from integrations.google_drive.sync import (
    SyncBusy,
    process_pending_documents,
    sync_connection,
)

logger = logging.getLogger("lumaindex.drive.worker")

# Touched after every pass. The container healthcheck reads its mtime, so a
# loop that wedges on a hung call is restarted rather than sitting there
# looking fine because the process is technically alive.
HEARTBEAT_PATH = Path(os.environ.get("LUMA_WORKER_HEARTBEAT",
                                     "/tmp/lumaindex-sync-worker.heartbeat"))  # noqa: S108

POLL_SECONDS = 15
SYNC_INTERVAL_MINUTES = 60
# Document batches per connection per pass. Bounded so one enormous library
# cannot starve every other connection on the instance.
DOCUMENT_PASSES = 4


class Command(BaseCommand):
    help = "Poll for Drive connections needing a sync and process them."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true",
                            help="Run a single pass and exit.")
        parser.add_argument("--poll-seconds", type=int, default=POLL_SECONDS)
        parser.add_argument("--interval-minutes", type=int, default=SYNC_INTERVAL_MINUTES,
                            help="How stale a connection may get before a scheduled sync.")

    def handle(self, *args, **options):
        self._running = True

        def stop(signum, frame):
            # Finish the connection in flight rather than abandoning a walk
            # partway through and leaving a SyncRun stuck in 'running'.
            logger.info("shutdown requested", extra={"event": "drive.worker.stopping"})
            self._running = False

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        poll = options["poll_seconds"]
        interval = options["interval_minutes"]
        self.beat()
        logger.info("sync worker started",
                    extra={"event": "drive.worker.started", "poll_seconds": poll,
                           "interval_minutes": interval})

        while self._running:
            try:
                worked = self.pass_once(interval)
            except Exception as exc:
                # A crash here would stop syncing for everyone until someone
                # noticed, so the loop absorbs and reports instead.
                logger.exception("sync worker pass failed",
                                 extra={"event": "drive.worker.error",
                                        "reason": type(exc).__name__})
                worked = False
            finally:
                # A long-lived process must not hold a connection Postgres has
                # already closed underneath it.
                db_connection.close_if_unusable_or_obsolete()
                self.beat()

            if options["once"]:
                return
            if not self._running:
                break
            # Sleep in short slices so SIGTERM is answered promptly.
            slept = 0.0
            step = 0.5 if worked else 1.0
            while self._running and slept < poll:
                time.sleep(step)
                slept += step

        logger.info("sync worker stopped", extra={"event": "drive.worker.stopped"})

    # ---------------------------------------------------------------- #

    def beat(self) -> None:
        try:
            HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
            HEARTBEAT_PATH.touch()
        except OSError:
            # A missing heartbeat costs a restart, not correctness; never let
            # it take down a working loop.
            logger.warning("could not write worker heartbeat",
                           extra={"event": "drive.worker.heartbeat_failed"})

    def due_connections(self, interval_minutes: int):
        """Connections a user asked to sync, or that have gone stale.

        Expired and revoked connections are excluded: retrying them produces
        nothing but failed runs and Google API calls until the user reconnects.
        """
        from django.db.models import F, Q

        cutoff = timezone.now() - timezone.timedelta(minutes=interval_minutes)
        return DriveConnection.objects.filter(
            status=DriveConnection.Status.ACTIVE
        ).filter(
            Q(sync_requested_at__isnull=False)
            | Q(last_synced_at__isnull=True)
            | Q(last_synced_at__lt=cutoff)
        ).order_by(
            # nulls_last matters: PostgreSQL sorts NULLs first under DESC, so a
            # plain "-sync_requested_at" would put every *un*-requested
            # connection ahead of the one the user just asked for.
            F("sync_requested_at").desc(nulls_last=True),
            F("last_synced_at").asc(nulls_first=True),
        )

    def pass_once(self, interval_minutes: int) -> bool:
        did_work = False

        for drive in self.due_connections(interval_minutes):
            if not self._running:
                break
            did_work = True
            self.process(drive)

        # Books still waiting on a download, for connections that are otherwise
        # up to date. This is what lets a big library fill in over time.
        for drive in DriveConnection.objects.filter(status=DriveConnection.Status.ACTIVE):
            if not self._running:
                break
            if self.process_documents(drive):
                did_work = True

        return did_work

    def process(self, drive: DriveConnection) -> None:
        try:
            run = sync_connection(drive)
            logger.info("connection synced",
                        extra={"event": "drive.worker.synced", "connection_id": drive.pk,
                               "status": run.status, **run.counts})
        except SyncBusy:
            return  # another process has it
        except DriveAuthError:
            return  # already recorded on the connection; nothing to retry
        except DriveError as exc:
            logger.warning("sync failed",
                           extra={"event": "drive.worker.sync_failed",
                                  "connection_id": drive.pk, "reason": type(exc).__name__})

    def process_documents(self, drive: DriveConnection) -> bool:
        worked = False
        for _ in range(DOCUMENT_PASSES):
            if not self._running:
                break
            try:
                result = process_pending_documents(drive)
            except DriveAuthError:
                break
            except DriveError as exc:
                logger.warning("document batch failed",
                               extra={"event": "drive.worker.documents_failed",
                                      "connection_id": drive.pk,
                                      "reason": type(exc).__name__})
                break

            if result["processed"] or result["failed"]:
                worked = True
                logger.info("documents processed",
                            extra={"event": "drive.worker.documents",
                                   "connection_id": drive.pk, **result})
            if not result["remaining"]:
                break
        return worked
