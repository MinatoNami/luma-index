"""Generates a demo library of public-domain books.

Exists so the screenshots in the README can be regenerated rather than being
artefacts nobody can reproduce. Every title here is public domain; the point is
a library that looks like a library without publishing anyone's real one.

Run it against a *scratch* instance, never a real library:

    docker compose -p lumaindex-demo exec -T backend \
        python manage.py shell < scripts/demo_library.py
"""

from __future__ import annotations

import textwrap

# ---------------------------------------------------------------------------
# A minimal PDF writer. Raw construction rather than a dependency: the backend
# only ever *reads* PDFs, and adding reportlab to generate fixtures would be a
# production dependency carried for a screenshot.
# ---------------------------------------------------------------------------

PAGE_W, PAGE_H = 595, 842
MARGIN, LEADING, BODY_SIZE = 82, 21.0, 12.5


def _esc(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _text_ops(lines: list[tuple[str, int, float]],
              *, fill: tuple[float, float, float] | None = None,
              ink: tuple[float, float, float] = (0, 0, 0)) -> bytes:
    """lines: (text, font_size, y). `fill` paints the whole page first."""
    out = []
    if fill is not None:
        r, g, b = fill
        out.append(f"{r:.3f} {g:.3f} {b:.3f} rg 0 0 {PAGE_W} {PAGE_H} re f")
    r, g, b = ink
    out.append(f"{r:.3f} {g:.3f} {b:.3f} rg")
    for text, size, y in lines:
        out.append(
            f"BT /F1 {size} Tf {MARGIN} {y:.1f} Td ({_esc(text)}) Tj ET"
        )
    # cp1252, matching /WinAnsiEncoding above: latin-1 has no em-dash or
    # curly quote, so every one became a literal "?" on the page.
    return "\n".join(out).encode("cp1252", "replace")


def build_pdf(title: str, author: str, body: list[str], pages: int,
              tint: tuple[float, float, float] = (0.16, 0.18, 0.30)) -> bytes:
    """A designed cover followed by wrapped body text, with page numbers.

    The cover is a full-bleed colour rather than a white page: at thumbnail
    size a white first page reads as a missing cover, which is exactly the
    state the grid uses to mean "still loading".
    """
    measure = 64
    wrapped: list[str] = []
    for para in body:
        chunk = textwrap.wrap(para, width=measure,
                              initial_indent="    ", break_long_words=False)
        wrapped.extend(chunk)
        wrapped.append("")
    lines_per_page = int((PAGE_H - 2 * MARGIN) / LEADING) - 2

    sheets: list[bytes] = []

    # Cover.
    mid = PAGE_H / 2
    head = textwrap.wrap(title, width=22)[:3]
    cover: list[tuple[str, int, float]] = []
    y = mid + 90
    for line in head:
        cover.append((line, 30, y))
        y -= 38
    cover.append((author.upper(), 12, y - 26))
    cover.append(("LUMAINDEX DEMO LIBRARY - PUBLIC DOMAIN", 8, MARGIN))
    sheets.append(_text_ops(cover, fill=tint, ink=(0.97, 0.96, 0.93)))

    # Body pages, cycling the text so every page is full.
    cursor = 0
    for sheet in range(1, pages):
        page_lines: list[tuple[str, int, float]] = []
        y = PAGE_H - MARGIN
        for _ in range(lines_per_page):
            if not wrapped:
                break
            page_lines.append((wrapped[cursor % len(wrapped)], BODY_SIZE, y))
            cursor += 1
            y -= LEADING
        page_lines.append((str(sheet), 9, MARGIN - 24))
        sheets.append(_text_ops(page_lines))

    # Assemble: catalog, pages node, font, then a page + content pair each.
    objects: list[bytes] = [b"", b"", b""]
    page_ids = [4 + i * 2 for i in range(len(sheets))]
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = (f"<< /Type /Pages /Count {len(sheets)} /Kids "
                  f"[{' '.join(f'{p} 0 R' for p in page_ids)}] >>").encode()
    objects[2] = (b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman "
                  b"/Encoding /WinAnsiEncoding >>")

    for index, ops in enumerate(sheets):
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
            f"/Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {page_ids[index] + 1} 0 R >>".encode()
        )
        objects.append(b"<< /Length " + str(len(ops)).encode() + b" >>\nstream\n"
                       + ops + b"\nendstream")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body_bytes in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body_bytes + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n").encode()
    return bytes(out)


# ---------------------------------------------------------------------------
# The demo library itself. Public-domain works only, with their real opening
# lines, so a screenshot of the reader shows a page of actual prose.
# ---------------------------------------------------------------------------

