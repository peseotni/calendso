from __future__ import annotations

from audiobook_studio.library.paths import render_template, sanitize_component
from audiobook_studio.settings_store import CleanupOptions
from audiobook_studio.text.cleanup import clean_for_speech
from audiobook_studio.text.lexicon import Lexicon, Rule
from audiobook_studio.text.segment import (
    SegmentOptions,
    build_segments,
    chunk_text,
    heading_in_text,
    speakable_heading,
    split_dialogue,
    split_sentences,
)


def test_sentence_splitting_handles_abbreviations():
    text = "Mr. Hale met Dr. Watson at 5 p.m. on Baker St. Then they left! J. R. R. Tolkien wrote it. Did he?"
    assert split_sentences(text) == [
        "Mr. Hale met Dr. Watson at 5 p.m. on Baker St. Then they left!",
        "J. R. R. Tolkien wrote it.",
        "Did he?",
    ]


def test_chunking_respects_limit():
    text = " ".join(["This is a fairly ordinary sentence with some words in it."] * 20)
    chunks = chunk_text(text, 120)
    assert all(len(c) <= 120 for c in chunks)
    assert " ".join(chunks).split() == text.split()


def test_long_sentence_is_split_at_commas():
    sentence = ", ".join(["a clause that keeps going"] * 30) + "."
    chunks = chunk_text(sentence, 100)
    assert len(chunks) > 1 and all(len(c) <= 100 for c in chunks)


def test_dialogue_detection():
    assert split_dialogue("“Hello,” she said, “how are you?” He nodded.") == [
        ("dialogue", "Hello,"), ("narrator", "she said,"), ("dialogue", "how are you?"), ("narrator", "He nodded."),
    ]
    assert split_dialogue("She said, ‘Don’t go,’ and he didn’t.") == [
        ("narrator", "She said,"), ("dialogue", "Don’t go,"), ("narrator", "and he didn’t."),
    ]


def test_cleanup():
    options = CleanupOptions()
    text = "Mr. Smith—the baker—said hi[12]. See https://example.com now!!!"
    assert clean_for_speech(text, options, "en") == "Mister Smith, the baker, said hi. See now!"
    # abbreviations are only expanded for English
    assert clean_for_speech("Mr. Smith", options, "de") == "Mr. Smith"


def test_lexicon_rules():
    lexicon = Lexicon([
        Rule("Hermione", "Her-my-oh-nee"),
        Rule(r"\bDr\.\s", "Doctor ", is_regex=True),
        Rule("gif", "jif"),
    ])
    assert lexicon.apply("Hermione met Dr. Who. A gif, not a gift.") == "Her-my-oh-nee met Doctor Who. A jif, not a gift."
    assert lexicon.apply("Gif") == "Jif"


def test_segments_include_pauses_and_weights():
    text = "Chapter IV\n\nFirst paragraph here. Second sentence.\n\n* * *\n\n“Hi,” she said."
    segments = build_segments(text, SegmentOptions(dialogue=True))
    speech = [s for s in segments if s.kind == "speech"]
    assert speech[0].text == "Chapter 4"
    assert any(s.role == "dialogue" and s.text == "Hi," for s in speech)
    assert any(s.kind == "pause" and s.pause == 1.5 for s in segments)  # section break
    assert sum(s.weight for s in segments) == sum(len(p) for p in text.split("\n\n"))


def test_heading_helpers():
    assert speakable_heading("CHAPTER XII") == "Chapter 12"
    assert speakable_heading("IV.") == "4"
    assert heading_in_text("Chapter One\n\nIt was dark.", "Chapter 1")
    assert not heading_in_text("It was a dark and stormy night, and the wind howled.", "Chapter 1")


def test_path_templates():
    fields = {"author": "Ursula K. Le Guin", "title": "A Wizard of Earthsea", "series": "Earthsea", "series_index": "1"}
    template = "{author}/[{series}/][{series_index} - ]{title}"
    assert render_template(template, fields) == "Ursula K. Le Guin/Earthsea/1 - A Wizard of Earthsea"
    assert render_template(template, {"author": "", "title": "Solo"}) == "Unknown Author/Solo"
    assert render_template("{author}/[Book {series_index:02} - ]{title}", {**fields}) == "Ursula K. Le Guin/Book 01 - A Wizard of Earthsea"
    assert sanitize_component('AC/DC: "Live"?') == "AC DC Live"


def test_chapter_fingerprint_only_depends_on_matching_rules():
    from audiobook_studio.audio.render import chapter_fingerprint
    from audiobook_studio.settings_store import RenderSettings

    settings = RenderSettings()
    before = Lexicon([])
    after = Lexicon([Rule("Tobias", "Toe-bye-us")])
    with_name = ("One", "Tobias waved.")
    without_name = ("Two", "Mara smiled.")
    assert chapter_fingerprint(*with_name, settings, None, before) != chapter_fingerprint(*with_name, settings, None, after)
    assert chapter_fingerprint(*without_name, settings, None, before) == chapter_fingerprint(*without_name, settings, None, after)
    # rules are matched against the cleaned text as well ("Mr." becomes "Mister")
    mister = Lexicon([Rule("Mister", "Mr")])
    assert chapter_fingerprint("Three", "Mr. Hale.", settings, None, before) != chapter_fingerprint("Three", "Mr. Hale.", settings, None, mister)
