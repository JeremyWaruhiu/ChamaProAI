"""HTTP API over the ChamaPro pipeline.

    uvicorn chamapro.api.main:app --reload --reload-dir src --reload-dir scripts
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
                     HTTPException, Query, Request, UploadFile)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (FileResponse, JSONResponse, RedirectResponse,
                               Response as HTTPResponse)
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chamapro import config

from . import admin, audit, auth, comparator, loans, storage
from . import pipeline as pl
from . import schemas as s
from .auth import require_admin, require_officer
from .comparator import RECOMMENDED_DECISION
from .db import (Applicant, Assessment, Decision, Interview, LoanApplication, Response,
                 User, get_db, init_db, utcnow)
from .questions import CURRENT_SET, QUESTION_SETS, question

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("chamapro.api")

ERRORS = {code: {"model": s.Error} for code in (401, 403, 404, 409, 413, 415, 422, 502, 503)}
# Every endpoint except /api/health and /api/auth/login needs a signed-in user;
# staff endpoints refuse members.
OFFICER = [Depends(require_officer)]


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    storage.backend()      # fail at startup, not on the first upload, if misconfigured
    pl.load_asr()
    pl.start_worker()
    yield
    pl.stop_worker()


app = FastAPI(title="ChamaPro AI", version="0.1.0", lifespan=lifespan,
              responses={422: {"model": s.Error}, 500: {"model": s.Error}})
app.add_middleware(CORSMiddleware,
                   allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(loans.router)
app.include_router(admin.router)


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


def get_interview(db: Session, interview_id: int) -> Interview:
    iv = db.get(Interview, interview_id)
    if iv is None:
        raise HTTPException(404, f"interview {interview_id} not found")
    return iv


def require_open(iv: Interview) -> None:
    if iv.status == "assessed":
        raise HTTPException(409, f"interview {iv.id} is already assessed; its record is immutable")


def live_status_of(db: Session) -> tuple[int, int] | None:
    """(response_id, interview_id) of the clip being transcribed right now."""
    rid = pl.transcribing()
    if rid is None:
        return None
    iid = db.scalar(select(Response.interview_id)
                    .where(Response.id == rid, Response.status == "queued"))
    return (rid, iid) if iid is not None else None


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
    asr = pl.asr_status()
    kik = asr["kik"]
    return s.Health(status="ok" if present and key and pl.asr_loaded() else "degraded",
                    classifier_present=present, api_key_configured=key,
                    asr_model=kik["model"] or config.ASR_MODEL, asr_language=config.ASR_LANGUAGE,
                    asr_loaded=pl.asr_loaded(), asr_engine=kik["engine"], asr_device=kik["device"],
                    asr_decoding=config.ASR_DECODING, asr=asr,
                    extraction_model=pl.extraction_model(), classifier=meta)


# --- Sign-in -----------------------------------------------------------------

TOO_MANY = "too many failed sign-in attempts; try again later"


def check_rate_limit(key: str) -> None:
    wait = auth.limiter.retry_after(key)
    if wait is not None:
        raise HTTPException(429, TOO_MANY, headers={"Retry-After": str(wait)})


def signed_in(request: Request, response: HTTPResponse, db: Session, user: User,
              method: str) -> s.Me:
    """The one success path for every sign-in method: session, cookie, {username, role}."""
    token = auth.start_session(db, user, method)
    response.set_cookie(auth.COOKIE, token, max_age=config.SESSION_HOURS * 3600, path="/api",
                        httponly=True, samesite="strict", secure=auth.cookie_secure(request))
    return s.Me.model_validate(user)


@app.post("/api/auth/login", response_model=s.Me,
          responses={401: {"model": s.Error}, 429: {"model": s.Error}})
def login(body: s.LoginRequest, request: Request, response: HTTPResponse,
          db: Session = Depends(get_db)):
    name = body.username.strip()
    check_rate_limit(name)
    user = auth.authenticate(db, name, body.password)
    if user is None:
        auth.limiter.fail(name)
        raise HTTPException(401, auth.BAD_LOGIN)
    auth.limiter.clear(name)
    return signed_in(request, response, db, user, "password")


@app.get("/api/auth/config", response_model=s.AuthConfig)
def auth_config():
    """What the login page needs to know before anyone is signed in."""
    return s.AuthConfig(google_client_id=config.GOOGLE_CLIENT_ID)


@app.post("/api/auth/google", response_model=s.Me,
          responses={401: {"model": s.Error}, 404: {"model": s.Error},
                     429: {"model": s.Error}, 503: {"model": s.Error}})
def google_login(body: s.GoogleLogin, request: Request, response: HTTPResponse,
                 db: Session = Depends(get_db)):
    """Sign in an existing user whose linked email matches a verified Google
    account. Never creates a user; anything else is the password login's 401."""
    client_id = config.GOOGLE_CLIENT_ID
    if not client_id:
        raise HTTPException(404, "Google sign-in is not configured on this server; "
                                 "set GOOGLE_CLIENT_ID or sign in with a username and password")
    try:
        email = auth.verify_google_credential(body.credential, client_id)
    except auth.GoogleUnreachable:
        raise HTTPException(503, "could not reach Google to verify the sign-in; "
                                 "try again, or use your username and password")
    except auth.GoogleTokenRejected as e:
        log.info("google sign-in refused: %s", e)
        raise HTTPException(401, auth.BAD_LOGIN)
    key = f"google:{email}"  # its own counter, so it cannot lock a username
    check_rate_limit(key)
    user = auth.user_by_email(db, email)
    if user is None:
        auth.limiter.fail(key)
        raise HTTPException(401, auth.BAD_LOGIN)
    auth.limiter.clear(key)
    return signed_in(request, response, db, user, "google")


