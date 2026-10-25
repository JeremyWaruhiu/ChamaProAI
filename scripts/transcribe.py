"""Run an ASR model over the manifest clips and write hypotheses.

Importable: load_asr() builds the pipeline once on the chosen engine
(OpenVINO or torch) and says which engine and device it ended up on;
transcribe_clip() runs it on one file. The API holds one loaded pipeline per
language and calls transcribe_clip().

    python scripts/transcribe.py --engine openvino --device GPU
    python scripts/transcribe.py --engine torch --decoding plain
"""
import argparse, csv, json, math, os, time
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv
import soundfile as sf

MANIFEST = Path("data/manifest.csv")
ENGINES = ("openvino", "torch")
DECODINGS = ("timestamps", "plain")
# Generation cap: TOKENS_BASE + tokens_per_second * clip seconds. Normal speech
# in the 40 recorded answers peaks near 6.4 tokens/s; runaway continuations
# reach 220+ tokens on a 5 s clip. The base covers timestamp and end tokens.
TOKENS_PER_SECOND = 12.0
TOKENS_BASE = 16
# Whisper's decoder has 448 positions and the prompt takes up to four.
MAX_NEW_TOKENS = 440


@dataclass(frozen=True)
class ASR:
    """A loaded pipeline and what it actually runs on, after any fallback."""
    pipe: object        # transformers ASR pipeline (anything callable like one)
    engine: str         # openvino | torch
    device: str         # GPU | CPU
    model: str          # HF model id, or the OpenVINO model directory
    source: str = ""    # HF model id the OpenVINO export was made from

    @property
    def label(self):
        """Provenance stored with each transcript."""
        if self.engine == "openvino":
            return f"{self.source or Path(self.model).name} (openvino {self.device})"
        return self.model


def torch_device():
    import torch
    return 0 if torch.cuda.is_available() else -1


def load_torch(model_name):
    """The transformers pipeline on torch. Slow; do it once and reuse it."""
    from transformers import pipeline
    return pipeline("automatic-speech-recognition", model=model_name, device=torch_device())


def openvino_devices():
    import openvino as ov
    return ov.Core().available_devices


def load_openvino(model_dir, device):
    """The same pipeline over an OpenVINO export (scripts/export_openvino.py)."""
    from optimum.intel import OVModelForSpeechSeq2Seq
    from transformers import AutoProcessor, pipeline
    model_dir = str(model_dir)  # optimum treats the id as a string
    proc = AutoProcessor.from_pretrained(model_dir)
    model = OVModelForSpeechSeq2Seq.from_pretrained(model_dir, device=device)
    return pipeline("automatic-speech-recognition", model=model,
                    tokenizer=proc.tokenizer, feature_extractor=proc.feature_extractor)


def ov_exported(model_dir):
    return bool(model_dir) and (Path(model_dir) / "openvino_encoder_model.xml").is_file()


def ov_source(model_dir):
    """The HF model an export was made from, as optimum recorded it; "" if unknown."""
    try:
        cfg = json.loads((Path(model_dir) / "openvino_config.json").read_text(encoding="utf-8"))
        return (cfg.get("quantization_config") or {}).get("processor") or ""
    except (OSError, ValueError):
        return ""


def load_asr(model_name, engine="openvino", device="GPU", ov_dir=None, log=print,
             fallback=True):
    """Load ASR on the requested engine and device, falling back if need be.

    OpenVINO on a missing GPU falls back to the CPU; a missing OpenVINO export
    falls back to torch on model_name. Each fallback is logged, and the result
    names what was used. With fallback=False the first failure raises instead.
    """
    device = device.upper()
    if engine not in ENGINES:
        raise ValueError(f"unknown ASR engine {engine!r}; use one of {ENGINES}")
    if engine == "openvino":
        if not ov_exported(ov_dir):
            if not fallback:
                raise FileNotFoundError(f"no OpenVINO export in {ov_dir}")
            log(f"ASR: no OpenVINO model in {ov_dir}; falling back to torch {model_name} "
                "(run scripts/export_openvino.py)")
        else:
            try:
                if device == "GPU" and "GPU" not in openvino_devices():
                    if not fallback:
                        raise RuntimeError("OpenVINO reports no GPU")
                    log("ASR: OpenVINO reports no GPU; falling back to CPU")
                    device = "CPU"
                try:
                    pipe = load_openvino(ov_dir, device)
                except Exception as e:
                    if device == "CPU" or not fallback:
                        raise
                    log(f"ASR: GPU failed ({type(e).__name__}: {e}); falling back to CPU")
                    device = "CPU"
                    pipe = load_openvino(ov_dir, device)
                log(f"ASR: engine=openvino device={device} model={ov_dir}")
                return ASR(pipe, "openvino", device, str(ov_dir), ov_source(ov_dir))
            except Exception as e:
                if not fallback:
                    raise
                log(f"ASR: OpenVINO failed ({type(e).__name__}: {e}); falling back to torch {model_name}")
    pipe = load_torch(model_name)
    used = "GPU" if torch_device() == 0 else "CPU"
    log(f"ASR: engine=torch device={used} model={model_name}")
    return ASR(pipe, "torch", used, model_name)


