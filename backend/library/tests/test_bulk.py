"""Acting on a whole selection at once.

The arithmetic is not the interesting part. What matters is that a selection
containing something awkward — a folder that would land on a name already
there, an id belonging to someone else, a book inside a folder being trashed in
the same breath — still does the right thing for everything else, and says what
it skipped.
"""

from __future__ import annotations

import json

import pytest
from django.urls import reverse

from library.models import Book, Collection, CollectionBook, Folder, UserBookState


def act(client, payload):
    return client.post(reverse("library:bulk"), json.dumps(payload),
                       content_type="application/json", headers=client.headers)


def a_folder(user, name, parent=None):
    return Folder.objects.create(owner=user, name=name, parent=parent)


def a_book(user, title, folder=None):
    return Book.objects.create(owner=user, title=title, folder=folder)


# -- moving --------------------------------------------------------------------- #

@pytest.mark.django_db
def test_moving_a_mixed_selection(api, user):
    target = a_folder(user, "Target")
    folder = a_folder(user, "Moved")
    one, two = a_book(user, "One"), a_book(user, "Two")

    body = act(api, {"action": "move", "folders": [folder.pk],
                     "books": [one.pk, two.pk], "folder": target.pk}).json()

    assert (body["folders"], body["books"], body["skipped"]) == (1, 2, [])
    folder.refresh_from_db()
    one.refresh_from_db()
    assert folder.parent_id == target.pk
    assert one.folder_id == target.pk


@pytest.mark.django_db
def test_moving_to_the_top_level(api, user):
    """`folder: null` is the root, which is a different thing from no target at
    all — so the two must not collapse into one."""
    parent = a_folder(user, "Parent")
    inside = a_book(user, "Inside", folder=parent)

    body = act(api, {"action": "move", "books": [inside.pk], "folder": None}).json()

    inside.refresh_from_db()
    assert body["books"] == 1
    assert inside.folder_id is None


@pytest.mark.django_db
def test_a_move_with_no_target_given_is_rejected(api, user):
    book = a_book(user, "One")

    assert act(api, {"action": "move", "books": [book.pk]}).status_code == 400


@pytest.mark.django_db
def test_one_name_collision_does_not_stop_the_rest(api, user):
    """The whole point of reporting rather than failing: nineteen folders should
    not be held up by the twentieth."""
    target = a_folder(user, "Target")
    a_folder(user, "Clash", parent=target)          # already there
    clash = a_folder(user, "Clash")
    fine = a_folder(user, "Fine")

    body = act(api, {"action": "move", "folders": [clash.pk, fine.pk],
                     "folder": target.pk}).json()

    fine.refresh_from_db()
    clash.refresh_from_db()
    assert body["folders"] == 1
    assert fine.parent_id == target.pk
    assert clash.parent_id is None, "the one that clashed stayed put"
    assert body["skipped"] == [{"kind": "folder", "id": clash.pk,
                                "reason": "A folder with that name is already there."}]


@pytest.mark.django_db
def test_a_folder_cannot_be_moved_into_itself(api, user):
    folder = a_folder(user, "Self")

    body = act(api, {"action": "move", "folders": [folder.pk], "folder": folder.pk}).json()

    folder.refresh_from_db()
    assert body["folders"] == 0
    assert folder.parent_id is None
    assert "itself" in body["skipped"][0]["reason"]


@pytest.mark.django_db
def test_a_folder_cannot_be_moved_into_its_own_subfolder(api, user):
    outer = a_folder(user, "Outer")
    inner = a_folder(user, "Inner", parent=outer)

    body = act(api, {"action": "move", "folders": [outer.pk], "folder": inner.pk}).json()

    outer.refresh_from_db()
    assert body["folders"] == 0
    assert outer.parent_id is None


@pytest.mark.django_db
def test_a_folder_selected_with_its_own_parent_travels_with_it(api, user):
    """Moving both would pull the child back out of the parent it just moved
    with — a shape nobody asked for."""
    target = a_folder(user, "Target")
    outer = a_folder(user, "Outer")
    inner = a_folder(user, "Inner", parent=outer)

    body = act(api, {"action": "move", "folders": [outer.pk, inner.pk],
                     "folder": target.pk}).json()

    outer.refresh_from_db()
    inner.refresh_from_db()
    assert outer.parent_id == target.pk
    assert inner.parent_id == outer.pk, "still inside Outer, which moved"
    assert body["skipped"] == [{"kind": "folder", "id": inner.pk,
                                "reason": "Moves with the folder it is in."}]


# -- trashing ------------------------------------------------------------------- #

