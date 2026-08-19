"""Uploading a large file in pieces.

The happy path is the least interesting part. What matters is what happens when
the link drops: that a resumed upload lands the same bytes, that a chunk sent
twice does not land twice, and that a client which lost a response can find out
where it really got to.
"""

from __future__ import annotations

import io
import json
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from library.chunked import CHUNK_SIZE, ChunkConflict, append, begin, finish, purge_stale
from library.models import Book, ChunkedUpload, Folder

from .pdfs import make_pdf


def start(client, *, filename="Big.pdf", size=1000, folder=None):
    payload = {"filename": filename, "size": size}
    if folder is not None:
        payload["folder"] = folder
    return client.post(reverse("library:chunked-upload-start"), json.dumps(payload),
                       content_type="application/json", headers=client.headers)


def send(client, upload_id, offset, data):
    return client.put(
        f"{reverse('library:chunked-upload-detail', args=[upload_id])}?offset={offset}",
        data, content_type="application/octet-stream", headers=client.headers)


def complete(client, upload_id):
    return client.post(reverse("library:chunked-upload-complete", args=[upload_id]),
                       headers=client.headers)


# -- the ordinary path ----------------------------------------------------------- #

@pytest.mark.django_db
def test_a_file_sent_in_pieces_becomes_a_book(api, user):
    pdf = make_pdf(pages=2)
    began = start(api, filename="Split.pdf", size=len(pdf))
    assert began.status_code == 201
    upload_id = began.json()["id"]

    half = len(pdf) // 2
    assert send(api, upload_id, 0, pdf[:half]).json()["received"] == half
    assert send(api, upload_id, half, pdf[half:]).json()["received"] == len(pdf)

    done = complete(api, upload_id)

    assert done.status_code == 201
    assert done.json()["outcome"] == "imported"
    assert Book.objects.count() == 1


@pytest.mark.django_db
def test_the_assembled_bytes_are_the_bytes_that_were_sent(api, user):
    pdf = make_pdf(pages=3)
    upload_id = start(api, size=len(pdf)).json()["id"]
    for offset in range(0, len(pdf), 500):
        send(api, upload_id, offset, pdf[offset:offset + 500])

    complete(api, upload_id)

    book = Book.objects.get()
    assert book.source.file_size == len(pdf)


@pytest.mark.django_db
def test_it_lands_in_the_folder_it_was_started_for(api, user):
    folder = Folder.objects.create(owner=user, name="Target")
    pdf = make_pdf()
    upload_id = start(api, size=len(pdf), folder=folder.pk).json()["id"]
    send(api, upload_id, 0, pdf)

    complete(api, upload_id)

    assert Book.objects.get().folder_id == folder.pk


@pytest.mark.django_db
def test_the_client_is_told_how_big_a_chunk_to_send(api, user):
    assert start(api, size=999).json()["chunk_size"] == CHUNK_SIZE


# -- dropped connections --------------------------------------------------------- #

@pytest.mark.django_db
def test_resuming_asks_where_it_got_to(api, user):
    pdf = make_pdf(pages=2)
    upload_id = start(api, size=len(pdf)).json()["id"]
    send(api, upload_id, 0, pdf[:400])

    # What a client does after reconnecting.
    state = api.get(reverse("library:chunked-upload-detail", args=[upload_id])).json()

    assert state["received"] == 400
    assert state["size"] == len(pdf)


@pytest.mark.django_db
def test_a_chunk_sent_twice_does_not_land_twice(api, user):
    """The response can be lost while the bytes still arrive. A client retrying
    that chunk must not append it again."""
    pdf = make_pdf(pages=2)
    upload_id = start(api, size=len(pdf)).json()["id"]
    send(api, upload_id, 0, pdf[:400])

    again = send(api, upload_id, 0, pdf[:400])

    assert again.status_code == 409
    assert again.json()["received"] == 400, "told where it actually is"
    assert ChunkedUpload.objects.get(pk=upload_id).received == 400


@pytest.mark.django_db
def test_a_chunk_that_would_leave_a_hole_is_refused(api, user):
    pdf = make_pdf(pages=2)
    upload_id = start(api, size=len(pdf)).json()["id"]
    send(api, upload_id, 0, pdf[:400])

    ahead = send(api, upload_id, 900, pdf[900:1000])

    assert ahead.status_code == 409
    assert ahead.json()["received"] == 400
    assert ChunkedUpload.objects.get(pk=upload_id).received == 400