@app.post("/api/auth/logout", status_code=204)
def logout(request: Request, db: Session = Depends(get_db)):
    """Ends this browser's session. Succeeds even if it had already ended."""
    auth.end_session(db, request.cookies.get(auth.COOKIE))
    out = HTTPResponse(status_code=204)
    out.delete_cookie(auth.COOKIE, path="/api", httponly=True, samesite="strict",
                      secure=auth.cookie_secure(request))
    return out


@app.get("/api/auth/me", response_model=s.Me, responses={401: {"model": s.Error}})
def me(user: User = Depends(auth.current_user)):
    return s.Me.model_validate(user)


def live_stats(db: Session) -> dict:
    """Aggregate counts from the database; no row-level data leaves here.
    Practice interviews are left out of every figure."""
    live = Interview.mode == "live"
    n_assessed = db.scalar(select(func.count(Assessment.id))
                           .join(Interview, Interview.id == Assessment.interview_id).where(live)) or 0
    dist = dict(db.execute(select(Assessment.risk_class, func.count(Assessment.id))
                           .join(Interview, Interview.id == Assessment.interview_id).where(live)
                           .group_by(Assessment.risk_class)).all())
    completeness = db.scalar(select(func.avg(Assessment.extraction_completeness))
                             .join(Interview, Interview.id == Assessment.interview_id).where(live))
    pairs = db.execute(select(Assessment.risk_class, Decision.decision)
                       .join(Decision, Decision.interview_id == Assessment.interview_id)
                       .join(Interview, Interview.id == Assessment.interview_id).where(live)).all()
    agree = sum(RECOMMENDED_DECISION.get(rc) == d for rc, d in pairs)
    apps = db.scalars(select(LoanApplication)
                      .join(Interview, Interview.id == LoanApplication.interview_id)
                      .join(Assessment, Assessment.interview_id == Interview.id).where(live)).all()
    rule = [loans.comparator_of(a).agreement for a in apps]
    compared = rule.count("agree") + rule.count("diverge")
    return {
        "source": "live database; practice interviews excluded",
        "interview_count": db.scalar(select(func.count(Interview.id)).where(live)) or 0,
        "practice_interview_count": db.scalar(select(func.count(Interview.id))
                                              .where(Interview.mode == "practice")) or 0,
        "assessment_count": n_assessed,
        "risk_class_distribution": {**dict.fromkeys(RECOMMENDED_DECISION, 0), **dist},
        "mean_extraction_completeness": None if completeness is None else round(float(completeness), 4),
        "decision_agreement": {
            "rule": "agree when Low->approve, Medium->refer, High->decline",
            "decisions": len(pairs),
            "agreements": agree,
            "rate": round(agree / len(pairs), 4) if pairs else None,
        },
        "rule_agreement": {
            "rule": comparator.RULE,
            "applications": len(rule),
            "agreements": rule.count("agree"),
            "divergences": rule.count("diverge"),
            "undetermined": rule.count("undetermined"),
            "rate": round(rule.count("agree") / compared, 4) if compared else None,
        },
    }


