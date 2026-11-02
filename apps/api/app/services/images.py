"""Pictures for vision models. The original is always kept; a picture that is too big for
the model (longest side or bytes) gets a downscaled copy, made in a separate process
(PyAV/FFmpeg) with a time limit and, on Linux, a memory limit — so a hostile or huge
file can neither hang nor crash the API. Sizes are read from the file headers first;
pictures with more than CHAT_IMAGE_MAX_PIXELS pixels are never decoded.

    python -m app.services.images SRC DST FORMAT MAX_SIDE MAX_BYTES MEMORY_BYTES
"""

from __future__ import annotations

import asyncio
import json
import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import Settings

# Our sniffed media type → FFmpeg demuxer.
DEMUXERS = {
    "image/png": "png_pipe",
    "image/jpeg": "jpeg_pipe",
    "image/gif": "gif",
    "image/webp": "webp_pipe",
}


def image_size(head: bytes, media: str) -> tuple[int, int] | None:
    """(width, height) from the first bytes of a PNG, GIF, WebP or JPEG; None if unclear."""
    try:
        if media == "image/png" and head[12:16] == b"IHDR":
            w, h = struct.unpack(">II", head[16:24])
            return int(w), int(h)
        if media == "image/gif":
            w, h = struct.unpack("<HH", head[6:10])
            return int(w), int(h)
        if media == "image/webp":
            chunk = head[12:16]
            if chunk == b"VP8 ":
                w, h = struct.unpack("<HH", head[26:30])
                return w & 0x3FFF, h & 0x3FFF
            if chunk == b"VP8L":
                bits = int.from_bytes(head[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
            if chunk == b"VP8X":
                w = int.from_bytes(head[24:27], "little") + 1
                h = int.from_bytes(head[27:30], "little") + 1
                return w, h
            return None
        if media == "image/jpeg":
            return _jpeg_size(head)
    except struct.error:
        return None
    return None


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
            i += 1 if marker == 0xFF else 2
            continue
        length = int.from_bytes(data[i + 2 : i + 4], "big")
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h = int.from_bytes(data[i + 5 : i + 7], "big")
            w = int.from_bytes(data[i + 7 : i + 9], "big")
            return w, h
        i += 2 + length
    return None


@dataclass(frozen=True)
class ModelCopy:
    path: Path
    media_type: str
    width: int
    height: int


class ImageNotUsable(Exception):
    """The picture cannot be prepared for the model (the reason is safe to show)."""


async def make_model_copy(src: Path, dst: Path, media: str, settings: Settings) -> ModelCopy:
    """Write a downscaled copy of `src` to `dst` (+ extension); runs in a child process."""
    memory = max(1 << 30, settings.chat_image_max_pixels * 16 + (512 << 20))
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.services.images",
        str(src),
        str(dst),
        DEMUXERS[media],
        str(settings.chat_image_model_max_side),
        str(settings.chat_image_model_max_bytes),
        str(memory),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        # No secrets for the decoder: a hostile picture must not be able to read them.
        env={"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    try:
        out, _ = await asyncio.wait_for(
            proc.communicate(), timeout=settings.chat_image_timeout_seconds
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise ImageNotUsable("preparing the picture took too long") from None
    try:
        result = json.loads(out or b"{}")
    except ValueError:
        result = {}
    if proc.returncode != 0 or "path" not in result:
        raise ImageNotUsable(str(result.get("error") or "the picture could not be decoded"))
    return ModelCopy(Path(result["path"]), result["media_type"], result["width"], result["height"])


# --- child process ---------------------------------------------------------------------


def _encode(frame: Any, codec: str, pix_fmt: str, quality: int | None) -> bytes:
    import fractions

    import av

    ctx: Any = av.CodecContext.create(codec, "w")
    ctx.width, ctx.height, ctx.pix_fmt = frame.width, frame.height, pix_fmt
    ctx.time_base = fractions.Fraction(1, 25)
    if quality is not None:
        ctx.options = {"qmin": str(quality), "qmax": str(quality)}
    packets = [*ctx.encode(frame), *ctx.encode(None)]
    return b"".join(bytes(p) for p in packets)


_ALPHA = {"rgba", "bgra", "argb", "abgr", "ya8", "pal8", "rgba64be", "rgba64le", "yuva420p"}


def _downscale(
    src: str, dst: str, demuxer: str, max_side: int, max_bytes: int
) -> dict[str, object]:
    import av

    with av.open(src, format=demuxer) as container:
        frame = next(container.decode(video=0))  # the first frame of an animation
    width, height = frame.width, frame.height
    alpha = frame.format.name in _ALPHA
    side = min(max_side, max(width, height))
    for _ in range(8):
        scale = side / max(width, height)
        w, h = max(1, round(width * scale)), max(1, round(height * scale))
        tries: list[tuple[str, str, int | None, str, str]] = []
        if alpha:  # keep transparency when the PNG fits; else a JPEG on black
            tries.append(("png", "rgba", None, "image/png", ".png"))
        tries += [("mjpeg", "yuvj420p", q, "image/jpeg", ".jpg") for q in (3, 6, 10)]
        for codec, pix_fmt, quality, media, ext in tries:
            small = frame.reformat(width=w, height=h, format=pix_fmt, interpolation="AREA")
            data = _encode(small, codec, pix_fmt, quality)
            if len(data) <= max_bytes:
                out = Path(dst + ext)
                out.write_bytes(data)
                return {"path": str(out), "media_type": media, "width": w, "height": h}
        side = int(side * 0.75)
    return {"error": "the picture stays too large even when made smaller"}


def main(argv: list[str]) -> int:
    src, dst, demuxer, max_side, max_bytes, memory = argv[1:7]
    try:
        import resource

        limit = int(memory)
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ImportError, ValueError, OSError):
        pass  # not on Linux: the time limit still applies
    try:
        result = _downscale(src, dst, demuxer, int(max_side), int(max_bytes))
    except Exception:  # noqa: BLE001 — any decoder failure = not usable
        result = {"error": "the picture could not be decoded"}
    print(json.dumps(result))
    return 0 if "path" in result else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
