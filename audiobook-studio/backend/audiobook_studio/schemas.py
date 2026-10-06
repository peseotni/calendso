"""API request/response models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def _utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


UTCDateTime = Annotated[datetime, AfterValidator(_utc)]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MetadataFields(BaseModel):
    title: str | None = None
    subtitle: str | None = None
    author: str | None = None
    narrator: str | None = None
    series: str | None = None
    series_index: str | None = None
    genre: str | None = None
    tags: list[str] | None = None
    language: str | None = None
    publisher: str | None = None
    year: str | None = None
    description: str | None = None
    isbn: str | None = None


# ----------------------------------------------------------------- projects
class ChapterOut(ORM):
    id: int
    position: int
    title: str
    include: bool
    kind: str
    word_count: int
    voice: str | None
    status: str
    error: str
    duration: float
    audio_state: str = "none"  # none | ready | stale
    preview: str = ""
    estimated_seconds: float = 0


class ChapterDetail(ChapterOut):
    text: str


class ChapterUpdate(BaseModel):
    title: str | None = None
    text: str | None = None
    include: bool | None = None
    voice: str | None = Field(None, description="Override voice as 'engine:voice'; empty string clears it")


class ChapterBulk(BaseModel):
    chapter_ids: list[int]
    include: bool | None = None
    voice: str | None = None


class ChapterSplit(BaseModel):
    offset: int = Field(..., ge=1, description="Character offset in the chapter text where the new chapter starts")
    title: str | None = None


class ChapterMerge(BaseModel):
    chapter_ids: list[int] = Field(..., min_length=2)


class ChapterReorder(BaseModel):
    chapter_ids: list[int]


class ProjectSummary(ORM):
    id: int
    title: str
    author: str
    status: str
    error: str
    source_format: str
    source_filename: str
    cover_url: str | None = None
    chapter_count: int = 0
    included_chapters: int = 0
    word_count: int = 0
    estimated_seconds: float = 0
    rendered_seconds: float = 0
    book_id: int | None
    job_id: int | None = None
    job_progress: float | None = None
    job_message: str | None = None
    engine: str = ""
    voice: str = ""
    created_at: UTCDateTime
    updated_at: UTCDateTime
    rendered_at: UTCDateTime | None


class ProjectDetail(ProjectSummary):
    subtitle: str
    narrator: str
    series: str
    series_index: str
    genre: str
    tags: list[str]
    language: str
    publisher: str
    year: str
    description: str
    isbn: str
    settings: dict[str, Any]
    warnings: list[str]
    import_options: dict[str, Any]
    chapters: list[ChapterOut]
    workspace_bytes: int = 0
    stale_chapters: int = 0


class ProjectUpdate(MetadataFields):
    settings: dict[str, Any] | None = None


class TextProjectCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    author: str = ""
    text: str = Field(..., min_length=1)


class RenderRequest(BaseModel):
    chapter_ids: list[int] | None = None


class ReimportRequest(BaseModel):
    ocr: str = Field("auto", pattern="^(auto|force|off)$")
    language: str = ""


class PreviewRequest(BaseModel):
    text: str | None = None
    max_chars: int = Field(600, ge=20, le=3000)


# ----------------------------------------------------------------- library
class BookFile(BaseModel):
    path: str
    duration: float = 0
    size: int = 0
    title: str = ""


class BookChapter(BaseModel):
    title: str
    start: float
    end: float


class BookOut(ORM):
    id: int
    title: str
    subtitle: str
    author: str
    narrator: str
    series: str
    series_index: str
    genre: str
    tags: list[str]
    language: str
    publisher: str
    year: str
    description: str
    isbn: str
    path: str
    files: list[BookFile]
    chapters: list[BookChapter]
    duration: float
    size: int
    format: str
    source: str
    project_id: int | None
    rating: int
    favorite: bool
    progress: float
    finished: bool
    missing: bool
    last_played_at: UTCDateTime | None
    added_at: UTCDateTime
    updated_at: UTCDateTime
    cover_url: str | None = None
    thumb_url: str | None = None
    collection_ids: list[int] = []


class BookUpdate(MetadataFields):
    rating: int | None = Field(None, ge=0, le=5)
    favorite: bool | None = None
    finished: bool | None = None
    collection_ids: list[int] | None = None


class BulkBookUpdate(BaseModel):
    book_ids: list[int] = Field(..., min_length=1)
    changes: dict[str, Any] = {}
    add_collection_id: int | None = None
    remove_collection_id: int | None = None


class ProgressUpdate(BaseModel):
    position: float = Field(..., ge=0)
    finished: bool | None = None


class CollectionIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    color: str = ""


class CollectionOut(ORM):
    id: int
    name: str
    description: str
    color: str
    created_at: UTCDateTime
    book_count: int = 0
    cover_book_ids: list[int] = []


class CollectionBooks(BaseModel):
    book_ids: list[int]


class OrganizeRequest(BaseModel):
    template: str | None = None
    book_ids: list[int] | None = None


class ScanRequest(BaseModel):
    path: str | None = None


class CoverUrl(BaseModel):
    url: str


# ----------------------------------------------------------------- jobs
class JobOut(ORM):
    id: int
    kind: str
    status: str
    title: str
    project_id: int | None
    book_id: int | None
    progress: float
    message: str
    error: str
    result: dict[str, Any]
    created_at: UTCDateTime
    started_at: UTCDateTime | None
    finished_at: UTCDateTime | None
    eta_seconds: float | None = None
    elapsed_seconds: float | None = None


class JobDetail(JobOut):
    log: str
    payload: dict[str, Any]


# ----------------------------------------------------------------- tts
class VoicePreviewRequest(BaseModel):
    engine: str
    voice: str
    text: str = Field(..., min_length=1, max_length=2000)
    speed: float = Field(1.0, ge=0.5, le=2.0)
    language: str | None = None
    apply_lexicon: bool = True


class ModelDownload(BaseModel):
    engine: str
    model: str


# ----------------------------------------------------------------- lexicon
class LexiconIn(BaseModel):
    pattern: str = Field(..., min_length=1, max_length=500)
    replacement: str = Field("", max_length=500)
    is_regex: bool = False
    case_sensitive: bool = False
    whole_word: bool = True
    enabled: bool = True
    note: str = ""
    project_id: int | None = None


class LexiconPatch(BaseModel):
    pattern: str | None = None
    replacement: str | None = None
    is_regex: bool | None = None
    case_sensitive: bool | None = None
    whole_word: bool | None = None
    enabled: bool | None = None
    note: str | None = None


class LexiconOut(ORM):
    id: int
    project_id: int | None
    pattern: str
    replacement: str
    is_regex: bool
    case_sensitive: bool
    whole_word: bool
    enabled: bool
    note: str
    created_at: UTCDateTime


class LexiconTest(BaseModel):
    text: str = Field(..., max_length=20000)
    project_id: int | None = None
    language: str = "en"


class LexiconImport(BaseModel):
    rules: list[LexiconIn]
    replace: bool = False


# ----------------------------------------------------------------- settings / auth
class LoginRequest(BaseModel):
    password: str


class PasswordChange(BaseModel):
    current_password: str = ""
    new_password: str = Field("", max_length=200)
