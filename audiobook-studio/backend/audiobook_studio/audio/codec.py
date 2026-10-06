"""Low level audio helpers: WAV parsing, decoding via ffmpeg, resampling."""

from __future__ import annotations

import io
import shutil
import struct
import subprocess
import wave

import numpy as np


class AudioError(RuntimeError):
    pass


def ffmpeg_binary() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise AudioError("ffmpeg is not installed or not on PATH.")
    return path


def parse_wav_bytes(data: bytes) -> tuple[np.ndarray, int]:
    """Parse 16-bit PCM WAV bytes, tolerating bogus sizes in streamed headers."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise AudioError("Not a WAV file")
    pos = 12
    sample_rate, channels, bits = 22050, 1, 16
    audio_format = 1
    while pos + 8 <= len(data):
        chunk_id = data[pos : pos + 4]
        (size,) = struct.unpack("<I", data[pos + 4 : pos + 8])
        body = pos + 8
        if chunk_id == b"fmt ":
            audio_format, channels, sample_rate = struct.unpack("<HHI", data[body : body + 8])
            (bits,) = struct.unpack("<H", data[body + 14 : body + 16])
        elif chunk_id == b"data":
            end = len(data) if size in (0, 0xFFFFFFFF) or body + size > len(data) else body + size
            raw = data[body:end]
            if audio_format == 3 and bits == 32:
                samples = np.frombuffer(raw[: len(raw) // 4 * 4], dtype="<f4").astype(np.float32)
            elif bits == 16:
                samples = np.frombuffer(raw[: len(raw) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
            elif bits == 32:
                samples = np.frombuffer(raw[: len(raw) // 4 * 4], dtype="<i4").astype(np.float32) / 2147483648.0
            elif bits == 8:
                samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
            else:
                raise AudioError(f"Unsupported WAV sample width: {bits}")
            if channels > 1:
                samples = samples[: len(samples) // channels * channels].reshape(-1, channels).mean(axis=1)
            return samples, sample_rate
        pos = body + size + (size & 1)
    raise AudioError("WAV file has no data chunk")


def decode_audio_bytes(data: bytes, sample_rate: int = 24000) -> tuple[np.ndarray, int]:
    """Decode any audio format ffmpeg understands into mono float32."""
    if data[:4] == b"RIFF":
        try:
            return parse_wav_bytes(data)
        except AudioError:
            pass
    proc = subprocess.run(
        [ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
         "-f", "f32le", "-ac", "1", "-ar", str(sample_rate), "pipe:1"],
        input=data,
        capture_output=True,
        timeout=900,
        check=False,
    )
    if proc.returncode != 0:
        raise AudioError("Could not decode audio: " + proc.stderr.decode(errors="replace")[-500:])
    return np.frombuffer(proc.stdout, dtype=np.float32).copy(), sample_rate


def resample(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate or audio.size == 0:
        return audio
    try:
        import soxr

        return soxr.resample(audio, source_rate, target_rate).astype(np.float32)
    except ImportError:  # pragma: no cover - soxr is a dependency
        duration = audio.size / source_rate
        target_len = int(round(duration * target_rate))
        x_old = np.linspace(0, duration, num=audio.size, endpoint=False)
        x_new = np.linspace(0, duration, num=target_len, endpoint=False)
        return np.interp(x_new, x_old, audio).astype(np.float32)


def to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


def encode_preview(audio: np.ndarray, sample_rate: int, fmt: str = "mp3") -> tuple[bytes, str]:
    """Encode a short clip for the browser (mp3 keeps previews small)."""
    wav = to_wav_bytes(audio, sample_rate)
    if fmt == "wav":
        return wav, "audio/wav"
    proc = subprocess.run(
        [ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
         "-c:a", "libmp3lame", "-b:a", "96k", "-f", "mp3", "pipe:1"],
        input=wav,
        capture_output=True,
        timeout=300,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        return wav, "audio/wav"
    return proc.stdout, "audio/mpeg"


def fade_edges(audio: np.ndarray, sample_rate: int, ms: float = 4.0) -> np.ndarray:
    n = min(int(sample_rate * ms / 1000), audio.size // 2)
    if n <= 1:
        return audio
    audio = audio.copy()
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
    audio[:n] *= ramp
    audio[-n:] *= ramp[::-1]
    return audio
