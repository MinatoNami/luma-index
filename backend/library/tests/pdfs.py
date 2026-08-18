"""Builds real PDFs for tests.

Fixtures are genuine files rather than mocks: the point of these tests is that
pypdfium2 handles what arrives from someone's Drive, and a mock would only
confirm the code calls the functions it calls.
"""

from __future__ import annotations


def _build(objects: list[bytes]) -> bytes:
    """Assemble numbered objects into a PDF with a correct xref table."""
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


def make_pdf(pages: int = 1, *, text: str | None = "Hello LumaIndex") -> bytes:
    """A valid PDF with `pages` pages, with or without a text layer.

    `text=None` produces pages that draw a filled rectangle instead — the
    structural equivalent of a scanned page: renderable, but with nothing for
    text extraction to find.
    """
    page_ids = [3 + i * 2 for i in range(pages)]
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode(),
    ]

    for index in range(pages):
        content_id = page_ids[index] + 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 {3 + pages * 2} 0 R >> >> >>".encode()
        )
        if text is None:
            stream = b"0.2 0.2 0.2 rg 60 60 470 720 re f"
        else:
            body = f"{text} page {index + 1}".replace("(", "").replace(")", "")
            stream = f"BT /F1 24 Tf 60 700 Td ({body}) Tj ET".encode()
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )

    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    return _build(objects)


def write_pdf(path, pages: int = 1, *, text: str | None = "Hello LumaIndex"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(make_pdf(pages, text=text))
    return path
