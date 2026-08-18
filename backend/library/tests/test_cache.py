"""PDF cache behaviour.

PRD §25 requires a size cap with automatic cleanup, invalidation against the
provider's modification metadata, and stable identifiers. Each of those is a
test here; the size cap in particular was previously configured but not
enforced anywhere.
"""

from __future__ import annotations

import os
import threading

import pytest

from library.cache import CacheError, PdfCache

KEY_A = "a" * 64
KEY_B = "b" * 64
KEY_C = "c" * 64


def writer(payload: bytes):
    def write(handle):
        handle.write(payload)
    return write


@pytest.fixture
def cache(tmp_path):
    return PdfCache(root=tmp_path / "pdf-cache", max_bytes=10_000)


def test_store_then_get_round_trips(cache):
    cache.store(KEY_A, writer(b"%PDF-1.4 hello"))
    path = cache.get(KEY_A)
    assert path is not None
    assert path.read_bytes() == b"%PDF-1.4 hello"


def test_get_returns_none_when_absent(cache):
    assert cache.get(KEY_A) is None


def test_keys_are_sharded_into_subdirectories(cache):
    path = cache.store(KEY_A, writer(b"x"))
    assert path.parent.name == KEY_A[2:4]
    assert path.parent.parent.name == KEY_A[:2]


def test_a_non_hex_key_is_refused(cache):
    """The keys are digests today; this is what stops that assumption rotting."""
    for bad in ["../../etc/passwd", "abc/def", "not-hex-at-all", ""]:
        with pytest.raises(CacheError):
            cache.path_for(bad)


def test_a_failed_write_leaves_nothing_behind(cache):
    def explode(handle):
        handle.write(b"partial")
        raise OSError("disk went away")

    with pytest.raises(OSError):
        cache.store(KEY_A, explode)

    assert cache.get(KEY_A) is None
    assert not list(cache.root.rglob("*.part")), "staging file was left behind"


def test_readers_never_see_a_partial_file(cache):
    """The rename is what guarantees this; a direct write would not."""
    seen: list[bool] = []

    def slow_writer(handle):
        handle.write(b"first-half")
        seen.append(cache.get(KEY_A) is not None)  # mid-write visibility
        handle.write(b"second-half")

    cache.store(KEY_A, slow_writer)
    assert seen == [False]
    assert cache.get(KEY_A).read_bytes() == b"first-halfsecond-half"


@pytest.mark.django_db(transaction=True)
def test_fetch_populates_once(cache):
    calls = []

    def counting(handle):
        calls.append(1)
        handle.write(b"payload")

    cache.fetch(KEY_A, counting)
    cache.fetch(KEY_A, counting)
    assert len(calls) == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_fetch_downloads_once(cache):
    """Two readers opening the same uncached book must not both download it."""
    downloads = []
    barrier = threading.Barrier(2, timeout=10)

    def slow_download(handle):
        downloads.append(1)
        barrier.wait()  # hold the lock while the other thread arrives
        handle.write(b"%PDF payload")

    def run():
        from django.db import connection
        try:
            cache.fetch(KEY_A, slow_download)
        finally:
            connection.close()

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    # The second thread never enters the writer, so nothing waits on the
    # barrier's second slot; release it once the first is through.
    try:
        barrier.wait(timeout=10)
    except threading.BrokenBarrierError:
        pass
    for thread in threads:
        thread.join(timeout=15)

    assert len(downloads) == 1, "the advisory lock did not prevent a double download"


# -- eviction ----------------------------------------------------------------- #

@pytest.mark.django_db(transaction=True)
def test_eviction_enforces_the_size_cap(tmp_path):
    cache = PdfCache(root=tmp_path / "c", max_bytes=3_000)
    for index, key in enumerate([KEY_A, KEY_B, KEY_C]):
        cache.store(key, writer(b"x" * 1_500))
        os.utime(cache.path_for(key), (index, index))  # oldest first

    result = cache.evict_to_limit()

    assert result.removed >= 1
    assert cache.total_bytes() <= 3_000


