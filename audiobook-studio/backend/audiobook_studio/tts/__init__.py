"""Engine registry."""

from __future__ import annotations

import logging
from pathlib import Path

from .base import EngineContext, TTSEngine, TTSError, Voice
from .espeak import EspeakEngine
from .kokoro import KokoroEngine
from .piper import PiperEngine
from .remote import EdgeEngine, OpenAICompatibleEngine

log = logging.getLogger(__name__)

ENGINE_ORDER = ["kokoro", "piper", "edge", "openai", "espeak"]
DEFAULT_REGIONS = {
    "en": "en-us", "de": "de-de", "fr": "fr-fr", "es": "es-es", "pt": "pt-br", "it": "it-it",
    "nl": "nl-nl", "zh": "zh-cn", "ja": "ja-jp", "hi": "hi-in", "pl": "pl-pl", "ru": "ru-ru",
}


class EngineRegistry:
    def __init__(self, ctx: EngineContext):
        self.ctx = ctx
        self.engines: dict[str, TTSEngine] = {
            "kokoro": KokoroEngine(ctx),
            "piper": PiperEngine(ctx),
            "edge": EdgeEngine(ctx),
            "openai": OpenAICompatibleEngine(ctx),
            "espeak": EspeakEngine(ctx),
        }

    def get(self, engine_id: str) -> TTSEngine:
        engine = self.engines.get(engine_id)
        if engine is None:
            raise TTSError(f"Unknown TTS engine: {engine_id}")
        return engine

    def infos(self) -> list[dict]:
        return [self.engines[e].info() for e in ENGINE_ORDER]

    def ready_engines(self) -> list[TTSEngine]:
        result = []
        for engine_id in ENGINE_ORDER:
            engine = self.engines[engine_id]
            try:
                if engine.ready()[0] and engine.enabled():
                    result.append(engine)
            except Exception:  # noqa: BLE001
                continue
        return result

    def pick_voice(self, language: str, preferred_engine: str, preferred_voice: str) -> tuple[str, str]:
        """Choose an installed voice for a language, honouring the preference."""
        language = (language or "en").lower()
        lang = language.split("-")[0]
        try:
            engine = self.get(preferred_engine)
            if engine.ready()[0] and engine.has_voice(preferred_voice):
                voice_lang = (engine.language_for_voice(preferred_voice) or "").lower()
                if not voice_lang or voice_lang.split("-")[0] == lang:
                    return preferred_engine, preferred_voice
        except TTSError:
            pass
        region = language if "-" in language else DEFAULT_REGIONS.get(lang, lang)
        for engine in self.ready_engines():
            if engine.online:
                continue
            voices = [v for v in engine.list_voices() if v.installed and v.language.lower().split("-")[0] == lang]
            if voices:
                def rank(v: Voice) -> tuple[int, int]:
                    code = v.language.lower()
                    return (0 if code == region else 1 if code == lang else 2, 0 if v.recommended else 1)

                return engine.id, min(voices, key=rank).id
        # Nothing matches the language: fall back to the preference or eSpeak.
        try:
            engine = self.get(preferred_engine)
            if engine.ready()[0]:
                return preferred_engine, preferred_voice
        except TTSError:
            pass
        espeak = self.engines["espeak"]
        if espeak.ready()[0]:
            ids = {v.id for v in espeak.list_voices()}
            for candidate in (language, lang, "en-us"):
                if candidate in ids:
                    return "espeak", candidate
        return preferred_engine, preferred_voice


_registry: EngineRegistry | None = None


def init_registry(models_dir: Path, settings_provider) -> EngineRegistry:
    global _registry
    _registry = EngineRegistry(EngineContext(models_dir=models_dir, settings=settings_provider))
    return _registry


def get_registry() -> EngineRegistry:
    if _registry is None:
        raise RuntimeError("TTS registry not initialised")
    return _registry


__all__ = ["EngineRegistry", "TTSEngine", "TTSError", "Voice", "get_registry", "init_registry"]
