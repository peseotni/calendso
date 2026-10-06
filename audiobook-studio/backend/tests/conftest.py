from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory) -> Path:
    data = tmp_path_factory.mktemp("studio-data")
    os.environ["STUDIO_DATA_DIR"] = str(data)
    os.environ["STUDIO_DISABLE_BACKGROUND"] = "1"
    os.environ.pop("STUDIO_PASSWORD", None)
    os.environ.pop("STUDIO_LIBRARY_DIR", None)
    from audiobook_studio.config import get_config

    get_config.cache_clear()
    return data


@pytest.fixture(scope="session")
def app(data_dir):
    from audiobook_studio.main import create_app
    from audiobook_studio.tts import get_registry
    from audiobook_studio.tts.base import TTSEngine, Voice

    application = create_app()

    class ToneEngine(TTSEngine):
        """Deterministic stand-in for a real TTS engine."""

        id = "tone"
        name = "Test tone"
        max_chars = 200

        def list_voices(self):
            return [Voice(id="beep", name="Beep", engine="tone", language="en-US"),
                    Voice(id="boop", name="Boop", engine="tone", language="en-US")]

        def language_for_voice(self, voice):
            return "en-US"

        def synthesize(self, text, voice, speed=1.0, language=None, sentence_pause=0.25):
            rate = 16000
            seconds = max(0.05, len(text) * 0.01 / speed)
            t = np.arange(int(rate * seconds)) / rate
            freq = 440 if voice == "beep" else 660
            return (0.2 * np.sin(2 * np.pi * freq * t)).astype(np.float32), rate

    registry = get_registry()
    registry.engines["tone"] = ToneEngine(registry.ctx)
    return application


@pytest.fixture(scope="session")
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def run_jobs():
    from audiobook_studio.jobs.runner import runner

    return runner.run_pending


@pytest.fixture
def samples_dir(tmp_path) -> Path:
    return tmp_path
