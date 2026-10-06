"""eSpeak NG: tiny, robotic but always available (100+ languages)."""

from __future__ import annotations

import re
import shutil
import subprocess

from ..audio.codec import AudioError, parse_wav_bytes
from .base import TTSEngine, TTSError, Voice

_LANGUAGE_NAMES = {
    "en-us": "English (US)", "en": "English (UK)", "en-gb-x-rp": "English (RP)", "de": "German",
    "fr-fr": "French", "es": "Spanish", "it": "Italian", "pt-br": "Portuguese (Brazil)",
    "pt": "Portuguese", "nl": "Dutch", "pl": "Polish", "ru": "Russian", "sv": "Swedish",
}


class EspeakEngine(TTSEngine):
    id = "espeak"
    name = "eSpeak NG"
    description = "Classic formant synthesizer: robotic, but tiny, instant and available for 100+ languages."
    max_chars = 1000

    def __init__(self, ctx):
        super().__init__(ctx)
        self._voices: list[Voice] | None = None

    @staticmethod
    def binary() -> str | None:
        return shutil.which("espeak-ng") or shutil.which("espeak")

    def available(self) -> tuple[bool, str]:
        if not self.binary():
            return False, "espeak-ng is not installed"
        return True, ""

    def list_voices(self) -> list[Voice]:
        if self._voices is not None:
            return self._voices
        binary = self.binary()
        if not binary:
            return []
        try:
            output = subprocess.run([binary, "--voices"], capture_output=True, text=True, timeout=20).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        voices: list[Voice] = []
        for line in output.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 4:
                continue
            code, gender_age, name = parts[1], parts[2], parts[3]
            gender = {"M": "male", "F": "female"}.get(gender_age.split("/")[-1], "")
            voices.append(Voice(
                id=code,
                name=name.replace("_", " "),
                engine=self.id,
                language=_bcp47(code),
                language_name=_LANGUAGE_NAMES.get(code, name.replace("_", " ")),
                gender=gender,
                quality="robotic",
            ))
        for base in ("en-us", "en"):
            if any(v.id == base for v in voices):
                label = _LANGUAGE_NAMES.get(base, base)
                voices.append(Voice(id=f"{base}+f3", name=f"{label} female", engine=self.id,
                                    language=_bcp47(base), language_name=label, gender="female", quality="robotic"))
        self._voices = voices
        return voices

    def has_voice(self, voice: str) -> bool:
        return bool(self.binary())

    def synthesize(self, text, voice, speed=1.0, language=None, sentence_pause=0.25):
        binary = self.binary()
        if not binary:
            raise TTSError("espeak-ng is not installed")
        words_per_minute = str(int(max(80, min(450, 165 * speed))))
        command = [binary, "-v", voice or "en-us", "-s", words_per_minute, "-b", "1", "--stdout", "--stdin"]
        with self.lock:
            proc = subprocess.run(command, input=text.encode("utf-8"), capture_output=True, timeout=600, check=False)
        if proc.returncode != 0 or not proc.stdout:
            raise TTSError("espeak-ng failed: " + proc.stderr.decode(errors="replace")[-300:])
        try:
            return parse_wav_bytes(proc.stdout)
        except AudioError as exc:
            raise TTSError(f"espeak-ng returned invalid audio: {exc}") from exc


def _bcp47(code: str) -> str:
    code = re.sub(r"-x-.*$", "", code)
    if code == "en":
        return "en-GB"
    parts = code.split("-")
    if len(parts) >= 2 and len(parts[1]) == 2:
        return f"{parts[0]}-{parts[1].upper()}"
    return code
