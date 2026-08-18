from __future__ import annotations

import pytest

from library.documents import (
    THUMBNAIL_WIDTH,
    DocumentEncrypted,
    DocumentError,
    probe,
    render_thumbnail,
    thumbnail_size,
)

from .pdfs import write_pdf


@pytest.fixture
def pdf(tmp_path):
    return write_pdf(tmp_path / "book.pdf", pages=3)


def test_probe_counts_pages(tmp_path):
    assert probe(write_pdf(tmp_path / "a.pdf", pages=7)).page_count == 7


def test_probe_detects_a_text_layer(pdf):
    assert probe(pdf).has_text_layer is True


def test_probe_detects_a_scanned_document(tmp_path):
    """PRD §27: the user must be told when search is unavailable."""
    scanned = write_pdf(tmp_path / "scan.pdf", pages=4, text=None)
    info = probe(scanned)
    assert info.page_count == 4
    assert info.has_text_layer is False


def test_probe_samples_across_the_document(tmp_path):
    """A typeset cover on a scanned book must not make it look searchable."""
    from library.documents import _sample_pages

    sample = _sample_pages(900)
    assert len(sample) <= 8
    assert max(sample) > 400, f"sample stayed at the front: {sample}"


def test_probe_rejects_a_truncated_file(tmp_path):
    broken = tmp_path / "truncated.pdf"
    broken.write_bytes(write_pdf(tmp_path / "src.pdf").read_bytes()[:120])
    with pytest.raises(DocumentError):
        probe(broken)


def test_probe_rejects_a_file_that_is_not_a_pdf(tmp_path):
    not_pdf = tmp_path / "cover.png"
    not_pdf.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 200)
    with pytest.raises(DocumentError):
        probe(not_pdf)


def test_probe_rejects_an_empty_file(tmp_path):
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    with pytest.raises(DocumentError):
        probe(empty)


def test_render_thumbnail_produces_an_image(pdf, tmp_path):
    out = render_thumbnail(pdf, tmp_path / "thumbs" / "book.webp")
    assert out.exists() and out.stat().st_size > 0
    width, height = thumbnail_size(out)
    # Against the constant, not a literal: the width is a product decision that
    # changes with the UI, and a test should not have to be edited when it does.
    assert width == THUMBNAIL_WIDTH
    assert height > width, "A4 is taller than it is wide"


def test_thumbnail_width_is_stable_across_page_sizes(pdf, tmp_path):
    out = render_thumbnail(pdf, tmp_path / "t.webp", width=250)
    assert thumbnail_size(out)[0] == 250


def test_render_leaves_no_partial_file_on_failure(tmp_path):
    """A crash mid-render must not leave something that looks like a thumbnail."""
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4\ngarbage")
    destination = tmp_path / "thumbs" / "broken.webp"

    with pytest.raises(DocumentError):
        render_thumbnail(broken, destination)

    assert not destination.exists()
    if destination.parent.exists():
        assert list(destination.parent.iterdir()) == [], "a partial render was left behind"


def test_scanned_documents_still_get_a_thumbnail(tmp_path):
    scanned = write_pdf(tmp_path / "scan.pdf", pages=1, text=None)
    out = render_thumbnail(scanned, tmp_path / "scan.webp")
    assert out.stat().st_size > 0


def test_encrypted_pdf_raises_a_distinct_error(tmp_path):
    """Distinct so the UI can say 'password-protected' rather than 'broken'."""
    # pypdfium2 reports encryption through PdfiumError; assert the mapping
    # rather than hand-rolling an encrypted PDF.
    import pypdfium2 as pdfium

    from library import documents

    original = pdfium.PdfDocument

    class Encrypted:
        def __init__(self, *a, **k):
            raise pdfium.PdfiumError("Failed to load document (password required)")

    pdfium.PdfDocument = Encrypted
    try:
        with pytest.raises(DocumentEncrypted):
            documents.probe(tmp_path / "whatever.pdf")
    finally:
        pdfium.PdfDocument = original