@pytest.mark.django_db
def test_trashing_a_mixed_selection(api, user):
    folder = a_folder(user, "Folder")
    a_book(user, "Inside", folder=folder)
    loose = a_book(user, "Loose")

    body = act(api, {"action": "trash", "folders": [folder.pk], "books": [loose.pk]}).json()

    assert body["folders"] == 1
    assert body["books"] == 2, "the book inside counts too"
    assert Book.objects.filter(deleted_at__isnull=True).count() == 0


@pytest.mark.django_db
def test_a_book_inside_a_trashed_folder_is_not_counted_twice(api, user):
    """It goes with the folder; selecting it as well should not inflate the
    number the user is shown."""
    folder = a_folder(user, "Folder")
    inside = a_book(user, "Inside", folder=folder)

    body = act(api, {"action": "trash", "folders": [folder.pk], "books": [inside.pk]}).json()

    assert body["books"] == 1


# -- favourites and collections ------------------------------------------------- #

@pytest.mark.django_db
def test_favouriting_a_selection(api, user):
    one, two = a_book(user, "One"), a_book(user, "Two")

    body = act(api, {"action": "favourite", "books": [one.pk, two.pk]}).json()

    assert body["books"] == 2
    assert UserBookState.objects.filter(user=user, is_favourite=True).count() == 2


@pytest.mark.django_db
def test_unfavouriting_a_selection(api, user):
    book = a_book(user, "One")
    UserBookState.objects.create(user=user, book=book, is_favourite=True)

    act(api, {"action": "unfavourite", "books": [book.pk]})

    assert not UserBookState.objects.get(user=user, book=book).is_favourite


@pytest.mark.django_db
def test_adding_a_selection_to_a_collection(api, user):
    collection = Collection.objects.create(owner=user, name="Reading")
    one, two = a_book(user, "One"), a_book(user, "Two")
    CollectionBook.objects.create(collection=collection, book=one)   # already in

    body = act(api, {"action": "collect", "books": [one.pk, two.pk],
                     "collection": collection.pk}).json()

    assert body["books"] == 1
    assert body["skipped"] == [{"kind": "book", "id": one.pk,
                                "reason": "Already in that collection."}]
    assert CollectionBook.objects.filter(collection=collection).count() == 2


@pytest.mark.django_db
def test_favouriting_folders_is_rejected_rather_than_ignored(api, user):
    """Silently dropping half a selection would look like it worked."""
    folder = a_folder(user, "Folder")

    assert act(api, {"action": "favourite", "folders": [folder.pk]}).status_code == 400


# -- the authorization boundary -------------------------------------------------- #

@pytest.mark.django_db
def test_another_users_items_are_skipped_not_reported(api, user, other_user):
    """Skipped exactly like an id that does not exist — saying which is which
    would confirm the row is there."""
    theirs_folder = a_folder(other_user, "Theirs")
    theirs_book = a_book(other_user, "Theirs")
    mine = a_book(user, "Mine")
    target = a_folder(user, "Target")

    body = act(api, {"action": "move", "folders": [theirs_folder.pk],
                     "books": [theirs_book.pk, mine.pk], "folder": target.pk}).json()

    theirs_folder.refresh_from_db()
    theirs_book.refresh_from_db()
    assert (body["folders"], body["books"]) == (0, 1)
    assert body["skipped"] == [], "nothing said about ids that were not ours"
    assert theirs_folder.parent_id is None and theirs_book.folder_id is None


@pytest.mark.django_db
def test_an_id_that_does_not_exist_is_skipped_silently(api, user):
    mine = a_book(user, "Mine")

    body = act(api, {"action": "trash", "books": [mine.pk, 999_999]}).json()

    assert body["books"] == 1
    assert body["skipped"] == []


@pytest.mark.django_db
def test_moving_into_another_users_folder_is_a_404(api, user, other_user):
    theirs = a_folder(other_user, "Theirs")
    mine = a_book(user, "Mine")

    response = act(api, {"action": "move", "books": [mine.pk], "folder": theirs.pk})

    assert response.status_code == 404
    mine.refresh_from_db()
    assert mine.folder_id is None


@pytest.mark.django_db
def test_bulk_actions_need_a_signed_in_user(client, user):
    book = a_book(user, "Mine")

    response = client.post(reverse("library:bulk"),
                           json.dumps({"action": "trash", "books": [book.pk]}),
                           content_type="application/json")

    assert response.status_code in (401, 403)
    book.refresh_from_db()
    assert book.deleted_at is None


# -- shape ---------------------------------------------------------------------- #

@pytest.mark.django_db
def test_an_empty_selection_is_rejected(api, user):
    assert act(api, {"action": "trash"}).status_code == 400


@pytest.mark.django_db
def test_an_unknown_action_is_rejected(api, user):
    book = a_book(user, "Mine")

    assert act(api, {"action": "incinerate", "books": [book.pk]}).status_code == 400
    book.refresh_from_db()
    assert book.deleted_at is None
