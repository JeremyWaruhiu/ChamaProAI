# ChamaPro AI: the dashboard and the API in one image, served from one origin.
#
#   docker compose up --build            # CPU, demo database (README "Docker")
#
# Nothing private is baked in. models/ and data/ (databases, uploads) are
# mounted as volumes and .env is passed at run time; .dockerignore is an
# allow-list of what the build can see.

# --- 1. Dashboard: frontend/dist ----------------------------------------------
FROM node:24-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- 2. Runtime ------------------------------------------------------------------
FROM python:3.12-slim

# ffmpeg decodes what browsers record (webm, mp4). The Intel GPU compute
# runtime (OpenCL + Level Zero) lets OpenVINO find an Intel GPU, including
# through WSL2's /dev/dxg (compose profile "gpu"); with no GPU visible the
# ASR falls back to the CPU and /api/health says so.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg intel-opencl-icd libze-intel-gpu1 libze1 \
    && rm -rf /var/lib/apt/lists/*

# Non-root. UID 1000 matches the usual first user on the host, so files the
# app writes into the mounted data/ stay owned by that user.
ARG UID=1000
RUN useradd --create-home --uid "${UID}" --user-group app

WORKDIR /app
# The exact environment the tests run in (CPU torch wheels included).
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt

COPY pyproject.toml alembic.ini ./
COPY scripts/ scripts/
COPY results/summary.json results/
COPY src/ src/
COPY --from=frontend /frontend/dist frontend/dist

# The source tree stays at /app (not site-packages): config.PROJECT_ROOT is
# two levels above chamapro/config.py, and the API imports scripts/ from there.
ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/home/app/.cache/huggingface \
    FORWARDED_ALLOW_IPS=127.0.0.1
RUN mkdir -p data models && chown app:app data models
USER app

EXPOSE 8000
# /api/health answers 200 once the API is up, "degraded" or not; the start
# period covers loading the ASR model (longer on a GPU: it compiles first).
HEALTHCHECK --interval=30s --timeout=5s --start-period=240s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

# --proxy-headers: behind a tunnel or reverse proxy, take the client scheme
# (https) and address from X-Forwarded-* so the session cookie is marked
# Secure. Only peers in FORWARDED_ALLOW_IPS are believed; uvicorn reads that
# variable itself (docker-compose.yml sets it).
CMD ["uvicorn", "chamapro.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
