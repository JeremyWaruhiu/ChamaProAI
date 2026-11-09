# ChamaPro AI as a Hugging Face Docker Space: CPU only, port 7860, user 1000.
#
# This file is the root of the Space repo, which deploy/hf-space/assemble.sh builds from
# the project (README "Deployment"). Nothing private is in it: the classifier and the
# OpenVINO Paza export are fetched at start from a private model repo with HF_TOKEN
# (space/fetch_models.py), and every key is a Space secret, read at run time.

# --- 1. Dashboard: frontend/dist ----------------------------------------------
FROM node:24-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- 2. Runtime ------------------------------------------------------------------
FROM python:3.12-slim-bookworm

# ffmpeg decodes what browsers record (webm, mp4) and encodes the spoken replies (mp3).
# Retries: a download that arrives corrupt ("Hash Sum mismatch") is fetched again.
RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Spaces run the container as UID 1000; the app and its caches belong to that user.
RUN useradd --create-home --uid 1000 user

# The locked environment the tests run in. torch and torchvision first, from PyTorch's
# CPU index alone, so pip never fetches CUDA wheels; the rest from the lock.
COPY requirements.lock.txt /tmp/requirements.lock.txt
ENV PIP_RETRIES=10 PIP_DEFAULT_TIMEOUT=120
RUN pip install --no-cache-dir --no-deps \
        --index-url https://download.pytorch.org/whl/cpu \
        $(grep -E '^(torch|torchvision)==' /tmp/requirements.lock.txt) \
    && pip install --no-cache-dir -r /tmp/requirements.lock.txt \
    && rm /tmp/requirements.lock.txt

USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONPATH=/home/user/app/src \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/home/user/.cache/huggingface \
    # Everything written at run time is under ~/.cache, and gone when the Space restarts.
    CHAMAPRO_MODELS_CACHE=/home/user/.cache/chamapro/models \
    TTS_CACHE_DIR=/home/user/.cache/chamapro/tts \
    CHAMAPRO_UPLOADS=/home/user/.cache/chamapro/uploads \
    # Speech: the OpenVINO INT8 Paza on OpenVINO's CPU device (torch only if that fails).
    # English Whisper (torch, from the hub) is loaded and warmed after Paza: measured at
    # 4.4 GB peak for the whole app with it, of the 16 GB the free tier has.
    ASR_ENGINE=openvino \
    ASR_DEVICE=CPU \
    ASR_WARM_ENGLISH=1 \
    # Audio in Supabase Storage and Gemini on: the database and keys are Space secrets.
    STORAGE_BACKEND=supabase \
    CONVERSATION_GEMINI_LIVE=1 \
    # Only Hugging Face's proxy reaches this port: believe its X-Forwarded-Proto/-For.
    FORWARDED_ALLOW_IPS=*

WORKDIR /home/user/app
COPY --chown=user pyproject.toml alembic.ini ./
COPY --chown=user results/summary.json results/
COPY --chown=user scripts/ scripts/
COPY --chown=user src/ src/
COPY --chown=user space/ space/
COPY --chown=user --from=frontend /frontend/dist frontend/dist
# config.MODELS_DIR is <app>/models: point it at the writable cache the models land in.
RUN mkdir -p "$CHAMAPRO_MODELS_CACHE" data && ln -s "$CHAMAPRO_MODELS_CACHE" models

EXPOSE 7860
CMD ["sh", "space/start.sh"]
