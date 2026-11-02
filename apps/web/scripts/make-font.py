"""The heading font "Moloko Pixel", drawn for moloko after the lettering of the owner's logo.

Reads the glyph bitmaps from assets/brand/moloko-pixel.txt (the format is described at the top of
that file) and writes app/fonts/MolokoPixel.woff2. Re-run after editing the bitmaps (from apps/web):

    uv run --with fonttools==4.67.0 --with brotli==1.2.0 python scripts/make-font.py

One design pixel is one unit of the logo's lettering (its strokes are 4 pixels thick). The em is
24 pixels, so at the size of page titles (text-2xl, 24 px) every design pixel is one CSS pixel,
and at 48 px it is two.
"""

import re
import sys
from pathlib import Path

from fontTools.agl import UV2AGL
from fontTools.fontBuilder import FontBuilder
from fontTools.misc.timeTools import timestampFromString
from fontTools.pens.ttGlyphPen import TTGlyphPen

WEB = Path(__file__).resolve().parent.parent
SOURCE = WEB / "assets/brand/moloko-pixel.txt"
OUTPUT = WEB / "app/fonts/MolokoPixel.woff2"

FAMILY = "Moloko Pixel"
VERSION = "1.000"
CREATED = "Mon Nov 02 00:00:00 2026"  # fixed, so the same bitmaps always give the same file

PX = 50  # font units per design pixel
EM = 24  # design pixels per em
X_HEIGHT = 13  # the logo's lowercase: o is 12 × 13 pixels
CAP_HEIGHT = 17  # = the ascender of the logo's l and k
# Line metrics in em are those of the previous heading font (Tiny5: 0.875 + 0.25), so line boxes
# and baselines stay where they were. Ё and Й reach exactly the ascent; descenders stay within 5.
ASCENT = 21
DESCENT = 6
SIDE = 1  # blank pixels left and right of every glyph: letters stand 2 pixels apart, as in the logo

INK, BLANK, BASELINE = "#", ".", "-"

# Everything the app's headings may show: printable ASCII, Russian, and the typographic extras.
REQUIRED = (
    [*range(0x20, 0x7F)]
    + [*range(0x410, 0x450), 0x401, 0x451]
    + [ord(c) for c in "«»—–…№“”„‘’·×°₽₸€"]
)


def parse(text: str) -> list[tuple[list[int], list[str], int]]:
    """Glyphs as (code points, rows top to bottom, number of rows below the baseline)."""
    glyphs: list[tuple[list[int], list[str], int]] = []
    errors: list[str] = []
    current: tuple[list[int], list[str], int] | None = None
    header_line = 0

    def finish() -> None:
        if current is None:
            return
        codes, rows, _ = current
        name = " ".join(f"U+{c:04X}" for c in codes)
        if not rows:
            errors.append(f"line {header_line}: {name} has no rows")
            return
        widths = {len(r) for r in rows}
        if len(widths) != 1:
            errors.append(f"line {header_line}: {name} rows have different widths {sorted(widths)}")
            return
        marks = [i for i, r in enumerate(rows) if set(r) == {BASELINE}]
        if len(marks) > 1:
            errors.append(f"line {header_line}: {name} has more than one baseline row")
            return
        below = 0
        if marks:
            below = len(rows) - marks[0] - 1
            rows = rows[: marks[0]] + rows[marks[0] + 1 :]
        if any(set(r) - {INK, BLANK} for r in rows):
            errors.append(f"line {header_line}: {name} uses characters other than '{INK}' and '{BLANK}'")
            return
        glyphs.append((codes, rows, below))

    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("=="):
            finish()
            codes = [int(h, 16) for h in re.findall(r"U\+([0-9A-Fa-f]{4,6})", line)]
            if not codes:
                errors.append(f"line {number}: a glyph header needs at least one U+XXXX")
            current = (codes, [], 0)
            header_line = number
            continue
        if current is None:
            errors.append(f"line {number}: a row before the first '==' header")
            continue
        current[1].append(line.strip())
    finish()

    seen: dict[int, int] = {}
    for codes, _, _ in glyphs:
        for code in codes:
            if code in seen:
                errors.append(f"U+{code:04X} is drawn twice")
            seen[code] = 1
    missing = [c for c in REQUIRED if c not in seen]
    if missing:
        errors.append("missing: " + " ".join(f"U+{c:04X} {chr(c)}" for c in missing))
    if errors:
        sys.exit("moloko-pixel.txt:\n  " + "\n  ".join(errors))
    return glyphs


def outline(rows: list[str], below: int) -> list[list[tuple[int, int]]]:
    """The union of the ink pixels as closed orthogonal contours, in pixel coordinates (y up).

    Each pixel side between ink and blank becomes an edge directed so that the ink is on its right:
    outer contours then run clockwise and holes counter-clockwise, as TrueType wants. The edges are
    chained into loops; where two pixels touch only at a corner, the walk turns right, so the loops
    meet at that point without crossing. Points in the middle of a straight run are dropped.
    """
    height = len(rows)
    ink = {(x, height - below - 1 - r) for r, row in enumerate(rows) for x, c in enumerate(row) if c == INK}
    edges: dict[tuple[int, int], list[tuple[int, int]]] = {}

    def add(a: tuple[int, int], b: tuple[int, int]) -> None:
        edges.setdefault(a, []).append(b)

    for x, y in ink:
        if (x, y + 1) not in ink:
            add((x, y + 1), (x + 1, y + 1))  # top, left to right
        if (x + 1, y) not in ink:
            add((x + 1, y + 1), (x + 1, y))  # right, downwards
        if (x, y - 1) not in ink:
            add((x + 1, y), (x, y))  # bottom, right to left
        if (x - 1, y) not in ink:
            add((x, y), (x, y + 1))  # left, upwards

    def right_turn_rank(incoming: tuple[int, int], outgoing: tuple[int, int]) -> int:
        # Prefer a right turn, then straight on, then a left turn.
        ix, iy = incoming
        ox, oy = outgoing
        if (ox, oy) == (iy, -ix):
            return 0
        if (ox, oy) == (ix, iy):
            return 1
        return 2

    contours: list[list[tuple[int, int]]] = []
    while edges:
        start = min(edges)  # lowest x, then lowest y: deterministic
        loop = [start]
        point = start
        direction: tuple[int, int] | None = None
        while True:
            targets = edges[point]
            if direction is not None and len(targets) > 1:
                targets.sort(key=lambda t: right_turn_rank(direction, (t[0] - point[0], t[1] - point[1])))
            nxt = targets.pop(0)
            if not targets:
                del edges[point]
            direction = (nxt[0] - point[0], nxt[1] - point[1])
            point = nxt
            if point == start:
                break
            loop.append(point)
        contours.append(simplify(loop))
    return contours


