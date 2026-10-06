"""Synthesise one chapter into a FLAC file."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..settings_store import RenderSettings
from ..text.cleanup import clean_for_speech
from ..text.lexicon import Lexicon
from ..text.segment import Segment, SegmentOptions, build_segments, heading_in_text, speakable_heading
from ..tts import EngineRegistry, TTSError
from .codec import fade_edges, resample

log = logging.getLogger(__name__)

LEAD_IN = 0.4
TITLE_PAUSE = 1.0


@dataclass
class VoiceChoice:
    engine: str
    voice: str


def parse_voice_ref(ref: str | None, default_engine: str) -> VoiceChoice | None:
    """'piper:en_US-amy-medium' -> VoiceChoice; bare ids use the default engine."""
    if not ref:
        return None
    engine, sep, voice = ref.partition(":")
    if sep and engine in ("kokoro", "piper", "espeak", "openai", "edge"):
        return VoiceChoice(engine, voice)
    return VoiceChoice(default_engine, ref)


def chapter_fingerprint(
    title: str, text: str, settings: RenderSettings, voice_override: str | None, lexicon: Lexicon
) -> str:
    relevant = settings.model_dump(
        include={"engine", "voice", "speed", "language", "dialogue_enabled", "dialogue_engine",
                 "dialogue_voice", "announce_chapters", "sentence_pause", "paragraph_pause",
                 "section_pause", "chapter_pause", "cleanup"}
    )
    language = settings.language or "en"
    cleanup = settings.cleanup
    # Only pronunciation rules that occur in this chapter change its audio.
    rules = lexicon.fingerprint_for(
        f"{title}\n\n{text}",
        variant=cleanup.model_dump_json() + language,
        expand=lambda value: clean_for_speech(value, cleanup, language),
    )
    payload = json.dumps([title, text, relevant, voice_override, rules], sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def plan_segments(
    title: str,
    text: str,
    settings: RenderSettings,
    registry: EngineRegistry,
    lexicon: Lexicon,
    voice_override: str | None = None,
) -> tuple[list[Segment], dict[str, VoiceChoice], str]:
    narrator = parse_voice_ref(voice_override, settings.engine) or VoiceChoice(settings.engine, settings.voice)
    roles = {"narrator": narrator}
    dialogue = None
    if settings.dialogue_enabled and settings.dialogue_voice:
        dialogue = VoiceChoice(settings.dialogue_engine or settings.engine, settings.dialogue_voice)
        roles["dialogue"] = dialogue
    narrator_engine = registry.get(narrator.engine)
    language = settings.language or narrator_engine.language_for_voice(narrator.voice) or "en"
    options = SegmentOptions(
        cleanup=settings.cleanup,
        language=language,
        dialogue=dialogue is not None,
        max_chars=narrator_engine.max_chars,
        dialogue_max_chars=registry.get(dialogue.engine).max_chars if dialogue else narrator_engine.max_chars,
        sentence_pause=settings.sentence_pause,
        paragraph_pause=settings.paragraph_pause,
        section_pause=settings.section_pause,
    )
    segments: list[Segment] = []
    if settings.announce_chapters and title.strip() and not heading_in_text(text, title):
        spoken = speakable_heading(title).replace(":", ".").strip()
        if spoken and spoken[-1] not in ".!?":
            spoken += "."
        segments.append(Segment("speech", text=lexicon.apply(spoken), role="narrator"))
        segments.append(Segment("pause", pause=TITLE_PAUSE))
    segments.extend(build_segments(text, options, lexicon))
    return segments, roles, language


class FlacWriter:
    """Streams float audio into a FLAC file once the sample rate is known."""

    def __init__(self, path: Path):
        self.path = path
        self.sample_rate: int | None = None
        self.frames = 0
        self._file = None
        self._pending_silence = 0.0

    def silence(self, seconds: float) -> None:
        if seconds <= 0:
            return
        if self.sample_rate is None:
            self._pending_silence += seconds
        else:
            self.write(np.zeros(int(seconds * self.sample_rate), dtype=np.float32))

    def write(self, audio: np.ndarray, sample_rate: int | None = None) -> None:
        if self._file is None:
            import soundfile as sf

            self.sample_rate = sample_rate or self.sample_rate or 24000
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = sf.SoundFile(str(self.path), "w", samplerate=self.sample_rate, channels=1,
                                      format="FLAC", subtype="PCM_16")
            if self._pending_silence:
                pending, self._pending_silence = self._pending_silence, 0.0
                self.silence(pending)
        elif sample_rate and sample_rate != self.sample_rate:
            audio = resample(audio, sample_rate, self.sample_rate)  # type: ignore[arg-type]
        if audio.size:
            self._file.write(np.clip(audio, -1.0, 1.0).astype(np.float32))
            self.frames += int(audio.size)

    def close(self) -> float:
        if self._file is None:
            self.write(np.zeros(int(0.5 * 24000), dtype=np.float32), 24000)
        assert self._file is not None
        self._file.close()
        return self.frames / float(self.sample_rate or 24000)


def render_chapter(
    title: str,
    text: str,
    settings: RenderSettings,
    registry: EngineRegistry,
    lexicon: Lexicon,
    out_path: Path,
    voice_override: str | None = None,
    on_progress: Callable[[int], None] | None = None,
    check_cancelled: Callable[[], None] | None = None,
    log_warning: Callable[[str], None] | None = None,
) -> float:
    """Render a chapter, returning its duration in seconds."""
    segments, roles, language = plan_segments(title, text, settings, registry, lexicon, voice_override)
    tmp_path = out_path.with_name(out_path.stem + ".part.flac")
    writer = FlacWriter(tmp_path)
    writer.silence(LEAD_IN)
    try:
        for segment in segments:
            if check_cancelled:
                check_cancelled()
            if segment.kind == "pause":
                writer.silence(segment.pause)
            else:
                choice = roles.get(segment.role, roles["narrator"])
                engine = registry.get(choice.engine)
                voice_language = settings.language or (language if choice is roles["narrator"] else None)
                audio, sample_rate = _synthesize_with_retry(
                    engine, segment.text, choice.voice, settings.speed, voice_language,
                    settings.sentence_pause, log_warning,
                )
                if audio.size:
                    writer.write(fade_edges(audio, sample_rate), sample_rate)
            if on_progress and segment.weight:
                on_progress(segment.weight)
        writer.silence(settings.chapter_pause)
        duration = writer.close()
    except BaseException:
        if writer._file is not None:
            writer._file.close()
        tmp_path.unlink(missing_ok=True)
        raise
    tmp_path.replace(out_path)
    return duration


def _synthesize_with_retry(engine, text, voice, speed, language, sentence_pause, log_warning):
    try:
        return engine.synthesize(text, voice, speed=speed, language=language, sentence_pause=sentence_pause)
    except TTSError:
        raise
    except Exception as exc:  # noqa: BLE001 - engine specific glitches
        log.warning("Synthesis failed (%s), retrying: %r", exc, text[:80])
        try:
            return engine.synthesize(text, voice, speed=speed, language=language, sentence_pause=sentence_pause)
        except Exception as exc2:  # noqa: BLE001
            if len(text) < 40:
                if log_warning:
                    log_warning(f"Skipped unspeakable text {text!r}: {exc2}")
                return np.zeros(0, dtype=np.float32), 24000
            raise TTSError(f"Synthesis failed for text {text[:60]!r}: {exc2}") from exc2


def preview(
    text: str,
    settings: RenderSettings,
    registry: EngineRegistry,
    lexicon: Lexicon,
    max_chars: int = 600,
    title: str = "",
) -> tuple[np.ndarray, int]:
    """Synthesise a short sample into memory."""
    sample = text[:max_chars]
    if len(text) > max_chars:
        cut = max(sample.rfind(". "), sample.rfind("\n\n"), sample.rfind("? "), sample.rfind("! "))
        if cut > max_chars // 3:
            sample = sample[: cut + 1]
    segments, roles, language = plan_segments(title, sample, settings, registry, lexicon)
    parts: list[np.ndarray] = []
    rate: int | None = None
    for segment in segments:
        if segment.kind == "pause":
            if rate:
                parts.append(np.zeros(int(segment.pause * rate), dtype=np.float32))
            continue
        choice = roles.get(segment.role, roles["narrator"])
        engine = registry.get(choice.engine)
        audio, sample_rate = engine.synthesize(
            segment.text, choice.voice, speed=settings.speed,
            language=settings.language or (language if choice is roles["narrator"] else None),
            sentence_pause=settings.sentence_pause,
        )
        if rate is None:
            rate = sample_rate
        elif sample_rate != rate:
            audio = resample(audio, sample_rate, rate)
        parts.append(fade_edges(audio, rate))
    if not parts or rate is None:
        raise TTSError("Nothing to speak in this text.")
    return np.concatenate(parts), rate