@app.get("/api/results", responses=ERRORS, dependencies=[Depends(require_admin)])
def results(db: Session = Depends(get_db)):
    """Exported evaluation summary plus live system stats. Read-only."""
    path = config.RESULTS_SUMMARY_PATH
    if not path.is_file():
        raise HTTPException(404, "results summary not found; run "
                                 "python scripts/export_results.py to create results/summary.json")
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(503, f"{path.name} is not valid JSON; rerun scripts/export_results.py")
    return {**summary, "live": live_stats(db)}


@app.get("/api/questions", response_model=list[s.Question], responses=ERRORS, dependencies=OFFICER)
def questions(version: s.QuestionSet = Query(CURRENT_SET, description="Question set")):
    """One question set, in order. text_kik is "" where not yet supplied."""
    return QUESTION_SETS[version]


# FinAccess A21 categories behind the four marital_* features.
MARITAL_LABEL = {"married": "Married / living with partner", "single": "Single / never married",
                 "widowed": "Widowed", "divorced": "Divorced / separated"}


@app.get("/api/applicant-form", response_model=s.ApplicantFormOptions, responses=ERRORS,
         dependencies=OFFICER)
def applicant_form():
    """The choices on the applicant form, with the codes the classifier was trained on."""
    sc = pl.score_interview
    return s.ApplicantFormOptions(
        sex=[s.Option(value="female", label="Female"), s.Option(value="male", label="Male")],
        education=[s.Option(value=code, label=label) for label, code in sc.EDU_LADDER.items()],
        marital_status=[s.Option(value=m, label=MARITAL_LABEL[m]) for m in sc.MARITAL_STATUSES])


@app.post("/api/interviews", status_code=201, response_model=s.InterviewCreated,
          responses=ERRORS)
def create_interview(body: s.InterviewCreate | None = None, db: Session = Depends(get_db),
                     user: User = Depends(require_officer)):
    body = body or s.InterviewCreate()
    if body.question_set == "v2" and body.applicant is None:
        raise HTTPException(422, "applicant: the applicant form (age, sex, education, "
                                 "marital_status) is required for question set v2")
    name = (body.applicant_name or "").strip()
    form = body.applicant.model_dump() if body.applicant else {}
    iv = Interview(applicant=Applicant(name=name or None, **form),
                   question_set=body.question_set, language=body.language, mode=body.mode)
    db.add(iv)
    db.flush()
    audit.record(db, user, "interview.create", "interview", iv.id,
                 question_set=iv.question_set, language=iv.language, mode=iv.mode)
    db.commit()
    return s.InterviewCreated(id=iv.id, status=iv.status)


@app.get("/api/interviews", response_model=list[s.InterviewSummary], responses=ERRORS,
         dependencies=OFFICER)
def list_interviews(db: Session = Depends(get_db)):
    """Every interview, newest first, with response counts and any risk class."""
    per_status = {st: func.coalesce(func.sum(case((Response.status == st, 1), else_=0)), 0)
                  for st in ("queued", "transcribed", "failed")}
    counts = (select(Response.interview_id, *(c.label(st) for st, c in per_status.items()))
              .group_by(Response.interview_id).subquery())
    rows = db.execute(
        select(Interview.id, Interview.created_at, Interview.status, Interview.question_set,
               Interview.language, Interview.mode, Applicant.name,
               Assessment.risk_class, Decision.decision,
               counts.c.queued, counts.c.transcribed, counts.c.failed)
        .join(Applicant, Interview.applicant_id == Applicant.id)
        .outerjoin(Assessment, Assessment.interview_id == Interview.id)
        .outerjoin(Decision, Decision.interview_id == Interview.id)
        .outerjoin(counts, counts.c.interview_id == Interview.id)
        .order_by(Interview.created_at.desc(), Interview.id.desc()))
    busy = live_status_of(db)
    out = []
    for r in rows:
        c = s.Counts(queued=r.queued or 0, transcribed=r.transcribed or 0, failed=r.failed or 0)
        if busy and busy[1] == r.id:
            c.queued, c.transcribing = c.queued - 1, 1
        out.append(s.InterviewSummary(
            id=r.id, applicant_name=r.name, created_at=r.created_at, status=r.status,
            question_set=r.question_set, language=r.language, mode=r.mode,
            responses_recorded=c.queued + c.transcribing + c.transcribed + c.failed,
            questions_total=len(QUESTION_SETS[r.question_set]), counts=c,
            risk_class=r.risk_class, decision=r.decision))
    return out


