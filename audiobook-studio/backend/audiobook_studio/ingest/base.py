"""Shared data structures and heuristics for ebook parsers."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

ProgressFn = Callable[[float, str], None]


class IngestError(Exception):
    """A user-facing error while reading a source document."""


@dataclass
class ParsedChapter:
    title: str
    text: str
    kind: str = "chapter"  # front | chapter | back
    include: bool = True

    @property
    def word_count(self) -> int:
        return count_words(self.text)


@dataclass
class ParsedBook:
    title: str = ""
    subtitle: str = ""
    authors: list[str] = field(default_factory=list)
    language: str = ""
    publisher: str = ""
    year: str = ""
    description: str = ""
    isbn: str = ""
    series: str = ""
    series_index: str = ""
    subjects: list[str] = field(default_factory=list)
    cover: bytes | None = None
    chapters: list[ParsedChapter] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Para:
    """A paragraph with an optional heading level (0 = body text)."""

    text: str
    level: int = 0


# --------------------------------------------------------------------------
# Inline text helpers

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­"), None)
_WS_RE = re.compile(r"[ \t\r\f\v  -   　]+")
_LIGATURES = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
}


def clean_inline(text: str) -> str:
    """Normalise whitespace inside a paragraph, keeping explicit line breaks."""
    if not text:
        return ""
    text = text.translate(_ZERO_WIDTH)
    for lig, rep in _LIGATURES.items():
        if lig in text:
            text = text.replace(lig, rep)
    lines = [_WS_RE.sub(" ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def count_words(text: str) -> int:
    return len(re.findall(r"\w+", text))


def join_wrapped(left: str, right: str) -> str:
    """Join two hard-wrapped lines, undoing end-of-line hyphenation."""
    if left.endswith("-") and len(left) > 1 and left[-2].isalpha() and right[:1].islower():
        return left[:-1] + right
    if left.endswith(("—", "–", "/")):
        return left + right
    return left + " " + right


def paras_to_text(paragraphs: list[str]) -> str:
    return "\n\n".join(p for p in (clean_inline(x) for x in paragraphs) if p)


def normalize_title(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).lower()
    return re.sub(r"[\W_]+", " ", text).strip()


def strip_html(text: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>|</p>", "\n", text or "")
    text = re.sub(r"<[^>]+>", "", text)
    import html

    return "\n".join(line.strip() for line in html.unescape(text).splitlines() if line.strip())


def first_year(value: str) -> str:
    match = re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b", value or "")
    return match.group(1) if match else ""


ISBN_RE = re.compile(r"(97[89][\d-]{10,14}|\b[\d-]{9,12}[\dXx]\b)")


def extract_isbn(value: str) -> str:
    value = (value or "").replace("urn:isbn:", "")
    match = ISBN_RE.search(value)
    if not match:
        return ""
    digits = re.sub(r"[^\dXx]", "", match.group(1))
    return digits if len(digits) in (10, 13) else ""


# --------------------------------------------------------------------------
# Chapter heuristics

_NUMBER_WORDS = (
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
    r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|"
    r"seventy|eighty|ninety|hundred|first|second|third|fourth|fifth|sixth|seventh|"
    r"eighth|ninth|tenth|last|final"
)
CHAPTER_RE = re.compile(
    r"^\s*(?:"
    r"(?:chapter|chap\.|part|book|volume|act|scene|section|kapitel|teil|chapitre|partie|"
    r"cap[ií]tulo|capitolo|parte|hoofdstuk|rozdział|глава)\s+"
    r"(?:\d+|[ivxlcdm]+|(?:" + _NUMBER_WORDS + r")(?:[\s-](?:" + _NUMBER_WORDS + r"))*)\b"
    r"|prologue|prolog|epilogue|epilog|introduction|preface|foreword|afterword|"
    r"interlude|postscript|acknowledg(?:e)?ments|appendix|vorwort|nachwort|einleitung|"
    r"prólogo|épilogue|prologo|epilogo"
    r")",
    re.IGNORECASE,
)
_LONE_NUMBER_RE = re.compile(r"^\s*(?:\d{1,3}|[IVXLC]{1,7})\.?\s*$")

FRONT_MATTER_RE = re.compile(
    r"\b(cover|title ?page|half ?title|copyright|contents|table of contents|toc|"
    r"also by|other books|books by|praise for|colophon|imprint|newsletter|sign up|"
    r"index|frontmatter|front matter|landmarks|about the publisher)\b",
    re.IGNORECASE,
)
_BOILERPLATE_RE = re.compile(
    r"(all rights reserved|isbn[\s:-]*\d|copyright\s*(?:©|\(c\))?\s*\d{4}|"
    r"project gutenberg license|published by|printed in|library of congress)",
    re.IGNORECASE,
)


def is_heading_like(text: str) -> bool:
    text = text.strip()
    if not text or "\n" in text or len(text) > 120:
        return False
    if CHAPTER_RE.match(text) and count_words(text) <= 12:
        return True
    return bool(_LONE_NUMBER_RE.match(text))


def looks_like_front_matter(title: str, text: str) -> bool:
    """Guess whether a section is non-narrative (cover, copyright, TOC...)."""
    words = count_words(text)
    if FRONT_MATTER_RE.search(title or "") and words < 2500:
        return True
    if words < 400 and len(_BOILERPLATE_RE.findall(text)) >= 1:
        return True
    if words < 8 and not is_heading_like(text):
        return True
    return False


def chapters_from_paras(
    paras: list[Para], fallback_title: str = "Part", target_words: int = 4000
) -> list[ParsedChapter]:
    """Split a flat list of paragraphs into chapters.

    Strategy: real headings first (the outermost level that occurs at least
    twice), then chapter-like lines ("Chapter 3", "IV", "Prologue"), finally
    evenly sized parts.
    """
    paras = [p for p in paras if p.text.strip()]
    if not paras:
        return []

    levels = Counter(p.level for p in paras if p.level > 0)
    split_level = 0
    for level in sorted(levels):
        if levels[level] >= 2:
            split_level = level
            break
    if split_level:
        starts = [i for i, p in enumerate(paras) if 0 < p.level <= split_level]
    else:
        starts = [i for i, p in enumerate(paras) if is_heading_like(p.text)]
        if len(starts) < 2:
            starts = []

    if not starts:
        return _split_evenly(paras, fallback_title, target_words)

    chapters: list[ParsedChapter] = []
    if starts[0] > 0:
        front = paras[: starts[0]]
        text = "\n\n".join(p.text for p in front)
        title = next((p.text for p in front if p.level > 0), "Opening")
        chapters.append(
            ParsedChapter(
                title=title[:200],
                text=text,
                kind="front",
                include=not looks_like_front_matter(title, text),
            )
        )

    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(paras)
        block = paras[start:end]
        title = block[0].text.strip()
        # "Chapter 3" / "III" followed by a short subtitle -> "Chapter 3: The Storm"
        if len(block) > 1:
            nxt = block[1]
            bare = bool(_LONE_NUMBER_RE.match(title) or (CHAPTER_RE.match(title) and count_words(title) <= 3))
            if bare and (nxt.level > 0 or _short(nxt.text)) and not is_heading_like(nxt.text):
                title = f"{title.rstrip('.:')}: {nxt.text.strip()}"
        text = "\n\n".join(p.text for p in block)
        chapters.append(ParsedChapter(title=title[:200], text=text))

    return _merge_empty_headings(chapters)


def _short(text: str) -> bool:
    return count_words(text) <= 10 and len(text) <= 100 and not text.rstrip().endswith((".", "!", "?"))


def _merge_empty_headings(chapters: list[ParsedChapter]) -> list[ParsedChapter]:
    """A chapter consisting only of its heading (e.g. "Part One") is kept, but
    two consecutive heading-only chapters are merged."""
    result: list[ParsedChapter] = []
    for chapter in chapters:
        if (
            result
            and count_words(result[-1].text) <= 6
            and result[-1].kind == "chapter"
            and normalize_title(result[-1].text) == normalize_title(result[-1].title)
        ):
            previous = result.pop()
            chapter = ParsedChapter(
                title=f"{previous.title} – {chapter.title}",
                text=previous.text + "\n\n" + chapter.text,
                kind=chapter.kind,
                include=chapter.include,
            )
        result.append(chapter)
    return result


def _split_evenly(paras: list[Para], title: str, target_words: int) -> list[ParsedChapter]:
    total = sum(count_words(p.text) for p in paras)
    if total <= target_words * 1.5:
        return [ParsedChapter(title=title if title != "Part" else "Full text", text="\n\n".join(p.text for p in paras))]
    chapters: list[ParsedChapter] = []
    current: list[str] = []
    words = 0
    for p in paras:
        current.append(p.text)
        words += count_words(p.text)
        if words >= target_words:
            chapters.append(ParsedChapter(title=f"{title} {len(chapters) + 1}", text="\n\n".join(current)))
            current, words = [], 0
    if current:
        if chapters and words < target_words * 0.3:
            chapters[-1].text += "\n\n" + "\n\n".join(current)
        else:
            chapters.append(ParsedChapter(title=f"{title} {len(chapters) + 1}", text="\n\n".join(current)))
    return chapters


# --------------------------------------------------------------------------
# Language guess (used when the source has no language metadata)

_STOPWORDS = {
    "en": "the and of to a in is that it was he for with as his on be at by i you her she had not",
    "de": "der die und das ist nicht ein eine zu den von mit sich des auf für im dem ich sie er es",
    "fr": "le la les et des est une un du que dans pas pour qui sur il au ne je se elle avec",
    "es": "el la de que y en los las por un una con no para es se del lo su al como más",
    "it": "il di che è la e un una per non sono del della le gli si con mi ho anche nel",
    "pt": "o a de que e do da em um uma para com não os as se na no mais por foi ao",
    "nl": "de het een en van is dat niet op te zijn voor met die er maar ook om ik je",
}
_STOPWORD_SETS = {lang: set(words.split()) for lang, words in _STOPWORDS.items()}


def guess_language(text: str) -> str:
    tokens = re.findall(r"[^\W\d_]+", text[:60000].lower())
    if len(tokens) < 20:
        return ""
    scores = {lang: sum(1 for t in tokens if t in words) for lang, words in _STOPWORD_SETS.items()}
    best = max(scores, key=lambda k: scores[k])
    if scores[best] < len(tokens) * 0.08:
        return ""
    return best


def normalize_language(value: str) -> str:
    """'en-US', 'eng', 'English' -> 'en' style short codes (keeps region)."""
    value = (value or "").strip()
    if not value:
        return ""
    names = {
        "english": "en", "eng": "en", "german": "de", "deutsch": "de", "ger": "de", "deu": "de",
        "french": "fr", "fre": "fr", "fra": "fr", "spanish": "es", "spa": "es", "italian": "it",
        "ita": "it", "portuguese": "pt", "por": "pt", "dutch": "nl", "nld": "nl", "dut": "nl",
        "japanese": "ja", "jpn": "ja", "chinese": "zh", "zho": "zh", "chi": "zh", "russian": "ru",
        "rus": "ru", "polish": "pl", "pol": "pl", "hindi": "hi", "hin": "hi",
    }
    lowered = value.lower().replace("_", "-")
    if lowered in names:
        return names[lowered]
    parts = lowered.split("-")
    if len(parts[0]) == 2:
        return parts[0] + ("-" + parts[1].upper() if len(parts) > 1 and len(parts[1]) == 2 else "")
    return names.get(parts[0], "")
