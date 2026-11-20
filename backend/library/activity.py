"""Reading activity: what a streak and a daily goal are made of.

Apple Books, Kindle and StoryGraph all show a reader how often they read, and
PRD §43 lists statistics, goals and streaks. What they need that the schema did
not have is history: ReadingProgress is one row per book that is overwritten on
every move, so it knows where you are and nothing about yesterday.

A page counts when you *arrive* on it — when a progress write moves you
somewhere you were not. Opening a book where you left it is not reading, and
neither is the same page reported ten times while you sit on it.

Dates are the reader's, not the server's. The server keeps UTC, which in
Singapore would end "today" at eight in the morning; the browser says what day
it is where the reader is, and the server only checks that the claim is
plausible.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from django.db import transaction
from django.db.models import Func, IntegerField, Sum
from django.utils import timezone

from .models import Book, ReadingDay, ReadingProgress

# How far a client's "today" may sit from the server's UTC date. Time zones run
# from UTC-12 to UTC+14, so a real device is never more than a day either way;
# anything further is a broken clock or a made-up date.
MAX_SKEW = timedelta(days=1)

WEEK = 7


def local_today(raw: str | None) -> date:
    """The reader's date, if they gave a believable one, else the server's."""
    server = timezone.now().date()
    if not raw:
        return server
    try:
        claimed = date.fromisoformat(str(raw)[:10])
    except ValueError:
        return server
    return claimed if abs(claimed - server) <= MAX_SKEW else server


def record_arrival(user, book: Book, page: int, day: date) -> None:
    """Note that `user` arrived on `page` of `book` on `day`.

    Idempotent per page and day — the same page twice is still one page — and
    safe against two tabs writing at once: the row is locked while the page
    list is read and extended.
    """
    with transaction.atomic():
        record, _ = ReadingDay.objects.select_for_update().get_or_create(
            user=user, book=book, day=day)
        if page not in record.pages:
            record.pages = [*record.pages, page]
            record.save(update_fields=["pages", "updated_at"])


class _Cardinality(Func):
    function = "cardinality"
    output_field = IntegerField()


def _pages_by_day(user, since: date | None = None) -> dict[date, int]:
    rows = ReadingDay.objects.filter(user=user)
    if since is not None:
        rows = rows.filter(day__gte=since)
    totals = rows.values("day").annotate(pages=Sum(_Cardinality("pages"))).order_by()
    return {row["day"]: row["pages"] or 0 for row in totals if row["pages"]}


def streaks(days: set[date], today: date) -> tuple[int, int]:
    """(current, longest) runs of consecutive days with any reading.

    The current streak survives a day that has not happened yet: at breakfast,
    having read yesterday, you are on a streak — it is broken only once a whole
    day has passed without a page. So it counts back from today if you have
    read today, and from yesterday if not.
    """
    if not days:
        return 0, 0

    current = 0
    cursor = today if today in days else today - timedelta(days=1)
    while cursor in days:
        current += 1
        cursor -= timedelta(days=1)

    longest = run = 0
    previous: date | None = None
    for day in sorted(days):
        run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day
    return current, longest


def summary(user, today: date, *, goal: int) -> dict:
    """Everything the activity panel shows, in one response."""
    by_day = _pages_by_day(user)
    current, longest = streaks(set(by_day), today)

    week = [today - timedelta(days=offset) for offset in range(WEEK - 1, -1, -1)]
    year_start = date(today.year, 1, 1)
    this_year = {day: pages for day, pages in by_day.items() if year_start <= day <= today}

    finished = (
        ReadingProgress.objects
        .filter(user=user, finished_at__isnull=False, book__deleted_at__isnull=True,
                finished_at__date__gte=year_start)
        .count()
    )

    return {
        "today": today.isoformat(),
        "goal_pages": goal,
        "today_pages": by_day.get(today, 0),
        "streak": {"current": current, "longest": longest},
        "week": [{"date": day.isoformat(), "pages": by_day.get(day, 0)} for day in week],
        "year": {
            "pages": sum(this_year.values()),
            "days": len(this_year),
            "books_finished": finished,
        },
    }


def mark_finished(record: ReadingProgress, now: datetime) -> None:
    """Stamp the first time a reader reaches the end, and only the first."""
    if record.is_finished and record.finished_at is None:
        record.finished_at = now
