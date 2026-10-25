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
requirements.txt                      Python dependencies, pinned (CPU-only torch, OpenVINO)
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
  interview_questions.txt             question set v1: the 40 sentences of the recorded corpus (DRAFT)
  wireframes/                         Figures 4.8-4.12 of the design chapter
  design_changes.md                   where the dashboard departs from the wireframes, and why
scripts/                              pipeline stages; each is a CLI and importable
src/chamapro/config.py                loads .env, exposes keys and paths
src/chamapro/questions.json           question sets v1 (built from docs/) and v2 (edited here), served to the dashboard
models/                               classifier and OpenVINO ASR exports (gitignored; see Setup)
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

`requirements.txt` pins the environment the system is tested on, including
the CPU-only build of PyTorch with its matching torchvision (a mismatched
torchvision breaks `from transformers import pipeline`;
`tests/test_environment.py` checks the installed versions against the pins).
No CUDA is needed.

Speech recognition runs on OpenVINO with int8 weights, on an Intel GPU where
there is one and on the CPU otherwise. Export the two models once (downloads
about 3 GB into `.hf_cache/`, writes `models/paza-ov-int8/` and
`models/whisper-en-ov-int8/`, both gitignored):

```powershell
python scripts/export_openvino.py              # or --only kik / --only en
```

Without an export the API falls back to the torch model, which is several
times slower on a CPU.

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
`data/asr_output.csv`; it takes the same engine settings as the API
(`--engine openvino|torch`, `--device GPU|CPU`, `--ov-dir`, `--decoding
timestamps|plain`, `--tokens-per-second`, defaulting to the `ASR_*` variables
below). `translate_extract.py` batches responses into requests
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

`src/chamapro/questions.json` holds every question set as one list. Each
question has `id`, `version`, `topic`, `order`, `text_en`, `text_kik` ("" until a
native speaker supplies it) and `features`, the classifier features it is asked
for.

- **v2** (current, 8 questions) is what new interviews ask. It is edited in
  `questions.json` directly. Age, sex, highest education and marital status
  are not asked: the officer enters them on the **applicant form** when
  creating the interview (`GET /api/applicant-form` lists the choices with the
  codes the classifier was trained on). Form plus v2 cover the classifier's 40
  features exactly once; `tests/test_questions.py` checks it. The main source
  of income named in answer to question 2 also sets its income-source flag
  (an extraction rule), but the flags are listed under question 3 only.
- **v1** (40 sentences) is the set of the recorded corpus, kept so the
  Kikuyu demo interview and the evaluation still load. Interviews created
  before question sets existed are v1. `docs/interview_questions.txt` is the
  single place to edit its wording; after changing it, run

      python scripts/build_questions.py

  Domains come from the manifest. Kikuyu text already in the JSON is kept, so
  a native speaker's translations survive edits to the English, and other sets
  are left as they are. `--check` reports whether the JSON is out of date, and
  the test suite runs that check.

Feature extraction sends each answer with its question and the fields that
question targets, at temperature 0, under the same rules as before: only
what the applicant stated, nothing inferred, each fact recorded once. Fields
the applicant form fills are left out of the prompt and merged into the
feature vector directly; the assessment stores the form values beside the
extraction model's reply.

### Environment variables

Set in `.env` (see `.env.example`): `GEMINI_API_KEY`, `GEMINI_MODEL`,
`ASR_MODEL`, `ASR_LANGUAGE`, `HF_TOKEN`. `ASR_LANGUAGE=sw` uses Swahili as the
nearest proxy, since Whisper has no Kikuyu token.

| Variable                 | Default                                 | Meaning |
|--------------------------|-----------------------------------------|---------|
| `ASR_ENGINE`             | `openvino`                              | `openvino` or `torch` |
| `ASR_DEVICE`             | `GPU`                                   | `GPU` or `CPU`; OpenVINO falls back to the CPU when there is no usable GPU |
| `ASR_OV_MODEL_DIR`       | `models/paza-ov-int8`                   | Kikuyu OpenVINO export; if missing, the torch engine runs `ASR_MODEL` |
| `ASR_MODEL`              | `microsoft/paza-whisper-large-v3-turbo` | Kikuyu torch model |
| `ASR_EN_OV_MODEL_DIR`    | `models/whisper-en-ov-int8`             | English OpenVINO export (same fallback, to `ASR_EN_MODEL`) |
| `ASR_EN_MODEL`           | `openai/whisper-large-v3-turbo`         | English torch model |
| `ASR_DECODING`           | `timestamps`                            | `timestamps` or `plain`; see the ASR benchmark before changing it |
| `ASR_TOKENS_PER_SECOND`  | `12`                                    | generation cap: `max_new_tokens` = 16 + this × clip seconds |

Every transcription keeps the decoding safeguards: `condition_on_prev_tokens`
off, and with timestamped decoding any chunk that starts after the clip's end
is dropped. The token cap stops a run-on continuation from being generated in
the first place. The server logs which engine and device it ended up on, and
`/api/health` reports them (`asr_engine`, `asr_device`, and `asr` per
language).

