"""Pronunciation dictionary (global and per project)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import studio
from ..db import get_db
from ..models import LexiconRule, Project
from ..schemas import LexiconImport, LexiconIn, LexiconOut, LexiconPatch, LexiconTest
from ..settings_store import CleanupOptions
from ..text.cleanup import clean_for_speech
from ..text.lexicon import LexiconError, Rule, compile_rule
from ..text.segment import chunk_text
from .common import get_or_404, render_settings

router = APIRouter(prefix="/api/lexicon", tags=["pronunciation"])


def _validate(pattern: str, is_regex: bool, case_sensitive: bool, whole_word: bool) -> None:
    try:
        compile_rule(Rule(pattern, "", is_regex, case_sensitive, whole_word))
    except LexiconError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("", response_model=list[LexiconOut])
def list_rules(project_id: int | None = None, scope: str = "global", session: Session = Depends(get_db)):
    query = session.query(LexiconRule)
    if project_id is not None:
        query = query.filter(LexiconRule.project_id == project_id)
    elif scope == "global":
        query = query.filter(LexiconRule.project_id.is_(None))
    return query.order_by(LexiconRule.pattern).all()


@router.post("", response_model=LexiconOut)
def create_rule(body: LexiconIn, session: Session = Depends(get_db)):
    _validate(body.pattern, body.is_regex, body.case_sensitive, body.whole_word)
    if body.project_id is not None:
        get_or_404(session, Project, body.project_id, "Project")
    rule = LexiconRule(**body.model_dump())
    session.add(rule)
    session.commit()
    return rule


@router.patch("/{rule_id}", response_model=LexiconOut)
def update_rule(rule_id: int, body: LexiconPatch, session: Session = Depends(get_db)):
    rule = get_or_404(session, LexiconRule, rule_id, "Rule")
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(rule, key, value)
    _validate(rule.pattern, rule.is_regex, rule.case_sensitive, rule.whole_word)
    session.commit()
    return rule


@router.delete("/{rule_id}")
def delete_rule(rule_id: int, session: Session = Depends(get_db)):
    rule = get_or_404(session, LexiconRule, rule_id, "Rule")
    session.delete(rule)
    session.commit()
    return {"ok": True}


@router.post("/test")
def test_rules(body: LexiconTest, session: Session = Depends(get_db)):
    lexicon = studio.lexicon_for(session, body.project_id)
    cleanup = CleanupOptions()
    language = body.language
    if body.project_id is not None:
        project = get_or_404(session, Project, body.project_id, "Project")
        settings = render_settings(project)
        cleanup = settings.cleanup
        language = settings.language or project.language or language
    paragraphs = [p for p in body.text.split("\n\n") if p.strip()]
    cleaned = [clean_for_speech(p.replace("\n", " "), cleanup, language) for p in paragraphs]
    result = [lexicon.apply(p) for p in cleaned]
    chunks = [c for p in result for c in chunk_text(p, 350)]
    return {"cleaned": "\n\n".join(cleaned), "result": "\n\n".join(result), "chunks": chunks}


@router.get("/export")
def export_rules(project_id: int | None = None, session: Session = Depends(get_db)):
    rules = list_rules(project_id=project_id, scope="global", session=session)
    return {"rules": [
        {k: getattr(r, k) for k in ("pattern", "replacement", "is_regex", "case_sensitive", "whole_word", "enabled", "note")}
        for r in rules
    ]}


@router.post("/import")
def import_rules(body: LexiconImport, project_id: int | None = None, session: Session = Depends(get_db)):
    if body.replace:
        query = session.query(LexiconRule)
        query = query.filter(LexiconRule.project_id == project_id) if project_id else query.filter(LexiconRule.project_id.is_(None))
        query.delete(synchronize_session=False)
    added = 0
    for item in body.rules:
        try:
            compile_rule(Rule(item.pattern, "", item.is_regex, item.case_sensitive, item.whole_word))
        except LexiconError:
            continue
        data = item.model_dump()
        data["project_id"] = project_id
        session.add(LexiconRule(**data))
        added += 1
    session.commit()
    return {"added": added}
