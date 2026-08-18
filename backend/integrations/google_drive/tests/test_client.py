"""Drive client behaviour, against an in-memory Drive.

Everything here is a failure mode PRD §35 requires handling, or a Drive API
detail from docs/google-oauth.md that silently produces a wrong import.
"""

from __future__ import annotations

import io

import httpx
import pytest

from integrations.google_drive.client import DriveClient, WalkStats
from integrations.google_drive.errors import (
    DriveAuthError,
    DriveForbidden,
    DriveNotFound,
    DriveUnavailable,
)

from .fake_drive import FakeDrive


def make_client(drive: FakeDrive, **kwargs) -> DriveClient:
    slept: list[float] = []
    client = DriveClient("access-token", http=drive.client(), sleep=slept.append, **kwargs)
    client.slept = slept  # type: ignore[attr-defined]
    return client


@pytest.fixture
def library() -> FakeDrive:
    """Roughly the tree from PRD §10."""
    drive = FakeDrive()
    drive.folder("root", "Books")
    drive.folder("prog", "Programming", "root")
    drive.folder("py", "Python", "prog")
    drive.folder("arch", "Architecture", "prog")
    drive.folder("fic", "Fiction", "root")
    drive.pdf("f1", "Fluent Python.pdf", "py")
    drive.pdf("f2", "DDIA.pdf", "arch")
    drive.pdf("f3", "Dune.pdf", "fic")
    return drive


# -- walking ------------------------------------------------------------------ #

def test_walk_finds_pdfs_recursively_with_their_paths(library):
    files = list(make_client(library).walk_pdfs("root", root_name="Books"))
    assert {f.name for f in files} == {"Fluent Python.pdf", "DDIA.pdf", "Dune.pdf"}
    assert {f.path for f in files} == {
        "Books/Programming/Python/Fluent Python.pdf",
        "Books/Programming/Architecture/DDIA.pdf",
        "Books/Fiction/Dune.pdf",
    }


def test_walk_ignores_non_pdf_files(library):
    library.other("g1", "Notes", "root", "application/vnd.google-apps.document")
    library.other("g2", "cover.png", "root", "image/png")
    library.other("g3", "book.epub", "root", "application/epub+zip")

    files = list(make_client(library).walk_pdfs("root"))
    assert {f.name for f in files} == {"Fluent Python.pdf", "DDIA.pdf", "Dune.pdf"}


def test_walk_skips_trashed_files(library):
    library.files["f3"].trashed = True
    files = list(make_client(library).walk_pdfs("root"))
    assert "Dune.pdf" not in {f.name for f in files}


def test_walk_resolves_shortcuts(library):
    """A library organised with shortcuts would otherwise import as nothing."""
    drive = FakeDrive()
    drive.folder("root", "Books")
    drive.folder("elsewhere", "Elsewhere")
    drive.pdf("real", "SICP.pdf", "elsewhere")
    drive.shortcut("sc", "SICP.pdf", "root", target="real")

    stats = WalkStats()
    files = list(make_client(drive).walk_pdfs("root", stats=stats))

    assert len(files) == 1
    assert files[0].id == "real"        # the bytes come from the target
    assert files[0].name == "SICP.pdf"  # the name is what the user sees
    assert stats.shortcuts_resolved == 1


def test_walk_tolerates_a_broken_shortcut(library):
    drive = FakeDrive()
    drive.folder("root", "Books")
    drive.pdf("ok", "Real.pdf", "root")
    drive.shortcut("sc", "Gone.pdf", "root", target="deleted-target")

    stats = WalkStats()
    files = list(make_client(drive).walk_pdfs("root", stats=stats))

    assert {f.name for f in files} == {"Real.pdf"}
    assert any("broken shortcut" in e for e in stats.errors)


def test_walk_does_not_loop_on_a_folder_cycle():
    """A folder shortcut pointing back up the tree must not spin forever."""
    drive = FakeDrive()
    drive.folder("root", "Books")
    drive.folder("sub", "Sub", "root")
    drive.pdf("f1", "A.pdf", "sub")
    # 'root' reachable again from inside itself.
    drive.files["root"].parents = ["sub"]

    stats = WalkStats()
    files = list(make_client(drive).walk_pdfs("root", stats=stats))

    assert {f.name for f in files} == {"A.pdf"}
    assert stats.cycles_skipped >= 1


def test_one_unreadable_subfolder_does_not_abandon_the_import(library):
    library.forbidden_folders.add("arch")

    stats = WalkStats()
    files = list(make_client(library).walk_pdfs("root", stats=stats))

    assert {f.name for f in files} == {"Fluent Python.pdf", "Dune.pdf"}
    assert stats.errors, "the skipped folder should be recorded, not silently dropped"


