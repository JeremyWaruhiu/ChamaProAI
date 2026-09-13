"""Translation bake-off: Kikuyu -> English on FLORES+ dev.

Compares candidate translation systems on the same sentence pairs and reports
chrF++ (decision metric) and BLEU. Every source/reference/system output is saved
to results/bakeoff.json, which is written after every sentence so a crash or
rate-limit keeps partial progress and a re-run resumes where it stopped.

The results file holds the UNION of all sentences ever worked on; --n only
limits which sentences this invocation translates. Scores are reported on
explicitly labelled sets so systems run on different sample sizes are never
silently compared.

Usage:
    python run_bakeoff.py                        # gemini + nllb, first 100 pairs
    python run_bakeoff.py --n 50 --systems khaya # one system, first 50 (asks first)
    python run_bakeoff.py --score-only           # re-score everything in the file
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
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
    #: exact model / endpoint identifier, recorded in results meta
    model_id: str
    #: seconds to sleep between calls (API rate limiting); 0 for local models
    delay: float = 0.0
    #: ask before spending calls (metered APIs)
    confirm_before_run: bool = False

    @abstractmethod
    def translate(self, text: str) -> str: ...

    def translate_batch(self, texts: list[str]) -> list[str]:
        """Default: one at a time. Local models override to batch."""
        return [self.translate(t) for t in texts]


class AbortRun(Exception):
    """Stop this system's run entirely (don't move on to the next sentence).

    Raised when continuing would spend more calls on a request that is broken
    the same way every time: auth/quota rejections, or a response we can't parse.
    """


# HTTP statuses that will not change on retry. Waiting fixes neither a spent
# quota (429) nor a bad key (401/403) nor a malformed request (400/404).
NO_RETRY = {
    429: "QUOTA EXHAUSTED - retrying spends quota that is already gone",
    401: "AUTH - bad or missing API key",
    403: "AUTH - key not permitted for this resource",
    400: "BAD REQUEST - the request itself is malformed",
    404: "NOT FOUND - model/endpoint does not exist for this key",
}


def _error_body(e: Exception) -> str:
    """Full error payload, not a truncated str(e)."""
    body = getattr(e, "details", None) or getattr(e, "response_json", None)
    if body:
        return json.dumps(body, ensure_ascii=False, indent=1)
    return str(e)


def _retry(fn, attempts: int = 5, base_wait: float = 10.0):
    """Call fn(); retry transient failures (5xx, network) with backoff.

    Non-transient HTTP errors (see NO_RETRY) raise AbortRun immediately.
    """
    for k in range(attempts):
        try:
            return fn()
        except AbortRun:
            raise
        except Exception as e:  # noqa: BLE001
            code = getattr(e, "code", None)
            if code in NO_RETRY:
                raise AbortRun(f"HTTP {code}: {NO_RETRY[code]}\n{_error_body(e)}") from e
            wait = base_wait * (2 ** k)
            print(f"    ! {type(e).__name__} (HTTP {code}): {str(e)[:100]} - transient, retry {k + 1}/{attempts} in {wait:.0f}s")
            time.sleep(wait)
    raise RuntimeError(f"gave up after {attempts} transient failures")


class GeminiTranslator(Translator):
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
        self.model_id = model
        self.name = f"gemini:{model}"
        self.delay = delay
        self.cfg = types.GenerateContentConfig(
            system_instruction=self.SYSTEM,
            temperature=0.0,
            max_output_tokens=512,
            # Flash models "think" by default; translation doesn't need it and
            # it roughly doubles latency. (gemini-3.6-flash rejects budget=0;
            # gemini-3.8-flash accepts it.)
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )

    def translate(self, text: str) -> str:
        def call():
            r = self.client.models.generate_content(model=self.model_id, contents=text, config=self.cfg)
            if not r.text:
                reason = r.candidates[0].finish_reason if r.candidates else None
                raise RuntimeError(f"empty response (finish_reason={reason})")
            return r.text.strip().strip('"')

        return _retry(call)


class NLLBTranslator(Translator):
    name = "nllb"
    model_id = "nickdee96/nllb-200-600m-kikuyu-english"

    def __init__(self, batch_size: int = 8, num_beams: int = 4):
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        print(f"  loading {self.model_id} (first run downloads ~1.3 GB) ...")
        t0 = time.time()
        self.tok = AutoTokenizer.from_pretrained(self.model_id, src_lang=SRC_LANG, token=config.HF_TOKEN)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(
            self.model_id, dtype=torch.float32, token=config.HF_TOKEN
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
    """GhanaNLP Khaya Translation API v2 (ISO 639-3 pair codes).

    QUOTA: free tier is 100 calls/month across the whole product. So:
      - exactly one HTTP attempt per sentence, never _retry()
      - auth/quota errors and unparseable responses abort the whole run
      - the main loop asks for confirmation before the first call
    """

    name = "khaya"
    BASE_URL = "https://translation-api.ghananlp.org/v2"
    LANG_PAIR = "kik-eng"
    MAX_CHARS = 1000
    model_id = f"{BASE_URL}/translate lang={LANG_PAIR}"
    confirm_before_run = True

    def __init__(self, delay: float = 1.0):
        self.key = config.require("KHAYA_API_KEY")
        self.delay = delay  # >0 puts us on the one-at-a-time, save-after-each path

    def translate(self, text: str) -> str:
        import requests

        assert len(text) <= self.MAX_CHARS, f"Khaya limit is {self.MAX_CHARS} chars; got {len(text)}"
        r = requests.post(
            f"{self.BASE_URL}/translate",
            headers={"Ocp-Apim-Subscription-Key": self.key, "Content-Type": "application/json"},
            json={"in": text, "lang": self.LANG_PAIR},
            timeout=60,
        )
        if r.status_code in (401, 403, 429):
            raise AbortRun(f"HTTP {r.status_code} (auth/quota) - raw response:\n{r.text[:1000]}")
        if r.status_code != 200:
            # Other server errors: this sentence is lost, but the next may work.
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        return self._parse(r)

    @staticmethod
    def _parse(r) -> str:
        """Accept only shapes we recognise; anything else aborts with the raw body."""
        try:
            body = r.json()
        except ValueError:
            raise AbortRun(f"non-JSON response - raw:\n{r.text[:1000]}")
        if isinstance(body, str) and body.strip():
            return body.strip()
        if isinstance(body, dict):
            str_vals = [v for v in body.values() if isinstance(v, str) and v.strip()]
            if len(str_vals) == 1:
                return str_vals[0].strip()
        raise AbortRun(f"unexpected response shape - raw:\n{json.dumps(body, ensure_ascii=False)[:1000]}")


def build_systems(names: list[str], args) -> list[Translator]:
    systems: list[Translator] = []
    for n in names:
        if n == "gemini":
            systems.append(GeminiTranslator(args.gemini_model, args.delay))
        elif n == "nllb":
            systems.append(NLLBTranslator())
        elif n == "khaya":
            systems.append(KhayaTranslator())
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
# Results file (resumable, union of everything ever run)
# ---------------------------------------------------------------------------
def load_results(pairs: list[dict]) -> tuple[dict, list[dict]]:
    """Return (data, work) where data holds ALL sentences in the file merged with
    `pairs`, and work is the subset (this run's --n) to translate."""
    if RESULTS_PATH.exists():
        data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
        n_outputs = sum(1 for s in data["sentences"] for v in s["outputs"].values() if v is not None)
        print(f"  resuming from {RESULTS_PATH.name}: {len(data['sentences'])} sentences, {n_outputs} outputs present")
    else:
        data = {"meta": {"dataset": DATASET, "split": SPLIT, "src": SRC_LANG, "tgt": TGT_LANG, "systems": {}},
                "sentences": [], "scores": {}}
    data["meta"].setdefault("systems", {})

    by_id = {s["id"]: s for s in data["sentences"]}
    for p in pairs:
        if p["id"] not in by_id:
            by_id[p["id"]] = {**p, "outputs": {}}
    data["sentences"] = sorted(by_id.values(), key=lambda s: s["id"])
    work = [by_id[p["id"]] for p in pairs]
    return data, work


def save_results(data: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = RESULTS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    # Atomic on the same filesystem. On Windows the rename can be denied for a
    # moment if an editor/indexer has the target open, so retry briefly.
    for attempt in range(10):
        try:
            tmp.replace(RESULTS_PATH)
            return
        except PermissionError:
            time.sleep(0.5 * (attempt + 1))
    tmp.replace(RESULTS_PATH)  # final attempt: let the error surface


# ---------------------------------------------------------------------------
# Scoring and reporting
# ---------------------------------------------------------------------------
NUM_RE = re.compile(r"\d[\d,.:]*\d|\d")


def numbers_in(text: str) -> list[str]:
    return sorted(m.group(0).replace(",", "") for m in NUM_RE.finditer(text))


def systems_in(data: dict) -> list[str]:
    return sorted({k for s in data["sentences"] for k, v in s["outputs"].items() if v is not None})


def rows_for(data: dict, sys_name: str, ids: set[int] | None = None) -> list[dict]:
    """Sentences where sys_name has output, optionally restricted to ids."""
    return [s for s in data["sentences"]
            if s["outputs"].get(sys_name) is not None and (ids is None or s["id"] in ids)]


def score_rows(rows: list[dict], sys_name: str) -> dict:
    from sacrebleu import corpus_bleu, corpus_chrf

    hyps = [s["outputs"][sys_name] for s in rows]
    refs = [s["ref"] for s in rows]
    if not hyps:
        return {"n": 0}
    chrfpp = corpus_chrf(hyps, [refs], word_order=2)  # chrF++ = chrF with word 2-grams
    bleu = corpus_bleu(hyps, [refs])
    mism = [s["id"] for s in rows if numbers_in(s["ref"]) != numbers_in(s["outputs"][sys_name])]
    return {
        "n": len(hyps),
        "chrf++": round(chrfpp.score, 2),
        "bleu": round(bleu.score, 2),
        "sentences_with_numbers": sum(1 for s in rows if numbers_in(s["ref"])),
        "number_mismatches": len(mism),
        "number_mismatch_ids": mism,
    }


def paired_bootstrap(data: dict, names: list[str], ids: set[int], n_samples: int) -> dict:
    """Paired bootstrap resampling on the common set. First name is the baseline."""
    from sacrebleu.metrics import BLEU, CHRF
    from sacrebleu.significance import PairedTest

    rows = [s for s in data["sentences"] if s["id"] in ids]
    refs = [[s["ref"] for s in rows]]
    named = [(n, [s["outputs"][n] for s in rows]) for n in names]
    pt = PairedTest(named, {"chrF++": CHRF(word_order=2), "BLEU": BLEU()},
                    references=refs, test_type="bs", n_samples=n_samples, n_jobs=1)
    _, results = pt()
    out = {"test": "paired bootstrap resampling", "n_samples": n_samples, "n": len(rows),
           "baseline": names[0], "systems": {n: {} for n in names}}
    for metric, res_list in results.items():
        if metric == "System":
            continue
        # sacrebleu reports under the metric's own name (e.g. "chrF2++"); normalise.
        metric = "chrF++" if "chrF" in metric else metric
        for name, r in zip(names, res_list):
            out["systems"][name][metric] = {
                "score": round(float(r.score), 2),
                "ci95": round(float(r.ci), 2) if r.ci is not None else None,
                "p_value": round(float(r.p_value), 4) if r.p_value is not None else None,
            }
    return out


def score_all(data: dict, n_samples: int) -> None:
    names = systems_in(data)
    common = {s["id"] for s in data["sentences"] if all(s["outputs"].get(n) is not None for n in names)}
    scores = {"common_set": {"n": len(common), "systems": names, "ids": sorted(common)},
              "by_system": {}}
    for n in names:
        scores["by_system"][n] = {
            "common": score_rows(rows_for(data, n, common), n),
            "all": score_rows(rows_for(data, n), n),
        }
    if len(names) >= 2 and len(common) >= 2:
        ranked = sorted(names, key=lambda n: scores["by_system"][n]["common"]["chrf++"], reverse=True)
        scores["significance"] = paired_bootstrap(data, ranked, common, n_samples)
    data["scores"] = scores


def report(data: dict, n_examples: int) -> None:
    import pandas as pd

    sc = data["scores"]
    names = sc["common_set"]["systems"]
    n_common = sc["common_set"]["n"]

    print("\n=== Summary (chrF++ is the decision metric) ===")
    rows = []
    for n in names:
        for set_name, label in (("common", f"common ({len(names)}-way)"), ("all", "all outputs")):
            r = sc["by_system"][n][set_name]
            rows.append({"system": n, "set": label, "n": r["n"], "chrF++": r.get("chrf++"), "BLEU": r.get("bleu"),
                         "num_sent": r.get("sentences_with_numbers"), "num_mismatch": r.get("number_mismatches")})
    df = pd.DataFrame(rows).sort_values(["set", "chrF++"], ascending=[True, False])
    print(df.to_string(index=False))
    print(f"\n  'common' = the {n_common} sentences where ALL {len(names)} systems have output; only rows with")
    print("  the same set AND the same n are comparable. 'all outputs' rows have different n per system.")

    if "significance" in sc:
        sig = sc["significance"]
        print(f"\n=== Significance on the common set (n={sig['n']}, {sig['test']}, {sig['n_samples']} resamples) ===")
        print(f"  baseline = {sig['baseline']} (chrF++ leader). p < 0.05 means the gap to baseline is unlikely to be noise.")
        for name, m in sig["systems"].items():
            c, b = m["chrF++"], m["BLEU"]
            tag = "baseline" if name == sig["baseline"] else f"p={c['p_value']}"
            print(f"  {name:>24}  chrF++ {c['score']:6.2f} ±{c['ci95']:.2f}   BLEU {b['score']:6.2f} ±{b['ci95']:.2f}   {tag}")

    print(f"\n=== First {n_examples} examples per system ===")
    for s in data["sentences"][:n_examples]:
        print(f"\n[{s['id']}] SRC: {s['src']}")
        print(f"      REF: {s['ref']}")
        for name in names:
            print(f"  {name:>24}: {s['outputs'].get(name)}")

    print("\n=== Number / amount mismatches (reference numerals vs system numerals, common set) ===")
    by_id = {s["id"]: s for s in data["sentences"]}
    for name in names:
        r = sc["by_system"][name]["common"]
        ids = r.get("number_mismatch_ids", [])
        print(f"\n{name}: {len(ids)} of {r.get('sentences_with_numbers', 0)} numeric sentences mismatched")
        for i in ids[:5]:
            s = by_id[i]
            print(f"  [{i}] ref nums {numbers_in(s['ref'])} -> sys nums {numbers_in(s['outputs'][name])}")
            print(f"        REF: {s['ref']}")
            print(f"        SYS: {s['outputs'][name]}")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=100, help="number of sentence pairs this run works on (default 100)")
    ap.add_argument("--systems", default="gemini,nllb", help="comma-separated: gemini,nllb,khaya")
    ap.add_argument("--delay", type=float, default=7.0, help="seconds between Gemini calls (free tier ~10 RPM)")
    ap.add_argument("--gemini-model", default="gemini-3.8-flash",
                    help="gemini-2.5-flash is retired for new API users; 3.8 accepts thinking_budget=0")
    ap.add_argument("--examples", type=int, default=5)
    ap.add_argument("--bootstrap", type=int, default=1000, help="paired bootstrap resamples")
    ap.add_argument("--score-only", action="store_true", help="skip translation; re-score everything in the file")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt for metered APIs (Khaya)")
    args = ap.parse_args()
    sys_names = [s.strip() for s in args.systems.split(",") if s.strip()]

    print(f"[1/4] Loading {DATASET} {SPLIT} ({SRC_LANG} -> {TGT_LANG}), first {args.n} pairs")
    pairs = load_pairs(args.n)
    print("\n  --- Alignment check: do these pairs mean the same thing? ---")
    for p in pairs[:3]:
        print(f"  [{p['id']}] KIK: {p['src']}\n        ENG: {p['ref']}\n")

    data, work = load_results(pairs)

    if not args.score_only:
        print("[2/4] Building systems")
        systems = build_systems(sys_names, args)

        print("[3/4] Translating")
        for system in systems:
            todo = [s for s in work if s["outputs"].get(system.name) is None]
            print(f"\n  {system.name}: {len(todo)} to do, {len(work) - len(todo)} cached (of {len(work)} in scope)")
            if not todo:
                continue
            if system.confirm_before_run and not args.yes:
                print(f"  >> {system.name} will make {len(todo)} API call(s) against a metered quota.")
                try:
                    ok = input("  >> Proceed? [y/N] ").strip().lower() == "y"
                except EOFError:  # non-interactive shell: never proceed silently
                    ok = False
                if not ok:
                    print(f"  {system.name}: skipped (re-run with --yes to skip this prompt)")
                    continue
            data["meta"]["systems"][system.name] = {
                "model_id": system.model_id,
                "last_run": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "n_requested": len(work),
            }
            t0 = time.time()
            if system.delay:  # API: one at a time, save after each, sleep between
                for k, s in enumerate(todo, 1):
                    try:
                        s["outputs"][system.name] = system.translate(s["src"])
                    except AbortRun as e:
                        save_results(data)
                        have = sum(1 for x in data["sentences"] if x["outputs"].get(system.name) is not None)
                        print(f"\n    STOP at [{s['id']}] {system.name}: {e}\n")
                        print(f"  {system.name}: aborted. {have}/{len(work)} sentences complete and saved; "
                              f"re-run later to resume from the cache.")
                        sys.exit(2)
                    except Exception as e:  # noqa: BLE001
                        print(f"    x [{s['id']}] FAILED: {e}")
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

    print("\n[4/4] Scoring everything in the results file")
    score_all(data, args.bootstrap)
    data["meta"]["scored_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_results(data)
    report(data, args.examples)
    print(f"\nSaved: {RESULTS_PATH}")


if __name__ == "__main__":
    main()
