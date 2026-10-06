"""Kokoro-82M via kokoro-onnx: high quality, CPU friendly, Apache-2.0 model."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from .base import TTSEngine, TTSError, Voice

log = logging.getLogger(__name__)

_GH = "https://github.com/thewh1teagle/kokoro-onnx/releases/download"
_HF = "https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main"

VARIANTS: dict[str, dict[str, Any]] = {
    "kokoro-v1.0": {
        "label": "Kokoro v1.0 – full precision",
        "file": "kokoro-v1.0.onnx",
        "size_mb": 311,
        "urls": [
            f"{_GH}/model-files-v1.0/kokoro-v1.0.onnx",
            f"{_GH}/model-files-v1.1/kokoro-v1.0.onnx",
            f"{_HF}/onnx/model.onnx",
        ],
    },
    "kokoro-v1.0-int8": {
        "label": "Kokoro v1.0 – int8 quantized (smaller)",
        "file": "kokoro-v1.0.int8.onnx",
        "size_mb": 88,
        "urls": [
            f"{_GH}/model-files-v1.0/kokoro-v1.0.int8.onnx",
            f"{_GH}/model-files-v1.1/kokoro-v1.0.int8.onnx",
            f"{_HF}/onnx/model_quantized.onnx",
        ],
    },
}
VOICES_FILE = "voices-v1.0.bin"
VOICES_URLS = [f"{_GH}/model-files-v1.0/{VOICES_FILE}", f"{_GH}/model-files-v1.1/{VOICES_FILE}"]
VOICES_SIZE_MB = 27
HF_VOICE_URL = _HF + "/voices/{name}.bin"

# prefix letter -> (kokoro-onnx/espeak language, BCP-47, display name)
LANGUAGES = {
    "a": ("en-us", "en-US", "English (US)"),
    "b": ("en-gb", "en-GB", "English (UK)"),
    "e": ("es", "es-ES", "Spanish"),
    "f": ("fr-fr", "fr-FR", "French"),
    "h": ("hi", "hi-IN", "Hindi"),
    "i": ("it", "it-IT", "Italian"),
    "j": ("ja", "ja-JP", "Japanese"),
    "p": ("pt-br", "pt-BR", "Portuguese (Brazil)"),
    "z": ("cmn", "zh-CN", "Chinese (Mandarin)"),
}
VOICE_NAMES = [
    "af_heart", "af_alloy", "af_aoede", "af_bella", "af_jessica", "af_kore", "af_nicole", "af_nova",
    "af_river", "af_sarah", "af_sky", "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam",
    "am_michael", "am_onyx", "am_puck", "am_santa", "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis", "ef_dora", "em_alex", "em_santa", "ff_siwis",
    "hf_alpha", "hf_beta", "hm_omega", "hm_psi", "if_sara", "im_nicola", "jf_alpha", "jf_gongitsune",
    "jf_nezumi", "jf_tebukuro", "jm_kumo", "pf_dora", "pm_alex", "pm_santa", "zf_xiaobei",
    "zf_xiaoni", "zf_xiaoxiao", "zf_xiaoyi", "zm_yunjian", "zm_yunxi", "zm_yunxia", "zm_yunyang",
]
RECOMMENDED = {"af_heart", "af_bella", "af_nicole", "am_michael", "am_fenrir", "am_puck", "bf_emma", "bm_george", "bm_fable", "ff_siwis"}


def describe_voice(name: str, installed: bool = True) -> Voice:
    prefix = name[:1]
    _, bcp47, language_name = LANGUAGES.get(prefix, ("en-us", "en-US", "English (US)"))
    gender = {"f": "female", "m": "male"}.get(name[1:2], "")
    display = name.split("_", 1)[-1].replace("_", " ").title()
    return Voice(
        id=name,
        name=display,
        engine="kokoro",
        language=bcp47,
        language_name=language_name,
        gender=gender,
        quality="neural",
        installed=installed,
        recommended=name in RECOMMENDED,
    )


class KokoroEngine(TTSEngine):
    id = "kokoro"
    name = "Kokoro"
    description = "Natural sounding neural voices (82M parameter model). Runs on CPU, best quality for English."
    needs_download = True
    max_chars = 300
    supports_blending = True

    def __init__(self, ctx):
        super().__init__(ctx)
        self._model = None
        self._model_file: Path | None = None
        self._voice_names: list[str] | None = None

    @property
    def folder(self) -> Path:
        return self.ctx.models_dir / "kokoro"

    def model_path(self, variant: str | None = None) -> Path | None:
        preferred = variant or self.ctx.settings().kokoro_variant
        order = [preferred] + [v for v in VARIANTS if v != preferred]
        for key in order:
            if key in VARIANTS:
                path = self.folder / VARIANTS[key]["file"]
                if path.exists():
                    return path
        return None

    @property
    def voices_path(self) -> Path:
        return self.folder / VOICES_FILE

    def installed_variants(self) -> list[str]:
        return [key for key, v in VARIANTS.items() if (self.folder / v["file"]).exists()]

    def available(self) -> tuple[bool, str]:
        try:
            import kokoro_onnx  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            return False, f"kokoro-onnx is not installed ({exc})"
        return True, ""

    def ready(self) -> tuple[bool, str]:
        ok, message = self.available()
        if not ok:
            return ok, message
        if self.model_path() is None or not self.voices_path.exists():
            return False, "Model not downloaded yet"
        return True, ""

    def list_voices(self) -> list[Voice]:
        installed = self.ready()[0]
        names = self._installed_voice_names() if installed else None
        return [describe_voice(n, installed=installed) for n in (names or VOICE_NAMES)]

    def _installed_voice_names(self) -> list[str]:
        if self._voice_names is None:
            try:
                with np.load(self.voices_path) as data:
                    self._voice_names = sorted(data.files, key=lambda n: (VOICE_NAMES.index(n) if n in VOICE_NAMES else 999, n))
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not read Kokoro voices file: %s", exc)
                self._voice_names = list(VOICE_NAMES)
        return self._voice_names

    def language_for_voice(self, voice: str) -> str:
        first = voice.split("+", 1)[0].split(":", 1)[0].strip()
        return LANGUAGES.get(first[:1], ("en-us", "en-US", ""))[1]

    def has_voice(self, voice: str) -> bool:
        names = set(self._installed_voice_names()) if self.ready()[0] else set()
        parts = [p.split(":", 1)[0].strip() for p in voice.split("+")]
        return bool(parts) and all(p in names for p in parts)

    def _load(self):
        path = self.model_path()
        if path is None or not self.voices_path.exists():
            raise TTSError("The Kokoro model is not installed. Download it on the Voices page.")
        if self._model is None or self._model_file != path:
            from kokoro_onnx import Kokoro

            log.info("Loading Kokoro model %s", path.name)
            self._model = Kokoro(str(path), str(self.voices_path))
            self._model_file = path
        return self._model

    def _style(self, model, voice: str):
        if "+" not in voice and ":" not in voice:
            return voice
        total = 0.0
        style = None
        for part in voice.split("+"):
            name, _, weight_text = part.strip().partition(":")
            try:
                weight = float(weight_text) if weight_text else 1.0
            except ValueError as exc:
                raise TTSError(f"Invalid voice blend: {voice}") from exc
            vector = model.get_voice_style(name.strip()) * weight
            style = vector if style is None else style + vector
            total += weight
        if style is None or total <= 0:
            raise TTSError(f"Invalid voice blend: {voice}")
        return (style / total).astype(np.float32)

    def synthesize(self, text, voice, speed=1.0, language=None, sentence_pause=0.25):
        with self.lock:
            model = self._load()
            first = voice.split("+", 1)[0].split(":", 1)[0].strip()
            lang = LANGUAGES.get(first[:1], ("en-us",))[0]
            if language and not language.lower().startswith(lang.split("-")[0]):
                lang = _espeak_code(language) or lang
            try:
                style = self._style(model, voice)
                audio, sample_rate = model.create(
                    text,
                    voice=style,
                    speed=float(min(2.0, max(0.5, speed))),
                    lang=lang,
                    sentence_pause=sentence_pause,
                )
            except KeyError as exc:
                raise TTSError(f"Unknown Kokoro voice: {voice}") from exc
        return np.asarray(audio, dtype=np.float32), int(sample_rate)

    def unload(self) -> None:
        with self.lock:
            self._model = None
            self._voice_names = None


def _espeak_code(language: str) -> str | None:
    code = language.lower()
    mapping = {"en-us": "en-us", "en-gb": "en-gb", "en": "en-us", "es": "es", "fr": "fr-fr", "hi": "hi",
               "it": "it", "ja": "ja", "pt": "pt-br", "pt-br": "pt-br", "zh": "cmn", "zh-cn": "cmn"}
    return mapping.get(code) or mapping.get(code.split("-")[0])
