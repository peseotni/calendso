"""Split chapter text into speakable segments.

A chapter becomes a flat list of ``Segment``s: speech chunks (sized for the
TTS engine, split at sentence boundaries, optionally tagged as dialogue) and
explicit pauses (sentence, paragraph, section breaks).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from ..settings_store import CleanupOptions
from .cleanup import clean_for_speech, is_section_break, skip_paragraph
from .lexicon import Lexicon

ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "mt", "no", "vol", "fig",
    "gen", "col", "lt", "capt", "sgt", "rev", "hon", "inc", "ltd", "co", "corp", "jan", "feb",
    "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "approx", "dept",
    "est", "govt", "e.g", "i.e", "a.m", "p.m", "u.s", "u.k", "ch", "pp", "p", "ca", "cf",
    "z.b", "bzw", "usw", "ggf", "nr", "s", "m", "mme", "mlle", "sra", "sr", "dra",
}
_SENTENCE_END_RE = re.compile(r"([.!?…]+|[。！？]+)([\"”’»)\]]*)(\s*)")
_ROMAN_RE = re.compile(r"\b(Chapter|Part|Book|Volume|Act|Scene|Section|Kapitel|Teil|Chapitre|Livre)\s+([IVXLCDM]{1,7})\b\.?", re.IGNORECASE)
_LONE_ROMAN_RE = re.compile(r"^\s*([IVXLCDM]{1,7})\.?\s*$")


@dataclass
class Segment:
    kind: str  # "speech" | "pause"
    text: str = ""
    role: str = "narrator"  # narrator | dialogue
    pause: float = 0.0
    weight: int = 0  # source characters represented (for progress)


@dataclass
class SegmentOptions:
    cleanup: CleanupOptions = field(default_factory=CleanupOptions)
    language: str = "en"
    dialogue: bool = False
    max_chars: int = 350
    dialogue_max_chars: int = 350
    sentence_pause: float = 0.25
    paragraph_pause: float = 0.6
    section_pause: float = 1.5


def roman_to_int(value: str) -> int | None:
    numerals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    value = value.upper()
    if not value or any(c not in numerals for c in value):
        return None
    total = 0
    for i, char in enumerate(value):
        current = numerals[char]
        nxt = numerals[value[i + 1]] if i + 1 < len(value) else 0
        total += -current if current < nxt else current
    return total if total > 0 else None


def speakable_heading(text: str) -> str:
    """Normalise headings for speech: roman numerals, ALL CAPS, colons."""
    text = text.strip()
    lone = _LONE_ROMAN_RE.match(text)
    if lone and roman_to_int(lone.group(1)):
        return str(roman_to_int(lone.group(1)))

    def roman(match: re.Match[str]) -> str:
        number = roman_to_int(match.group(2))
        return f"{match.group(1)} {number}" if number else match.group(0)

    text = _ROMAN_RE.sub(roman, text)
    letters = [c for c in text if c.isalpha()]
    if letters and all(c.isupper() for c in letters) and len(text.split()) >= 1 and len(letters) > 3:
        text = text.title()
    return text


def split_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    start = 0
    for match in _SENTENCE_END_RE.finditer(text):
        punct, _closing, space = match.groups()
        end = match.end(2)
        rest = text[match.end():]
        if not rest:
            break
        cjk = punct[0] in "。！？"
        if not cjk:
            if not space:
                continue
            first = rest.lstrip("\"“‘«([")[:1]
            if not (first.isupper() or first.isdigit()):
                continue
            if punct == ".":
                word_match = re.search(r"(\S+)$", text[start:match.start()])
                word = word_match.group(1).lower().lstrip("(\"“‘") if word_match else ""
                if word in ABBREVIATIONS or (len(word) == 1 and word.isalpha()):
                    continue
        sentence = text[start:end].strip()
        if sentence:
            sentences.append(sentence)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def _split_long(sentence: str, max_chars: int) -> list[str]:
    parts = re.split(r"(?<=[,;:])\s+", sentence)
    pieces: list[str] = []
    current = ""
    for part in parts:
        if len(part) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            words = part.split()
            line = ""
            for word in words:
                if line and len(line) + 1 + len(word) > max_chars:
                    pieces.append(line)
                    line = word
                else:
                    line = f"{line} {word}".strip()
            if line:
                pieces.append(line)
            continue
        if current and len(current) + 1 + len(part) > max_chars:
            pieces.append(current)
            current = part
        else:
            current = f"{current} {part}".strip()
    if current:
        pieces.append(current)
    return pieces


def chunk_text(text: str, max_chars: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for sentence in split_sentences(text):
        if len(sentence) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_long(sentence, max_chars))
            continue
        if current and len(current) + 1 + len(sentence) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return [c for c in chunks if _speakable(c)]


def _speakable(text: str) -> bool:
    return any(unicodedata.category(c)[0] in "LN" for c in text)


_OPENERS = {"“": "”", "«": "»", "„": "“", '"': '"', "»": "«", "「": "」", "『": "』"}


def split_dialogue(text: str) -> list[tuple[str, str]]:
    """Split a paragraph into (role, text) parts: quoted speech is 'dialogue'."""
    double_style = any(ch in text for ch in "“\"«„「")
    single_style = not double_style and "‘" in text
    parts: list[tuple[str, str]] = []
    buffer: list[str] = []
    in_quote = False
    closing = ""

    def flush(role: str) -> None:
        chunk = "".join(buffer).strip().lstrip(",;: ").strip()
        buffer.clear()
        if chunk and _speakable(chunk):
            if parts and parts[-1][0] == role:
                parts[-1] = (role, parts[-1][1] + " " + chunk)
            else:
                parts.append((role, chunk))

    for i, ch in enumerate(text):
        prev = text[i - 1] if i else " "
        nxt = text[i + 1] if i + 1 < len(text) else " "
        if not in_quote:
            if double_style and ch in _OPENERS and (ch != "»" or "«" not in text):
                flush("narrator")
                in_quote, closing = True, _OPENERS[ch]
                continue
            if single_style and ch == "‘" and not prev.isalnum():
                flush("narrator")
                in_quote, closing = True, "’"
                continue
        else:
            is_close = ch == closing or (closing == "”" and ch == '"')
            if closing == "’":
                is_close = ch == "’" and not nxt.isalpha()
            if is_close:
                flush("dialogue")
                in_quote = False
                continue
        buffer.append(ch)
    flush("dialogue" if in_quote else "narrator")
    return parts or [("narrator", text)]


def _verse_to_line(paragraph: str) -> str:
    lines = [line.strip() for line in paragraph.split("\n") if line.strip()]
    out = []
    for line in lines:
        if line[-1:].isalnum():
            line += ","
        out.append(line)
    result = " ".join(out)
    return result[:-1] + "." if result.endswith(",") else result


def build_segments(text: str, options: SegmentOptions, lexicon: Lexicon | None = None) -> list[Segment]:
    lexicon = lexicon or Lexicon()
    segments: list[Segment] = []
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    for index, paragraph in enumerate(paragraphs):
        weight = len(paragraph)
        if is_section_break(paragraph):
            segments.append(Segment("pause", pause=options.section_pause, weight=weight))
            continue
        if skip_paragraph(paragraph, options.cleanup):
            segments.append(Segment("pause", pause=0.0, weight=weight))
            continue
        flat = _verse_to_line(paragraph) if "\n" in paragraph else paragraph
        if len(flat) < 120 and (index == 0 or _LONE_ROMAN_RE.match(flat) or flat.isupper()):
            flat = speakable_heading(flat)
        cleaned = lexicon.apply(clean_for_speech(flat, options.cleanup, options.language))
        if not _speakable(cleaned):
            segments.append(Segment("pause", pause=0.0, weight=weight))
            continue
        parts = split_dialogue(cleaned) if options.dialogue else [("narrator", cleaned)]
        speech: list[Segment] = []
        for role, part in parts:
            limit = options.dialogue_max_chars if role == "dialogue" else options.max_chars
            for chunk in chunk_text(part, limit):
                speech.append(Segment("speech", text=chunk, role=role))
        if not speech:
            segments.append(Segment("pause", pause=0.0, weight=weight))
            continue
        total_chars = sum(len(s.text) for s in speech) or 1
        assigned = 0
        for n, seg in enumerate(speech):
            seg.weight = weight - assigned if n == len(speech) - 1 else int(weight * len(seg.text) / total_chars)
            assigned += seg.weight
            if n:
                previous = speech[n - 1]
                gap = options.sentence_pause if previous.role == seg.role else min(0.2, options.sentence_pause)
                segments.append(Segment("pause", pause=gap))
            segments.append(seg)
        segments.append(Segment("pause", pause=options.paragraph_pause))
    # Drop the trailing paragraph pause; the renderer adds the chapter pause.
    while segments and segments[-1].kind == "pause" and segments[-1].weight == 0:
        segments.pop()
    return segments


def heading_in_text(text: str, title: str) -> bool:
    """True when the chapter text already starts with its heading."""
    first = text.strip().split("\n\n", 1)[0].strip()
    if not first:
        return False

    def norm(value: str) -> str:
        return re.sub(r"[\W_]+", " ", unicodedata.normalize("NFKD", value).lower()).strip()

    if norm(first) and (norm(first) == norm(title) or norm(title).startswith(norm(first)) or norm(first).startswith(norm(title))):
        return True
    words = len(first.split())
    return words <= 10 and len(first) < 90 and first[-1:] not in ".!?…\"”’,;" and "\n" not in first
