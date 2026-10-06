"""Cover image storage (normalised JPEG + thumbnail)."""

from __future__ import annotations

import io
import logging
from pathlib import Path

log = logging.getLogger(__name__)

MAX_SIZE = 1400
THUMB_WIDTH = 360


class CoverError(ValueError):
    pass


def normalize_cover(data: bytes) -> bytes:
    """Convert any image to an RGB JPEG no larger than MAX_SIZE."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image)
    except (UnidentifiedImageError, OSError) as exc:
        raise CoverError("The file is not a supported image.") from exc
    if image.mode not in ("RGB", "L"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        if image.mode in ("RGBA", "LA") or "transparency" in image.info:
            rgba = image.convert("RGBA")
            background.paste(rgba, mask=rgba.split()[-1])
            image = background
        else:
            image = image.convert("RGB")
    elif image.mode == "L":
        image = image.convert("RGB")
    image.thumbnail((MAX_SIZE, MAX_SIZE))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=88, optimize=True)
    return out.getvalue()


def save_cover(data: bytes, path: Path) -> Path:
    """Store ``data`` as ``path`` (JPEG) and ``path_thumb.jpg``."""
    from PIL import Image

    jpeg = normalize_cover(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(jpeg)
    image = Image.open(io.BytesIO(jpeg))
    if image.width > THUMB_WIDTH:
        ratio = THUMB_WIDTH / image.width
        image = image.resize((THUMB_WIDTH, max(1, int(image.height * ratio))), Image.LANCZOS)
    image.save(thumb_path(path), "JPEG", quality=82, optimize=True)
    return path


def thumb_path(path: Path) -> Path:
    return path.with_name(path.stem + "_thumb.jpg")


def delete_cover(path: Path | None) -> None:
    if not path:
        return
    path.unlink(missing_ok=True)
    thumb_path(path).unlink(missing_ok=True)


def fetch_cover(url: str) -> bytes:
    import httpx

    if not url.lower().startswith(("http://", "https://")):
        raise CoverError("Only http(s) URLs are supported.")
    try:
        response = httpx.get(url, follow_redirects=True, timeout=20, headers={"User-Agent": "AudiobookStudio/1.0"})
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise CoverError(f"Could not download the image: {exc}") from exc
    if len(response.content) > 25 * 1024 * 1024:
        raise CoverError("The image is too large.")
    return response.content
