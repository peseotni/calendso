"""Engine integrations (Kokoro, Piper, OpenAI-compatible) and model downloads."""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("onnx")
pytest.importorskip("kokoro_onnx")
pytest.importorskip("piper")

import fake_models  # noqa: E402
from audiobook_studio.audio.codec import to_wav_bytes  # noqa: E402
from audiobook_studio.settings_store import AppSettings  # noqa: E402
from audiobook_studio.tts.base import EngineContext  # noqa: E402
from audiobook_studio.tts.kokoro import KokoroEngine  # noqa: E402
from audiobook_studio.tts.piper import PiperEngine  # noqa: E402
from audiobook_studio.tts.remote import OpenAICompatibleEngine  # noqa: E402


@pytest.fixture
def ctx(tmp_path):
    settings = AppSettings()
    return EngineContext(models_dir=tmp_path / "models", settings=lambda: settings)


def test_kokoro_engine(ctx):
    engine = KokoroEngine(ctx)
    assert engine.ready() == (False, "Model not downloaded yet")
    assert len(engine.list_voices()) == 54 and not engine.list_voices()[0].installed
    fake_models.make_kokoro(ctx.models_dir / "kokoro")
    assert engine.ready()[0]
    voices = {v.id: v for v in engine.list_voices()}
    assert set(voices) == {"af_heart", "af_bella", "bf_emma"}
    assert voices["bf_emma"].language == "en-GB" and voices["bf_emma"].gender == "female"
    assert engine.has_voice("af_heart") and not engine.has_voice("am_adam")
    audio, rate = engine.synthesize("Hello there. This is a test of the narrator.", "af_heart", speed=1.2)
    assert rate == 24000 and audio.dtype == np.float32 and audio.size > 1000
    blended, _ = engine.synthesize("Blended voices work too.", "af_heart:0.7+af_bella:0.3")
    assert blended.size > 1000
    assert engine.has_voice("af_heart:0.7+af_bella:0.3")


def test_piper_engine(ctx):
    engine = PiperEngine(ctx)
    assert not engine.ready()[0]
    folder = ctx.models_dir / "piper"
    fake_models.make_piper(folder)
    fake_models.make_piper(folder, "en_GB-duo-medium", speakers={"alice": 0, "bob": 1})
    assert engine.ready()[0]
    voices = {v.id: v for v in engine.list_voices()}
    assert voices["en_US-test-medium"].language == "en-US"
    assert voices["en_GB-duo-medium"].speakers == ["alice", "bob"]
    audio, rate = engine.synthesize("One sentence. And a second one!", "en_US-test-medium", speed=1.5)
    assert rate == 22050 and audio.size > 1000
    audio, _ = engine.synthesize("Speaker selection.", "en_GB-duo-medium#bob")
    assert audio.size > 100
    engine.delete_model("en_US-test-medium")
    assert "en_US-test-medium" not in engine.installed_models()


