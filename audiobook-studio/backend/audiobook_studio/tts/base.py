"""Common interface for text-to-speech engines."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from ..settings_store import AppSettings


class TTSError(RuntimeError):
    """A user-facing synthesis error."""


@dataclass
class Voice:
    id: str
    name: str
    engine: str
    language: str  # BCP-47 like "en-US"
    language_name: str = ""
    gender: str = ""  # female | male | ""
    quality: str = ""
    description: str = ""
    installed: bool = True
    recommended: bool = False
    speakers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EngineContext:
    models_dir: Path
    settings: Callable[[], AppSettings]


class TTSEngine:
    id: str = ""
    name: str = ""
    description: str = ""
    online: bool = False
    needs_download: bool = False
    max_chars: int = 350
    supports_blending: bool = False

    def __init__(self, ctx: EngineContext):
        self.ctx = ctx
        self.lock = threading.RLock()

    # -- status --------------------------------------------------------
    def available(self) -> tuple[bool, str]:
        """Are the engine's dependencies installed?"""
        return True, ""

    def ready(self) -> tuple[bool, str]:
        """Can it synthesise right now (models present, configured)?"""
        return self.available()

    def enabled(self) -> bool:
        return True

    def info(self) -> dict[str, Any]:
        available, message = self.available()
        ready, ready_message = self.ready() if available else (False, message)
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "online": self.online,
            "needs_download": self.needs_download,
            "available": available,
            "ready": ready and self.enabled(),
            "enabled": self.enabled(),
            "message": ready_message or message,
            "supports_blending": self.supports_blending,
        }

    # -- voices --------------------------------------------------------
    def list_voices(self) -> list[Voice]:
        return []

    def language_for_voice(self, voice: str) -> str:
        for v in self.list_voices():
            if v.id == voice.split("#", 1)[0]:
                return v.language
        return "en-US"

    def has_voice(self, voice: str) -> bool:
        base = voice.split("#", 1)[0]
        return any(v.id == base and v.installed for v in self.list_voices())

    # -- synthesis -----------------------------------------------------
    def synthesize(
        self,
        text: str,
        voice: str,
        speed: float = 1.0,
        language: str | None = None,
        sentence_pause: float = 0.25,
    ) -> tuple[np.ndarray, int]:
        raise NotImplementedError

    def unload(self) -> None:
        """Release cached models."""


def silence(seconds: float, sample_rate: int) -> np.ndarray:
    return np.zeros(max(0, int(seconds * sample_rate)), dtype=np.float32)
