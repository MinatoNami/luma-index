"""Reading activity: pages a day, streaks, a goal, books finished.

What counts as reading is the decision here, so most of these are about that:
arriving somewhere new counts, reopening where you were does not, and the day
is the reader's own.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.settings_models import UserSettings
from library import activity
from library.models import Book, BookSource, ReadingDay, ReadingProgress


def make_book(owner, title: str = "Walden", *, pages: int = 100, shared: bool = False) -> Book:
    book = Book.objects.create(
        owner=owner, title=title, page_count=pages,
        visibility=Book.Visibility.SHARED if shared else Book.Visibility.PRIVATE,
    )
    BookSource.objects.create(book=book, storage_key=f"{book.pk:064d}",
                              original_filename=f"{title}.pdf", file_size=1024)
    return book


def move(client, book, page: int, *, fraction: float = 0.0, **extra):
    response = client.put(
        reverse("library:book-progress", args=[book.pk]),
        {"page": page, "page_fraction": fraction, **extra},
        content_type="application/json", headers=getattr(client, "headers", {}),
    )
    assert response.status_code == 200, response.content
    return response


def pages_on(user, day: date) -> list[int]:
    return sorted(p for row in ReadingDay.objects.filter(user=user, day=day) for p in row.pages)


def today() -> date:
    return timezone.now().date()


# -- what counts as a page read ------------------------------------------------- #

@pytest.mark.django_db
def test_arriving_on_a_page_counts_it(api, user):
    book = make_book(user)
    move(api, book, 1)
    move(api, book, 2)
    move(api, book, 3)
    assert pages_on(user, today()) == [1, 2, 3]


@pytest.mark.django_db
def test_opening_a_book_where_you_left_it_is_not_reading(api, user):
    book = make_book(user)
    move(api, book, 0)  # first open, at the cover
    assert pages_on(user, today()) == []

    move(api, book, 5)
    ReadingDay.objects.all().delete()
    move(api, book, 5)  # reopened on another day, same place
    assert pages_on(user, today()) == []


@pytest.mark.django_db
def test_the_same_page_twice_is_one_page(api, user):
    book = make_book(user)
    for page in (4, 5, 4, 5, 4):
        move(api, book, page)
    assert pages_on(user, today()) == [4, 5]


@pytest.mark.django_db
def test_jumping_through_the_contents_is_one_page_not_two_hundred(api, user):
    book = make_book(user, pages=400)
    move(api, book, 250)
    assert pages_on(user, today()) == [250]


@pytest.mark.django_db
def test_a_stale_write_from_another_device_does_not_count(api, user):
    book = make_book(user)
    now = timezone.now()
    move(api, book, 10, client_updated_at=now.isoformat())
    move(api, book, 3, client_updated_at=(now - timedelta(minutes=5)).isoformat())
    assert pages_on(user, today()) == [10]


# -- whose day ------------------------------------------------------------------ #

@pytest.mark.django_db
def test_the_readers_own_date_is_used_when_it_is_believable(api, user):
    """Late evening in Honolulu is already tomorrow in UTC; the reader's
    calendar is the one a streak has to make sense against."""
    book = make_book(user)
    yesterday = today() - timedelta(days=1)
    move(api, book, 7, local_date=yesterday.isoformat())
    assert pages_on(user, yesterday) == [7]


@pytest.mark.parametrize("claimed", ["1999-01-01", "2999-12-31", "yesterday", ""])
@pytest.mark.django_db
def test_an_implausible_date_falls_back_to_the_servers(api, user, claimed):
    book = make_book(user)
    move(api, book, 7, local_date=claimed)
    assert pages_on(user, today()) == [7]


def test_local_today_accepts_a_day_either_side():
    server = timezone.now().date()
    for offset in (-1, 0, 1):
        claimed = server + timedelta(days=offset)
        assert activity.local_today(claimed.isoformat()) == claimed
    assert activity.local_today((server + timedelta(days=2)).isoformat()) == server
    assert activity.local_today(None) == server


# -- streaks -------------------------------------------------------------------- #

D = date(2026, 6, 15)


def days(*offsets: int) -> set[date]:
    return {D - timedelta(days=n) for n in offsets}


def test_no_reading_is_no_streak():
    assert activity.streaks(set(), D) == (0, 0)


def test_a_streak_counts_back_from_today():
    assert activity.streaks(days(0, 1, 2), D) == (3, 3)


def test_a_streak_is_not_broken_by_a_day_still_in_progress():
    """At breakfast, having read yesterday, you are still on a streak."""
    assert activity.streaks(days(1, 2, 3), D) == (3, 3)


def test_a_whole_missed_day_ends_it():
    assert activity.streaks(days(2, 3, 4), D) == (0, 3)


def test_the_longest_run_is_remembered():
    assert activity.streaks(days(0, 1, 5, 6, 7, 8, 20), D) == (2, 4)


# -- the summary ---------------------------------------------------------------- #

@pytest.mark.django_db
def test_the_summary_has_today_the_goal_and_a_week_oldest_first(api, user):
    book = make_book(user)
    other = make_book(user, "Essays")
    ReadingDay.objects.create(user=user, book=book, day=today(), pages=[1, 2, 3])
    ReadingDay.objects.create(user=user, book=other, day=today(), pages=[9])
    ReadingDay.objects.create(user=user, book=book, day=today() - timedelta(days=2),
                              pages=[40, 41])
    settings = UserSettings.for_user(user)
    settings.daily_page_goal = 20
    settings.save()

    body = api.get(reverse("library:activity"), {"today": today().isoformat()}).json()

    assert body["today"] == today().isoformat()
    assert body["goal_pages"] == 20
    assert body["today_pages"] == 4, "pages from every book count towards the day"
    assert body["streak"] == {"current": 1, "longest": 1}
    assert len(body["week"]) == 7
    assert body["week"][-1] == {"date": today().isoformat(), "pages": 4}
    assert body["week"][-3] == {"date": (today() - timedelta(days=2)).isoformat(), "pages": 2}
    assert body["week"][0]["date"] == (today() - timedelta(days=6)).isoformat()


@pytest.mark.django_db
def test_the_year_counts_pages_days_and_books_finished(api, user):
    book = make_book(user, pages=10)
    ReadingDay.objects.create(user=user, book=book, day=today(), pages=[1, 2])
    ReadingDay.objects.create(user=user, book=book, day=date(today().year - 1, 12, 31),
                              pages=[5, 6, 7])
    move(api, book, 9, fraction=1.0)

    year = api.get(reverse("library:activity")).json()["year"]
    assert year["books_finished"] == 1
    # Last year's pages are not this year's; today's arrival on page 9 is.
    assert year["pages"] == 3 and year["days"] == 1


@pytest.mark.django_db
def test_activity_is_per_reader(api, user, other_user):
    book = make_book(user, shared=True)
    ReadingDay.objects.create(user=other_user, book=book, day=today(), pages=[1, 2, 3])

    body = api.get(reverse("library:activity")).json()
    assert body["today_pages"] == 0 and body["streak"]["current"] == 0


@pytest.mark.django_db
def test_activity_needs_a_signed_in_reader(db):
    assert Client().get(reverse("library:activity")).status_code in (401, 403)


# -- finishing ------------------------------------------------------------------ #

@pytest.mark.django_db
def test_reaching_the_end_stamps_when_and_going_back_keeps_it(api, user):
    book = make_book(user, pages=10)
    move(api, book, 5)
    assert ReadingProgress.objects.get().finished_at is None

    move(api, book, 9, fraction=1.0)
    finished = ReadingProgress.objects.get().finished_at
    assert finished is not None

    move(api, book, 2)  # back to reread a chapter
    move(api, book, 9, fraction=1.0)
    assert ReadingProgress.objects.get().finished_at == finished, (
        "finishing again moved the date you first finished it")


# -- the goal ------------------------------------------------------------------- #

@pytest.mark.django_db
def test_the_goal_is_a_setting_and_is_bounded(api):
    url = reverse("accounts:settings")
    assert api.get(url).json()["daily_page_goal"] == 0, "no goal unless one is chosen"

    ok = api.patch(url, {"daily_page_goal": 25}, content_type="application/json",
                   headers=api.headers)
    assert ok.status_code == 200 and ok.json()["daily_page_goal"] == 25

    for nonsense in (-1, 1001):
        refused = api.patch(url, {"daily_page_goal": nonsense},
                            content_type="application/json", headers=api.headers)
        assert refused.status_code == 400
