"""Chat files on disk (FILE_STORAGE_ROOT) and the streaming upload that fills them.

An upload never sits in memory or in /tmp (a RAM disk in the container): the multipart
body is parsed as it arrives and the file part goes straight into a temporary file next
to its final place, while its SHA-256, size, first bytes and (for text) the decoded text
are computed on the way. The disk keeps CHAT_UPLOAD_MIN_FREE_BYTES free.
"""

from __future__ import annotations

import asyncio
import codecs
import hashlib
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import IO

from python_multipart.exceptions import FormParserError
from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.requests import Request

from app.core.config import Settings
from app.core.errors import AppError

HEAD_BYTES = 1 << 20  # first bytes kept for type and picture-size detection
FREE_CHECK_EVERY = 64 << 20  # re-check the free disk space this often (bytes written)
FLUSH_EVERY = 1 << 20  # hand data to the writer thread in chunks of about this size


class InvalidUpload(AppError):
    status_code = 422
    code = "invalid_attachment"
    message = "This file cannot be attached."


class AttachmentTooLarge(AppError):
    status_code = 413
    code = "attachment_too_large"
    message = "The file is larger than the limit set on this server."


class InsufficientStorage(AppError):
    status_code = 507
    code = "insufficient_storage"
    message = "The server's disk is almost full: the file was not saved."


