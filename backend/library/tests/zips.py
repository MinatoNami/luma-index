"""Builds ZIP archives for tests, including malicious ones."""

from __future__ import annotations

import io
import zipfile

from .pdfs import make_pdf


def build_zip(entries: dict[str, bytes], *, symlinks: dict[str, str] | None = None,
              compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
        for name, target in (symlinks or {}).items():
            info = zipfile.ZipInfo(name)
            # 0xA1FF0000 sets S_IFLNK in the Unix mode bits.
            info.external_attr = 0xA1FF0000
            archive.writestr(info, target)
    return buffer.getvalue()


def library_zip() -> bytes:
    """The tree from PRD §10, as an archive."""
    return build_zip({
        "Books/Programming/Python/Fluent Python.pdf": make_pdf(pages=2),
        "Books/Programming/Architecture/DDIA.pdf": make_pdf(pages=3),
        "Books/Fiction/Dune.pdf": make_pdf(pages=1),
    })


def zip_bomb(*, size: int = 40 * 1024 * 1024) -> bytes:
    """Highly compressible padding masquerading as a PDF."""
    return build_zip({"bomb.pdf": b"%PDF-" + b"\0" * size})
