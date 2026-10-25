"""Export the ASR models to OpenVINO IR with int8 weights, via optimum-cli.

    python scripts/export_openvino.py              # both models
    python scripts/export_openvino.py --only en    # just the English model
    python scripts/export_openvino.py --force      # re-export over an existing one

Kikuyu (Paza) -> models/paza-ov-int8, English -> models/whisper-en-ov-int8.
The exports are gitignored (models/*-ov-*/). Downloads go to HF_HOME, which
chamapro.config points at .hf_cache/ unless it is set.
"""
from __future__ import annotations

import argparse, os, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    "kik": ("microsoft/paza-whisper-large-v3-turbo", ROOT / "models" / "paza-ov-int8"),
    "en": ("openai/whisper-large-v3-turbo", ROOT / "models" / "whisper-en-ov-int8"),
}


def command(model_id: str, out: Path) -> list[str]:
    cli = shutil.which("optimum-cli") or "optimum-cli"
    return [cli, "export", "openvino", "--model", model_id,
            "--task", "automatic-speech-recognition-with-past",
            "--weight-format", "int8", str(out)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=sorted(MODELS), help="export one model only")
    ap.add_argument("--force", action="store_true", help="re-export even if the output exists")
    a = ap.parse_args()
    os.environ.setdefault("HF_HOME", str(ROOT / ".hf_cache"))

    failed = []
    for key in [a.only] if a.only else list(MODELS):
        model_id, out = MODELS[key]
        if (out / "openvino_encoder_model.xml").exists() and not a.force:
            print(f"{key}: {out.relative_to(ROOT)} exists; skipping (use --force to redo)")
            continue
        cmd = command(model_id, out)
        print(f"{key}: {' '.join(cmd)}", flush=True)
        if subprocess.run(cmd).returncode != 0:
            failed.append(key)
            print(f"{key}: export FAILED", file=sys.stderr)
        else:
            print(f"{key}: wrote {out.relative_to(ROOT)}")
    if failed:
        sys.exit(f"failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
