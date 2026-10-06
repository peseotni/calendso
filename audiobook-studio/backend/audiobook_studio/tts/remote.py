"""Network engines: any OpenAI-compatible speech API, and Microsoft Edge voices."""

from __future__ import annotations

import asyncio
import json
import logging
import time

import numpy as np

from ..audio.codec import AudioError, decode_audio_bytes
from .base import TTSEngine, TTSError, Voice

log = logging.getLogger(__name__)

OPENAI_DEFAULT_VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse"]


class OpenAICompatibleEngine(TTSEngine):
    """Works with OpenAI and self-hosted servers exposing /v1/audio/speech
    (Kokoro-FastAPI, openedai-speech, AllTalk, LocalAI, ...)."""

    id = "openai"
    name = "OpenAI-compatible API"
    description = "Use any server with an OpenAI-style /v1/audio/speech endpoint, e.g. a GPU box running Kokoro-FastAPI, or OpenAI itself."
    online = True
    max_chars = 1500

    def __init__(self, ctx):
        super().__init__(ctx)
        self._remote_voices: tuple[str, float, list[str]] | None = None

    def _base_url(self) -> str:
        return self.ctx.settings().openai_base_url.strip().rstrip("/")

    def ready(self) -> tuple[bool, str]:
        if not self._base_url():
            return False, "Set the API base URL in Settings"
        return True, ""

    def enabled(self) -> bool:
        return bool(self._base_url())

    def _headers(self) -> dict[str, str]:
        key = self.ctx.settings().openai_api_key.strip()
        return {"Authorization": f"Bearer {key}"} if key else {}

    def _voice_names(self) -> list[str]:
        settings = self.ctx.settings()
        configured = [v.strip() for v in settings.openai_voices.split(",") if v.strip()]
        if configured:
            return configured
        base = self._base_url()
        if not base:
            return []
        cached = self._remote_voices
        if cached and cached[0] == base and time.time() - cached[1] < 600:
            return cached[2]
        names: list[str] = []
        try:
            import httpx

            response = httpx.get(f"{base}/audio/voices", headers=self._headers(), timeout=5)
            if response.status_code == 200:
                data = response.json()
                items = data.get("voices", data) if isinstance(data, dict) else data
                for item in items:
                    name = item if isinstance(item, str) else (item.get("id") or item.get("name"))
                    if name:
                        names.append(str(name))
        except Exception as exc:  # noqa: BLE001 - optional endpoint
            log.debug("Voice list endpoint unavailable: %s", exc)
        names = names or OPENAI_DEFAULT_VOICES
        self._remote_voices = (base, time.time(), names)
        return names

    def list_voices(self) -> list[Voice]:
        return [
            Voice(id=name, name=name.replace("_", " ").title(), engine=self.id, language="",
                  language_name="Any", quality="remote")
            for name in self._voice_names()
        ]

    def language_for_voice(self, voice: str) -> str:
        return ""

    def has_voice(self, voice: str) -> bool:
        return self.enabled()

    def synthesize(self, text, voice, speed=1.0, language=None, sentence_pause=0.25):
        import httpx

        base = self._base_url()
        if not base:
            raise TTSError("The OpenAI-compatible engine is not configured (Settings → Engines).")
        payload = {
            "model": self.ctx.settings().openai_model or "tts-1",
            "input": text,
            "voice": voice,
            "speed": float(min(4.0, max(0.25, speed))),
            "response_format": "wav",
        }
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = httpx.post(f"{base}/audio/speech", json=payload, headers=self._headers(), timeout=300)
                if response.status_code >= 400:
                    raise TTSError(f"API error {response.status_code}: {response.text[:300]}")
                return decode_audio_bytes(response.content, 24000)
            except (httpx.HTTPError, AudioError) as exc:
                last_error = exc
                time.sleep(1.5 * (attempt + 1))
        raise TTSError(f"Speech API request failed: {last_error}")


class EdgeEngine(TTSEngine):
    """Microsoft Edge's online read-aloud voices via the edge-tts package."""

    id = "edge"
    name = "Microsoft Edge (online)"
    description = "Hundreds of very natural voices in 100+ languages. Requires an internet connection; text is sent to Microsoft."
    online = True
    max_chars = 1500

    def __init__(self, ctx):
        super().__init__(ctx)
        self._voices: list[Voice] | None = None
        self._voices_time = 0.0

    def available(self) -> tuple[bool, str]:
        try:
            import edge_tts  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            return False, f"edge-tts is not installed ({exc})"
        return True, ""

    def enabled(self) -> bool:
        return self.ctx.settings().edge_enabled

    def list_voices(self) -> list[Voice]:
        if not self.enabled() or not self.available()[0]:
            return []
        if self._voices is not None and time.time() - self._voices_time < 6 * 3600:
            return self._voices
        cache = self.ctx.models_dir / "edge-voices.json"
        raw = None
        try:
            import edge_tts

            raw = _run_async(edge_tts.list_voices())
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(raw), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            log.info("Could not fetch Edge voices: %s", exc)
            if cache.exists():
                raw = json.loads(cache.read_text(encoding="utf-8"))
        voices = []
        for item in raw or []:
            short = item.get("ShortName", "")
            if not short:
                continue
            locale = item.get("Locale", "")
            display = short.split("-", 2)[-1].replace("Neural", "").replace("Multilingual", " Multilingual")
            voices.append(Voice(
                id=short,
                name=display.strip(),
                engine=self.id,
                language=locale,
                language_name=locale,
                gender=(item.get("Gender") or "").lower(),
                quality="online",
                description=", ".join(item.get("VoiceTag", {}).get("VoicePersonalities", [])),
                recommended="Multilingual" in short,
            ))
        if voices:
            self._voices = voices
            self._voices_time = time.time()
        return voices

    def language_for_voice(self, voice: str) -> str:
        parts = voice.split("-")
        return "-".join(parts[:2]) if len(parts) >= 2 else "en-US"

    def has_voice(self, voice: str) -> bool:
        return self.enabled()

    def synthesize(self, text, voice, speed=1.0, language=None, sentence_pause=0.25):
        if not self.enabled():
            raise TTSError("The Edge engine is disabled in Settings.")
        import edge_tts

        rate = f"{round((speed - 1.0) * 100):+d}%"

        async def collect() -> bytes:
            communicate = edge_tts.Communicate(text, voice, rate=rate)
            chunks = []
            async for message in communicate.stream():
                if message.get("type") == "audio" and message.get("data"):
                    chunks.append(message["data"])
            return b"".join(chunks)

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                data = _run_async(collect())
                if not data:
                    raise TTSError("No audio received from the Edge service")
                audio, sample_rate = decode_audio_bytes(data, 24000)
                return audio.astype(np.float32), sample_rate
            except Exception as exc:  # noqa: BLE001 - network flakiness
                last_error = exc
                time.sleep(2 * (attempt + 1))
        raise TTSError(f"Edge TTS failed: {last_error}")


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Called from inside an event loop: run in a helper thread.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