@app.post("/api/interviews/{interview_id}/responses", status_code=202,
          response_model=s.ResponseQueued, responses=ERRORS)
def upload_response(interview_id: int, background: BackgroundTasks,
                    file: UploadFile = File(...), sentence_no: int = Form(..., ge=1),
                    db: Session = Depends(get_db), user: User = Depends(require_officer)):
    iv = get_interview(db, interview_id)
    q = require_answerable(db, iv, sentence_no)

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

        r = Response(interview_id=iv.id, sentence_no=sentence_no, domain=q.topic,
                     source="audio", audio_path="", status="queued")
        db.add(r)
        db.flush()
        key = storage.clip_key(iv.id, r.id, sentence_no)
        dst = config.UPLOADS_DIR / key      # converted here; the backend keeps it from here
        try:
            r.duration_s = pl.convert_upload(incoming, dst)
        except pl.NotAudio as e:
            db.rollback()
            raise HTTPException(415, str(e))
        store = storage.backend()
        try:
            r.audio_path = ref = store.save(dst, key)
        except Exception:
            db.rollback()
            dst.unlink(missing_ok=True)
            log.exception("could not store audio for interview %s sentence %s", iv.id, sentence_no)
            raise HTTPException(503, "audio storage is unavailable; try again")
        audit.record(db, user, "response.create", "response", r.id, interview_id=iv.id,
                     sentence_no=sentence_no, source="audio")
        loans.sync_with_interview(db, iv, user)
        try:
            db.commit()
        except IntegrityError:  # lost a race for the same sentence_no
            db.rollback()
            try:
                store.delete(ref)
            except Exception:  # an orphan clip is harmless; the 409 is what matters
                log.exception("could not remove %s", ref)
            raise HTTPException(409, f"sentence {sentence_no} already has a response")
    finally:
        incoming.unlink(missing_ok=True)

    background.add_task(pl.enqueue, r.id)
    return s.ResponseQueued(id=r.id, interview_id=iv.id, sentence_no=sentence_no,
                            status=r.status)


def require_answerable(db: Session, iv: Interview, sentence_no: int) -> s.Question:
    """The question an answer is for: open interview, in its set, not yet answered."""
    require_open(iv)
    q = question(iv, sentence_no)
    if q is None:
        raise HTTPException(422, f"sentence_no: question set {iv.question_set} has no question "
                                 f"{sentence_no}")
    if db.scalar(select(Response.id).where(Response.interview_id == iv.id,
                                           Response.sentence_no == sentence_no)):
        raise HTTPException(409, f"sentence {sentence_no} already has a response")
    return q


@app.post("/api/interviews/{interview_id}/responses/typed", status_code=201,
          response_model=s.ResponseOut, responses=ERRORS)
def type_response(interview_id: int, body: s.TypedResponse, db: Session = Depends(get_db),
                  user: User = Depends(require_officer)):
    """An answer typed by the officer instead of recorded: no audio, no ASR,
    ready for review at once."""
    iv = get_interview(db, interview_id)
    q = require_answerable(db, iv, body.sentence_no)
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "text: must not be blank")
    r = Response(interview_id=iv.id, sentence_no=body.sentence_no, domain=q.topic,
                 source="typed", audio_path="", status="transcribed", transcript=text)
    try:
        db.add(r)
        db.flush()
        audit.record(db, user, "response.create", "response", r.id, interview_id=iv.id,
                     sentence_no=body.sentence_no, source="typed")
        loans.sync_with_interview(db, iv, user)
        db.commit()
    except IntegrityError:  # lost a race for the same sentence_no
        db.rollback()
        raise HTTPException(409, f"sentence {body.sentence_no} already has a response")
    return s.ResponseOut.model_validate(r)


