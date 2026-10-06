"""Text normalisation applied right before synthesis."""

from __future__ import annotations

import re

from ..settings_store import CleanupOptions

_URL_RE = re.compile(r"\b(?:https?://|www\.)[^\s<>\"]+[^\s<>\".,;:!?)\]]", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_FOOTNOTE_RE = re.compile(r"(?<=[\w.,;:!?\"”’)])\s?(?:\[\d{1,3}\]|\[[a-z]\]|[¹²³⁴⁵⁶⁷⁸⁹⁰]+|\*{1,3}(?=\s|$)|[†‡]+)")
_BRACKETED_RE = re.compile(r"\s*\[[^\]]{1,200}\]")
_REPEATED_PUNCT_RE = re.compile(r"([!?])\1+")
_DOTS_RE = re.compile(r"\.{4,}")
_SPACED_DOTS_RE = re.compile(r"(?:\.\s){2,}\.")

# English abbreviations that TTS engines often mispronounce.
_ABBREVIATIONS = [
    (r"\bMr\.", "Mister"),
    (r"\bMrs\.", "Missus"),
    (r"\bMs\.", "Miz"),
    (r"\bDr\.(?=\s+[A-Z])", "Doctor"),
    (r"\bProf\.(?=\s+[A-Z])", "Professor"),
    (r"\bSt\.(?=\s+[A-Z])", "Saint"),
    (r"\bJr\.", "Junior"),
    (r"\bSr\.(?=\s|,|$)", "Senior"),
    (r"\bCapt\.", "Captain"),
    (r"\bLt\.", "Lieutenant"),
    (r"\bSgt\.", "Sergeant"),
    (r"\bCol\.(?=\s+[A-Z])", "Colonel"),
    (r"\bGen\.(?=\s+[A-Z])", "General"),
    (r"\bGov\.(?=\s+[A-Z])", "Governor"),
    (r"\bRev\.(?=\s+[A-Z])", "Reverend"),
    (r"\bHon\.(?=\s+[A-Z])", "Honorable"),
    (r"\bvs\.", "versus"),
    (r"\betc\.", "et cetera."),
    (r"\be\.g\.", "for example"),
    (r"\bi\.e\.", "that is"),
    (r"\bapprox\.", "approximately"),
    (r"\bNo\.(?=\s*\d)", "Number"),
    (r"\bvol\.(?=\s*\d)", "volume"),
    (r"\bch\.(?=\s*\d)", "chapter"),
    (r"\bp\.(?=\s*\d)", "page"),
    (r"\bpp\.(?=\s*\d)", "pages"),
    (r"(?<=\d)\s?%", " percent"),
    (r"&", " and "),
]
_ABBREVIATION_RES = [(re.compile(p), r) for p, r in _ABBREVIATIONS]


def clean_for_speech(text: str, options: CleanupOptions, language: str = "en") -> str:
    if options.remove_urls:
        text = _URL_RE.sub("", text)
        text = _EMAIL_RE.sub("", text)
    if options.remove_footnote_markers:
        text = _FOOTNOTE_RE.sub("", text)
    if options.remove_bracketed_text:
        text = _BRACKETED_RE.sub("", text)
    if options.expand_abbreviations and (language or "en").lower().startswith("en"):
        for pattern, replacement in _ABBREVIATION_RES:
            text = pattern.sub(replacement, text)
    if options.normalize_punctuation:
        text = _SPACED_DOTS_RE.sub("…", text)
        text = _DOTS_RE.sub("…", text)
        text = _REPEATED_PUNCT_RE.sub(r"\1", text)
        text = text.replace("_", " ").replace("~", " ")
        text = re.sub(r"\s*[—―]\s*", ", ", text)  # em dash -> natural pause
        text = re.sub(r"(?<=\w)\s+–\s+(?=\w)", ", ", text)  # spaced en dash
        text = re.sub(r"[*#|<>=^`{}\\]+", " ", text)
        text = re.sub(r",\s*([.!?…])", r"\1", text)
        text = re.sub(r"^\s*,\s*", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" +([,.;:!?…])", r"\1", text)
    return text.strip()


_SECTION_BREAK_RE = re.compile(r"^\s*(?:[*•·~#=_\-–—]\s*){1,7}$|^\s*(?:\*\s*){3}$|^\s*§\s*$")


def is_section_break(paragraph: str) -> bool:
    return bool(_SECTION_BREAK_RE.match(paragraph))


def skip_paragraph(paragraph: str, options: CleanupOptions) -> bool:
    if options.skip_all_caps_headers:
        letters = [c for c in paragraph if c.isalpha()]
        if letters and len(paragraph) < 80 and all(c.isupper() for c in letters):
            return True
    return False
