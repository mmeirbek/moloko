"""Brand images from the owner's logo (assets/brand/logo-source.jpg).

Writes the logo tile (cow in a meadow) and the "moloko" wordmark mask used by
components/brand/logo.tsx, plus the favicon and PWA icons. Re-run after replacing
the source image (from apps/web):

    uv run --with pillow==13.0.0 python scripts/make-brand.py
"""

from collections import deque
from pathlib import Path

from PIL import Image

WEB = Path(__file__).resolve().parent.parent
SOURCE = WEB / "assets/brand/logo-source.jpg"
BRAND = WEB / "public/brand"
ICONS = WEB / "public/icons"
NAVY = (12, 16, 36)  # the logo's night background (globals.css --background, dark)

TILE_BOX = (96, 108, 512, 518)  # the cow tile, including its dark pixel outline
WORD_BOX = (570, 220, 1226, 382)  # the wordmark "moloko"
BG_TOLERANCE = 26  # sum of channel differences still counted as background (JPEG noise)
WORD_THRESHOLD = 150  # luminance above which a pixel belongs to the cream letters
COLORS = 128  # palette size of the written PNGs


def tile_with_transparent_corners(src: Image.Image) -> Image.Image:
    """Crop the tile, square it, and make the background around its rounded corners transparent.

    A flood fill from the border removes only background connected to the outside, so the
    near-black outline (it differs from the background mostly in blue) and the scene stay.
    """
    tile = src.crop(TILE_BOX).convert("RGBA")
    w, h = tile.size
    bg = src.getpixel((4, 4))
    px = tile.load()

    def is_bg(x: int, y: int) -> bool:
        r, g, b, _ = px[x, y]
        return abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) <= BG_TOLERANCE

    seen = [[False] * h for _ in range(w)]
    queue = deque((x, y) for x in range(w) for y in (0, h - 1)) + deque((x, y) for y in range(h) for x in (0, w - 1))
    while queue:
        x, y = queue.popleft()
        if seen[x][y] or not is_bg(x, y):
            continue
        seen[x][y] = True
        px[x, y] = (0, 0, 0, 0)
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not seen[nx][ny]:
                queue.append((nx, ny))

    side = max(w, h)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(tile, ((side - w) // 2, (side - h) // 2))
    return square


def wordmark_mask(src: Image.Image, height: int) -> Image.Image:
    """White letters on transparency: the page tints them with the theme colour (CSS mask)."""
    word = src.crop(WORD_BOX).convert("L")
    alpha = word.point(lambda v: 255 if v >= WORD_THRESHOLD else 0)
    bbox = alpha.getbbox()
    assert bbox, "no wordmark found: check WORD_BOX"
    alpha = alpha.crop(bbox)
    width = round(alpha.width * height / alpha.height)
    alpha = alpha.resize((width, height), Image.Resampling.LANCZOS)
    mask = Image.new("RGBA", alpha.size, (255, 255, 255, 0))
    mask.putalpha(alpha)
    return mask


def on_background(tile: Image.Image, size: int, scale: float, background: tuple[int, int, int] | None) -> Image.Image:
    """`tile` scaled to `scale`·`size`, centred on a square canvas (transparent or `background`)."""
    canvas = Image.new("RGBA", (size, size), (*background, 255) if background else (0, 0, 0, 0))
    inner = round(size * scale)
    scaled = tile.resize((inner, inner), Image.Resampling.LANCZOS)
    offset = (size - inner) // 2
    canvas.alpha_composite(scaled, (offset, offset))
    return canvas


def main() -> None:
    src = Image.open(SOURCE).convert("RGB")
    BRAND.mkdir(parents=True, exist_ok=True)
    tile = tile_with_transparent_corners(src)

    outputs = {
        BRAND / "logo-tile.png": tile.resize((192, 192), Image.Resampling.LANCZOS),
        BRAND / "wordmark-mask.png": wordmark_mask(src, 96),
        ICONS / "favicon-32.png": on_background(tile, 32, 1.0, None),
        ICONS / "icon-192.png": on_background(tile, 192, 0.96, None),
        ICONS / "icon-512.png": on_background(tile, 512, 0.96, None),
        # Maskable: the launcher may crop to a circle — keep the tile inside the 80 % safe zone.
        ICONS / "maskable-512.png": on_background(tile, 512, 0.74, NAVY),
        # iOS fills transparency with black and rounds the corners itself.
        ICONS / "apple-touch-icon.png": on_background(tile, 180, 0.88, NAVY),
    }
    for path, image in outputs.items():
        if path.name != "wordmark-mask.png":
            # A palette PNG: a fraction of the size, and it also drops the JPEG noise.
            image = image.quantize(colors=COLORS, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
        image.save(path, optimize=True)
        print(f"{path.relative_to(WEB)}  {image.size[0]}×{image.size[1]}  {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
