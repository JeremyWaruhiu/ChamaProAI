# ChamaPro AI

[![CI](https://github.com/JeremyWaruhiu/ChamaProAI/actions/workflows/ci.yml/badge.svg)](https://github.com/JeremyWaruhiu/ChamaProAI/actions/workflows/ci.yml)

Interpretable machine-learning credit assessment for rural Kenyan SACCOs serving
Kikuyu-speaking communities. Final-year BSc Informatics & Computer Science
project, Strathmore University.

The system asks a loan applicant interview questions in Kikuyu (spoken),
transcribes the answer, translates it to English, extracts structured features,
and produces a three-class credit-risk classification with an explanation.

**Exactly one model is trained in this project: the credit-scoring classifier.**
Every speech and language component is a published artefact used at inference
time only. Target hardware is CPU-only, 16 GB RAM.

The repository contains the research experiments behind those design
decisions, the pipeline scripts, an HTTP API (`src/chamapro/api/`) over the
pipeline, and the loan officer's dashboard (`frontend/`).

## Layout

```
.env.example                          variable names for secrets (copy to .env)
requirements.txt                      Python dependencies (CPU-only torch)
data/
  README.md                           data provenance and how to obtain it
  raw/                                FinAccess .dta goes here (never committed)
  explore/                            explorer outputs (generated, never committed)
docs/
  ETHICS.md                           consent and data-protection statement
experiments/
  01_translation_bakeoff/             Kikuyu->English translator comparison
  02_finaccess_prep/                  builds the modelling frame from FinAccess
  03_classifier/                      credit-risk classifier, comparator, SHAP
  04_borrower_subset/                 SACCO/chama borrowers with loan features
  */results/                          committed JSON summaries; CSVs/logs ignored
docs/
  interview_questions.txt             the 40 interviewer questions (DRAFT)
  wireframes/                         Figures 4.8-4.12 of the design chapter
  design_changes.md                   where the dashboard departs from the wireframes, and why
scripts/                              pipeline stages; each is a CLI and importable
src/chamapro/config.py                loads .env, exposes keys and paths
src/chamapro/questions.json           question script served to the dashboard (built from docs/)
src/chamapro/api/                     FastAPI app over the pipeline (SQLite storage)
frontend/                             React dashboard (Vite + TypeScript); see frontend/README.md
tests/                                API and script tests (pytest)
scripts/explore_finaccess.py            browse the FinAccess microdata
```

## Prerequisites

- **Python 3.11** (developed on 3.11.9). The commands below are for Windows
  PowerShell; on macOS/Linux use `source .venv/bin/activate` and `cp`.
- **Git**.
- About 5 GB of free disk for the virtual environment and the Hugging Face
  model cache (NLLB-200 is downloaded on first run of experiment 01).
- **The FinAccess 2024 microdata**, `2024_Finaccess_Publicdata.dta`, placed in
  `data/raw/`. It is licensed and not in this repository; see
  [data/README.md](data/README.md) for how to obtain it. Experiments 02-04 and
  the explorer need it; experiment 01 does not.

## Setup

```powershell
git clone https://github.com/JeremyWaruhiu/ChamaProAI.git
cd ChamaProAI
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .            # makes src/chamapro importable (needed by the API)
copy .env.example .env      # then fill in the values
```

`requirements.txt` pulls the CPU-only build of PyTorch; no GPU or CUDA is
needed.

### Environment variables

`.env` is read by `src/chamapro/config.py`. It is gitignored; never commit it.

| Variable         | Needed by      | Where to get it                                              |
|------------------|----------------|--------------------------------------------------------------|
| `GOOGLE_API_KEY` | experiment 01  | Google AI Studio -> Get API key                              |
| `HF_TOKEN`       | experiment 01  | huggingface.co -> Settings -> Access Tokens (read). You must also accept the terms of `openlanguagedata/flores_plus`. |
| `KHAYA_API_KEY`  | experiment 01  | GhanaNLP Khaya studio (only if Kikuyu is supported)          |
| `HF_HOME`        | optional       | Hugging Face cache location; defaults to `.hf_cache/` in the project |

Experiments 02-04 and the explorer need no keys, only the FinAccess file.

## Running

All commands are run from the project root with the virtual environment
active.

### Experiment 01: translation bake-off

Decides which Kikuyu->English translator the pipeline uses, measured on the
first 100 FLORES+ `dev` sentence pairs with chrF++ (decision metric) and BLEU.

```powershell
python experiments\01_translation_bakeoff\run_bakeoff.py
```

Options: `--systems gemini,nllb`, `--n 100`, `--delay 7` (seconds between
Gemini calls), `--score-only` (re-score saved outputs). The script prints the
first three pairs so you can confirm alignment, writes every output to
`experiments/01_translation_bakeoff/results/bakeoff.json` after each sentence,
and resumes from that file on re-run.

Reference points for Kikuyu->English on FLORES: base NLLB-200 about 3 chrF++,
Khaya about 16. Anything under about 10 is not usable as a pipeline component.

### Experiment 02: FinAccess modelling frame

Builds the labelled modelling frame. Central Kenya is held out of training
entirely and used as an unseen target population. Leakage variables are
excluded; `--include-suspect` re-admits the borderline ones so their effect can
be measured.

```powershell
python experiments\02_finaccess_prep\prep.py
python experiments\02_finaccess_prep\prep.py --include-suspect
```

Writes `modelling_frame[_suspect].csv` (gitignored, derived from licensed data)
and `prep_profile[_suspect].json` (committed) to `results/`.

### Experiment 03: classifier

Trains the credit-risk classifier on the frame from experiment 02, compares it
with a rule-based baseline, and reports SHAP explanations. Run experiment 02
first.

```powershell
python experiments\03_classifier\model.py --tag _base_3c
python experiments\03_classifier\model.py --frame experiments\02_finaccess_prep\results\modelling_frame_suspect.csv --tag _suspect_3c
```

Options: `--binary` (default/no-default, banded back into three classes),
`--low-vs-high` (drop the Medium class), `--random-split` (stratified split
instead of the Central Kenya holdout), `--seed 42`. Results go to
`results/model_results<tag>.json`.

### Experiment 04: borrower subset

Restricts to SACCO and chama borrowers and adds loan-module features. Central
Kenya is too small to hold out here, so classification uses a stratified random
split.

```powershell
python experiments\04_borrower_subset\prep_borrowers.py
python experiments\03_classifier\model.py --frame experiments\04_borrower_subset\results\borrower_frame.csv --random-split --tag _e04_3c
```

`model.py` always writes to `experiments/03_classifier/results/`; the committed
experiment 04 results were moved into `experiments/04_borrower_subset/results/`.

### FinAccess explorer

The microdata is 20,871 rows x 3,816 variables, too large to open whole. The
explorer writes a codebook and slices to `data/explore/` (gitignored).

```powershell
python tools\explore_finaccess.py --dictionary          # full codebook
python tools\explore_finaccess.py --search "sacco|chama"
python tools\explore_finaccess.py --values E2E
python tools\explore_finaccess.py --export county,E2E,A18,Sex,B3Ii
```

## Data protection

Licensed survey data, interview audio and signed consent forms are never
committed; `.gitignore` enforces this. See [docs/ETHICS.md](docs/ETHICS.md).

## Running the pipeline

Place recordings in `data/raw_audio/<SPEAKER>/`, then:

    python scripts/ingest_audio.py --in data/raw_audio/S01 --speaker S01
    python scripts/transcribe.py
    python scripts/translate_extract.py --chunk 5

`ingest_audio.py` converts to 16 kHz mono WAV and builds `data/manifest.csv`,
the index every later stage reads. `transcribe.py` writes ASR hypotheses to
`data/asr_output.csv`. `translate_extract.py` batches responses into requests
of five, retries 429/500/503 with exponential backoff, and writes English
translations with extracted financial signals to `data/translation_output.csv`.

### Scoring translations

    python scripts/score.py

Scores translation outputs against `english_ref` in `data/manifest.csv` (the
recording worksheet's English, which describes a fictional applicant). It reports
chrF++ (the decision metric, as in experiment 01) and BLEU, for the whole corpus
and per domain. By default it scores both cascades,
`translation_output_whisper_small.csv` and `translation_output.csv` (Paza). Pass
other files as arguments, and `--json out.json` to save the figures. A blank
translation counts as an empty hypothesis, so the corpus score reflects what
the cascade actually delivered.

### Interview questions

`docs/interview_questions.txt` is the single place to edit the question
wording. After changing it, run

    python scripts/build_questions.py

to regenerate `src/chamapro/questions.json`, which the API serves. Domains come
from the manifest. Kikuyu text already in the JSON is kept, so a native
speaker's translations survive edits to the English. `--check` reports whether
the JSON is out of date, and the test suite runs that check.

### Environment variables

Set in `.env` (see `.env.example`): `GEMINI_API_KEY`, `GEMINI_MODEL`,
`ASR_MODEL`, `ASR_LANGUAGE`, `HF_TOKEN`. `ASR_LANGUAGE=sw` uses Swahili as the
nearest proxy, since Whisper has no Kikuyu token.

To isolate translation quality from transcription error, run
`translate_extract.py --source ref`, which reads `kikuyu_ref` from the manifest
instead of the ASR output.

### Running the API

    uvicorn chamapro.api.main:app --reload --reload-dir src --reload-dir scripts
    pytest                      # API tests; no model download or network

`--reload-dir` keeps the reloader to the code. Loading the speech model
writes Python files into `.hf_cache/`, and the server also writes to `data/`;
a plain `--reload` sees those writes, restarts, reloads the model and loops
forever, so the dashboard never gets an answer.

Interactive docs at http://localhost:8000/docs. Startup loads `ASR_MODEL` once,
which takes a minute on CPU. State lives in `data/chamapro.db` (SQLite) and
uploaded audio in `data/uploads/<interview_id>/`; both are gitignored. Optional
`CHAMAPRO_DB` and `CHAMAPRO_UPLOADS` move them elsewhere.

| Method | Path                               | Purpose                                         |
|--------|------------------------------------|-------------------------------------------------|
| POST   | `/api/interviews`                  | start an interview `{applicant_name?}`          |
| GET    | `/api/questions`                   | the 40-question script (`kikuyu` is "" until supplied) |
| GET    | `/api/interviews`                  | all interviews, newest first, with response counts, risk class and decision |
| POST   | `/api/interviews/{id}/responses`   | upload one clip (`file`, `sentence_no`); 202, transcribed in the background |
| GET    | `/api/interviews/{id}`             | full state; the dashboard polls this            |
| PATCH  | `/api/responses/{id}`              | correct a transcript `{transcript}` before assessment |
| DELETE | `/api/responses/{id}`              | discard a clip so its sentence can be re-recorded; 409 while it is being transcribed |
| GET    | `/api/responses/{id}/audio`        | the stored 16 kHz clip, for replay              |
| POST   | `/api/interviews/{id}/assess`      | translate, extract, score; stores the assessment |
| POST   | `/api/interviews/{id}/decision`    | the officer's decision `{decision: approve\|decline\|refer, note?}`, after assessment, once |
| GET    | `/api/health`                      | classifier, API key, ASR model status (no sign-in needed) |
| POST   | `/api/auth/login`                  | `{username, password}`; sets the session cookie, returns `{username, role}` |
| POST   | `/api/auth/google`                 | `{credential}` (Google ID token); signs in the linked user; 404 when not configured |
| GET    | `/api/auth/config`                 | `{google_client_id}`, null when Google sign-in is off (no sign-in needed) |
| POST   | `/api/auth/logout`                 | ends the session and clears the cookie          |
| GET    | `/api/auth/me`                     | `{username, role}` of the signed-in user, or 401 |
| GET    | `/api/results`                     | model and evaluation summary plus live stats (admin only) |

Every endpoint except `/api/health`, `/api/auth/config` and the sign-in endpoints needs a signed-in
user: 401 without one, 403 for an officer on an admin-only endpoint. Officers
and admins may use the interview, response, assessment and decision endpoints;
only admins may read `/api/results`. Sign-in sets an HttpOnly, SameSite=Strict
session cookie that lasts 8 hours (Secure except on localhost;
`CHAMAPRO_COOKIE_SECURE=1` or `0` overrides). Five failed sign-ins for one
username within 15 minutes lock it out for the rest of that window (429).
Passwords are stored as salted scrypt hashes and sessions as SHA-256 hashes of
the token. Each assessment and decision records the username that made it;
rows from before sign-in existed keep a null there.

An assessment is written once and never changed: it stores the exact feature
vector the classifier saw, the probabilities, SHAP contributions and the
classifier's filename and SHA-256. The officer's decision is a separate record,
written once after the assessment. SQLite triggers reject any UPDATE or DELETE
on the `assessments` and `decisions` tables. Once an interview is assessed, its
responses can no longer be added, edited or deleted. Clips are transcribed one at a time, so a full
interview of 40 clips takes about 20 minutes to clear the queue.

### Users

There are no default users and no passwords in the repository. Create the
first administrator from the command line; the script asks for the password
twice and never prints it:

    python scripts/create_user.py admin --role admin

Then add each loan officer (the role defaults to `officer`):

    python scripts/create_user.py wanjiru

Passwords must be at least 10 characters. The script creates the database
tables if they do not exist yet, so it can run before the API has started.

### Sign in with Google (optional)

Users can also sign in with a Google account, alongside their username and
password. Google sign-in **only signs in users who already exist** and have that
Google email linked; it never creates an account. An unlinked or unknown email
gets the same "incorrect username or password" as a failed password sign-in.
Without `GOOGLE_CLIENT_ID` the login page shows no Google button at all.

**1. Google Cloud setup** (once, at https://console.cloud.google.com):

1. Create or pick a project.
2. *Google Auth Platform* (formerly *APIs & Services → OAuth consent screen*):
   set the app name and support email, choose **External** audience, and leave
   the publishing status on **Testing**.
3. Under *Audience → Test users*, add every Google account that will sign in.
   In Testing mode no other account can.
4. Under *Clients* (formerly *Credentials*), create an **OAuth client ID** of
   type **Web application**. Under **Authorised JavaScript origins** add both
   `http://localhost` and `http://localhost:5173`. No redirect URI is needed:
   the dashboard uses Google's pop-up.
5. Copy the client ID (`….apps.googleusercontent.com`). It is not a secret, but
   it belongs in `.env`, not in the code.

**2. Configure the server.** Add it to `.env` (never committed) and restart
the API:

    GOOGLE_CLIENT_ID=1234567890-abc….apps.googleusercontent.com

`GET /api/auth/config` then returns it, and the login page shows Google's
"Sign in with Google" button under the password form.

**3. Link a Google email to a user:**

    python scripts/link_google.py admin you@gmail.com   # link (stored lower-case)
    python scripts/link_google.py admin                 # show the current link
    python scripts/link_google.py admin --clear         # unlink

or when creating the user: `python scripts/create_user.py wanjiru --email wanjiru@gmail.com`.
Each email can be linked to one user. The password stays required, so an
officer without a Google account, or a branch without internet, can always sign in.

Google sign-in needs internet access in the browser (to load
`accounts.google.com/gsi/client`) and on the server (to fetch Google's signing
keys). It requires `email_verified` and checks the audience and issuer, and it
shares the password login's session, cookie, 8-hour expiry and rate limit (5
failures per email per 15 minutes). Each session records whether it began with
a password or with Google.

### Known limitations

- Corpus is 40 responses from one speaker; no speaker-independent claim holds.
- ASR runs at 1.9x real time on CPU; the five-minute performance target applies
  to the typed-input path only.
- Decoder repetition collapse affects ~10% of clips.
- Cascade yield is 62.5%; asset-ownership responses currently yield nothing.
- Feature extraction requires connectivity; capture and typed entry do not.

## Running the full system for a demo

Prerequisites: setup above, a `.env` with `GEMINI_API_KEY`, the trained
classifier in `models/` (`python scripts/train_and_save.py`), and Node.js
20.19 or later for the dashboard.

1. **Seed the demo interview** (about a second, no model needed):

       python scripts/seed_demo.py

2. **Start the backend** in one terminal. It loads the speech model, which
   takes about a minute. Wait for `Application startup complete`.

       uvicorn chamapro.api.main:app --reload --reload-dir src --reload-dir scripts

   Keep both `--reload-dir` flags: without them the server restarts in a loop
   (see [Running the API](#running-the-api)).

3. **Start the dashboard** in a second terminal:

       cd frontend
       npm install          # first time only
       npm run dev

4. **Create a user** the first time (see [Users](#users)):

       python scripts/create_user.py admin --role admin

5. Open **http://localhost:5173** and sign in. Check
   http://localhost:8000/api/health shows `"status": "ok"`. Admins see a
   **Model & Evaluation** link in the interview list header; officers do not.

A demo run:

- Open **Demo applicant (S01)**. All 40 answers are already transcribed.
- On **Review transcripts**, correct a transcript and save it to show the
  *Edited* mark.
- Press **Run assessment**. Translation and scoring take about half a minute
  and need internet access for Gemini.
- On the assessment, record the officer's decision.
- To show live recording, start a **New interview** and record an answer with
  the laptop microphone. It is transcribed in the background in about 35 s
  while you move to the next question.

Run `seed_demo.py` again before the next demo. An assessed demo cannot be
changed, so the script then starts a fresh one. See
[frontend/README.md](frontend/README.md) for more on the dashboard.

### Demo data

    python scripts/seed_demo.py

Creates one open interview holding all 40 S01 responses, marked transcribed,
from `data/asr_paza.csv` and `data/audio_16k/`, so a full interview can be
reviewed and assessed without an hour of transcription. Takes about a second
and needs no model. Safe to re-run: it changes nothing if the demo is
complete, restores any response deleted for re-recording, and starts a fresh
demo once the previous one has been assessed. Audio is copied into
`data/uploads/`, so re-recording in the dashboard never touches the corpus.