class FileStore:
    def __init__(self, settings: Settings, root: Path | None = None) -> None:
        self.root = root if root is not None else Path(settings.file_storage_root)
        self.min_free = settings.chat_upload_min_free_bytes

    def chat_dir(self, conversation_id: uuid.UUID) -> Path:
        return self.root / "chats" / str(conversation_id)

    def resolve(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("path outside the file store")
        return path

    def relative(self, path: Path) -> str:
        return str(path.relative_to(self.root))

    def free_bytes(self) -> int:
        self.root.mkdir(parents=True, exist_ok=True)
        return shutil.disk_usage(self.root).free

    def ensure_space(self, extra: int = 0) -> None:
        if self.min_free and self.free_bytes() - extra < self.min_free:
            raise InsufficientStorage(details={"min_free_bytes": self.min_free})

    def remove_chat(self, conversation_id: uuid.UUID) -> None:
        shutil.rmtree(self.chat_dir(conversation_id), ignore_errors=True)


class TextSniffer:
    """Decodes as it goes: UTF-8 (BOM optional) or UTF-16 with a BOM. Keeps the first
    `keep` characters and counts all of them. Any NUL byte or invalid sequence = binary."""

    def __init__(self, keep: int) -> None:
        self.keep = keep
        self.is_text = True
        self.chars = 0
        self.parts: list[str] = []
        self._kept = 0
        self._pending = b""
        self._decoder: codecs.IncrementalDecoder | None = None
        self._utf8 = True

    def feed(self, data: bytes, final: bool = False) -> None:
        if not self.is_text:
            return
        if self._decoder is None:
            self._pending += data
            if len(self._pending) < 4 and not final:
                return
            data, self._pending = self._pending, b""
            if data.startswith(codecs.BOM_UTF8):
                data = data[3:]
            elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
                self._utf8 = False
            self._decoder = codecs.getincrementaldecoder("utf-8" if self._utf8 else "utf-16")()
        if self._utf8 and b"\x00" in data:
            self._binary()
            return
        try:
            text = self._decoder.decode(data, final)
        except UnicodeDecodeError:
            self._binary()
            return
        if not self._utf8 and "\x00" in text:
            self._binary()
            return
        self.chars += len(text)
        room = self.keep - self._kept
        if room > 0 and text:
            piece = text[:room]
            self.parts.append(piece)
            self._kept += len(piece)

    def _binary(self) -> None:
        self.is_text = False
        self.parts = []

    @property
    def text(self) -> str:
        return "".join(self.parts) if self.is_text else ""


class _Sink:
    """Receives the file part's bytes (called in a worker thread)."""

    def __init__(self, path: Path, store: FileStore, settings: Settings) -> None:
        self.path = path
        self.store = store
        self.max_bytes = settings.chat_attachment_max_bytes
        self.fh: IO[bytes] = path.open("xb")
        self.sha = hashlib.sha256()
        self.size = 0
        self.head = bytearray()
        self.text = TextSniffer(settings.chat_attachment_text_max_chars)
        self._next_check = FREE_CHECK_EVERY

    def write(self, data: bytes) -> None:
        self.size += len(data)
        if self.max_bytes and self.size > self.max_bytes:
            raise AttachmentTooLarge(details={"max_bytes": self.max_bytes})
        if self.size >= self._next_check:
            self.store.ensure_space()
            self._next_check = self.size + FREE_CHECK_EVERY
        self.fh.write(data)
        self.sha.update(data)
        if len(self.head) < HEAD_BYTES:
            self.head += data[: HEAD_BYTES - len(self.head)]
        self.text.feed(data)

    def finish(self) -> None:
        self.text.feed(b"", final=True)
        self.fh.flush()
        self.fh.close()

    def abort(self) -> None:
        self.fh.close()
        self.path.unlink(missing_ok=True)


@dataclass
class Received:
    path: Path  # temporary file on the same disk as the final place
    filename: str
    content_type: str
    size: int
    sha256: str
    head: bytes
    text: TextSniffer = field(repr=False)


def safe_filename(raw: str) -> str:
    name = PurePath(raw.replace("\\", "/")).name.replace("\x00", "")
    return name[:200] or "file"


def _decode(value: bytes) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value.decode("latin-1")


class _Parts:
    """python-multipart callbacks: remembers the first file part named `file` and
    collects its bytes for the writer; every other field is skipped, never buffered."""

    def __init__(self) -> None:
        self.headers: list[tuple[bytes, bytes]] = []
        self.header_name = b""
        self.header_value = b""
        self.in_file = False
        self.seen_file = False
        self.ended = False
        self.filename = ""
        self.content_type = ""
        self.pending: list[bytes] = []
        self.pending_size = 0

    def on_part_begin(self) -> None:
        self.headers = []

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self.header_name += data[start:end]

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self.header_value += data[start:end]

    def on_header_end(self) -> None:
        self.headers.append((self.header_name.lower(), self.header_value))
        self.header_name, self.header_value = b"", b""

    def on_headers_finished(self) -> None:
        headers = dict(self.headers)
        _, options = parse_options_header(headers.get(b"content-disposition"))
        self.in_file = (
            not self.seen_file and options.get(b"name") == b"file" and b"filename" in options
        )
        if self.in_file:
            self.seen_file = True
            self.filename = _decode(options[b"filename"])
            self.content_type = _decode(headers.get(b"content-type", b""))[:100]

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if self.in_file:
            self.pending.append(data[start:end])
            self.pending_size += end - start

    def on_part_end(self) -> None:
        if self.in_file:
            self.in_file = False
            self.ended = True

    def take(self) -> bytes:
        data = b"".join(self.pending)
        self.pending, self.pending_size = [], 0
        return data


async def receive_upload(
    request: Request, store: FileStore, settings: Settings, folder: Path
) -> Received:
    """Stream the multipart field `file` of `request` into a new file in `folder`."""
    media, params = parse_options_header(request.headers.get("content-type"))
    boundary = params.get(b"boundary")
    if media != b"multipart/form-data" or not boundary:
        raise InvalidUpload("Send the file as multipart/form-data (field “file”).")
    await asyncio.to_thread(store.ensure_space)
    await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)

    parts = _Parts()
    parser = MultipartParser(
        boundary,
        {
            "on_part_begin": parts.on_part_begin,
            "on_part_data": parts.on_part_data,
            "on_part_end": parts.on_part_end,
            "on_header_field": parts.on_header_field,
            "on_header_value": parts.on_header_value,
            "on_header_end": parts.on_header_end,
            "on_headers_finished": parts.on_headers_finished,
        },
    )
    path = folder / f".upload-{uuid.uuid4().hex}"
    sink: _Sink | None = None
    try:
        async for chunk in request.stream():
            parser.write(chunk)
            if parts.seen_file and sink is None:
                sink = await asyncio.to_thread(_Sink, path, store, settings)
            if sink is not None and parts.pending_size >= FLUSH_EVERY:
                await asyncio.to_thread(sink.write, parts.take())
        parser.finalize()
        if sink is None:
            raise InvalidUpload("No file in the upload (field “file”).")
        if not parts.ended:
            raise InvalidUpload("The upload was cut off.")
        await asyncio.to_thread(sink.write, parts.take())
        await asyncio.to_thread(sink.finish)
    except FormParserError:
        await _abort(sink, path)
        raise InvalidUpload("The upload is not valid multipart data.") from None
    except BaseException:
        await _abort(sink, path)
        raise
    return Received(
        path=path,
        filename=safe_filename(parts.filename),
        content_type=parts.content_type,
        size=sink.size,
        sha256=sink.sha.hexdigest(),
        head=bytes(sink.head),
        text=sink.text,
    )


async def _abort(sink: _Sink | None, path: Path) -> None:
    if sink is not None:
        await asyncio.to_thread(sink.abort)
    else:
        await asyncio.to_thread(path.unlink, missing_ok=True)
