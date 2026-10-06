"""ORM models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class MetadataMixin:
    """Bibliographic fields shared by projects and library books."""

    title: Mapped[str] = mapped_column(String, default="")
    subtitle: Mapped[str] = mapped_column(String, default="")
    author: Mapped[str] = mapped_column(String, default="", index=True)
    narrator: Mapped[str] = mapped_column(String, default="")
    series: Mapped[str] = mapped_column(String, default="", index=True)
    series_index: Mapped[str] = mapped_column(String, default="")
    genre: Mapped[str] = mapped_column(String, default="", index=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    language: Mapped[str] = mapped_column(String, default="")
    publisher: Mapped[str] = mapped_column(String, default="")
    year: Mapped[str] = mapped_column(String, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    isbn: Mapped[str] = mapped_column(String, default="")


METADATA_FIELDS = (
    "title",
    "subtitle",
    "author",
    "narrator",
    "series",
    "series_index",
    "genre",
    "tags",
    "language",
    "publisher",
    "year",
    "description",
    "isbn",
)


class Project(MetadataMixin, Base):
    """A conversion project: one source ebook being turned into an audiobook."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_filename: Mapped[str] = mapped_column(String, default="")
    source_format: Mapped[str] = mapped_column(String, default="")
    source_path: Mapped[str | None] = mapped_column(String, nullable=True)
    cover_path: Mapped[str | None] = mapped_column(String, nullable=True)
    # importing | ready | queued | rendering | done | error
    status: Mapped[str] = mapped_column(String, default="importing", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    import_options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    book_id: Mapped[int | None] = mapped_column(
        ForeignKey("books.id", ondelete="SET NULL"), nullable=True
    )
    rendered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    chapters: Mapped[list[Chapter]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="Chapter.position",
    )


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String, default="")
    text: Mapped[str] = mapped_column(Text, default="")
    include: Mapped[bool] = mapped_column(Boolean, default=True)
    # front | chapter | back
    kind: Mapped[str] = mapped_column(String, default="chapter")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    # Optional per-chapter voice override ("engine:voice").
    voice: Mapped[str | None] = mapped_column(String, nullable=True)
    # pending | rendering | done | error
    status: Mapped[str] = mapped_column(String, default="pending")
    error: Mapped[str] = mapped_column(Text, default="")
    audio_path: Mapped[str | None] = mapped_column(String, nullable=True)
    audio_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    duration: Mapped[float] = mapped_column(Float, default=0.0)

    project: Mapped[Project] = relationship(back_populates="chapters")


collection_books = Table(
    "collection_books",
    Base.metadata,
    Column("collection_id", ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True),
    Column("book_id", ForeignKey("books.id", ondelete="CASCADE"), primary_key=True),
    Column("added_at", DateTime, default=utcnow),
)


class Book(MetadataMixin, Base):
    """An audiobook in the library (rendered by the studio or imported)."""

    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Directory of the book, relative to the library root (or absolute when
    # the book lives outside of it).
    path: Mapped[str] = mapped_column(String, default="")
    # [{"path": str, "duration": float, "size": int, "title": str}]
    files: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # [{"title": str, "start": float, "end": float}] on the global timeline
    chapters: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    size: Mapped[int] = mapped_column(Integer, default=0)
    format: Mapped[str] = mapped_column(String, default="")
    cover_path: Mapped[str | None] = mapped_column(String, nullable=True)
    # studio | import
    source: Mapped[str] = mapped_column(String, default="studio")
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating: Mapped[int] = mapped_column(Integer, default=0)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    finished: Mapped[bool] = mapped_column(Boolean, default=False)
    last_played_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    missing: Mapped[bool] = mapped_column(Boolean, default=False)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    collections: Mapped[list[Collection]] = relationship(
        secondary=collection_books, back_populates="books"
    )


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    books: Mapped[list[Book]] = relationship(
        secondary=collection_books, back_populates="collections"
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String, index=True)
    lane: Mapped[str] = mapped_column(String, default="general")
    # queued | running | done | error | cancelled
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    title: Mapped[str] = mapped_column(String, default="")
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    book_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(String, default="")
    log: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LexiconRule(Base):
    """Pronunciation / text replacement rule (global or per project)."""

    __tablename__ = "lexicon"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    pattern: Mapped[str] = mapped_column(String)
    replacement: Mapped[str] = mapped_column(String, default="")
    is_regex: Mapped[bool] = mapped_column(Boolean, default=False)
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    whole_word: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
