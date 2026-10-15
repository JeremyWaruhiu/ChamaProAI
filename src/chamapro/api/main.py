"""HTTP API over the ChamaPro pipeline.

    uvicorn chamapro.api.main:app --reload
"""
from __future__ import annotations

import json
import logging
import math
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import requests
from fastapi import (BackgroundTasks, Depends, FastAPI, File, Form,
                     HTTPException, Request, UploadFile)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chamapro import config

from . import pipeline as pl
from . import schemas as s
from .db import Applicant, Assessment, Interview, Response, SessionLocal, init_db, utcnow

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("chamapro.api")

ERRORS = {code: {"model": s.Error} for code in (404, 409, 413, 415, 422, 502, 503)}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    pl.load_asr()
    pl.start_worker()
    yield
    pl.stop_worker()


app = FastAPI(title="ChamaPro AI", version="0.1.0", lifespan=lifespan,
              responses={422: {"model": s.Error}, 500: {"model": s.Error}})
app.add_middleware(CORSMiddleware,
                   allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
                   allow_methods=["*"], allow_headers=["*"])


# --- Errors: always {"detail": "<string>"} -----------------------------------

@app.exception_handler(RequestValidationError)
async def _validation(request: Request, exc: RequestValidationError):
    msgs = []
    for e in exc.errors():
        loc = ".".join(str(p) for p in e["loc"] if p not in ("body", "query", "path"))
        msgs.append(f"{loc}: {e['msg']}" if loc else e["msg"])
    return JSONResponse(status_code=422, content={"detail": "; ".join(msgs)})


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


def get_db():
    with SessionLocal() as db:
        yield db


def get_interview(db: Session, interview_id: int) -> Interview:
    iv = db.get(Interview, interview_id)
    if iv is None:
        raise HTTPException(404, f"interview {interview_id} not found")
    return iv


def require_open(iv: Interview) -> None:
    if iv.status == "assessed":
        raise HTTPException(409, f"interview {iv.id} is already assessed; its record is immutable")


def upstream_error(stage: str, e: Exception) -> HTTPException:
    """Map a pipeline-stage failure from the Gemini client to an HTTP error."""
    if isinstance(e, json.JSONDecodeError | pl.score_interview.FeatureParseError
                  | KeyError | IndexError):
        return HTTPException(502, f"{stage}: extraction service returned unparseable output")
    if isinstance(e, requests.RequestException | RuntimeError):
        return HTTPException(503, f"{stage}: extraction service unavailable after retries ({e})")
    raise e


# --- Endpoints ---------------------------------------------------------------

@app.get("/api/health", response_model=s.Health)
def health():
    present = config.CLASSIFIER_PATH.exists()
    meta = None
    if config.CLASSIFIER_META_PATH.exists():
        meta = json.loads(config.CLASSIFIER_META_PATH.read_text(encoding="utf-8"))
    key = bool(config.GEMINI_API_KEY)
    return s.Health(status="ok" if present and key and pl.asr_loaded() else "degraded",
                    classifier_present=present, api_key_configured=key,
                    asr_model=config.ASR_MODEL, asr_language=config.ASR_LANGUAGE,
                    asr_loaded=pl.asr_loaded(), extraction_model=pl.extraction_model(),
                    classifier=meta)


@app.post("/api/interviews", status_code=201, response_model=s.InterviewCreated)
def create_interview(body: s.InterviewCreate | None = None, db: Session = Depends(get_db)):
    name = (body.applicant_name or "").strip() if body else ""
    iv = Interview(applicant=Applicant(name=name or None))
    db.add(iv)
    db.commit()
    return s.InterviewCreated(id=iv.id, status=iv.status)


@app.post("/api/interviews/{interview_id}/responses", status_code=202,
          response_model=s.ResponseQueued, responses=ERRORS)
