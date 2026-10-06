"""Process-level configuration, read from ``STUDIO_*`` environment variables.

Everything a user may want to change at runtime (voices, templates, ...) lives in
the database-backed settings store instead (see ``settings_store.py``).
"""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STUDIO_", extra="ignore")

    data_dir: Path = Path("./data")
    library_dir: Path | None = None
    inbox_dir: Path | None = None
    models_dir: Path | None = None
    frontend_dir: Path | None = None

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"

    # Optional password; overrides the one configured in the web UI.
    password: str | None = None
    secret_key: str | None = None

    render_workers: int = 1
    general_workers: int = 2
    max_upload_mb: int = 2048
    # Disables background threads (job runner, inbox watcher) - used by tests.
    disable_background: bool = False

    # ------------------------------------------------------------------ paths
    @property
    def db_path(self) -> Path:
        return self.data_dir / "studio.db"

    @property
    def projects_path(self) -> Path:
        return self.data_dir / "projects"

    @property
    def covers_path(self) -> Path:
        return self.data_dir / "covers"

    @property
    def tmp_path(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def library_path(self) -> Path:
        return self.library_dir or (self.data_dir / "library")

    @property
    def inbox_path(self) -> Path:
        return self.inbox_dir or (self.data_dir / "inbox")

    @property
    def models_path(self) -> Path:
        return self.models_dir or (self.data_dir / "models")

    @property
    def frontend_path(self) -> Path | None:
        if self.frontend_dir:
            return self.frontend_dir
        here = Path(__file__).resolve().parent
        for candidate in (here / "static", here.parent.parent / "frontend" / "dist"):
            if (candidate / "index.html").exists():
                return candidate
        return None

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.projects_path,
            self.covers_path,
            self.tmp_path,
            self.library_path,
            self.inbox_path,
            self.models_path,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def get_secret_key(self) -> str:
        if self.secret_key:
            return self.secret_key
        key_file = self.data_dir / ".secret_key"
        if key_file.exists():
            return key_file.read_text().strip()
        key = secrets.token_urlsafe(48)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        key_file.write_text(key)
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass
        return key


@lru_cache
def get_config() -> Config:
    config = Config()
    config.data_dir = config.data_dir.resolve()
    if config.library_dir:
        config.library_dir = config.library_dir.resolve()
    if config.inbox_dir:
        config.inbox_dir = config.inbox_dir.resolve()
    if config.models_dir:
        config.models_dir = config.models_dir.resolve()
    return config
