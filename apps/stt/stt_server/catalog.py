"""The Whisper models moloko can run, pinned to exact Hugging Face commits, and their
one-time download (the only step that needs the internet).

All weights are CTranslate2 conversions of OpenAI Whisper (MIT). ``model.bin`` is checked
against its SHA-256 before the model is marked complete; an interrupted download resumes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("stt")

COMPLETE = ".complete"


@dataclass(frozen=True)
class ModelSpec:
    repo: str
    revision: str  # exact commit on huggingface.co
    model_sha256: str
    files: tuple[str, ...]
    size_mb: int


_COMMON = ("config.json", "model.bin", "tokenizer.json")

CATALOG: dict[str, ModelSpec] = {
    "small": ModelSpec(
        "Systran/faster-whisper-small",
        "536b0662742c02347bc0e980a01041f333bce120",
        "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671",
        (*_COMMON, "vocabulary.txt"),
        484,
    ),
    "medium": ModelSpec(
        "Systran/faster-whisper-medium",
        "08e178d48790749d25932bbc082711ddcfdfbc4f",
        "9b45e1009dcc4ab601eff815b61d80e60ce3fd8c74c1a14f4a282258286b51ae",
        (*_COMMON, "vocabulary.txt"),
        1528,
    ),
    "large-v3": ModelSpec(
        "Systran/faster-whisper-large-v3",
        "edaa852ec7e145841d8ffdb056a99866b5f0a478",
        "69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1",
        (*_COMMON, "vocabulary.json", "preprocessor_config.json"),
        3087,
    ),
    # Whisper large-v3 with 4 decoder layers instead of 32 (OpenAI, MIT): close to
    # large-v3 quality at a fraction of the decoding time.
    "large-v3-turbo": ModelSpec(
        "dropbox-dash/faster-whisper-large-v3-turbo",
        "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf",
        "e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da",
        (*_COMMON, "vocabulary.json", "preprocessor_config.json"),
        1618,
    ),
}


class UnknownModel(ValueError):
    pass


def spec(name: str) -> ModelSpec:
    try:
        return CATALOG[name]
    except KeyError:
        raise UnknownModel(
            f"Unknown STT_MODEL {name!r}; choose one of: {', '.join(CATALOG)}"
        ) from None


def model_dir(models_dir: Path, name: str) -> Path:
    return models_dir / name


def is_complete(models_dir: Path, name: str) -> bool:
    marker = model_dir(models_dir, name) / COMPLETE
    try:
        return bool(json.loads(marker.read_text()).get("revision") == spec(name).revision)
    except (OSError, ValueError):
        return False


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def download(models_dir: Path, name: str) -> Path:
    """Fetch ``name`` into ``models_dir/name`` unless it is already there. Idempotent."""
    from huggingface_hub import hf_hub_download

    model = spec(name)
    target = model_dir(models_dir, name)
    if is_complete(models_dir, name):
        log.info("model %s is already downloaded", name)
        return target
    partial = models_dir / f".partial-{name}"
    partial.mkdir(parents=True, exist_ok=True)
    log.info(
        "downloading %s (%s @ %s, ~%d MB)", name, model.repo, model.revision[:7], model.size_mb
    )
    for filename in model.files:
        hf_hub_download(model.repo, filename, revision=model.revision, local_dir=partial)
    actual = sha256_of(partial / "model.bin")
    if actual != model.model_sha256:
        shutil.rmtree(partial, ignore_errors=True)
        raise RuntimeError(f"checksum mismatch for {name}: got {actual}")
    shutil.rmtree(partial / ".cache", ignore_errors=True)
    if target.exists():
        shutil.rmtree(target)
    partial.rename(target)
    (target / COMPLETE).write_text(json.dumps({"repo": model.repo, "revision": model.revision}))
    log.info("model %s is ready in %s", name, target)
    return target