@app.get("/api/interviews/{interview_id}", response_model=s.InterviewState,
         responses=ERRORS, dependencies=OFFICER)
def interview_state(interview_id: int, db: Session = Depends(get_db)):
    iv = get_interview(db, interview_id)
    busy = live_status_of(db)
    counts, responses = s.Counts(), []
    for r in iv.responses:
        out = s.ResponseOut.model_validate(r)
        if busy and busy[0] == r.id:
            out.status = "transcribing"
        setattr(counts, out.status, getattr(counts, out.status) + 1)
        responses.append(out)
    return s.InterviewState(id=iv.id, status=iv.status, question_set=iv.question_set,
                            language=iv.language, mode=iv.mode, created_at=iv.created_at,
                            applicant=s.Applicant.model_validate(iv.applicant),
                            counts=counts, responses=responses,
                            assessment=assessment_out(iv),
                            decision=iv.decision and s.DecisionOut.model_validate(iv.decision),
                            application_id=iv.application and iv.application.id)


def assessment_out(iv: Interview) -> s.AssessmentOut | None:
    """The stored assessment, with the SACCO rule beside it when the interview
    belongs to a loan application."""
    if iv.assessment is None:
        return None
    out = s.AssessmentOut.model_validate(iv.assessment)
    if iv.application is not None:
        out.comparator = loans.comparator_of(iv.application)
    return out


@app.get("/api/responses/{response_id}/audio", response_class=FileResponse,
         responses={200: {"content": {"audio/wav": {}}},
                    307: {"description": "Supabase storage: a short-lived signed URL"}, **ERRORS},
         dependencies=OFFICER)
def response_audio(response_id: int, db: Session = Depends(get_db)):
    """The stored 16 kHz clip, for replay. Readable after assessment too.
    With Supabase storage, a redirect to a signed URL that soon expires."""
    r = db.get(Response, response_id)
    if r is None:
        raise HTTPException(404, f"response {response_id} not found")
    if r.source == "typed":
        raise HTTPException(404, f"response {response_id} was typed; it has no audio")
    if not r.audio_path:
        raise HTTPException(404, f"audio for response {response_id} is missing")
    store = storage.for_ref(r.audio_path)
    try:
        url = store.signed_url(r.audio_path)
    except Exception:
        log.exception("could not sign the audio URL for response %s", response_id)
        raise HTTPException(503, "audio storage is unavailable; try again")
    if url is not None:
        return RedirectResponse(url, status_code=307)
    path = store.local_path(r.audio_path)
    if not path.is_file():
        raise HTTPException(404, f"audio for response {response_id} is missing")
    return FileResponse(path, media_type="audio/wav",
                        filename=f"interview{r.interview_id}_s{r.sentence_no:02d}.wav")


@app.patch("/api/responses/{response_id}", response_model=s.ResponseOut, responses=ERRORS)
def edit_transcript(response_id: int, body: s.TranscriptEdit, db: Session = Depends(get_db),
                    user: User = Depends(require_officer)):
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
    audit.record(db, user, "response.edit", "response", r.id, interview_id=r.interview_id,
                 sentence_no=r.sentence_no)
    db.commit()
    return s.ResponseOut.model_validate(r)


@app.delete("/api/responses/{response_id}", response_model=s.ResponseDeleted,
            responses=ERRORS)
