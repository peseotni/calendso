"""Voices, engines, previews and model downloads."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from .. import studio
from ..audio.codec import encode_preview
from ..audio.render import preview as render_preview
from ..db import get_db
from ..jobs.runner import runner
from ..models import Job
from ..schemas import JobOut, ModelDownload, VoicePreviewRequest
from ..settings_store import RenderSettings
from ..text.lexicon import Lexicon
from ..tts import TTSError, get_registry
from ..tts import kokoro as kokoro_mod
from .common import job_out

router = APIRouter(prefix="/api/tts", tags=["voices"])


@router.get("/engines")
def engines():
    registry = get_registry()
    return registry.infos()


@router.get("/voices")
def voices(engine: str | None = None, include_unavailable: bool = False):
    registry = get_registry()
    result = []
    for engine_id in ([engine] if engine else list(registry.engines)):
        try:
            current = registry.get(engine_id)
        except TTSError as exc:
            raise HTTPException(404, str(exc)) from exc
        if not include_unavailable and not (current.available()[0] and current.enabled()):
            continue
        try:
            items = current.list_voices()
        except Exception as exc:  # noqa: BLE001 - one broken engine must not break the list
            items = []
            if engine:
                raise HTTPException(502, f"Could not list voices: {exc}") from exc
        result.extend(v.to_dict() for v in items if include_unavailable or v.installed)
    return result


@router.post("/preview")
def preview(body: VoicePreviewRequest, session: Session = Depends(get_db)):
    settings = RenderSettings(engine=body.engine, voice=body.voice, speed=body.speed, language=body.language,
                              announce_chapters=False)
    lexicon = studio.lexicon_for(session, None) if body.apply_lexicon else Lexicon()
    try:
        audio, rate = render_preview(body.text, settings, get_registry(), lexicon, max_chars=2000)
    except TTSError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Synthesis failed: {exc}") from exc
    data, mime = encode_preview(audio, rate)
    return Response(content=data, media_type=mime, headers={"Cache-Control": "no-store"})


def _active_downloads(session: Session) -> dict[str, int]:
    jobs = session.query(Job).filter(Job.kind == "download_model", Job.status.in_(("queued", "running"))).all()
    return {f"{j.payload.get('engine')}:{j.payload.get('model')}": j.id for j in jobs}


@router.get("/models")
def models(session: Session = Depends(get_db)):
    registry = get_registry()
    kokoro = registry.get("kokoro")
    downloads = _active_downloads(session)
    installed = set(kokoro.installed_variants())
    voices_installed = kokoro.voices_path.exists()
    kokoro_models = [
        {
            "engine": "kokoro",
            "id": key,
            "label": info["label"],
            "size_mb": info["size_mb"] + (0 if voices_installed else kokoro_mod.VOICES_SIZE_MB),
            "installed": key in installed and voices_installed,
            "job_id": downloads.get(f"kokoro:{key}"),
        }
        for key, info in kokoro_mod.VARIANTS.items()
    ]
    return {"kokoro": kokoro_models, "piper_installed": list(registry.get("piper").installed_models())}


@router.get("/models/piper")
def piper_catalog(refresh: bool = False, session: Session = Depends(get_db)):
    piper = get_registry().get("piper")
    try:
        if refresh:
            piper.catalog(refresh=True)
        items = piper.catalog_voices()
    except TTSError as exc:
        raise HTTPException(502, str(exc)) from exc
    downloads = _active_downloads(session)
    for item in items:
        item["job_id"] = downloads.get(f"piper:{item['id']}")
    return items


@router.post("/models/download", response_model=JobOut)
def download(body: ModelDownload, session: Session = Depends(get_db)):
    if body.engine not in ("kokoro", "piper"):
        raise HTTPException(400, "This engine has no downloadable models.")
    if body.engine == "kokoro" and body.model not in kokoro_mod.VARIANTS:
        raise HTTPException(400, "Unknown Kokoro model.")
    existing = _active_downloads(session).get(f"{body.engine}:{body.model}")
    if existing:
        return job_out(session.get(Job, existing))
    job = runner.enqueue(session, "download_model", f"Download {body.engine} voice {body.model}",
                         {"engine": body.engine, "model": body.model})
    return job_out(job)


@router.delete("/models/{engine}/{model}")
def delete_model(engine: str, model: str):
    registry = get_registry()
    if engine == "piper":
        registry.get("piper").delete_model(model)
    elif engine == "kokoro":
        info = kokoro_mod.VARIANTS.get(model)
        if info is None:
            raise HTTPException(404, "Unknown model")
        kokoro = registry.get("kokoro")
        kokoro.unload()
        (kokoro.folder / info["file"]).unlink(missing_ok=True)
        if not kokoro.installed_variants():
            kokoro.voices_path.unlink(missing_ok=True)
    else:
        raise HTTPException(400, "This engine has no downloadable models.")
    return {"ok": True}