def token_cap(duration, tokens_per_second=TOKENS_PER_SECOND, base=TOKENS_BASE):
    """max_new_tokens for a clip: room for its speech, none for a run-on."""
    return max(1, min(MAX_NEW_TOKENS, math.ceil(base + tokens_per_second * float(duration))))


def transcribe_clip(path, model, language, duration=None, *, decoding="timestamps",
                    tokens_per_second=TOKENS_PER_SECOND):
    """Transcribe one clip with a loaded pipeline -> {text, seconds}.

    Generation stops at token_cap(duration). With timestamped decoding, chunks
    timestamped past the clip's end are dropped (decoder run-on); duration is
    read from the file when not given.
    """
    if decoding not in DECODINGS:
        raise ValueError(f"unknown decoding {decoding!r}; use one of {DECODINGS}")
    t = time.time()
    dur = float(duration) if duration is not None else sf.info(str(path)).duration
    gen = {"language": language, "task": "transcribe",
           "condition_on_prev_tokens": False,
           "max_new_tokens": token_cap(dur, tokens_per_second)}
    if decoding == "plain":
        res = model(str(path), generate_kwargs=gen)
        return {"text": res["text"].strip(), "seconds": round(time.time()-t, 2)}
    res = model(str(path), generate_kwargs=gen, return_timestamps=True)
    keep = [c["text"] for c in res.get("chunks", [])
            if c.get("timestamp") and c["timestamp"][0] is not None
            and c["timestamp"][0] < dur]
    txt = ("".join(keep) if keep else res["text"]).strip()
    return {"text": txt, "seconds": round(time.time()-t, 2)}


def main():
    load_dotenv(override=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only first N clips")
    ap.add_argument("--model", default=os.getenv("ASR_MODEL", "microsoft/paza-whisper-large-v3-turbo"),
                    help="torch model, also the fallback when the OpenVINO export is missing")
    ap.add_argument("--engine", choices=ENGINES, default=os.getenv("ASR_ENGINE", "openvino"))
    ap.add_argument("--device", choices=["GPU", "CPU"], type=str.upper,
                    default=os.getenv("ASR_DEVICE", "GPU"))
    ap.add_argument("--ov-dir", default=os.getenv("ASR_OV_MODEL_DIR", "models/paza-ov-int8"))
    ap.add_argument("--language", default=os.getenv("ASR_LANGUAGE", "sw"))
    ap.add_argument("--decoding", choices=DECODINGS, default=os.getenv("ASR_DECODING", "timestamps"))
    ap.add_argument("--tokens-per-second", type=float,
                    default=float(os.getenv("ASR_TOKENS_PER_SECOND") or TOKENS_PER_SECOND))
    ap.add_argument("--out", default="data/asr_output.csv",
                    help="output path; use a distinct file per model to compare runs")
    a = ap.parse_args()

    OUT = Path(a.out)
    with MANIFEST.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if a.limit: rows = rows[:a.limit]
    if not rows: raise SystemExit("manifest empty")

    asr = load_asr(a.model, a.engine, a.device, a.ov_dir)
    print(f"engine={asr.engine} device={asr.device} model={asr.model} language={a.language} "
          f"decoding={a.decoding} tokens/s={a.tokens_per_second}")
    print(f"{len(rows)} clips -> {OUT}\n")

    out, t0 = [], time.time()
    for i, r in enumerate(rows, 1):
        p = r["path"]
        if not Path(p).exists():
            print(f"  [{i}/{len(rows)}] MISSING {p}"); continue
        try:
            res = transcribe_clip(p, asr.pipe, a.language, duration=r["duration_s"],
                                  decoding=a.decoding, tokens_per_second=a.tokens_per_second)
        except Exception as e:
            print(f"  [{i}/{len(rows)}] FAIL {r['id']}: {e}"); continue
        out.append({"id": r["id"], "sentence_no": r["sentence_no"],
                    "domain": r["domain"], "hypothesis": res["text"],
                    "asr_seconds": res["seconds"]})
        print(f"  [{i}/{len(rows)}] {r['id']}: {res['text'][:70]}")

    if not out:
        raise SystemExit("\nnothing transcribed; existing output left untouched")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["id","sentence_no","domain","hypothesis","asr_seconds"])
        w.writeheader(); w.writerows(out)
    print(f"\n{len(out)} transcribed in {time.time()-t0:.0f}s -> {OUT}")


if __name__ == "__main__":
    main()
