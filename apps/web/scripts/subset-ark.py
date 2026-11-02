"""Body and code fonts: Ark Pixel 12px (TakWolf, SIL OFL 1.1), subset to what moloko shows.

Downloads the pinned release, checks its SHA-256, keeps Latin + Cyrillic + punctuation,
currency signs, arrows and box drawing, and writes self-hosted WOFF2 files plus the licence
to app/fonts. Re-run after changing the version or the character set (from apps/web):

    uv run --with fonttools==4.67.0 --with brotli==1.2.0 python scripts/subset-ark.py
"""

import hashlib
import io
import urllib.request
import zipfile
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

WEB = Path(__file__).resolve().parent.parent
FONTS = WEB / "app/fonts"
VERSION = "2026.10.25"
BASE = f"https://github.com/TakWolf/ark-pixel-font/releases/download/{VERSION}"
SOURCES = {
    # output file: (zip name, sha256 of the zip, font inside the zip)
    "ArkPixel12.woff2": (
        f"ark-pixel-font-12px-proportional-otf.woff2-v{VERSION}.zip",
        "a1b26a1e505bf0b04f6f8faa0f796d6e0b32a1c2539fd1295db1013f8883314e",
        "ark-pixel-12px-proportional-latin.otf.woff2",
    ),
    "ArkPixel12Mono.woff2": (
        f"ark-pixel-font-12px-monospaced-otf.woff2-v{VERSION}.zip",
        "7dd511b72fc647e9a5746cc432c805382055771c61c0de663e338fe09f07e210",
        "ark-pixel-12px-monospaced-latin.otf.woff2",
    ),
}
UNICODES = [
    *range(0x20, 0x7F),  # ASCII
    *range(0xA0, 0x100),  # Latin-1 (« » × ° …)
    *range(0x100, 0x180),  # Latin Extended-A
    *range(0x400, 0x460),  # Cyrillic (Russian)
    *range(0x490, 0x500),  # Cyrillic supplement, where the font has it
    *range(0x2010, 0x2028),  # dashes, quotes, bullet, ellipsis
    *range(0x2030, 0x203B),  # per mille, angle quotes
    0x20AC, 0x20B8, 0x20BD, 0x2116,  # € ₸ ₽ №
    *range(0x2190, 0x219A),  # arrows
    0x21E7, 0x2318, 0x2325, 0x23CE,  # ⇧ ⌘ ⌥ ⏎
    *range(0x2500, 0x2580),  # box drawing (code blocks)
    *range(0x25A0, 0x2600),  # geometric shapes ■ □ ▲ ▼ ● ◆
    0x2713, 0x2714, 0x2715, 0x2716,  # ✓ ✔ ✕ ✖
]


def fetch(name: str, sha256: str) -> zipfile.ZipFile:
    with urllib.request.urlopen(f"{BASE}/{name}", timeout=120) as response:
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != sha256:
        raise SystemExit(f"{name}: sha256 {digest} does not match the pinned {sha256}")
    return zipfile.ZipFile(io.BytesIO(data))


def main() -> None:
    FONTS.mkdir(parents=True, exist_ok=True)
    licence = None
    for out, (name, sha256, inner) in SOURCES.items():
        archive = fetch(name, sha256)
        licence = archive.read("OFL.txt")
        font = TTFont(io.BytesIO(archive.read(inner)))
        options = subset.Options()
        options.flavor = "woff2"
        options.layout_features = ["*"]
        options.name_IDs = ["*"]  # keep the copyright and licence names
        subsetter = subset.Subsetter(options)
        subsetter.populate(unicodes=UNICODES)
        subsetter.subset(font)
        font.flavor = "woff2"
        font.save(FONTS / out)
        print(f"app/fonts/{out}  {len(font.getBestCmap())} chars  {(FONTS / out).stat().st_size // 1024} KB")
    if licence:
        (FONTS / "ArkPixel-OFL.txt").write_bytes(licence)


if __name__ == "__main__":
    main()