class _Handler(BaseHTTPRequestHandler):
    files: dict[str, bytes] = {}
    requests: list[dict] = []

    def log_message(self, *args):  # silence
        pass

    def do_GET(self):  # noqa: N802
        if self.path == "/v1/audio/voices":
            self._send(200, json.dumps({"voices": ["alpha", "beta"]}).encode(), "application/json")
        elif self.path in self.files:
            self._send(200, self.files[self.path], "application/octet-stream")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).requests.append({"path": self.path, "body": body, "auth": self.headers.get("Authorization")})
        if self.path == "/v1/audio/speech":
            rate = 24000
            tone = (0.2 * np.sin(2 * np.pi * 300 * np.arange(rate // 2) / rate)).astype(np.float32)
            self._send(200, to_wav_bytes(tone, rate), "audio/wav")
        else:
            self._send(404, b"", "text/plain")

    def _send(self, code, data, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def server():
    _Handler.files = {}
    _Handler.requests = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_openai_compatible_engine(tmp_path, server):
    settings = AppSettings(openai_base_url=f"{server}/v1", openai_api_key="secret", openai_model="kokoro")
    engine = OpenAICompatibleEngine(EngineContext(models_dir=tmp_path, settings=lambda: settings))
    assert engine.ready()[0] and engine.enabled()
    assert [v.id for v in engine.list_voices()] == ["alpha", "beta"]
    audio, rate = engine.synthesize("Remote speech", "beta", speed=1.25)
    assert rate == 24000 and abs(audio.size - 12000) < 10
    request = _Handler.requests[-1]
    assert request["auth"] == "Bearer secret"
    assert request["body"] == {"model": "kokoro", "input": "Remote speech", "voice": "beta", "speed": 1.25, "response_format": "wav"}

    unconfigured = OpenAICompatibleEngine(EngineContext(models_dir=tmp_path, settings=lambda: AppSettings()))
    assert not unconfigured.ready()[0]


def test_model_downloads(tmp_path, server, monkeypatch):
    from audiobook_studio.tts import downloads
    from audiobook_studio.tts import kokoro as kokoro_mod
    from audiobook_studio.tts import piper as piper_mod

    source = tmp_path / "source"
    fake_models.make_kokoro(source)
    _Handler.files["/kokoro.onnx"] = (source / "kokoro-v1.0.onnx").read_bytes()
    _Handler.files["/voices.bin"] = (source / "voices-v1.0.bin").read_bytes()
    variants = {key: dict(value) for key, value in kokoro_mod.VARIANTS.items()}
    # the first mirror is broken: the download falls back to the second one
    variants["kokoro-v1.0"]["urls"] = [f"{server}/missing.onnx", f"{server}/kokoro.onnx"]
    monkeypatch.setattr(kokoro_mod, "VARIANTS", variants)
    monkeypatch.setattr(kokoro_mod, "VOICES_URLS", [f"{server}/voices.bin"])

    models = tmp_path / "models"
    updates: list[tuple[float, str]] = []
    downloads.download_kokoro(models, "kokoro-v1.0", lambda f, m: updates.append((f, m)), lambda: False)
    assert (models / "kokoro" / "kokoro-v1.0.onnx").read_bytes() == _Handler.files["/kokoro.onnx"]
    assert (models / "kokoro" / "voices-v1.0.bin").exists()
    assert updates and all(0 <= f <= 1 for f, _ in updates)
    settings = AppSettings()
    engine = KokoroEngine(EngineContext(models_dir=models, settings=lambda: settings))
    assert engine.ready()[0]

    # Piper: catalog entry with checksums
    voice_dir = tmp_path / "piper-src"
    fake_models.make_piper(voice_dir, "en_US-fake-low")
    onnx_bytes = (voice_dir / "en_US-fake-low.onnx").read_bytes()
    json_bytes = (voice_dir / "en_US-fake-low.onnx.json").read_bytes()
    _Handler.files["/en/en_US/fake/low/en_US-fake-low.onnx"] = onnx_bytes
    _Handler.files["/en/en_US/fake/low/en_US-fake-low.onnx.json"] = json_bytes
    catalog = {
        "en_US-fake-low": {
            "name": "fake", "quality": "low", "num_speakers": 1,
            "language": {"code": "en_US", "name_english": "English", "country_english": "United States"},
            "files": {
                "en/en_US/fake/low/en_US-fake-low.onnx": {"size_bytes": len(onnx_bytes), "md5_digest": hashlib.md5(onnx_bytes).hexdigest()},
                "en/en_US/fake/low/en_US-fake-low.onnx.json": {"size_bytes": len(json_bytes), "md5_digest": hashlib.md5(json_bytes).hexdigest()},
                "en/en_US/fake/low/MODEL_CARD": {"size_bytes": 10, "md5_digest": "x"},
            },
        }
    }
    monkeypatch.setattr(piper_mod, "HF_BASE", server)
    piper = PiperEngine(EngineContext(models_dir=models, settings=lambda: settings))
    (models / "piper").mkdir(parents=True, exist_ok=True)
    (models / "piper" / "voices.json").write_text(json.dumps(catalog))
    listed = piper.catalog_voices()
    assert listed[0]["id"] == "en_US-fake-low" and not listed[0]["installed"]
    downloads.download_piper(piper, "en_US-fake-low", lambda f, m: None, lambda: False)
    assert "en_US-fake-low" in piper.installed_models()
    assert piper.catalog_voices()[0]["installed"]

    # A corrupted download is rejected by the checksum.
    catalog["en_US-fake-low"]["files"]["en/en_US/fake/low/en_US-fake-low.onnx"]["md5_digest"] = "0" * 32
    (models / "piper" / "voices.json").write_text(json.dumps(catalog))
    piper._catalog = None
    piper.delete_model("en_US-fake-low")
    with pytest.raises(Exception, match="checksum"):
        downloads.download_piper(piper, "en_US-fake-low", lambda f, m: None, lambda: False)
    assert not (models / "piper" / "en_US-fake-low.onnx").exists()


def test_render_with_kokoro_through_api(client, data_dir, run_jobs):
    """A whole book narrated by the Kokoro integration (fake weights)."""
    from audiobook_studio.tts import get_registry

    fake_models.make_kokoro(Path(data_dir) / "models" / "kokoro")
    get_registry().get("kokoro").unload()
    detail = client.post("/api/projects/text", json={"title": "Kokoro Test", "text": "# One\n\nHello there.\n\n# Two\n\nGoodbye now."}).json()
    assert detail["settings"]["engine"] == "kokoro"  # Kokoro is preferred once installed
    response = client.patch(f"/api/projects/{detail['id']}", json={"settings": {"voice": "bf_emma", "normalize": False}})
    assert response.status_code == 200
    preview = client.post(f"/api/projects/{detail['id']}/preview", json={})
    assert preview.status_code == 200
    client.post(f"/api/projects/{detail['id']}/render")
    run_jobs()
    detail = client.get(f"/api/projects/{detail['id']}").json()
    assert detail["status"] == "done", detail["error"]
    book = client.get(f"/api/books/{detail['book_id']}").json()
    assert book["narrator"] == "Kokoro – Emma" and book["duration"] > 2