### ASR benchmark

    python scripts/benchmark_asr.py            # all 40 clips; about 45 minutes, most of it torch CPU
    python scripts/benchmark_asr.py --runs openvino:GPU --limit 5

Runs the 40 manifest clips under torch CPU, OpenVINO CPU int8 and OpenVINO GPU
int8, each with (a) timestamped decoding + end-of-clip truncation + token cap
and (b) plain decoding + token cap. It records total and mean real-time factor
(ASR seconds per audio second), the repetition-collapse count (the rule in
`scripts/view_results.py`) and character-level agreement with
`data/asr_paza.csv`. Per-clip transcripts go to `data/asr_benchmark/`
(gitignored); only aggregates go to `results/asr_benchmark.json`. A run that
cannot load its engine or device is recorded as skipped, never silently
measured on another.

Results on this machine (Intel Core Ultra 7 256V CPU, integrated "Intel(R) Graphics [0x64a0]" GPU as OpenVINO reports it; 40 clips,
217 s of audio; `results/asr_benchmark.json`):

| Engine   | Device | Decoding   | Total RTF | Mean RTF | Collapsed | Agreement (mean) | Exact |
|----------|--------|------------|----------:|---------:|----------:|-----------------:|------:|
| torch    | CPU    | timestamps | 3.73 | 3.90 | 0 | 0.913 | 34 |
| torch    | CPU    | plain      | 3.53 | 3.69 | 0 | 0.329 | 0 |
| OpenVINO | CPU    | timestamps | 1.08 | 1.14 | 0 | 0.845 | 22 |
| OpenVINO | CPU    | plain      | 1.69 | 1.72 | 0 | 0.305 | 0 |
| OpenVINO | GPU    | timestamps | 0.44 | 0.45 | 0 | 0.825 | 22 |
| OpenVINO | GPU    | plain      | 0.47 | 0.47 | 0 | 0.303 | 0 |

Agreement is similarity to the earlier uncapped torch run, not accuracy: the
six torch-timestamps clips that differ are exactly the six whose reference
ran on past the speech, where the cap cut the continuation short. Plain
decoding keeps generating after the speech ends, up to the cap. The default
stays `timestamps` until a decision is made on these figures.

To isolate translation quality from transcription error, run
`translate_extract.py --source ref`, which reads `kikuyu_ref` from the manifest
instead of the ASR output.

### Cascade quality by ASR engine

Whether the OpenVINO GPU int8 transcripts cost translation quality. Each ASR
output is translated twice; the Paza torch transcripts are re-translated as a
control, because the committed Paza figures predate pinning the translator's
temperature to 0. Only the worksheet's fictional content is sent to Gemini.

    python scripts/translate_extract.py --input data/asr_benchmark/openvino_gpu_timestamps.csv --out data/translation_output_ov_gpu_int8_r1.csv
    python scripts/translate_extract.py --input data/asr_paza.csv --out data/translation_output_paza_rerun_r1.csv
    # repeat both with _r2, then:
    python scripts/aggregate_cascade.py

`aggregate_cascade.py` scores the four translations with `score.py` and writes
only aggregates to `results/cascade_openvino_gpu_int8.json`; translations stay
in `data/` (gitignored). It records `GEMINI_MODEL` from `.env` as the
translator (`--translator` to override). Results (`gemini-3.5-flash`, mean of
two repeats):

| Transcripts                            | chrF++ |  BLEU |
|----------------------------------------|-------:|------:|
| Paza torch, committed figures          |  47.15 | 29.67 |
| Paza torch, re-translated              |  46.87 | 30.32 |
| OpenVINO GPU int8, timestamped         |  46.87 | 27.36 |

The two control repeats differ by 1.7 chrF++, as much as any engine effect.
Per domain, chama drops sharply on GPU int8 (32.59 to 15.38 chrF++) while
income and expenditure rise; five sentences per domain make these indicative only.

### Running the API

    uvicorn chamapro.api.main:app --reload --reload-dir src --reload-dir scripts
    pytest                      # API tests; no model download or network

`--reload-dir` keeps the reloader to the code. Loading the speech model
writes Python files into `.hf_cache/`, and the server also writes to `data/`;
a plain `--reload` sees those writes, restarts, reloads the model and loops
forever, so the dashboard never gets an answer.

Interactive docs at http://localhost:8000/docs. Startup loads the Kikuyu ASR
model once (about 15 s for the OpenVINO GPU export, a minute for torch on
CPU); the English model loads the first time an English answer is
transcribed. State lives in `data/chamapro.db` (SQLite) and
uploaded audio in `data/uploads/<interview_id>/`; both are gitignored. Optional
`CHAMAPRO_DB` and `CHAMAPRO_UPLOADS` move them elsewhere.

