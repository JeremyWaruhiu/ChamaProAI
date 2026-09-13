# Data

## FinAccess Household Survey (`raw/`)

Source: FSD Kenya / Central Bank of Kenya / Kenya National Bureau of Statistics,
FinAccess Household Survey. Download the Stata `.dta` file from the FSD Kenya
data portal (https://fsdkenya.org/ → Research → FinAccess) after accepting the
data-use terms, and place it in `data/raw/`.

The file is licensed for research use and is **never committed** — `.gitignore`
excludes everything in `raw/`. Read it with `pyreadstat.read_dta(...)`.

This is the only dataset used to *train* anything in this project (the credit
scoring classifier).

## FLORES+ (downloaded automatically)

`openlanguagedata/flores_plus` on Hugging Face, `dev` split, languages
`kik_Latn` and `eng_Latn`. Used only to *evaluate* translation candidates in
`experiments/01_translation_bakeoff`. The dataset is gated: accept the terms on
Hugging Face and set `HF_TOKEN` in `.env`. It is cached under `.hf_cache/`.
