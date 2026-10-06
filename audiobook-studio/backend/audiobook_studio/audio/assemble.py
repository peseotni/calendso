"""Encode rendered chapters into final audiobook files with ffmpeg."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .codec import AudioError, ffmpeg_binary
from .tags import BookTags, write_tags

log = logging.getLogger(__name__)

LOUDNORM = "loudnorm=I=-18:TP=-1.5:LRA=11"


@dataclass
class ChapterAudio:
    title: str
    path: Path
    duration: float


@dataclass
class OutputFile:
    path: Path
    duration: float
    title: str


@dataclass
class AssemblyResult:
    files: list[OutputFile]
    chapters: list[dict]  # {"title", "start", "end"} on the global timeline
    duration: float
    format: str


def ffprobe(path: Path) -> dict:
    binary = shutil.which("ffprobe")
    if not binary:
        raise AudioError("ffprobe is not installed")
    proc = subprocess.run(
        [binary, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", "-show_chapters", str(path)],
        capture_output=True, text=True, timeout=120, check=False,
    )
    if proc.returncode != 0:
        raise AudioError(f"ffprobe failed for {path.name}: {proc.stderr[-300:]}")
    return json.loads(proc.stdout or "{}")


def probe_duration(path: Path) -> float:
    try:
        return float(ffprobe(path).get("format", {}).get("duration") or 0.0)
    except (AudioError, ValueError):
        return 0.0


def run_ffmpeg(
    args: list[str],
    total_seconds: float = 0.0,
    on_progress: Callable[[float], None] | None = None,
    check_cancelled: Callable[[], None] | None = None,
) -> None:
    command = [ffmpeg_binary(), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-progress", "pipe:1", *args]
    log.debug("Running %s", " ".join(command))
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stderr_lines: list[str] = []

    def drain() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_lines.append(line)
            del stderr_lines[:-50]

    thread = threading.Thread(target=drain, daemon=True)
    thread.start()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if check_cancelled:
                check_cancelled()
            key, _, value = line.strip().partition("=")
            if key in ("out_time_us", "out_time_ms") and total_seconds > 0 and on_progress:
                try:
                    on_progress(min(1.0, int(value) / 1e6 / total_seconds))
                except ValueError:
                    pass
        proc.wait()
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    finally:
        thread.join(timeout=5)
    if proc.returncode != 0:
        raise AudioError("ffmpeg failed: " + "".join(stderr_lines)[-800:])


def _escape_meta(value: str) -> str:
    return re.sub(r"([=;#\\\n])", r"\\\1", value.replace("\r", ""))


def ffmetadata(book: BookTags, chapters: list[dict]) -> str:
    lines = [";FFMETADATA1"]
    for key, value in (
        ("title", book.album), ("album", book.album), ("artist", book.author), ("album_artist", book.author),
        ("composer", book.narrator), ("genre", book.genre), ("date", book.year), ("comment", book.description[:1000]),
    ):
        if value:
            lines.append(f"{key}={_escape_meta(value)}")
    for chapter in chapters:
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={int(round(chapter['start'] * 1000))}",
            f"END={int(round(chapter['end'] * 1000))}",
            f"title={_escape_meta(chapter['title'])}",
        ]
    return "\n".join(lines) + "\n"


def timeline(chapters: list[ChapterAudio]) -> list[dict]:
    result, position = [], 0.0
    for chapter in chapters:
        result.append({"title": chapter.title, "start": round(position, 3), "end": round(position + chapter.duration, 3)})
        position += chapter.duration
    return result


def _concat_list(chapters: list[ChapterAudio], folder: Path) -> Path:
    path = folder / "concat.txt"
    lines = []
    for chapter in chapters:
        escaped = str(chapter.path.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _filters(normalize: bool, sample_rate: int) -> list[str]:
    if not normalize:
        return []
    return ["-af", f"{LOUDNORM},aresample={sample_rate}"]


def _sample_rate(chapters: list[ChapterAudio]) -> int:
    try:
        import soundfile as sf

        return int(sf.info(str(chapters[0].path)).samplerate)
    except Exception:  # noqa: BLE001
        return 24000


def assemble(
    chapters: list[ChapterAudio],
    out_dir: Path,
    basename: str,
    fmt: str,
    book: BookTags,
    cover: bytes | None,
    bitrate: str = "64k",
    normalize: bool = True,
    on_progress: Callable[[float], None] | None = None,
    check_cancelled: Callable[[], None] | None = None,
) -> AssemblyResult:
    if not chapters:
        raise AudioError("There are no rendered chapters to assemble.")
    out_dir.mkdir(parents=True, exist_ok=True)
    marks = timeline(chapters)
    total = sum(c.duration for c in chapters)
    sample_rate = _sample_rate(chapters)

    if fmt in ("m4b", "mp3_single"):
        ext = "m4b" if fmt == "m4b" else "mp3"
        target = out_dir / f"{basename}.{ext}"
        with tempfile.TemporaryDirectory(dir=out_dir) as tmp:
            tmp_dir = Path(tmp)
            concat = _concat_list(chapters, tmp_dir)
            meta = tmp_dir / "meta.txt"
            meta.write_text(ffmetadata(book, marks), encoding="utf-8")
            partial = tmp_dir / f"out.{ext}"
            if fmt == "m4b":
                codec = ["-c:a", "aac", "-b:a", bitrate, "-movflags", "+faststart", "-f", "ipod"]
            else:
                codec = ["-c:a", "libmp3lame", "-b:a", bitrate, "-id3v2_version", "3", "-f", "mp3"]
            run_ffmpeg(
                ["-f", "concat", "-safe", "0", "-i", str(concat), "-i", str(meta),
                 "-map", "0:a", "-map_metadata", "1", "-map_chapters", "1", "-ac", "1",
                 *_filters(normalize, sample_rate), "-ar", str(sample_rate), *codec, str(partial)],
                total, on_progress, check_cancelled,
            )
            write_tags(partial, book, cover)
            shutil.move(str(partial), target)
        duration = probe_duration(target) or total
        return AssemblyResult([OutputFile(target, duration, book.album)], marks, duration, fmt)

    if fmt in ("mp3", "opus"):
        ext = fmt
        files: list[OutputFile] = []
        width = max(2, len(str(len(chapters))))
        done = 0.0
        for index, chapter in enumerate(chapters, start=1):
            safe_title = _safe_name(chapter.title)[:80] or f"Chapter {index}"
            target = out_dir / f"{index:0{width}d} - {safe_title}.{ext}"
            partial = out_dir / f".{index:0{width}d}.part.{ext}"
            if fmt == "mp3":
                codec = ["-c:a", "libmp3lame", "-b:a", bitrate, "-f", "mp3"]
                rate = sample_rate
            else:
                codec = ["-c:a", "libopus", "-b:a", bitrate, "-application", "audio", "-f", "ogg"]
                rate = 48000
            base = done

            def progress(fraction: float, base=base, length=chapter.duration) -> None:
                if on_progress and total:
                    on_progress(min(1.0, (base + fraction * length) / total))

            run_ffmpeg(["-i", str(chapter.path), "-ac", "1", *_filters(normalize, rate), "-ar", str(rate), *codec, str(partial)],
                       chapter.duration, progress, check_cancelled)
            write_tags(partial, book, cover, track=(index, len(chapters)), track_title=chapter.title)
            partial.replace(target)
            files.append(OutputFile(target, chapter.duration, chapter.title))
            done += chapter.duration
        return AssemblyResult(files, marks, total, fmt)

    raise AudioError(f"Unknown output format: {fmt}")


def _safe_name(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value