def upload_response(interview_id: int, background: BackgroundTasks,
                    file: UploadFile = File(...), sentence_no: int = Form(..., ge=1),
                    db: Session = Depends(get_db)):
    iv = get_interview(db, interview_id)
    require_open(iv)
    if db.scalar(select(Response.id).where(Response.interview_id == iv.id,
                                           Response.sentence_no == sentence_no)):
        raise HTTPException(409, f"sentence {sentence_no} already has a response")

    suffix = Path(file.filename or "").suffix.lower()
    ctype = (file.content_type or "").split(";")[0].strip().lower()
    if not (ctype.startswith("audio/") or suffix in pl.AUDIO_SUFFIXES):
        raise HTTPException(415, f"not an audio file (content type {ctype or 'unknown'!r})")

    folder = config.UPLOADS_DIR / str(iv.id)
    folder.mkdir(parents=True, exist_ok=True)
    incoming = folder / f".incoming-{uuid.uuid4().hex}{suffix}"
    try:
        size = 0
        with incoming.open("wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"audio exceeds {config.MAX_UPLOAD_BYTES // 2**20} MB")
                out.write(chunk)
        if size == 0:
            raise HTTPException(415, "empty upload")

        r = Response(interview_id=iv.id, sentence_no=sentence_no,
                     domain=pl.ingest_audio.domain_for(sentence_no) or None,
                     audio_path="", status="queued")
        db.add(r)
        db.flush()
        dst = folder / f"response_{r.id}_s{sentence_no:02d}.wav"
        try:
            r.duration_s = pl.convert_upload(incoming, dst)
        except pl.NotAudio as e:
            db.rollback()
            raise HTTPException(415, str(e))
        r.audio_path = str(dst)
        try:
            db.commit()
        except IntegrityError:  # lost a race for the same sentence_no
            db.rollback()
            dst.unlink(missing_ok=True)
            raise HTTPException(409, f"sentence {sentence_no} already has a response")
    finally:
        incoming.unlink(missing_ok=True)

    background.add_task(pl.enqueue, r.id)
    return s.ResponseQueued(id=r.id, interview_id=iv.id, sentence_no=sentence_no,
                            status=r.status)


@app.get("/api/interviews/{interview_id}", response_model=s.InterviewState,
         responses=ERRORS)
def interview_state(interview_id: int, db: Session = Depends(get_db)):
    iv = get_interview(db, interview_id)
    counts = s.Counts()
    for r in iv.responses:
        setattr(counts, r.status, getattr(counts, r.status) + 1)
    return s.InterviewState(id=iv.id, status=iv.status, created_at=iv.created_at,
                            applicant=s.Applicant.model_validate(iv.applicant),
                            counts=counts,
                            responses=[s.ResponseOut.model_validate(r) for r in iv.responses],
                            assessment=iv.assessment and s.AssessmentOut.model_validate(iv.assessment))


@app.patch("/api/responses/{response_id}", response_model=s.ResponseOut, responses=ERRORS)
def edit_transcript(response_id: int, body: s.TranscriptEdit, db: Session = Depends(get_db)):
    r = db.get(Response, response_id)
    if r is None:
        raise HTTPException(404, f"response {response_id} not found")
    require_open(r.interview)
    if r.status == "queued":
        raise HTTPException(409, f"response {response_id} is still being transcribed")
    text = body.transcript.strip()
    if not text:
        raise HTTPException(422, "transcript: must not be blank")
    # transcript_asr keeps the model's output; a failed clip may be typed in by hand
    r.transcript, r.edited, r.edited_at = text, True, utcnow()
    r.status, r.error = "transcribed", None
    # the old translation described the old text; assess will redo it
    r.translation, r.signals, r.translated_at = None, None, None
    db.commit()
    return s.ResponseOut.model_validate(r)


@app.delete("/api/responses/{response_id}", response_model=s.ResponseDeleted,
            responses=ERRORS)
def delete_response(response_id: int, db: Session = Depends(get_db)):
    r = db.get(Response, response_id)
    if r is None:
        raise HTTPException(404, f"response {response_id} not found")
    require_open(r.interview)
    out = dict(id=r.id, interview_id=r.interview_id, sentence_no=r.sentence_no)
    audio = Path(r.audio_path) if r.audio_path else None
    try:
        with pl.withheld(r.id) as was_queued:
            db.delete(r)
            db.commit()
    except pl.TranscriptionBusy:
        raise HTTPException(409, f"response {response_id} is being transcribed right now; "
                                 "retry in a few seconds", headers={"Retry-After": "10"})
    if audio:
        try:
            audio.unlink(missing_ok=True)
        except OSError:  # the row is gone either way; an orphan file is harmless
            log.exception("could not remove %s", audio)
    return s.ResponseDeleted(**out, was_queued=was_queued)


@app.post("/api/interviews/{interview_id}/assess", status_code=201,
          response_model=s.AssessmentOut, responses=ERRORS)
def assess(interview_id: int, db: Session = Depends(get_db)):
    iv = get_interview(db, interview_id)
    require_open(iv)
    queued = [r.sentence_no for r in iv.responses if r.status == "queued"]
    if queued:
        raise HTTPException(409, f"{len(queued)} response(s) still being transcribed: "
                                 f"sentences {queued}")
    usable = [r for r in iv.responses if r.status == "transcribed" and (r.transcript or "").strip()]
    if not usable:
        raise HTTPException(409, "no transcribed responses to assess")
    if not config.GEMINI_API_KEY:
        raise HTTPException(503, "extraction service not configured: GEMINI_API_KEY is not set")
    if not (config.CLASSIFIER_PATH.exists() and config.CLASSIFIER_META_PATH.exists()):
        raise HTTPException(503, "classifier not available; run scripts/train_and_save.py")

    pending = [r for r in usable if r.translated_at is None]
    if pending:
        try:
            results = pl.translate_extract.translate_batch(
                [(r.sentence_no, r.transcript) for r in pending], chunk=5,
                key=config.GEMINI_API_KEY, model=config.GEMINI_MODEL, log=log.info)
        except Exception as e:
            raise upstream_error("translation", e)
        by_n = {r.sentence_no: r for r in pending}
        now = utcnow()
        for d in results:
            r = by_n[d["n"]]
            sig = d["signals"] if isinstance(d["signals"], list) else []
            r.translation, r.signals, r.translated_at = str(d["english"] or ""), [str(x) for x in sig], now
        db.commit()  # keep translations even if extraction fails below

    english = [(r.sentence_no, r.translation or "") for r in usable]
    if not any(e.strip() for _, e in english):
        raise HTTPException(409, "no response produced an English translation")
    try:
        feats = pl.score_interview.extract_features(
            english, key=config.GEMINI_API_KEY, model=config.GEMINI_MODEL, log=log.info)
    except Exception as e:
        raise upstream_error("feature extraction", e)
    if not isinstance(feats, dict):
        raise HTTPException(502, "feature extraction: expected a JSON object")

    scored = pl.score_interview.score(feats, config.CLASSIFIER_PATH, config.CLASSIFIER_META_PATH)
    out = scored.assessment
    vector = {c: None if math.isnan(v := float(x)) else v
              for c, x in scored.vector.iloc[0].items()}
    a = Assessment(interview_id=iv.id, risk_class=out["risk_class"],
                   probabilities=out["probabilities"], feature_vector=vector,
                   contributions=out["top_contributions"], extracted=out["extracted"],
                   extraction_completeness=out["extraction_completeness"],
                   features_populated=out["features_populated"],
                   features_total=out["features_total"],
                   features_not_extractable=out["features_not_extractable_from_interview"],
                   extraction_model=pl.extraction_model(),
                   model_file=scored.model_file, model_sha256=scored.model_sha256)
    db.add(a)
    iv.status = "assessed"
    try:
        db.commit()
    except IntegrityError:  # a concurrent assess won
        db.rollback()
        raise HTTPException(409, f"interview {iv.id} is already assessed; its record is immutable")
    return s.AssessmentOut.model_validate(a)
