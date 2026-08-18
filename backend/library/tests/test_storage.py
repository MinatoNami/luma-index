"""Content-addressed storage.

The difference from the cache this replaced: nothing here can be regenerated,
so nothing may be evicted and a full disk must be refused rather than absorbed.
"""

from __future__ import annotations

import pytest

from library.models import Book, BookSource
from library.storage import InsufficientSpace, LibraryStorage, StorageError


@pytest.fixture
def storage(settings):
    return LibraryStorage(root=settings.LIBRARY_DIR)


def chunks(payload: bytes, size: int = 8):
    return (payload[i:i + size] for i in range(0, len(payload), size))


def test_store_and_read_back(storage):
    blob = storage.store_stream(chunks(b"%PDF-1.4 hello"))
    assert blob.path.read_bytes() == b"%PDF-1.4 hello"
    assert storage.exists(blob.storage_key)


def test_the_key_is_the_content_hash(storage):
    import hashlib

    payload = b"%PDF-1.4 hello"
    blob = storage.store_stream(chunks(payload))
    assert blob.storage_key == hashlib.sha256(payload).hexdigest()


def test_identical_files_are_stored_once(storage):
    """Retrying a half-finished ZIP import should cost no extra disk."""
    first = storage.store_stream(chunks(b"%PDF-1.4 same"))
    second = storage.store_stream(chunks(b"%PDF-1.4 same"))

    assert second.storage_key == first.storage_key
    assert second.deduplicated is True
    assert len(list(storage.root.rglob("*.pdf"))) == 1


def test_different_files_get_different_keys(storage):
    a = storage.store_stream(chunks(b"%PDF-1.4 one"))
    b = storage.store_stream(chunks(b"%PDF-1.4 two"))
    assert a.storage_key != b.storage_key


def test_keys_are_sharded(storage):
    blob = storage.store_stream(chunks(b"%PDF-x"))
    assert blob.path.parent.name == blob.storage_key[2:4]
    assert blob.path.parent.parent.name == blob.storage_key[:2]


def test_a_non_digest_key_is_refused(storage):
    for bad in ["../../etc/passwd", "abc", "", "z" * 64]:
        with pytest.raises(StorageError):
            storage.path_for(bad)


def test_a_failed_write_leaves_nothing_behind(storage):
    def explode():
        yield b"%PDF-"
        raise OSError("disk went away")

    with pytest.raises(OSError):
        storage.store_stream(explode())

    assert list(storage.root.rglob("*.pdf")) == []
    assert list(storage.root.rglob("*.part")) == [], "staging file left behind"


def test_an_upload_is_refused_when_the_disk_is_nearly_full(storage, settings):
    """Storage is canonical, so it cannot evict its way out of a full disk."""
    settings.MIN_FREE_DISK_BYTES = storage.free_bytes() + 10**9
    with pytest.raises(InsufficientSpace):
        storage.store_stream(chunks(b"%PDF-x"), expected_size=1000)


@pytest.mark.django_db
def test_a_blob_shared_by_two_books_is_not_deleted_with_one(storage, user):
    blob = storage.store_stream(chunks(b"%PDF-1.4 shared"))

    for title in ("First", "Second"):
        created = Book.objects.create(owner=user, title=title)
        BookSource.objects.create(book=created, storage_key=blob.storage_key,
                                  original_filename=f"{title}.pdf", file_size=blob.size)

    Book.objects.filter(title="First").delete()
    assert storage.delete_if_unreferenced(blob.storage_key) is False
    assert storage.exists(blob.storage_key), "the surviving book lost its file"

    Book.objects.filter(title="Second").delete()
    assert storage.delete_if_unreferenced(blob.storage_key) is True
    assert not storage.exists(blob.storage_key)


def test_total_bytes_counts_what_is_stored(storage):
    storage.store_stream(chunks(b"%PDF-" + b"x" * 100))
    storage.store_stream(chunks(b"%PDF-" + b"y" * 200))
    assert storage.total_bytes() == 105 + 205
