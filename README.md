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

## Layout

```
.env.example                        variable names for secrets (copy to .env)
requirements.txt
data/raw/                           FinAccess .dta goes here (never committed)
data/README.md                      data provenance and how to obtain it
experiments/01_translation_bakeoff/ Kikuyu->English translator comparison
src/chamapro/config.py              loads .env, exposes keys and paths
```

## Setup (Windows, Python 3.11)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # then fill in the values
```

`.env` needs:

| Variable         | Where to get it                                              |
|------------------|--------------------------------------------------------------|
| `GOOGLE_API_KEY` | Google AI Studio -> Get API key                              |
| `HF_TOKEN`       | huggingface.co -> Settings -> Access Tokens (read). You must also accept the terms of `openlanguagedata/flores_plus`. |
| `KHAYA_API_KEY`  | GhanaNLP Khaya studio (only if Kikuyu is supported)          |

Hugging Face models and datasets are cached in `.hf_cache/` inside the project
(override with `HF_HOME`).

## Experiment 1: translation bake-off

Decides which Kikuyu->English translator the pipeline uses, measured on the
first 100 FLORES+ `dev` sentence pairs with chrF++ (decision metric) and BLEU.

```powershell
.venv\Scripts\python experiments\01_translation_bakeoff\run_bakeoff.py
```

Options: `--systems gemini,nllb`, `--n 100`, `--delay 7` (seconds between
Gemini calls), `--score-only` (re-score saved outputs). The script prints the
first three pairs so you can confirm alignment, writes every output to
`experiments/01_translation_bakeoff/results/bakeoff.json` after each sentence,
and resumes from that file on re-run.

Reference points for Kikuyu->English on FLORES: base NLLB-200 about 3 chrF++,
Khaya about 16. Anything under about 10 is not usable as a pipeline component.
