"""Light -> dark, the way the app does it: swap tokens, change nothing else.

Every pair below is lifted from frontend/assets/css/tokens.css. Two things are
deliberately not themed: cover artwork (it is artwork, not surface) and a
rendered PDF page (PDF.js paints the real document, which is white paper).
"""

import glob
import pathlib

SHADOWS = [
    ("0 8px 16px rgb(28 27 24 / 8%), 0 16px 40px rgb(28 27 24 / 12%)",
     "0 12px 32px rgb(0 0 0 / 55%)"),
    ("0 2px 4px rgb(28 27 24 / 6%), 0 4px 12px rgb(28 27 24 / 8%)",
     "0 2px 8px rgb(0 0 0 / 45%)"),
    ("0 1px 2px rgb(28 27 24 / 6%), 0 1px 3px rgb(28 27 24 / 4%)",
     "0 1px 2px rgb(0 0 0 / 40%)"),
]

# White means two different things; the property tells them apart.
CONTEXTUAL = [
    ("background: #FFFFFF", "background: #1D1C20"),
    ("color: #FFFFFF", "color: #14131A"),
    ('stroke="#FFFFFF"', 'stroke="#14131A"'),
    ("rgb(255 255 255 / 92%)", "rgb(29 28 32 / 92%)"),
]

TOKENS = [
    ("#F7F6F3", "#151417"), ("#EFEDE8", "#111013"), ("#F2F0EB", "#26252C"),
    ("#DFDCD4", "#2E2C33"), ("#8C887D", "#6E6978"),
    ("#1C1B18", "#F2F0EC"), ("#57534B", "#B3AEA6"), ("#7A756B", "#8B8680"),
    ("#4B4ACF", "#8E8CFF"), ("#4140B8", "#9E9CFF"), ("#3F3EB8", "#A5A3FF"),
    ("#EDEDFB", "#24233A"), ("#8A5A00", "#E8B45C"), ("#1F6F43", "#6FD79B"),
]

PAPER = "KEEP_PAPER_WHITE"

PAIRS = [("Main", "MainDark"), ("Home", "HomeDark"), ("Reader", "ReaderDark"),
         ("BookDetail", "BookDetailDark"), ("Phone", "PhoneDark")]

for src, dst in PAIRS:
    s = pathlib.Path(src + ".dc.html").read_text()
    s = s.replace("width: 620px; background: #FFFFFF;",
                  "width: 620px; background: " + PAPER + ";")

    for a, b in SHADOWS + CONTEXTUAL + TOKENS:
        s = s.replace(a, b)
    s = s.replace(PAPER, "#FFFFFF")

    # Dark reads depth from borders, not shadow: a black shadow on a dark
    # ground is invisible, so the flat cards keep the border and drop it.
    s = s.replace("border-radius: 14px; box-shadow: 0 1px 2px rgb(0 0 0 / 40%);",
                  "border-radius: 14px;")
    pathlib.Path(dst + ".dc.html").write_text(s)
    print("  wrote " + dst + ".dc.html")

leaks = {}
for f in sorted(glob.glob("*Dark.dc.html")):
    text = pathlib.Path(f).read_text()
    found = [light for light, _ in TOKENS if light in text]
    if found:
        leaks[f] = found
print("  light tokens surviving in dark files: " + (str(leaks) if leaks else "none"))
