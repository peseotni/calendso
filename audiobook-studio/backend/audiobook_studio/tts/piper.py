"""Piper: fast local neural TTS with voices for 40+ languages."""

from __future__ import annotations

import json
import logging
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

import numpy as np

from .base import TTSEngine, TTSError, Voice, silence

log = logging.getLogger(__name__)

HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
CATALOG_URL = f"{HF_BASE}/voices.json"
RECOMMENDED = {
    "en_US-lessac-high", "en_US-ryan-high", "en_US-amy-medium", "en_GB-alba-medium",
    "en_GB-jenny_dioco-medium", "de_DE-thorsten-high", "fr_FR-siwis-medium", "es_ES-davefx-medium",
    "it_IT-paola-medium", "nl_NL-mls-medium", "pt_BR-faber-medium",
}


def _bcp47(code: str) -> str:
    return code.replace("_", "-")


class PiperEngine(TTSEngine):
    id = "piper"
    name = "Piper"
    description = "Fast, lightweight neural voices for more than 40 languages. Download only the voices you need."
    needs_download = True
    max_chars = 500

    def __init__(self, ctx):
        super().__init__(ctx)
        self._voices: OrderedDict[str, Any] = OrderedDict()
        self._catalog: dict[str, Any] | None = None
        self._catalog_time = 0.0

    @property
    def folder(self) -> Path:
        return self.ctx.models_dir / "piper"

    def available(self) -> tuple[bool, str]:
        try:
            import piper  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            return False, f"piper-tts is not installed ({exc})"
        return True, ""

    def ready(self) -> tuple[bool, str]:
        ok, message = self.available()
        if not ok:
            return ok, message
        if not self.installed_models():
            return False, "No Piper voices downloaded yet"
        return True, ""

    # -- models -------------------------------------------------------------
    def installed_models(self) -> dict[str, Path]:
        if not self.folder.exists():
            return {}
        models = {}
        for onnx in sorted(self.folder.glob("*.onnx")):
            if Path(f"{onnx}.json").exists():
                models[onnx.stem] = onnx
        return models

    def _config(self, path: Path) -> dict[str, Any]:
        try:
            return json.loads(Path(f"{path}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def catalog(self, refresh: bool = False) -> dict[str, Any]:
        """The official voice list (cached on disk for a week)."""
        cache = self.folder / "voices.json"
        if not refresh and self._catalog is not None and time.time() - self._catalog_time < 3600:
            return self._catalog
        if not refresh and cache.exists() and time.time() - cache.stat().st_mtime < 7 * 86400:
            try:
                self._catalog = json.loads(cache.read_text(encoding="utf-8"))
                self._catalog_time = time.time()
                return self._catalog
            except ValueError:
                pass
        import httpx

        try:
            response = httpx.get(CATALOG_URL, follow_redirects=True, timeout=30)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            if cache.exists():
                self._catalog = json.loads(cache.read_text(encoding="utf-8"))
                return self._catalog
            raise TTSError(f"Could not download the Piper voice catalog: {exc}") from exc
        self.folder.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data), encoding="utf-8")
        self._catalog = data
        self._catalog_time = time.time()
        return data

    def catalog_voices(self) -> list[dict[str, Any]]:
        installed = self.installed_models()
        result = []
        for key, entry in sorted(self.catalog().items()):
            language = entry.get("language", {})
            files = entry.get("files", {})
            size = sum(f.get("size_bytes", 0) for name, f in files.items() if name.endswith(".onnx"))
            result.append({
                "id": key,
                "name": entry.get("name", key).replace("_", " ").title(),
                "language": _bcp47(language.get("code", "")),
                "language_name": f"{language.get('name_english', '')} ({language.get('country_english', '')})".strip(" ()"),
                "quality": entry.get("quality", ""),
                "speakers": entry.get("num_speakers", 1),
                "size_mb": round(size / 1_000_000, 1),
                "installed": key in installed,
                "recommended": key in RECOMMENDED,
            })
        return result

    def catalog_entry(self, key: str) -> dict[str, Any]:
        entry = self.catalog().get(key)
        if not entry:
            raise TTSError(f"Unknown Piper voice: {key}")
        return entry

    def delete_model(self, key: str) -> None:
        for path in (self.folder / f"{key}.onnx", self.folder / f"{key}.onnx.json"):
            path.unlink(missing_ok=True)
        with self.lock:
            self._voices.pop(key, None)

    # -- voices -------------------------------------------------------------
    def list_voices(self) -> list[Voice]:
        voices = []
        for key, path in self.installed_models().items():
            config = self._config(path)
            language = config.get("language", {})
            code = language.get("code") or config.get("espeak", {}).get("voice", "en_US")
            name_english = language.get("name_english", "")
            country = language.get("country_english", "")
            parts = key.split("-")
            speaker_map = config.get("speaker_id_map") or {}
            voices.append(Voice(
                id=key,
                name=(parts[1] if len(parts) > 2 else key).replace("_", " ").title(),
                engine=self.id,
                language=_bcp47(code if "_" in code or "-" in code else code),
                language_name=f"{name_english} ({country})" if country else name_english,
                quality=config.get("audio", {}).get("quality", parts[-1] if parts else ""),
                installed=True,
                recommended=key in RECOMMENDED,
                speakers=sorted(speaker_map, key=lambda s: speaker_map[s]) if len(speaker_map) > 1 else [],
            ))
        return voices

    def _load(self, key: str):
        with self.lock:
            if key in self._voices:
                self._voices.move_to_end(key)
                return self._voices[key]
            path = self.installed_models().get(key)
            if path is None:
                raise TTSError(f"Piper voice '{key}' is not installed. Download it on the Voices page.")
            from piper import PiperVoice

            log.info("Loading Piper voice %s", key)
            voice = PiperVoice.load(str(path))
            self._voices[key] = voice
            while len(self._voices) > 3:
                self._voices.popitem(last=False)
            return voice

    def synthesize(self, text, voice, speed=1.0, language=None, sentence_pause=0.25):
        from piper import SynthesisConfig

        key, _, speaker = voice.partition("#")
        model = self._load(key)
        speaker_id = None
        speaker_map = getattr(model.config, "speaker_id_map", {}) or {}
        if speaker:
            speaker_id = speaker_map.get(speaker)
            if speaker_id is None and speaker.isdigit():
                speaker_id = int(speaker)
        base_scale = getattr(model.config, "length_scale", 1.0) or 1.0
        config = SynthesisConfig(
            speaker_id=speaker_id,
            length_scale=base_scale / max(0.25, speed),
            normalize_audio=True,
            volume=0.9,
        )
        sample_rate = model.config.sample_rate
        parts: list[np.ndarray] = []
        with self.lock:
            for chunk in model.synthesize(text, syn_config=config):
                if parts:
                    parts.append(silence(sentence_pause, sample_rate))
                parts.append(np.asarray(chunk.audio_float_array, dtype=np.float32))
                sample_rate = chunk.sample_rate
        if not parts:
            return np.zeros(0, dtype=np.float32), sample_rate
        return np.concatenate(parts), sample_rate

    def unload(self) -> None:
        with self.lock:
            self._voices.clear()