@pytest.mark.django_db
def test_completing_early_is_refused_rather_than_storing_half_a_file(api, user):
    pdf = make_pdf(pages=2)
    upload_id = start(api, size=len(pdf)).json()["id"]
    send(api, upload_id, 0, pdf[:400])

    response = complete(api, upload_id)

    assert response.status_code == 409
    assert response.json()["received"] == 400
    assert Book.objects.count() == 0


@pytest.mark.django_db
def test_more_bytes_than_declared_are_truncated(user):
    """The declared size is what the disk and quota checks were made against, so
    it is also the most that can be written."""
    upload = begin(user, filename="Odd.pdf", size=100)

    received = append(upload, offset=0, stream=io.BytesIO(b"x" * 500))

    assert received == 100


# -- refusing before the upload, not after ----------------------------------------- #

@pytest.mark.django_db
def test_a_file_over_the_limit_is_refused_before_a_byte_is_sent(api, user, settings):
    settings.MAX_UPLOAD_BYTES = 1024

    response = start(api, size=99_999)

    assert response.status_code == 400
    assert ChunkedUpload.objects.count() == 0


@pytest.mark.django_db
def test_an_account_with_no_room_is_refused_up_front(api, user, settings):
    from library.tests.test_quota import held
    settings.DEFAULT_USER_QUOTA_BYTES = 4 * 1024 * 1024
    held(user, "a" * 64, 4 * 1024 * 1024)

    response = start(api, size=1_000_000)

    assert response.status_code == 507
    assert ChunkedUpload.objects.count() == 0


@pytest.mark.django_db
def test_something_that_is_not_a_pdf_is_refused_at_the_end(api, user):
    """The magic-byte check lives in store_upload, and completion goes through
    it — so there is no second path where a non-PDF could slip in."""
    junk = b"not a pdf at all" * 10
    upload_id = start(api, size=len(junk)).json()["id"]
    send(api, upload_id, 0, junk)

    response = complete(api, upload_id)

    assert response.status_code == 400
    assert Book.objects.count() == 0


# -- other people's uploads --------------------------------------------------------- #

@pytest.mark.django_db
def test_another_users_upload_is_not_yours_to_touch(api, other_user):
    theirs = begin(other_user, filename="Theirs.pdf", size=100)

    assert send(api, theirs.pk, 0, b"x" * 10).status_code == 404
    assert complete(api, theirs.pk).status_code == 404
    assert api.get(reverse("library:chunked-upload-detail", args=[theirs.pk])).status_code == 404


@pytest.mark.django_db
def test_starting_an_upload_needs_a_signed_in_user(client):
    response = client.post(reverse("library:chunked-upload-start"),
                           json.dumps({"filename": "x.pdf", "size": 10}),
                           content_type="application/json")

    assert response.status_code in (401, 403)


# -- abandoned uploads -------------------------------------------------------------- #

@pytest.mark.django_db
def test_giving_up_removes_the_staging_file(api, user):
    from pathlib import Path
    upload_id = start(api, size=1000).json()["id"]
    staged = Path(ChunkedUpload.objects.get(pk=upload_id).staged_path)
    send(api, upload_id, 0, b"x" * 100)
    assert staged.exists()

    api.delete(reverse("library:chunked-upload-detail", args=[upload_id]),
               headers=api.headers)

    assert not staged.exists()
    assert ChunkedUpload.objects.count() == 0


@pytest.mark.django_db
def test_an_upload_nobody_finished_is_swept_up(user):
    """Its staging file is holding disk that nothing will ever claim, and the
    space check that let it start assumed it would finish."""
    from pathlib import Path
    upload = begin(user, filename="Forgotten.pdf", size=1000)
    append(upload, offset=0, stream=io.BytesIO(b"x" * 100))
    staged = Path(upload.staged_path)
    ChunkedUpload.objects.filter(pk=upload.pk).update(
        updated_at=timezone.now() - timedelta(hours=48))

    assert purge_stale(hours=24) == 1
    assert not staged.exists()
    assert ChunkedUpload.objects.count() == 0


@pytest.mark.django_db
def test_an_upload_still_in_progress_is_left_alone(user):
    begin(user, filename="Active.pdf", size=1000)

    assert purge_stale(hours=24) == 0
    assert ChunkedUpload.objects.count() == 1


@pytest.mark.django_db
def test_finishing_an_upload_whose_staging_file_vanished_says_so(user):
    from pathlib import Path
    upload = begin(user, filename="Gone.pdf", size=10)
    Path(upload.staged_path).unlink()

    with pytest.raises(Exception) as raised:
        finish(upload)
    assert "staged" in str(raised.value)


def test_chunk_conflict_carries_the_resume_point():
    assert ChunkConflict(4096).received == 4096