def delete_response(response_id: int, db: Session = Depends(get_db),
                    user: User = Depends(require_officer)):
    r = db.get(Response, response_id)
    if r is None:
        raise HTTPException(404, f"response {response_id} not found")
    require_open(r.interview)
    out = dict(id=r.id, interview_id=r.interview_id, sentence_no=r.sentence_no)
    iv, audio = r.interview, r.audio_path
    try:
        with pl.withheld(r.id) as was_queued:
            db.delete(r)
            db.flush()
            audit.record(db, user, "response.delete", "response", out["id"],
                         interview_id=out["interview_id"], sentence_no=out["sentence_no"])
            loans.sync_with_interview(db, iv, user)
            db.commit()
    except pl.TranscriptionBusy:
        raise HTTPException(409, f"response {response_id} is being transcribed right now; "
                                 "retry in a few seconds", headers={"Retry-After": "10"})
    if audio:
        try:
            storage.for_ref(audio).delete(audio)
        except Exception:  # the row is gone either way; an orphan file is harmless
            log.exception("could not remove %s", audio)
    return s.ResponseDeleted(**out, was_queued=was_queued)


def form_of(ap: Applicant) -> dict | None:
    """The applicant form as extraction fields, or None if it was never filled
    (interviews from before the form existed)."""
    if all(v is None for v in (ap.age, ap.sex, ap.education, ap.marital_status)):
        return None
    return pl.score_interview.form_values(ap.age, ap.sex, ap.education, ap.marital_status)


@app.post("/api/interviews/{interview_id}/assess", status_code=201,
          response_model=s.AssessmentOut, responses=ERRORS)
def assess(interview_id: int, db: Session = Depends(get_db),
           user: User = Depends(require_officer)):
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

    # English interviews were answered in English: nothing to translate.
    english_interview = iv.language == "en"
    pending = [] if english_interview else [r for r in usable if r.translated_at is None]
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

    sc = pl.score_interview
    answers = []
    for r in usable:
        q = question(iv, r.sentence_no)
        answers.append(sc.Answer(r.sentence_no,
                                 (r.transcript if english_interview else r.translation) or "",
                                 q.text_en if q else "", tuple(q.features) if q else ()))
    if not any(a.text.strip() for a in answers):
        raise HTTPException(409, "no response produced an English translation")
    form = form_of(iv.applicant)
    try:
        feats = sc.extract_features(answers, known=sc.FORM_FIELDS if form else (),
                                    key=config.GEMINI_API_KEY, model=config.GEMINI_MODEL,
                                    log=log.info)
    except Exception as e:
        raise upstream_error("feature extraction", e)
    if not isinstance(feats, dict):
        raise HTTPException(502, "feature extraction: expected a JSON object")

    scored = sc.score(feats, config.CLASSIFIER_PATH, config.CLASSIFIER_META_PATH, form=form)
    out = scored.assessment
    vector = {c: None if math.isnan(v := float(x)) else v
              for c, x in scored.vector.iloc[0].items()}
    a = Assessment(interview=iv, risk_class=out["risk_class"],
                   probabilities=out["probabilities"], feature_vector=vector,
                   contributions=out["top_contributions"], extracted=out["extracted"],
                   applicant_form=out["applicant_form"],
                   extraction_completeness=out["extraction_completeness"],
                   features_populated=out["features_populated"],
                   features_total=out["features_total"],
                   features_not_extractable=out["features_not_extractable_from_interview"],
                   extraction_model=pl.extraction_model(),
                   model_file=scored.model_file, model_sha256=scored.model_sha256,
                   assessed_by=user.username)
    db.add(a)
    iv.status = "assessed"
    try:
        db.flush()
        audit.record(db, user, "assessment.create", "assessment", a.id, interview_id=iv.id,
                     risk_class=a.risk_class)
        loans.sync_with_interview(db, iv, user)
        db.commit()
    except IntegrityError:  # a concurrent assess won
        db.rollback()
        raise HTTPException(409, f"interview {iv.id} is already assessed; its record is immutable")
    return assessment_out(iv)


@app.post("/api/interviews/{interview_id}/decision", status_code=201,
          response_model=s.DecisionOut, responses=ERRORS)
def record_decision(interview_id: int, body: s.DecisionCreate, db: Session = Depends(get_db),
                    user: User = Depends(require_officer)):
    """Record the officer's decision. Only after assessment, and only once.
    An interview with a loan application moves the application too (the
    same as POST /api/applications/{id}/decision)."""
    d = loans.decide(db, get_interview(db, interview_id), body, user)
    return s.DecisionOut.model_validate(d)
