"""Pronunciation dictionary: user-defined find & replace rules."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    pattern: str
    replacement: str
    is_regex: bool = False
    case_sensitive: bool = False
    whole_word: bool = True


class LexiconError(ValueError):
    pass


def compile_rule(rule: Rule) -> re.Pattern[str]:
    flags = 0 if rule.case_sensitive else re.IGNORECASE
    if rule.is_regex:
        source = rule.pattern
    else:
        source = re.escape(rule.pattern)
        if rule.whole_word:
            source = rf"(?<!\w){source}(?!\w)"
    try:
        return re.compile(source, flags)
    except re.error as exc:
        raise LexiconError(f"Invalid pattern {rule.pattern!r}: {exc}") from exc


class Lexicon:
    """Applies rules in order; project rules should come before global ones."""

    def __init__(self, rules: Iterable[Rule] = ()):  # noqa: B008
        self.rules = [r for r in rules if r.pattern]
        self._compiled: list[tuple[re.Pattern[str], Rule]] = []
        for rule in self.rules:
            try:
                self._compiled.append((compile_rule(rule), rule))
            except LexiconError:
                continue  # invalid rules are reported when saved; skip at render time

    def apply(self, text: str) -> str:
        for pattern, rule in self._compiled:
            if rule.is_regex:
                try:
                    text = pattern.sub(rule.replacement, text)
                except (re.error, IndexError):
                    text = pattern.sub(lambda _m, r=rule.replacement: r, text)
            else:
                replacement = rule.replacement
                if not rule.case_sensitive and rule.pattern.islower():
                    text = pattern.sub(lambda m, r=replacement: _match_case(m.group(0), r), text)
                else:
                    text = pattern.sub(lambda _m, r=replacement: r, text)
        return text

    def fingerprint(self) -> str:
        data = json.dumps([r.__dict__ for r in self.rules], sort_keys=True)
        return hashlib.sha1(data.encode()).hexdigest()[:12]


def _match_case(original: str, replacement: str) -> str:
    """Keep the capitalisation of sentence starts ("Hermione" -> "Her-my-oh-nee")."""
    if original[:1].isupper() and replacement[:1].islower():
        return replacement[:1].upper() + replacement[1:]
    return replacement
