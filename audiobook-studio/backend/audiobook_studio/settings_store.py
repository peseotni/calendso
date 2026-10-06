"""User-editable application settings, persisted in the database."""

from __future__ import annotations

import secrets
import threading
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from .models import Setting

OutputFormat = Literal["m4b", "mp3", "mp3_single", "opus"]


class CleanupOptions(BaseModel):
    """Text clean-up applied right before synthesis (stored text is untouched)."""

    remove_footnote_markers: bool = True
    remove_urls: bool = True
    expand_abbreviations: bool = True
    normalize_punctuation: bool = True
    remove_bracketed_text: bool = False
    skip_all_caps_headers: bool = False


class RenderSettings(BaseModel):
    """Voice and audio settings of a project (new projects copy the defaults)."""

    engine: str = "kokoro"
    voice: str = "af_heart"
    speed: float = Field(1.0, ge=0.5, le=2.0)
    language: str | None = None

    # Optional second voice for quoted dialogue.
    dialogue_enabled: bool = False
    dialogue_engine: str | None = None
    dialogue_voice: str | None = None

    announce_chapters: bool = True
    sentence_pause: float = Field(0.25, ge=0, le=5)
    paragraph_pause: float = Field(0.6, ge=0, le=10)
    section_pause: float = Field(1.5, ge=0, le=10)
    chapter_pause: float = Field(2.0, ge=0, le=10)

    output_format: OutputFormat = "m4b"
    bitrate: str = "64k"
    normalize: bool = True

    cleanup: CleanupOptions = Field(default_factory=CleanupOptions)

    @field_validator("bitrate")
    @classmethod
    def _bitrate(cls, value: str) -> str:
        value = value.strip().lower()
        if not value.endswith("k"):
            value = f"{value}k"
        number = value[:-1]
        if not number.isdigit() or not 16 <= int(number) <= 320:
            raise ValueError("bitrate must be between 16k and 320k")
        return value


class AppSettings(BaseModel):
    # Defaults for new projects
    render_defaults: RenderSettings = Field(default_factory=RenderSettings)

    # Library organisation
    library_template: str = "{author}/[{series}/][{series_index} - ]{title}"
    auto_organize: bool = True
    write_sidecars: bool = True
    keep_workspace_audio: bool = True

    # Watch folder
    inbox_enabled: bool = True
    inbox_auto_render: bool = False
    inbox_interval: int = Field(30, ge=5, le=3600)

    # Metadata
    online_metadata: bool = True

    # Engines
    kokoro_variant: str = "kokoro-v1.0"
    openai_base_url: str = ""
    openai_api_key: str = ""
    openai_model: str = "tts-1"
    openai_voices: str = ""
    edge_enabled: bool = True

    # Security / feeds
    password_hash: str = ""
    feed_token: str = ""

    # Interface
    first_run_done: bool = False


SECRET_FIELDS = {"password_hash", "openai_api_key"}

_lock = threading.Lock()
_cache: AppSettings | None = None


def _load(session: Session) -> AppSettings:
    rows = session.query(Setting).all()
    data: dict[str, Any] = {row.key: row.value for row in rows}
    known = AppSettings.model_fields
    settings = AppSettings.model_validate({k: v for k, v in data.items() if k in known})
    if not settings.feed_token:
        settings.feed_token = secrets.token_urlsafe(24)
        _save_field(session, "feed_token", settings.feed_token)
        session.commit()
    return settings


def _save_field(session: Session, key: str, value: Any) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value


def get_settings(session: Session) -> AppSettings:
    global _cache
    with _lock:
        if _cache is None:
            _cache = _load(session)
        return _cache.model_copy(deep=True)


def update_settings(session: Session, changes: dict[str, Any]) -> AppSettings:
    """Validate and persist a partial update; nested models are merged."""
    global _cache
    with _lock:
        current = _cache or _load(session)
        merged = current.model_dump()
        for key, value in changes.items():
            if key not in AppSettings.model_fields:
                continue
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = _deep_merge(merged[key], value)
            else:
                merged[key] = value
        updated = AppSettings.model_validate(merged)
        dumped = updated.model_dump()
        for key in AppSettings.model_fields:
            if dumped[key] != current.model_dump()[key]:
                _save_field(session, key, dumped[key])
        session.commit()
        _cache = updated
        return updated.model_copy(deep=True)


def current() -> AppSettings:
    """Settings for code running outside a request (workers, engines)."""
    with _lock:
        if _cache is not None:
            return _cache.model_copy(deep=True)
    from .db import new_session

    session = new_session()
    try:
        return get_settings(session)
    finally:
        session.close()


def invalidate_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def _deep_merge(base: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
