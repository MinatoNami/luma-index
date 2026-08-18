"""ZIP handling.

An uploaded archive is hostile input. Each test here is a way an extractor gets
exploited or a disk gets filled, and the assertion is that none of it reaches
the filesystem.
"""

from __future__ import annotations

import zipfile

import pytest

from library.tests.pdfs import make_pdf
from library.tests.zips import build_zip, library_zip, zip_bomb
from library.zip_import import ZipImportError, extract_entry, safe_path, scan


@pytest.fixture
def archive(tmp_path):
    def write(payload: bytes, name: str = "upload.zip"):
        path = tmp_path / name
        path.write_bytes(payload)
        return path
    return write


# -- path safety --------------------------------------------------------------- #

@pytest.mark.parametrize("hostile", [
    "../../../etc/cron.d/evil.pdf",
    "../outside.pdf",
    "/etc/passwd.pdf",
    "//absolute.pdf",
    "foo/../../bar.pdf",
    "..\\..\\windows\\system32\\evil.pdf",
    "C:\\Windows\\evil.pdf",
    "a/../../../b.pdf",
])
def test_zip_slip_paths_are_refused(hostile):
    """The classic: an entry name that escapes the extraction directory."""
    assert safe_path(hostile) is None


@pytest.mark.parametrize("name,expected", [
    ("Books/DDIA.pdf", (("Books",), "DDIA.pdf")),
    ("a/b/c/d.pdf", (("a", "b", "c"), "d.pdf")),
    ("plain.pdf", ((), "plain.pdf")),
    ("./Books/DDIA.pdf", (("Books",), "DDIA.pdf")),
    ("Books//DDIA.pdf", (("Books",), "DDIA.pdf")),
])
def test_ordinary_paths_survive(name, expected):
    assert safe_path(name) == expected


def test_absurdly_deep_paths_are_refused():
    assert safe_path("/".join(["deep"] * 40) + "/x.pdf") is None


def test_a_zip_slip_entry_is_rejected_by_the_scan(archive):
    path = archive(build_zip({
        "../../escape.pdf": make_pdf(),
        "Books/fine.pdf": make_pdf(),
    }))
    result = scan(path)
    assert [e.name for e in result.entries] == ["fine.pdf"]
    assert any("unsafe path" in r for r in result.rejected)


# -- other hostile archives ------------------------------------------------------ #

def test_symlinks_are_rejected(archive):
    """A symlink in an archive exists to make an extractor touch something else."""
    path = archive(build_zip({"Books/real.pdf": make_pdf()},
                             symlinks={"Books/sneaky.pdf": "/etc/passwd"}))
    result = scan(path)
    assert [e.name for e in result.entries] == ["real.pdf"]
    assert any("symlink" in r for r in result.rejected)


def test_a_zip_bomb_is_rejected(archive):
    path = archive(zip_bomb())
    result = scan(path)
    assert result.entries == []
    assert any("compression ratio" in r for r in result.rejected)


def test_an_entry_lying_about_its_size_is_caught(archive, tmp_path):
    """Header sizes are attacker-controlled; the write is bounded regardless."""
    path = archive(build_zip({"big.pdf": b"%PDF-" + b"x" * 5000}))
    result = scan(path)
    entry = result.entries[0]

    lying = type(entry)(name=entry.name, folder_parts=entry.folder_parts,
                        size=10, info=entry.info)
    with pytest.raises(ZipImportError, match="declared size"):
        extract_entry(path, lying, tmp_path / "out.pdf")


def test_too_many_entries_is_refused(archive):
    from library import zip_import

    payload = build_zip({f"f{i}.pdf": b"%PDF-x" for i in range(50)})
    original = zip_import.MAX_ENTRIES
    zip_import.MAX_ENTRIES = 10
    try:
        with pytest.raises(ZipImportError, match="entries"):
            scan(archive(payload))
    finally:
        zip_import.MAX_ENTRIES = original


def test_a_corrupt_archive_raises_cleanly(archive):
    with pytest.raises(ZipImportError):
        scan(archive(b"this is definitely not a zip file"))


def test_a_non_pdf_with_a_pdf_extension_is_rejected_at_extraction(archive, tmp_path):
    path = archive(build_zip({"fake.pdf": b"MZ\x90\x00 this is a windows executable"}))
    entry = scan(path).entries[0]
    with pytest.raises(ZipImportError, match="not a PDF"):
        extract_entry(path, entry, tmp_path / "out.pdf")


# -- ordinary archives ----------------------------------------------------------- #

def test_folder_structure_is_preserved(archive):
    result = scan(archive(library_zip()))
    assert {e.display_path for e in result.entries} == {
        "Books/Programming/Python/Fluent Python.pdf",
        "Books/Programming/Architecture/DDIA.pdf",
        "Books/Fiction/Dune.pdf",
    }


def test_non_pdfs_are_counted_not_imported(archive):
    result = scan(archive(build_zip({
        "Books/DDIA.pdf": make_pdf(),
        "Books/cover.jpg": b"\xff\xd8\xff",
        "Books/notes.txt": b"hello",
        "Books/book.epub": b"PK",
    })))
    assert [e.name for e in result.entries] == ["DDIA.pdf"]
    assert result.skipped_unsupported == 3


def test_macos_and_editor_junk_is_ignored(archive):
    """A ZIP made on a Mac is full of this, and none of it is a folder."""
    result = scan(archive(build_zip({
        "Books/DDIA.pdf": make_pdf(),
        "__MACOSX/Books/._DDIA.pdf": b"junk",
        "Books/.DS_Store": b"junk",
        "Books/._DDIA.pdf": b"junk",
    })))
    assert [e.name for e in result.entries] == ["DDIA.pdf"]
    assert result.skipped_unsupported == 0, "junk should be ignored, not reported"


def test_an_uncompressed_archive_is_fine(archive):
    result = scan(archive(build_zip({"Books/A.pdf": make_pdf()},
                                    compression=zipfile.ZIP_STORED)))
    assert len(result.entries) == 1


def test_extraction_writes_the_pdf(archive, tmp_path):
    path = archive(library_zip())
    entry = next(e for e in scan(path).entries if e.name == "DDIA.pdf")
    written = extract_entry(path, entry, tmp_path / "out" / "DDIA.pdf")
    assert written > 0
    assert (tmp_path / "out" / "DDIA.pdf").read_bytes().startswith(b"%PDF-")


def test_an_empty_archive_yields_nothing(archive):
    assert scan(archive(build_zip({}))).entries == []