| Method | Path                               | Purpose                                         |
|--------|------------------------------------|-------------------------------------------------|
| POST   | `/api/interviews`                  | start an interview `{applicant_name?, applicant: {age, sex, education, marital_status}, language?: kik\|en, mode?: live\|practice, question_set?: v2\|v1}`; the form is required for v2 |
| GET    | `/api/questions?version=v2`        | one question set, in order (`text_kik` is "" until supplied) |
| GET    | `/api/applicant-form`              | the applicant form's choices, with the classifier's codes |
| GET    | `/api/interviews`                  | all interviews, newest first, with response counts, risk class and decision |
| POST   | `/api/interviews/{id}/responses`   | upload one clip (`file`, `sentence_no`); 202, transcribed in the background |
| POST   | `/api/interviews/{id}/responses/typed` | a typed answer `{sentence_no, text}`; `source: "typed"`, no audio, no ASR, ready for review |
| GET    | `/api/interviews/{id}`             | full state; the dashboard polls this            |
| PATCH  | `/api/responses/{id}`              | correct a transcript `{transcript}` before assessment |
| DELETE | `/api/responses/{id}`              | discard a clip so its sentence can be re-recorded; 409 while it is being transcribed |
| GET    | `/api/responses/{id}/audio`        | the stored 16 kHz clip, for replay              |
| POST   | `/api/interviews/{id}/assess`      | translate (Kikuyu only), extract, score; stores the assessment |
| POST   | `/api/interviews/{id}/decision`    | the officer's decision `{decision: approve\|decline\|refer, note?}`, after assessment, once |
| GET    | `/api/health`                      | classifier, API key, ASR engine/device/model per language (no sign-in needed) |
| POST   | `/api/auth/login`                  | `{username, password}`; sets the session cookie, returns `{username, role}` |
| POST   | `/api/auth/google`                 | `{credential}` (Google ID token); signs in the linked user; 404 when not configured |
| GET    | `/api/auth/config`                 | `{google_client_id}`, null when Google sign-in is off (no sign-in needed) |
| POST   | `/api/auth/logout`                 | ends the session and clears the cookie          |
| GET    | `/api/auth/me`                     | `{username, role}` of the signed-in user, or 401 |
| GET    | `/api/results`                     | model and evaluation summary plus live stats, practice interviews excluded (admin only) |

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
responses can no longer be added, edited or deleted. Clips are transcribed one
at a time, in the background.

**Interview options.** An interview's `language` is `kik` (Kikuyu answers,
transcribed by Paza and translated to English before extraction) or `en`
(English answers, transcribed by the English model with language `en`, and
not translated). Its `mode` is `live` or `practice`: a practice interview
works the same way, but every dashboard screen of it shows a practice banner,
its decision is labelled practice, and it is left out of every live figure
on the Model & Evaluation page. Any answer can be typed instead of recorded.

The database is migrated in place at startup: existing interviews become
`v1`, `kik`, `live`, existing responses `audio`, and nothing else changes
(ADD COLUMN only, so the immutability triggers are untouched).

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
- ASR speed depends on the engine: see the ASR benchmark above. With the
  torch engine on a CPU it runs slower than real time.
- Decoder repetition collapse affects ~10% of clips.
- Cascade yield is 62.5%; asset-ownership responses currently yield nothing.
- Feature extraction requires connectivity; capture and typed entry do not.
- Question set v2 has no Kikuyu wording yet (`text_kik` is ""); the dashboard
  shows the English until a native speaker supplies it.
- v2 questions 3-5 name exactly the FinAccess options behind their flags
  (B3A__1-11, F1__1-5, B1L__1-6). The codebook does not define F1__4
  "Digital non-financial assets"; the question gives cryptocurrency as the
  example, which is this project's reading of the label.

## Running the full system for a demo

Prerequisites: setup above, a `.env` with `GEMINI_API_KEY`, the trained
classifier in `models/` (`python scripts/train_and_save.py`), and Node.js
20.19 or later for the dashboard.

1. **Seed the demo interviews** (about a second, no model needed):

       python scripts/seed_demo.py                  # --practice-only without the audio corpus

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
- Open **Practice: Mary Wambui (fictional)** for an English practice
  interview: the applicant form is filled in and all eight answers are typed,
  so it can be assessed at once. Every screen of it shows the practice
  banner, and it does not count in the live statistics.
- To show live recording, start a **New interview**, fill in the applicant
  form and record an answer with the laptop microphone. It is transcribed in
  the background while you move to the next question; any answer can be
  typed instead.

Run `seed_demo.py` again before the next demo. An assessed demo cannot be
changed, so the script then starts a fresh one. See
[frontend/README.md](frontend/README.md) for more on the dashboard.

### Demo data

    python scripts/seed_demo.py

Creates one open interview holding all 40 S01 responses (question set v1,
Kikuyu, live), marked transcribed, from `data/asr_paza.csv` and
`data/audio_16k/`, so a full interview can be reviewed and assessed without
an hour of transcription. It also creates an English practice interview
(question set v2) for a fictional applicant, with the applicant form filled
in and all eight answers typed; `--practice-only` creates just that one, for
a machine without the audio corpus. Takes about a second and needs no model.
Safe to re-run: it changes nothing if both are complete, restores any
response deleted for re-recording, and starts a fresh one once the previous
one has been assessed. Audio is copied into `data/uploads/`, so re-recording
in the dashboard never touches the corpus.
