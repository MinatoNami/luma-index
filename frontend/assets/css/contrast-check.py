"""Check the palette in tokens.css against WCAG AA.

Run it after changing a colour:

    python3 frontend/assets/css/contrast-check.py

Body and secondary text need 4.5:1; the strong border needs 3:1 because input
outlines are non-text UI components (WCAG 1.4.11). Exits non-zero on a failure
so it can go in CI when the palette settles.
"""

def srgb_to_linear(c):
    c = c / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def luminance(hex_colour):
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4))
    return 0.2126 * srgb_to_linear(r) + 0.7152 * srgb_to_linear(g) + 0.0722 * srgb_to_linear(b)

def ratio(a, b):
    la, lb = luminance(a), luminance(b)
    lo, hi = sorted((la, lb))
    return (hi + 0.05) / (lo + 0.05)

# Warm-neutral paper base, indigo accent. Reading apps want low glare, so the
# light background is off-white and the dark one is a deep neutral, not black.
LIGHT = {
    "bg":            "#F7F6F3",
    "surface":       "#FFFFFF",
    "surface_sunken":"#EFEDE8",
    "border":        "#DFDCD4",
    "border_strong": "#8C887D",
    "text":          "#1C1B18",
    "text_secondary":"#57534B",
    "text_tertiary": "#7A756B",
    "accent":        "#4B4ACF",
    "accent_text":   "#3F3EB8",
    "on_accent":     "#FFFFFF",
    "danger":        "#B3261E",
    "danger_text":   "#A21B14",
    "success":       "#1F6F43",
    "warning":       "#8A5A00",
    "focus":         "#4B4ACF",
}

DARK = {
    "bg":            "#151417",
    "surface":       "#1D1C20",
    "surface_sunken":"#111013",
    "border":        "#2E2C33",
    "border_strong": "#6E6978",
    "text":          "#F2F0EC",
    "text_secondary":"#B3AEA6",
    "text_tertiary": "#8B8680",
    "accent":        "#8E8CFF",
    "accent_text":   "#A5A3FF",
    "on_accent":     "#14131A",
    "danger":        "#FF8A80",
    "danger_text":   "#FF9E95",
    "success":       "#6FD79B",
    "warning":       "#E8B45C",
    "focus":         "#8E8CFF",
}

CHECKS = [
    ("body text",           "text",           "bg",       4.5),
    ("body text on surface","text",           "surface",  4.5),
    ("secondary text",      "text_secondary", "bg",       4.5),
    ("secondary on surface","text_secondary", "surface",  4.5),
    ("tertiary text",       "text_tertiary",  "surface",  3.0),
    ("link / accent text",  "accent_text",    "bg",       4.5),
    ("link on surface",     "accent_text",    "surface",  4.5),
    ("text on accent fill", "on_accent",      "accent",   4.5),
    ("danger text",         "danger_text",    "surface",  4.5),
    ("success text",        "success",        "surface",  4.5),
    ("warning text",        "warning",        "surface",  4.5),
    ("border visibility",   "border",         "surface",  1.2),
    ("strong border",       "border_strong",  "surface",  3.0),
    ("focus ring",          "focus",          "bg",       3.0),
]

failed = 0
for label, palette in (("LIGHT", LIGHT), ("DARK", DARK)):
    print(f"\n{label}")
    print("-" * 58)
    for name, fg, bg, minimum in CHECKS:
        r = ratio(palette[fg], palette[bg])
        ok = r >= minimum
        failed += not ok
        mark = "ok " if ok else "FAIL"
        print(f"  {mark} {name:22} {r:5.2f}:1  (need {minimum})")

print(f"\n{failed} failure(s)")
raise SystemExit(1 if failed else 0)
