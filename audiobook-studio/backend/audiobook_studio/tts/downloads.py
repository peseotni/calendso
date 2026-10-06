"""Downloading voice models (Kokoro, Piper) with progress and mirrors."""

from __future__ import annotations

import hashlib
import io
import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np

from . import kokoro as kokoro_mod
from .base import TTSError

log = logging.getLogger(__name__)

ProgressFn = Callable[[int, int], None]


def download_file(
    urls: list[str],
    dest: Path,
    progress: ProgressFn | None = None,
    cancelled: Callable[[], bool] | None = None,
    md5: str | None = None,
) -> None:
    import httpx

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    errors: list[str] = []
    for url in urls:
        try:
            with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(30.0, read=120.0)) as response:
                if response.status_code >= 400:
                    raise TTSError(f"HTTP {response.status_code}")
                total = int(response.headers.get("content-length") or 0)
                done = 0
                digest = hashlib.md5()  # noqa: S324 - integrity check only
                with tmp.open("wb") as handle:
                    for chunk in response.iter_bytes(1 << 16):
                        if cancelled and cancelled():
                            raise InterruptedError("cancelled")
                        handle.write(chunk)
                        digest.update(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, total)
            if md5 and digest.hexdigest() != md5:
                raise TTSError("checksum mismatch")
            tmp.replace(dest)
            return
        except InterruptedError:
            tmp.unlink(missing_ok=True)
            raise
        except Exception as exc:  # noqa: BLE001 - try the next mirror
            log.warning("Download from %s failed: %s", url, exc)
            errors.append(f"{url}: {exc}")
            tmp.unlink(missing_ok=True)
    raise TTSError("Download failed. " + " | ".join(errors[-3:]))


def download_kokoro(
    models_dir: Path,
    variant: str,
    progress: Callable[[float, str], None],
    cancelled: Callable[[], bool],
) -> None:
    info = kokoro_mod.VARIANTS.get(variant)
    if info is None:
        raise TTSError(f"Unknown Kokoro variant: {variant}")
    folder = models_dir / "kokoro"
    model_path = folder / info["file"]
    voices_path = folder / kokoro_mod.VOICES_FILE
    model_mb = info["size_mb"]
    total_mb = model_mb + (0 if voices_path.exists() else kokoro_mod.VOICES_SIZE_MB)

    if not model_path.exists():
        def on_model(done: int, total: int) -> None:
            mb = done / 1e6
            progress(min(0.99, mb / total_mb), f"Downloading model {mb:.0f} / {model_mb} MB")

        download_file(info["urls"], model_path, on_model, cancelled)

    if not voices_path.exists():
        def on_voices(done: int, total: int) -> None:
            mb = done / 1e6
            progress(min(0.99, (model_mb + mb) / total_mb), f"Downloading voices {mb:.0f} / {kokoro_mod.VOICES_SIZE_MB} MB")

        try:
            download_file(kokoro_mod.VOICES_URLS, voices_path, on_voices, cancelled)
        except TTSError:
            log.info("Falling back to per-voice Kokoro downloads")
            _build_voices_from_hf(voices_path, progress, cancelled)


def _build_voices_from_hf(voices_path: Path, progress, cancelled) -> None:
    import httpx

    arrays: dict[str, np.ndarray] = {}
    names = kokoro_mod.VOICE_NAMES
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        for n, name in enumerate(names):
            if cancelled():
                raise InterruptedError("cancelled")
            response = client.get(kokoro_mod.HF_VOICE_URL.format(name=name))
            if response.status_code != 200:
                continue
            arrays[name] = np.frombuffer(response.content, dtype=np.float32).reshape(-1, 1, 256)
            progress(0.9 + 0.09 * (n + 1) / len(names), f"Downloading voice {name}")
    if not arrays:
        raise TTSError("Could not download Kokoro voices from any mirror.")
    buffer = io.BytesIO()
    np.savez(buffer, **arrays)
    voices_path.write_bytes(buffer.getvalue())


def download_piper(
    engine,
    key: str,
    progress: Callable[[float, str], None],
    cancelled: Callable[[], bool],
) -> None:
    from .piper import HF_BASE

    entry = engine.catalog_entry(key)
    files = entry.get("files", {})
    wanted = [(path, meta) for path, meta in files.items() if path.endswith((".onnx", ".onnx.json"))]
    if len(wanted) < 2:
        raise TTSError(f"The catalog entry for {key} is incomplete.")
    total = sum(meta.get("size_bytes", 0) for _, meta in wanted) or 1
    finished = 0
    for path, meta in sorted(wanted, key=lambda item: item[0].endswith(".json")):
        dest = engine.folder / (f"{key}.onnx.json" if path.endswith(".json") else f"{key}.onnx")

        def on_progress(done: int, _total: int, base=finished) -> None:
            progress(min(0.99, (base + done) / total), f"Downloading {key} {(base + done) / 1e6:.0f} / {total / 1e6:.0f} MB")

        download_file([f"{HF_BASE}/{path}"], dest, on_progress, cancelled, md5=meta.get("md5_digest"))
        finished += meta.get("size_bytes", 0)
