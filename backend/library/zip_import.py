"""Reading a ZIP of PDFs safely.

An uploaded archive is hostile input, and the classic ways it bites are all
quiet ones — a file written outside the target directory, a disk filled by a
few kilobytes of compressed zeroes, a symlink pointing at /etc. Every entry is
therefore validated before anything is written, and the walk is bounded on
entry count, uncompressed size, compression ratio, and path depth.

What survives the filter is the folder structure the user actually had: a
`Programming/Python/Fluent Python.pdf` entry becomes those folders and that
book.
"""

from __future__ import annotations

import logging
import posixpath
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

logger = logging.getLogger("lumaindex.zip")

PDF_MAGIC = b"%PDF-"

MAX_ENTRIES = 10_000
MAX_TOTAL_UNCOMPRESSED = 20 * 1024**3
MAX_ENTRY_UNCOMPRESSED = 2 * 1024**3
# A PDF is already compressed, so it barely shrinks. Text-like padding
# compresses enormously — which is exactly what a zip bomb is made of.
MAX_COMPRESSION_RATIO = 200
MAX_PATH_DEPTH = 16
MAX_NAME_LENGTH = 255

# Archive noise nobody wants imported as a folder.
IGNORED_PREFIXES = ("__MACOSX/", ".git/")
IGNORED_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}


class ZipImportError(Exception):
    """The archive cannot be processed at all."""


@dataclass(frozen=True)
class ZipEntry:
    """A PDF worth importing."""

    name: str                 # file name only
    folder_parts: tuple[str, ...]   # sanitised folder chain, outermost first
    size: int
    info: zipfile.ZipInfo

    @property
    def display_path(self) -> str:
        return "/".join([*self.folder_parts, self.name])


@dataclass
class ScanResult:
    entries: list[ZipEntry] = field(default_factory=list)
    skipped_unsupported: int = 0
    rejected: list[str] = field(default_factory=list)
    total_uncompressed: int = 0


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    # Unix mode lives in the top 16 bits of external_attr; 0xA000 is S_IFLNK.
    return (info.external_attr >> 16) & 0xF000 == 0xA000


def _sanitise_component(part: str) -> str | None:
    """Make one path component safe, or reject it.

    Rejecting rather than mangling: a component that needed this much cleaning
    is not something the user meant to upload.
    """
    part = part.strip().replace("\x00", "")
    if part in ("", ".", ".."):
        return None
    if part.startswith("/") or ":" in part or "\\" in part:
        return None
    # Reserved on Windows, and a nuisance on any share.
    if part.upper().split(".")[0] in {
        "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        return None
    return part[:MAX_NAME_LENGTH]


def safe_path(raw_name: str) -> tuple[tuple[str, ...], str] | None:
    """Split an archive entry into (folders, filename), or None if unsafe.

    This is the zip-slip guard. `../../etc/cron.d/x` and `/etc/passwd` both
    come back as None rather than as something a later `open()` would honour.
    """
    name = raw_name.replace("\\", "/")
    if name.startswith("/") or ".." in PurePosixPath(name).parts:
        return None

    normalised = posixpath.normpath(name)
    if normalised.startswith(("/", "../")) or normalised in (".", ".."):
        return None

    parts = [p for p in PurePosixPath(normalised).parts if p not in ("/", ".")]
    if not parts:
        return None
    if len(parts) > MAX_PATH_DEPTH:
        return None

    *folders, filename = parts
    cleaned_folders: list[str] = []
    for folder in folders:
        safe = _sanitise_component(folder)
        if safe is None:
            return None
        cleaned_folders.append(safe)

    safe_name = _sanitise_component(filename)
    if safe_name is None:
        return None

    return tuple(cleaned_folders), safe_name


def _ignored(raw_name: str) -> bool:
    if raw_name.startswith(IGNORED_PREFIXES):
        return True
    tail = raw_name.rsplit("/", 1)[-1]
    return tail in IGNORED_NAMES or tail.startswith("._")


def scan(archive_path: Path) -> ScanResult:
    """List the importable PDFs in an archive, refusing anything dangerous."""
    result = ScanResult()

    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()

            if len(infos) > MAX_ENTRIES:
                raise ZipImportError(
                    f"Archive has {len(infos)} entries; the limit is {MAX_ENTRIES}."
                )

            for info in infos:
                if info.is_dir():
                    continue
                if _ignored(info.filename):
                    continue

                if _is_symlink(info):
                    # A symlink in an archive exists to make an extractor write
                    # or read somewhere it should not.
                    result.rejected.append(f"{info.filename}: symlink")
                    continue

                if info.file_size > MAX_ENTRY_UNCOMPRESSED:
                    result.rejected.append(f"{info.filename}: entry too large")
                    continue

                if info.compress_size > 0:
                    ratio = info.file_size / info.compress_size
                    if ratio > MAX_COMPRESSION_RATIO and info.file_size > 1024**2:
                        # A real PDF barely compresses; this does not.
                        result.rejected.append(
                            f"{info.filename}: compression ratio {ratio:.0f}:1"
                        )
                        continue

                result.total_uncompressed += info.file_size
                if result.total_uncompressed > MAX_TOTAL_UNCOMPRESSED:
                    raise ZipImportError("Archive expands beyond the size limit.")

                if not info.filename.lower().endswith(".pdf"):
                    result.skipped_unsupported += 1
                    continue

                safe = safe_path(info.filename)
                if safe is None:
                    result.rejected.append(f"{info.filename}: unsafe path")
                    continue

                folders, filename = safe
                result.entries.append(
                    ZipEntry(name=filename, folder_parts=folders,
                             size=info.file_size, info=info)
                )
    except zipfile.BadZipFile as exc:
        raise ZipImportError(f"Not a readable ZIP archive: {exc}") from exc

    return result


def extract_entry(archive_path: Path, entry: ZipEntry, destination: Path) -> int:
    """Write one entry out, verifying it really is a PDF. Returns bytes written.

    The declared size is checked against what actually arrives: a ZIP header can
    claim anything, and trusting it is how the size limits get bypassed.
    """
    written = 0
    limit = min(entry.size, MAX_ENTRY_UNCOMPRESSED) + 1
    destination.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive_path) as archive, archive.open(entry.info) as source:
        head = source.read(len(PDF_MAGIC))
        if not head.startswith(PDF_MAGIC):
            raise ZipImportError(f"{entry.display_path}: not a PDF despite the extension")

        with destination.open("wb") as out:
            out.write(head)
            written += len(head)
            while chunk := source.read(1024 * 256):
                written += len(chunk)
                if written > limit:
                    raise ZipImportError(
                        f"{entry.display_path}: larger than its declared size"
                    )
                out.write(chunk)

    return written