def test_walk_follows_pagination():
    drive = FakeDrive(page_size=2)
    drive.folder("root", "Books")
    for i in range(7):
        drive.pdf(f"f{i}", f"Book {i}.pdf", "root")

    files = list(make_client(drive).walk_pdfs("root"))
    assert len(files) == 7


def test_list_requests_shared_drive_support(library):
    """Without both parameters, files in Shared Drives are silently invisible."""
    list(make_client(library).walk_pdfs("root"))

    listings = [r for r in library.requests if r.url.path.endswith("/files")]
    assert listings
    for request in listings:
        assert request.url.params.get("supportsAllDrives") == "true"
        assert request.url.params.get("includeItemsFromAllDrives") == "true"


def test_list_uses_a_field_projection(library):
    """Quota is partly a function of payload size."""
    list(make_client(library).walk_pdfs("root"))
    listing = next(r for r in library.requests if r.url.path.endswith("/files"))
    fields = listing.url.params.get("fields", "")
    assert "files(" in fields and "nextPageToken" in fields


def test_walk_captures_size_and_checksum(library):
    library.files["f2"].checksum = "abc123"
    library.files["f2"].size = 5_242_880

    ddia = next(f for f in make_client(library).walk_pdfs("root") if f.name == "DDIA.pdf")
    assert ddia.checksum == "abc123"
    assert ddia.size == 5_242_880
    assert ddia.modified_at is not None


# -- failures ----------------------------------------------------------------- #

def test_expired_token_raises_an_auth_error(library):
    library.failures = [401] * 6
    with pytest.raises(DriveAuthError):
        make_client(library).get_account()


def test_quota_403_is_retried_not_treated_as_permission_denied(library):
    """Drive reports quota exhaustion as 403, unlike every other 403."""
    library.failures = [403]
    client = make_client(library)
    assert client.get_account()["emailAddress"] == "owner@gmail.com"
    assert client.slept, "a quota 403 should have backed off"


def test_missing_file_raises_not_found(library):
    library.missing_files.add("f1")
    with pytest.raises(DriveNotFound):
        make_client(library).get_file("f1")


def test_server_errors_are_retried_then_succeed(library):
    library.failures = [503, 500]
    client = make_client(library)
    assert client.get_account()["emailAddress"] == "owner@gmail.com"
    assert len(client.slept) == 2


def test_backoff_is_exponential(library):
    library.failures = [503, 503, 503]
    client = make_client(library)
    client.get_account()
    assert client.slept == sorted(client.slept), f"delays should grow: {client.slept}"
    assert client.slept[-1] > client.slept[0]


def test_persistent_server_errors_give_up(library):
    library.failures = [503] * 10
    with pytest.raises(DriveUnavailable):
        make_client(library).get_account()


def test_network_errors_are_retried():
    def explode(request):
        raise httpx.ConnectError("no route to host")

    slept: list[float] = []
    client = DriveClient("t", http=httpx.Client(transport=httpx.MockTransport(explode)),
                         sleep=slept.append)
    with pytest.raises(DriveUnavailable):
        client.get_account()
    assert len(slept) == 4  # MAX_ATTEMPTS - 1


def test_forbidden_folder_raises_forbidden(library):
    library.forbidden_folders.add("root")
    with pytest.raises(DriveForbidden):
        list(make_client(library).list_children("root"))


# -- download ----------------------------------------------------------------- #

def test_download_streams_content(library):
    library.files["f1"].content = b"%PDF-1.7\n" + b"x" * 5000
    buffer = io.BytesIO()
    written = make_client(library).download("f1", buffer)

    assert written == len(b"%PDF-1.7\n" + b"x" * 5000)
    assert buffer.getvalue().startswith(b"%PDF")


def test_download_of_a_missing_file_raises(library):
    library.missing_files.add("f1")
    with pytest.raises(DriveNotFound):
        make_client(library).download("f1", io.BytesIO())


def test_start_page_token_is_fetched(library):
    assert make_client(library).get_start_page_token() == "token-1"


def test_shortcut_resolution_costs_one_extra_call(library):
    """Shortcut targets arrive in the listing; re-reading them wastes quota."""
    drive = FakeDrive()
    drive.folder("root", "Books")
    drive.folder("elsewhere", "Elsewhere")
    drive.pdf("real", "SICP.pdf", "elsewhere")
    drive.shortcut("sc", "SICP.pdf", "root", target="real")

    list(make_client(drive).walk_pdfs("root"))

    lookups = [r for r in drive.requests if "/files/" in r.url.path]
    assert len(lookups) == 1, [str(r.url) for r in lookups]
