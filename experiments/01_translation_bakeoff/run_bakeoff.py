"""Translation bake-off: Kikuyu -> English on FLORES+ dev.

Compares candidate translation systems on the same N sentence pairs and reports
chrF++ (decision metric) and BLEU. Every source/reference/system output is saved
to results/bakeoff.json, which is written after every sentence so a crash or
rate-limit keeps partial progress and a re-run resumes where it stopped.

Usage:
    python run_bakeoff.py                      # gemini + nllb, first 100 pairs
    python run_bakeoff.py --systems nllb       # one system only
    python run_bakeoff.py --n 20 --delay 8     # smoke test with slower pacing
    python run_bakeoff.py --score-only         # re-score existing results
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path

# Make src/chamapro importable when run from anywhere.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from chamapro import config  # noqa: E402  (sets HF_HOME before HF imports)

# Windows console defaults to cp1252, which can't print Kikuyu diacritics.
sys.stdout.reconfigure(encoding="utf-8")

RESULTS_DIR = Path(__file__).resolve().parent / "results"
RESULTS_PATH = RESULTS_DIR / "bakeoff.json"

DATASET = "openlanguagedata/flores_plus"
SRC_LANG, TGT_LANG, SPLIT = "kik_Latn", "eng_Latn", "dev"


# ---------------------------------------------------------------------------
# Candidate systems
# ---------------------------------------------------------------------------
class Translator(ABC):
    name: str
    #: seconds to sleep between calls (API rate limiting); 0 for local models
    delay: float = 0.0

    @abstractmethod
    def translate(self, text: str) -> str: ...

    def translate_batch(self, texts: list[str]) -> list[str]:
        """Default: one at a time. Local models override to batch."""
        return [self.translate(t) for t in texts]


def _retry(fn, attempts: int = 5, base_wait: float = 10.0):
    """Call fn(); on exception wait base_wait * 2**k and retry. Raises after last."""
    for k in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - we want to survive any API hiccup
            wait = base_wait * (2 ** k)
            print(f"    ! {type(e).__name__}: {str(e)[:120]} - retry {k + 1}/{attempts} in {wait:.0f}s")
            time.sleep(wait)
    raise RuntimeError(f"gave up after {attempts} attempts")


class GeminiTranslator(Translator):
    name = "gemini"

    SYSTEM = (
        "You are a professional Kikuyu (Gikuyu) to English translator. "
        "Translate the user's text into natural English. Preserve all numbers, "
        "amounts, currencies, dates and names exactly. Return ONLY the English "
        "translation: no preamble, no notes, no quotation marks, no alternatives."
    )

    def __init__(self, model: str, delay: float):
        from google import genai
        from google.genai import types

        self.client = genai.Client(api_key=config.require("GOOGLE_API_KEY"))
        self.model = model
        self.delay = delay
        self.cfg = types.GenerateContentConfig(
            system_instruction=self.SYSTEM,
            temperature=0.0,
            max_output_tokens=512,
            # 2.5 Flash "thinks" by default; translation doesn't need it and it
            # roughly doubles latency on the free tier.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        self.name = f"gemini:{model}"

    def translate(self, text: str) -> str:
        def call():
            r = self.client.models.generate_content(
                model=self.model, contents=text, config=self.cfg
            )
            if not r.text:
                reason = r.candidates[0].finish_reason if r.candidates else None
                raise RuntimeError(f"empty response (finish_reason={reason})")
            return r.text.strip().strip('"')

        return _retry(call)


class NLLBTranslator(Translator):
    name = "nllb"
    MODEL_ID = "nickdee96/nllb-200-600m-kikuyu-english"

    def __init__(self, batch_size: int = 8, num_beams: int = 4):
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        print(f"  loading {self.MODEL_ID} (first run downloads ~1.3 GB) ...")
        t0 = time.time()
        self.tok = AutoTokenizer.from_pretrained(self.MODEL_ID, src_lang=SRC_LANG, token=config.HF_TOKEN)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(
            self.MODEL_ID, torch_dtype=torch.float32, token=config.HF_TOKEN
        ).eval()
        # Force the decoder to start with the English language token.
        self.forced_bos = self.tok.convert_tokens_to_ids(TGT_LANG)
        assert self.forced_bos != self.tok.unk_token_id, f"{TGT_LANG} not in tokenizer vocab"
        self.batch_size, self.num_beams = batch_size, num_beams
        print(f"  loaded in {time.time() - t0:.0f}s, {torch.get_num_threads()} CPU threads")

    def translate(self, text: str) -> str:
        return self.translate_batch([text])[0]

    def translate_batch(self, texts: list[str]) -> list[str]:
        import torch

        out: list[str] = []
        for i in range(0, len(texts), self.batch_size):
            chunk = texts[i : i + self.batch_size]
            enc = self.tok(chunk, return_tensors="pt", padding=True, truncation=True, max_length=512)
            with torch.inference_mode():
                gen = self.model.generate(
                    **enc,
                    forced_bos_token_id=self.forced_bos,
                    num_beams=self.num_beams,
                    max_new_tokens=256,
                )
            out.extend(s.strip() for s in self.tok.batch_decode(gen, skip_special_tokens=True))
        return out


class KhayaTranslator(Translator):
    """GhanaNLP Khaya API. Placeholder until Kikuyu support is confirmed.

    To enable: confirm the endpoint + language code in the Khaya studio, fill in
    translate(), and run with --systems gemini,nllb,khaya.
    """

    name = "khaya"

    def __init__(self, delay: float):
        self.key = config.require("KHAYA_API_KEY")
        self.delay = delay
        raise NotImplementedError("Khaya: confirm Kikuyu support and endpoint, then implement translate()")

    def translate(self, text: str) -> str:  # pragma: no cover
        raise NotImplementedError


def build_systems(names: list[str], args) -> list[Translator]:
    systems: list[Translator] = []
    for n in names:
        if n == "gemini":
            systems.append(GeminiTranslator(args.gemini_model, args.delay))
        elif n == "nllb":
            systems.append(NLLBTranslator())
        elif n == "khaya":
            systems.append(KhayaTranslator(args.delay))
        else:
            sys.exit(f"unknown system {n!r}; choose from gemini, nllb, khaya")
    return systems


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def load_pairs(n: int) -> list[dict]:
    from datasets import load_dataset

    kw = dict(split=SPLIT, token=config.HF_TOKEN)
    src = load_dataset(DATASET, SRC_LANG, **kw)
    tgt = load_dataset(DATASET, TGT_LANG, **kw)
    print(f"  {SRC_LANG}: {len(src)} rows, {TGT_LANG}: {len(tgt)} rows")

    # FLORES+ README: rows with the same `id` are translations of each other.
    # Align on id rather than trusting row order, then check the two agree.
    tgt_by_id = {r["id"]: r["text"] for r in tgt}
    pairs = []
    for i, r in enumerate(src):
        if r["id"] not in tgt_by_id:
            raise RuntimeError(f"id {r['id']} in {SRC_LANG} has no {TGT_LANG} counterpart")
        assert tgt[i]["id"] == r["id"], (
            f"row {i}: ids differ between languages - row-order alignment would be WRONG"
        )
        pairs.append({"id": r["id"], "src": r["text"], "ref": tgt_by_id[r["id"]]})
        if len(pairs) == n:
            break
    return pairs


# ---------------------------------------------------------------------------
# Results file (resumable)
# ---------------------------------------------------------------------------
def load_results(pairs: list[dict]) -> dict:
    if RESULTS_PATH.exists():
        data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
        prev = {s["id"]: s for s in data["sentences"]}
        # Re-use previous outputs for any sentence still in scope.
        for p in pairs:
            p["outputs"] = prev.get(p["id"], {}).get("outputs", {})
        done = sum(1 for p in pairs for v in p["outputs"].values() if v is not None)
        print(f"  resuming from {RESULTS_PATH.name}: {done} system outputs already present")
    else:
        for p in pairs:
            p["outputs"] = {}
    return {
        "meta": {"dataset": DATASET, "split": SPLIT, "src": SRC_LANG, "tgt": TGT_LANG, "n": len(pairs)},
        "sentences": pairs,
        "scores": {},
    }


def save_results(data: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = RESULTS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(RESULTS_PATH)  # atomic on the same filesystem


# ---------------------------------------------------------------------------
# Scoring and reporting
# ---------------------------------------------------------------------------
NUM_RE = re.compile(r"\d[\d,.]*\d|\d")


def numbers_in(text: str) -> list[str]:
    return sorted(m.group(0).replace(",", "") for m in NUM_RE.finditer(text))


def score(data: dict, sys_name: str) -> dict:
    from sacrebleu import corpus_bleu, corpus_chrf

    rows = [s for s in data["sentences"] if s["outputs"].get(sys_name) is not None]
    hyps = [s["outputs"][sys_name] for s in rows]
    refs = [s["ref"] for s in rows]
    if not hyps:
        return {"n_scored": 0}
    chrfpp = corpus_chrf(hyps, [refs], word_order=2)  # chrF++ = chrF with word 2-grams
    bleu = corpus_bleu(hyps, [refs])
    num_mismatch = [s["id"] for s in rows if numbers_in(s["ref"]) != numbers_in(s["outputs"][sys_name])]
    num_total = sum(1 for s in rows if numbers_in(s["ref"]))
    return {
        "n_scored": len(hyps),
        "chrf++": round(chrfpp.score, 2),
        "bleu": round(bleu.score, 2),
        "sentences_with_numbers": num_total,
        "number_mismatches": len(num_mismatch),
        "number_mismatch_ids": num_mismatch,
    }


def report(data: dict, sys_names: list[str], n_examples: int) -> None:
    import pandas as pd

    n = data["meta"]["n"]
    df = pd.DataFrame(
        [
            {"system": s, **{k: v for k, v in data["scores"][s].items() if k != "number_mismatch_ids"}}
            for s in sys_names
        ]
    ).set_index("system")
    print("\n=== Summary (chrF++ is the decision metric) ===")
    print(df.to_string())
    incomplete = [s for s in sys_names if data["scores"][s].get("n_scored", 0) < n]
    if incomplete:
        print(f"\n  NOTE: {incomplete} scored on fewer than {n} sentences - re-run to fill gaps before comparing.")

    print(f"\n=== First {n_examples} examples per system ===")
    for s in data["sentences"][:n_examples]:
        print(f"\n[{s['id']}] SRC: {s['src']}")
        print(f"      REF: {s['ref']}")
        for name in sys_names:
            print(f"  {name:>22}: {s['outputs'].get(name)}")

    print("\n=== Number / amount mismatches (reference numerals vs system numerals) ===")
    for name in sys_names:
        ids = data["scores"][name].get("number_mismatch_ids", [])
        total = data["scores"][name].get("sentences_with_numbers", 0)
        print(f"\n{name}: {len(ids)} of {total} numeric sentences mismatched")
        for s in data["sentences"]:
            if s["id"] in ids[:5]:
                print(f"  [{s['id']}] ref nums {numbers_in(s['ref'])} -> sys nums {numbers_in(s['outputs'][name])}")
                print(f"        REF: {s['ref']}")
                print(f"        SYS: {s['outputs'][name]}")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=100, help="number of sentence pairs (default 100)")
    ap.add_argument("--systems", default="gemini,nllb", help="comma-separated: gemini,nllb,khaya")
    ap.add_argument("--delay", type=float, default=7.0, help="seconds between API calls (free tier ~10 RPM)")
    ap.add_argument("--gemini-model", default="gemini-2.5-flash")
    ap.add_argument("--examples", type=int, default=5)
    ap.add_argument("--score-only", action="store_true", help="skip translation; re-score existing results")
    args = ap.parse_args()
    sys_names = [s.strip() for s in args.systems.split(",") if s.strip()]

    print(f"[1/4] Loading {DATASET} {SPLIT} ({SRC_LANG} -> {TGT_LANG}), first {args.n} pairs")
    pairs = load_pairs(args.n)
    print("\n  --- Alignment check: do these pairs mean the same thing? ---")
    for p in pairs[:3]:
        print(f"  [{p['id']}] KIK: {p['src']}\n        ENG: {p['ref']}\n")

    data = load_results(pairs)

    if not args.score_only:
        print("[2/4] Building systems")
        systems = build_systems(sys_names, args)

        print("[3/4] Translating")
        for system in systems:
            todo = [s for s in data["sentences"] if s["outputs"].get(system.name) is None]
            print(f"\n  {system.name}: {len(todo)} to do, {len(data['sentences']) - len(todo)} cached")
            if not todo:
                continue
            t0 = time.time()
            if system.delay:  # API: one at a time, save after each, sleep between
                for k, s in enumerate(todo, 1):
                    try:
                        s["outputs"][system.name] = system.translate(s["src"])
                    except Exception as e:  # noqa: BLE001
                        print(f"    x [{s['id']}] FAILED permanently: {e}")
                        s["outputs"][system.name] = None
                    save_results(data)
                    print(f"    {k}/{len(todo)} [{s['id']}] {str(s['outputs'][system.name])[:70]}")
                    if k < len(todo):
                        time.sleep(system.delay)
            else:  # local: batched, save after each batch
                bs = getattr(system, "batch_size", 8)
                for i in range(0, len(todo), bs):
                    chunk = todo[i : i + bs]
                    outs = system.translate_batch([s["src"] for s in chunk])
                    for s, o in zip(chunk, outs):
                        s["outputs"][system.name] = o
                    save_results(data)
                    print(f"    {min(i + bs, len(todo))}/{len(todo)}  [{chunk[0]['id']}] {outs[0][:70]}")
            print(f"  {system.name}: done in {time.time() - t0:.0f}s")
        sys_names = [s.name for s in systems]
    else:
        # Score whatever systems already have outputs in the file.
        sys_names = sorted({k for s in data["sentences"] for k in s["outputs"]})

    print("\n[4/4] Scoring")
    for name in sys_names:
        data["scores"][name] = score(data, name)
    save_results(data)
    report(data, sys_names, args.examples)
    print(f"\nSaved: {RESULTS_PATH}")


if __name__ == "__main__":
    main()