@pytest.mark.django_db(transaction=True)
def test_eviction_removes_least_recently_used_first(tmp_path):
    cache = PdfCache(root=tmp_path / "c", max_bytes=2_600)
    for key in (KEY_A, KEY_B, KEY_C):
        cache.store(key, writer(b"x" * 1_000))

    os.utime(cache.path_for(KEY_A), (100, 100))     # oldest
    os.utime(cache.path_for(KEY_B), (200, 200))
    os.utime(cache.path_for(KEY_C), (300, 300))     # newest

    cache.evict_to_limit()

    assert cache.get(KEY_A) is None, "the least recently used file survived"
    assert cache.get(KEY_C) is not None, "the most recently used file was evicted"


@pytest.mark.django_db(transaction=True)
def test_reading_a_file_protects_it_from_eviction(tmp_path):
    cache = PdfCache(root=tmp_path / "c", max_bytes=2_600)
    for key in (KEY_A, KEY_B, KEY_C):
        cache.store(key, writer(b"x" * 1_000))
    os.utime(cache.path_for(KEY_A), (100, 100))
    os.utime(cache.path_for(KEY_B), (200, 200))
    os.utime(cache.path_for(KEY_C), (300, 300))

    cache.get(KEY_A)  # touch the oldest — it is now the newest
    cache.evict_to_limit()

    assert cache.get(KEY_A) is not None
    assert cache.get(KEY_B) is None


@pytest.mark.django_db(transaction=True)
def test_eviction_is_a_no_op_below_the_cap(tmp_path):
    cache = PdfCache(root=tmp_path / "c", max_bytes=1_000_000)
    cache.store(KEY_A, writer(b"x" * 100))
    assert cache.evict_to_limit().removed == 0
    assert cache.get(KEY_A) is not None


@pytest.mark.django_db(transaction=True)
def test_an_unlimited_cache_never_evicts(tmp_path):
    cache = PdfCache(root=tmp_path / "c", max_bytes=0)
    cache.store(KEY_A, writer(b"x" * 5_000))
    assert cache.evict_if_needed().removed == 0
    assert cache.get(KEY_A) is not None


@pytest.mark.django_db(transaction=True)
def test_a_streaming_reader_survives_eviction(tmp_path):
    """Unlinking an open file is safe on Linux; the reader keeps its inode."""
    cache = PdfCache(root=tmp_path / "c", max_bytes=1_500)
    cache.store(KEY_A, writer(b"y" * 1_000))
    os.utime(cache.path_for(KEY_A), (100, 100))

    with cache.path_for(KEY_A).open("rb") as reader:
        head = reader.read(10)
        cache.store(KEY_B, writer(b"z" * 1_000))
        cache.evict_to_limit()
        assert cache.get(KEY_A) is None      # gone from the cache
        assert head + reader.read() == b"y" * 1_000   # still readable here


@pytest.mark.django_db(transaction=True)
def test_a_second_eviction_backs_off_instead_of_double_deleting(tmp_path):
    """Concurrent sweeps each ignore the other's deletions and over-evict."""
    from common.db import advisory_lock
    from library.cache import EVICTION_LOCK

    cache = PdfCache(root=tmp_path / "c", max_bytes=100)
    cache.store(KEY_A, writer(b"x" * 1_000))

    def hold():
        from django.db import connection
        with advisory_lock(EVICTION_LOCK):
            barrier.wait(timeout=10)   # lock is held from here...
            barrier.wait(timeout=10)   # ...until the main thread has tried
        connection.close()

    barrier = threading.Barrier(2, timeout=10)
    thread = threading.Thread(target=hold)
    thread.start()
    barrier.wait(timeout=10)

    result = cache.evict_to_limit()

    barrier.wait(timeout=10)
    thread.join(timeout=10)

    assert result.skipped is True
    assert result.removed == 0