OPENINGS = {
    "pride": [
        "It is a truth universally acknowledged, that a single man in "
        "possession of a good fortune, must be in want of a wife. However "
        "little known the feelings or views of such a man may be on his first "
        "entering a neighbourhood, this truth is so well fixed in the minds of "
        "the surrounding families, that he is considered the rightful property "
        "of some one or other of their daughters.",
    ],
    "moby": [
        "Call me Ishmael. Some years ago\u2014never mind how long precisely"
        "\u2014having little or no money in my purse, and nothing particular to "
        "interest me on shore, I thought I would sail about a little and see "
        "the watery part of the world. It is a way I have of driving off the "
        "spleen and regulating the circulation.",
        "There now is your insular city of the Manhattoes, belted round by "
        "wharves as Indian isles by coral reefs\u2014commerce surrounds it with "
        "her surf. Right and left, the streets take you waterward.",
    ],
    "time": [
        "The Time Traveller (for so it will be convenient to speak of him) was "
        "expounding a recondite matter to us. His pale grey eyes shone and "
        "twinkled, and his usually pale face was flushed and animated.",
    ],
    "frank": [
        "You will rejoice to hear that no disaster has accompanied the "
        "commencement of an enterprise which you have regarded with such evil "
        "forebodings. I arrived here yesterday; and my first task is to assure "
        "my dear sister of my welfare, and increasing confidence in the success "
        "of my undertaking.",
    ],
    "alice": [
        "Alice was beginning to get very tired of sitting by her sister on the "
        "bank, and of having nothing to do: once or twice she had peeped into "
        "the book her sister was reading, but it had no pictures or "
        "conversations in it, and what is the use of a book, thought Alice, "
        "without pictures or conversations?",
    ],
    "walden": [
        "When I wrote the following pages, or rather the bulk of them, I lived "
        "alone, in the woods, a mile from any neighbor, in a house which I had "
        "built myself, on the shore of Walden Pond, in Concord, Massachusetts, "
        "and earned my living by the labor of my hands only.",
    ],
    "medit": [
        "Begin the morning by saying to thyself, I shall meet with the busybody, "
        "the ungrateful, arrogant, deceitful, envious, unsocial. All these "
        "things happen to them by reason of their ignorance of what is good and "
        "evil.",
    ],
    "war": [
        "The art of war is of vital importance to the State. It is a matter of "
        "life and death, a road either to safety or to ruin. Hence it is a "
        "subject of inquiry which can on no account be neglected.",
    ],
    "dracula": [
        "Left Munich at 8:35 P.M., on 1st May, arriving at Vienna early next "
        "morning; should have arrived at 6:46, but train was an hour late. "
        "Buda-Pesth seems a wonderful place, from the glimpse which I got of it "
        "from the train.",
    ],
    "willows": [
        "The Mole had been working very hard all the morning, spring-cleaning "
        "his little home. First with brooms, then with dusters; then on ladders "
        "and steps and chairs, with a brush and a pail of whitewash; till he "
        "had dust in his throat and eyes.",
    ],
    "holmes": [
        "To Sherlock Holmes she is always the woman. I have seldom heard him "
        "mention her under any other name. In his eyes she eclipses and "
        "predominates the whole of her sex.",
    ],
    "view": [
        "The Signora had no business to do it, said Miss Bartlett, no business "
        "at all. She promised us south rooms with a view, close together, "
        "instead of which here are north rooms, looking into a courtyard, and a "
        "long way apart.",
    ],
}

# Muted, distinguishable spine colours — a library shelf rather than a palette.
TINTS = {
    "pride":   (0.42, 0.24, 0.30), "moby":    (0.13, 0.26, 0.35),
    "time":    (0.20, 0.28, 0.24), "frank":   (0.24, 0.20, 0.32),
    "alice":   (0.52, 0.34, 0.16), "walden":  (0.18, 0.32, 0.28),
    "medit":   (0.28, 0.26, 0.22), "war":     (0.38, 0.20, 0.18),
    "dracula": (0.16, 0.14, 0.18), "willows": (0.24, 0.34, 0.20),
    "holmes":  (0.20, 0.24, 0.36), "view":    (0.44, 0.30, 0.22),
}

LIBRARY = [
    ("Fiction", [
        ("Pride and Prejudice", "Jane Austen", "pride", 62),
        ("Moby-Dick; or, The Whale", "Herman Melville", "moby", 94),
        ("Dracula", "Bram Stoker", "dracula", 78),
        ("A Room with a View", "E. M. Forster", "view", 54),
    ]),
    ("Science Fiction", [
        ("The Time Machine", "H. G. Wells", "time", 48),
        ("Frankenstein; or, The Modern Prometheus", "Mary Shelley", "frank", 71),
    ]),
    ("Philosophy", [
        ("Meditations", "Marcus Aurelius", "medit", 66),
        ("The Art of War", "Sun Tzu", "war", 32),
    ]),
    ("Nature Writing", [
        ("Walden", "Henry David Thoreau", "walden", 83),
        ("The Wind in the Willows", "Kenneth Grahame", "willows", 57),
    ]),
    (None, [
        ("Alice's Adventures in Wonderland", "Lewis Carroll", "alice", 41),
        ("The Adventures of Sherlock Holmes", "Arthur Conan Doyle", "holmes", 69),
    ]),
]

DEMO_EMAIL = "reader@lumaindex.demo"


def seed() -> None:
    import secrets

    from django.contrib.auth import get_user_model
    from django.core.files.uploadedfile import SimpleUploadedFile

    from library.models import Book, Folder
    from library.services import store_upload

    User = get_user_model()
    if Book.objects.exists():
        print(f"REFUSING: this instance already holds {Book.objects.count()} "
              f"books. Seed a scratch instance only.")
        return

    user, made = User.objects.get_or_create(
        email=DEMO_EMAIL, defaults={"is_staff": True, "is_superuser": True})
    if made:
        user.set_password(secrets.token_urlsafe(32))
        user.save()

    for folder_name, books in LIBRARY:
        folder = None
        if folder_name:
            folder, _ = Folder.objects.get_or_create(owner=user, parent=None,
                                                     name=folder_name)
        for title, author, key, pages in books:
            pdf = build_pdf(title, author, OPENINGS[key], pages,
                            tint=TINTS[key])
            name = title.lower().replace(" ", "-").replace(";", "")[:60] + ".pdf"
            book, _ = store_upload(
                user,
                SimpleUploadedFile(name, pdf, content_type="application/pdf"),
                folder=folder,
            )
            book.title = f"{title} — {author}"
            book.save(update_fields=["title"])

    print(f"SEEDED {Book.objects.count()} books in "
          f"{Folder.objects.count()} folders for {user.email}")


seed()
