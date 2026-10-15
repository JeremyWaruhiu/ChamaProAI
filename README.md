# ChamaPro AI

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
decisions, the pipeline scripts, and an HTTP API (`src/chamapro/api/`) that
exposes the pipeline to the dashboard.

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
scripts/                              pipeline stages; each is a CLI and importable
src/chamapro/config.py                loads .env, exposes keys and paths
src/chamapro/api/                     FastAPI app over the pipeline (SQLite storage)
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

### Environment variables

Set in `.env` (see `.env.example`): `GEMINI_API_KEY`, `GEMINI_MODEL`,
`ASR_MODEL`, `ASR_LANGUAGE`, `HF_TOKEN`. `ASR_LANGUAGE=sw` uses Swahili as the
nearest proxy, since Whisper has no Kikuyu token.

To isolate translation quality from transcription error, run
`translate_extract.py --source ref`, which reads `kikuyu_ref` from the manifest
instead of the ASR output.

### Running the API

    uvicorn chamapro.api.main:app --reload
    pytest                      # API tests; no model download or network

Interactive docs at http://localhost:8000/docs. Startup loads `ASR_MODEL` once,
which takes a minute on CPU. State lives in `data/chamapro.db` (SQLite) and
uploaded audio in `data/uploads/<interview_id>/`; both are gitignored. Optional
`CHAMAPRO_DB` and `CHAMAPRO_UPLOADS` move them elsewhere.

| Method | Path                               | Purpose                                         |
|--------|------------------------------------|-------------------------------------------------|
| POST   | `/api/interviews`                  | start an interview `{applicant_name?}`          |
| GET    | `/api/interviews`                  | all interviews, newest first, with response counts and risk class |
| POST   | `/api/interviews/{id}/responses`   | upload one clip (`file`, `sentence_no`); 202, transcribed in the background |
| GET    | `/api/interviews/{id}`             | full state; the dashboard polls this            |
| PATCH  | `/api/responses/{id}`              | correct a transcript `{transcript}` before assessment |
| DELETE | `/api/responses/{id}`              | discard a clip so its sentence can be re-recorded; 409 while it is being transcribed |
| POST   | `/api/interviews/{id}/assess`      | translate, extract, score; stores the assessment |
| GET    | `/api/health`                      | classifier, API key, ASR model status           |

An assessment is written once and never changed: it stores the exact feature
vector the classifier saw, the probabilities, SHAP contributions and the
classifier's filename and SHA-256. SQLite triggers reject any UPDATE or DELETE
on the `assessments` table. Once an interview is assessed, its responses can no
longer be added, edited or deleted. Clips are transcribed one at a time, so a full
interview of 40 clips takes about 20 minutes to clear the queue.

### Demo data

    python scripts/seed_demo.py

Creates one open interview holding all 40 S01 responses, marked transcribed,
from `data/asr_paza.csv` and `data/audio_16k/`, so a full interview can be
reviewed and assessed without an hour of transcription. Takes about a second
and needs no model. Safe to re-run: it changes nothing if the demo is
complete, restores any response deleted for re-recording, and starts a fresh
demo once the previous one has been assessed. Audio is copied into
`data/uploads/`, so re-recording in the dashboard never touches the corpus.

### Known limitations

- Corpus is 40 responses from one speaker; no speaker-independent claim holds.
- ASR runs at 1.9x real time on CPU; the five-minute performance target applies
  to the typed-input path only.
- Decoder repetition collapse affects ~10% of clips.
- Cascade yield is 62.5%; asset-ownership responses currently yield nothing.
- Feature extraction requires connectivity; capture and typed entry do not.
