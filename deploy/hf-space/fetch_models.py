"""Fetch what the Space needs from the hub before (and just after) the API starts.

    python fetch_models.py            # private artefacts; stops the container if it cannot
    python fetch_models.py --public   # English Whisper weights, in the background

Private: models/classifier.joblib, its meta file and the OpenVINO INT8 Paza export
(models/paza-ov-int8) are not in git or in this image. They live in a private model repo,
CHAMAPRO_MODEL_REPO (default <the Space's owner>/chamapro-private), read with the HF_TOKEN
secret into MODELS_CACHE, which the image links to /home/user/app/models. Files already
there are kept, so a restart of a running container, or a local run with the folder
mounted, downloads nothing.

Public: the English Whisper weights (1.6 GB), fetched while the API starts and Paza loads,
so the English warm-up (ASR_WARM_ENGLISH=1) finds them on disk. The MMS voices are small
and come down when the speech warm-up first asks for them.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

MODELS_CACHE = Path(os.getenv("CHAMAPRO_MODELS_CACHE") or Path.home() / ".cache/chamapro/models")
PRIVATE = ["classifier.joblib", "classifier_meta.json", "paza-ov-int8/*"]
# What the API checks for (config.CLASSIFIER_PATH, transcribe.ov_exported).
REQUIRED = ["classifier.joblib", "classifier_meta.json", "paza-ov-int8/openvino_encoder_model.xml",
            "paza-ov-int8/openvino_decoder_model.xml"]
# A compiled-model cache for one GPU, not portable: never fetched.
IGNORE = ["paza-ov-int8/encoder/*", "**/model_cache/*"]
ENGLISH = os.getenv("ASR_EN_MODEL") or "openai/whisper-large-v3-turbo"


def say(msg: str) -> None:
    print(f"[fetch_models] {msg}", flush=True)


def model_repo() -> str | None:
    if repo := os.getenv("CHAMAPRO_MODEL_REPO"):
        return repo
    owner = os.getenv("SPACE_AUTHOR_NAME")          # set by Hugging Face in every Space
    return f"{owner}/chamapro-private" if owner else None


def private() -> None:
    missing = [f for f in REQUIRED if not (MODELS_CACHE / f).is_file()]
    if not missing:
        say(f"private models already in {MODELS_CACHE}; nothing to fetch")
        return
    repo, token = model_repo(), os.getenv("HF_TOKEN")
    if not repo:
        sys.exit("[fetch_models] no CHAMAPRO_MODEL_REPO and no SPACE_AUTHOR_NAME: cannot tell which repo holds the models")
    if not token:
        sys.exit(f"[fetch_models] HF_TOKEN is not set: add it as a Space secret (read access to {repo})")
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import HfHubHTTPError
    say(f"fetching {', '.join(missing)} ... from {repo}")
    started = time.perf_counter()
    try:
        snapshot_download(repo, repo_type="model", token=token, local_dir=MODELS_CACHE,
                          allow_patterns=PRIVATE, ignore_patterns=IGNORE)
    except HfHubHTTPError as e:
        sys.exit(f"[fetch_models] could not download from {repo}: {e.__class__.__name__}: {str(e).splitlines()[0]}")
    if still := [f for f in REQUIRED if not (MODELS_CACHE / f).is_file()]:
        sys.exit(f"[fetch_models] {repo} has no {', '.join(still)}")
    say(f"private models ready in {time.perf_counter() - started:.0f} s")


def public() -> None:
    from huggingface_hub import snapshot_download
    started = time.perf_counter()
    try:
        snapshot_download(ENGLISH, allow_patterns=["*.json", "*.txt", "model.safetensors"])
        say(f"{ENGLISH} weights cached in {time.perf_counter() - started:.0f} s")
    except Exception as e:      # the first English reply downloads them instead
        say(f"could not prefetch {ENGLISH}: {e.__class__.__name__}: {e}")


if __name__ == "__main__":
    public() if "--public" in sys.argv[1:] else private()
