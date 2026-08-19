"""Per-account storage limits.

The disk check protects the instance; this protects one account from another.
What is worth pinning down is not the arithmetic but the charging rule: which
bytes count, whose they are, and when they stop counting.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from library.models import Book, BookSource, Folder, UploadBatch
from library.quota import QuotaExceeded, check_quota_for, limit_for, remaining_for, usage_for
from library.services import process_zip_batch, store_upload
from library.storage import LibraryStorage

from .pdfs import make_pdf
from .test_api import pdf_file, upload
from .zips import build_zip

MIB = 1024 * 1024


def held(user, key, size, *, folder=None, trashed=False, title=None):
    """A book pointing at `key`, as if it had been uploaded."""
    from django.utils import timezone
    book = Book.objects.create(owner=user, folder=folder, title=title or key,
                               deleted_at=timezone.now() if trashed else None)
    BookSource.objects.create(book=book, storage_key=key, original_filename=f"{key}.pdf",
                              file_size=size)
    return book


# -- what counts ---------------------------------------------------------------- #

@pytest.mark.django_db
def test_usage_is_the_sum_of_the_files_a_library_points_at(user):
    held(user, "a" * 64, 3 * MIB)
    held(user, "b" * 64, 5 * MIB)

    assert usage_for(user) == 8 * MIB


@pytest.mark.django_db
def test_the_same_file_in_two_folders_is_charged_once(user):
    """Two books over one blob. Billing it twice would charge for disk that was
    never used — the second copy exists only as a row."""
    first = Folder.objects.create(owner=user, name="A")
    second = Folder.objects.create(owner=user, name="B")
    held(user, "a" * 64, 4 * MIB, folder=first)
    held(user, "a" * 64, 4 * MIB, folder=second)

    assert usage_for(user) == 4 * MIB


@pytest.mark.django_db
def test_trashed_books_still_count(user):
    """Their bytes are still on the disk. It is also what gives emptying the
    trash a point."""
    held(user, "a" * 64, 4 * MIB)
    held(user, "b" * 64, 6 * MIB, trashed=True)

    assert usage_for(user) == 10 * MIB


@pytest.mark.django_db
def test_another_account_holding_the_same_file_does_not_make_it_free(user, other_user):
    """Deduplication is a storage optimisation, not an entitlement. If it were
    shared, whether an upload cost anything would depend on whether a stranger
    uploaded it first — arbitrary, and a disclosure about their library."""
    held(other_user, "a" * 64, 9 * MIB)
    held(user, "a" * 64, 9 * MIB)

    assert usage_for(user) == 9 * MIB
    assert usage_for(other_user) == 9 * MIB


@pytest.mark.django_db
def test_an_empty_library_uses_nothing(user):
    assert usage_for(user) == 0


# -- where the limit comes from ------------------------------------------------- #

@pytest.mark.django_db
def test_the_instance_default_applies_when_a_user_has_no_allowance(user, settings):
    settings.DEFAULT_USER_QUOTA_BYTES = 50 * MIB

    assert user.storage_quota_bytes is None
    assert limit_for(user) == 50 * MIB


@pytest.mark.django_db
def test_a_users_own_allowance_wins(user, settings):
    settings.DEFAULT_USER_QUOTA_BYTES = 50 * MIB
    user.storage_quota_bytes = 200 * MIB

    assert limit_for(user) == 200 * MIB


@pytest.mark.django_db
def test_zero_on_a_user_means_unlimited_not_nothing(user, settings):
    """The distinction that makes two sentinels worth having: an exemption must
    not quietly revert the next time the instance default changes."""
    settings.DEFAULT_USER_QUOTA_BYTES = 50 * MIB
    user.storage_quota_bytes = 0
    held(user, "a" * 64, 900 * MIB)

    assert limit_for(user) == 0
    assert remaining_for(user) is None
    check_quota_for(user, 10_000 * MIB)  # does not raise


@pytest.mark.django_db
def test_unlimited_by_default(user, settings):
    """A single-user instance has nobody to be fair to, and a limit arriving by
    surprise is worse than no limit."""
    settings.DEFAULT_USER_QUOTA_BYTES = 0

    assert limit_for(user) == 0
    check_quota_for(user, 10_000 * MIB)


# -- refusing ------------------------------------------------------------------- #

@pytest.mark.django_db
def test_an_upload_that_fits_is_allowed(user, settings):
    settings.DEFAULT_USER_QUOTA_BYTES = 10 * MIB
    held(user, "a" * 64, 6 * MIB)

    check_quota_for(user, 4 * MIB)
    assert remaining_for(user) == 4 * MIB


@pytest.mark.django_db
def test_an_upload_that_does_not_fit_is_refused(user, settings):
    settings.DEFAULT_USER_QUOTA_BYTES = 10 * MIB
    held(user, "a" * 64, 6 * MIB)

    with pytest.raises(QuotaExceeded) as raised:
        check_quota_for(user, 5 * MIB)
    assert "trash" in str(raised.value), "the message should say where the space went"


# -- through the upload path ---------------------------------------------------- #

@pytest.mark.django_db
def test_uploading_over_the_limit_is_refused_with_507(api, user, settings):
    settings.DEFAULT_USER_QUOTA_BYTES = 1  # one byte: anything at all is too much

    response = upload(api, [pdf_file("Too big.pdf")])

    assert response.status_code == 507
    assert Book.objects.count() == 0


@pytest.mark.django_db
def test_a_refused_upload_leaves_nothing_on_disk(api, user, settings):
    """The file has to be written before its digest is known, so a refusal
    after the fact has to clean up after itself."""
    settings.DEFAULT_USER_QUOTA_BYTES = 1
    storage = LibraryStorage()

    upload(api, [pdf_file("Too big.pdf")])

    assert list(storage.root.rglob("*.pdf")) == []


@pytest.mark.django_db
def test_filing_a_file_you_already_hold_costs_nothing(api, user, settings):
    """At 99% full, re-filing a PDF this library already stores must not be
    refused: it adds a row, not bytes."""
    same = make_pdf(pages=1)

    first = upload(api, [SimpleUploadedFile("Book.pdf", same, content_type="application/pdf")])
    assert first.status_code == 201

    # Leave no room for new bytes at all.
    settings.DEFAULT_USER_QUOTA_BYTES = usage_for(user)
    elsewhere = Folder.objects.create(owner=user, name="Elsewhere")

    again = upload(api, [SimpleUploadedFile("Book.pdf", same, content_type="application/pdf")],
                   folder=elsewhere.pk)

    assert again.status_code == 201, again.json()
    assert Book.objects.filter(owner=user).count() == 2
    assert usage_for(user) == settings.DEFAULT_USER_QUOTA_BYTES, "no new bytes charged"


@pytest.mark.django_db
def test_an_account_with_no_room_cannot_even_stage_an_archive(api, user, settings):
    settings.DEFAULT_USER_QUOTA_BYTES = 1
    held(user, "a" * 64, 4 * MIB)

    response = upload(api, [SimpleUploadedFile(
        "library.zip", build_zip({"Books/One.pdf": make_pdf()}))])

    assert response.status_code == 507
    assert UploadBatch.objects.count() == 0


@pytest.mark.django_db
def test_a_zip_import_stops_at_the_limit_instead_of_failing_every_entry(api, user, settings):
    """One clear stop, not four hundred identical failures each preceded by a
    full write."""
    archive = build_zip({f"Books/{n:02}.pdf": make_pdf(pages=n + 1) for n in range(6)})
    response = upload(api, [SimpleUploadedFile("library.zip", archive)])
    assert response.status_code == 201

    batch = UploadBatch.objects.get()
    settings.DEFAULT_USER_QUOTA_BYTES = 3000  # room for the first entry or two

    process_zip_batch(batch)
    batch.refresh_from_db()

    assert batch.imported < batch.discovered, "it should have stopped early"
    assert batch.failed == 0, "stopping is not the same as failing every entry"
    assert "Stopped at" in batch.error_summary
    assert usage_for(user) <= 3000


@pytest.mark.django_db
def test_store_upload_reports_the_limit_in_the_message(user, settings):
    settings.DEFAULT_USER_QUOTA_BYTES = 4 * MIB
    held(user, "a" * 64, 4 * MIB)

    with pytest.raises(QuotaExceeded) as raised:
        store_upload(user, pdf_file("Another.pdf"))
    assert "4 MiB" in str(raised.value)


# -- reporting ------------------------------------------------------------------ #

@pytest.mark.django_db
def test_the_storage_endpoint_reports_usage_and_the_limit(api, user, settings):
    settings.DEFAULT_USER_QUOTA_BYTES = 10 * MIB
    held(user, "a" * 64, 6 * MIB)

    body = api.get(reverse("library:storage")).json()

    assert body["quota_bytes"] == 10 * MIB
    assert body["used_bytes"] == 6 * MIB


@pytest.mark.django_db
def test_usage_is_reported_even_without_a_limit(api, user, settings):
    """What your library weighs is worth knowing whether or not it is capped."""
    settings.DEFAULT_USER_QUOTA_BYTES = 0
    held(user, "a" * 64, 6 * MIB)

    body = api.get(reverse("library:storage")).json()

    assert body["quota_bytes"] == 0
    assert body["used_bytes"] == 6 * MIB


@pytest.mark.django_db
def test_one_accounts_usage_is_not_another_accounts(api, user, other_user):
    held(other_user, "b" * 64, 500 * MIB)
    held(user, "a" * 64, 2 * MIB)

    body = api.get(reverse("library:storage")).json()

    assert body["used_bytes"] == 2 * MIB