def simplify(loop: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Drop points that lie on a straight line between their neighbours."""
    out = []
    n = len(loop)
    for i, (x, y) in enumerate(loop):
        px, py = loop[i - 1]
        nx, ny = loop[(i + 1) % n]
        if (px == x == nx) or (py == y == ny):
            continue
        out.append((x, y))
    return out


def glyph_name(code: int) -> str:
    if code == 0x20:
        return "space"
    return UV2AGL.get(code, f"uni{code:04X}") if code < 0x80 else f"uni{code:04X}"


def to_glyph(contours: list[list[tuple[int, int]]]):
    """A TrueType glyph from pixel contours, shifted right by the side bearing."""
    pen = TTGlyphPen(None)
    for loop in contours:
        pen.moveTo(((loop[0][0] + SIDE) * PX, loop[0][1] * PX))
        for x, y in loop[1:]:
            pen.lineTo(((x + SIDE) * PX, y * PX))
        pen.closePath()
    return pen.glyph()


def build(glyphs: list[tuple[list[int], list[str], int]]) -> FontBuilder:
    fb = FontBuilder(EM * PX, isTTF=True)
    fb.font.recalcTimestamp = False
    stamp = timestampFromString(CREATED)
    fb.setupHead(unitsPerEm=EM * PX, created=stamp, modified=stamp, fontRevision=float(VERSION))

    order = [".notdef"]
    cmap: dict[int, str] = {}
    outlines = {}
    metrics: dict[str, tuple[int, int]] = {}

    # .notdef: a hollow box, cap-height tall (outer clockwise, inner counter-clockwise).
    w = 9
    box = [(0, 0), (0, CAP_HEIGHT), (w, CAP_HEIGHT), (w, 0)]
    hole = [(2, 2), (w - 2, 2), (w - 2, CAP_HEIGHT - 2), (2, CAP_HEIGHT - 2)]
    outlines[".notdef"] = to_glyph([box, hole])
    metrics[".notdef"] = ((w + 2 * SIDE) * PX, SIDE * PX)

    for codes, rows, below in glyphs:
        name = glyph_name(codes[0])
        order.append(name)
        for code in codes:
            cmap[code] = name
        contours = outline(rows, below)
        outlines[name] = to_glyph(contours)
        left = min((x for loop in contours for x, _ in loop), default=-SIDE)
        metrics[name] = ((len(rows[0]) + 2 * SIDE) * PX, (left + SIDE) * PX)

    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(outlines)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=ASCENT * PX, descent=-DESCENT * PX, lineGap=0)
    fb.setupNameTable(
        {
            "copyright": "Copyright 2026 the moloko project. Drawn for moloko after the owner's logo.",
            "familyName": FAMILY,
            "styleName": "Regular",
            "uniqueFontIdentifier": f"{VERSION};MOLOKO;MolokoPixel-Regular",
            "fullName": f"{FAMILY} Regular",
            "version": f"Version {VERSION}",
            "psName": "MolokoPixel-Regular",
        }
    )
    glyf = fb.font["glyf"]
    y_max = max(glyf[n].yMax for n in order if glyf[n].numberOfContours)
    y_min = min(glyf[n].yMin for n in order if glyf[n].numberOfContours)
    fb.setupOS2(
        version=4,
        usWeightClass=400,
        fsType=0,
        fsSelection=0b11000000,  # REGULAR + USE_TYPO_METRICS
        achVendID="NONE",
        sTypoAscender=ASCENT * PX,
        sTypoDescender=-DESCENT * PX,
        sTypoLineGap=0,
        usWinAscent=max(ASCENT * PX, y_max),
        usWinDescent=max(DESCENT * PX, -y_min),
        sxHeight=X_HEIGHT * PX,
        sCapHeight=CAP_HEIGHT * PX,
        usDefaultChar=0,
        usBreakChar=0x20,
        usMaxContext=0,
    )
    fb.setupPost(underlinePosition=-2 * PX, underlineThickness=2 * PX)
    os2 = fb.font["OS/2"]
    os2.recalcAvgCharWidth(fb.font)
    os2.recalcUnicodeRanges(fb.font)
    os2.recalcCodePageRanges(fb.font)
    return fb


def main() -> None:
    glyphs = parse(SOURCE.read_text(encoding="utf-8"))
    fb = build(glyphs)
    fb.font.flavor = "woff2"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fb.save(OUTPUT)
    drawn = len(fb.font.getGlyphOrder()) - 1  # without .notdef
    chars = len(fb.font.getBestCmap())
    print(f"{OUTPUT.relative_to(WEB)}  {drawn} glyphs, {chars} characters, {OUTPUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
