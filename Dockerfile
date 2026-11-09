# ChamaPro AI: the dashboard and the API in one image, served from one origin.
#
#   docker compose up --build            # CPU, demo database (README "Docker")
#   docker build --build-arg INTEL_GPU=1 .   # adds the Intel GPU runtime
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
# Pinned to bookworm: the package names below are Debian 12's, and the
# unpinned tag moves to each new Debian release.
FROM python:3.12-slim-bookworm

# ffmpeg decodes what browsers record (webm, mp4). INTEL_GPU=1 adds Intel's
# OpenCL compute runtime so OpenVINO can find an Intel GPU (compose profile
# "gpu"); bookworm has no Level Zero GPU driver, and OpenVINO needs only
# OpenCL. Off by default: the image then runs the ASR on the CPU, as it also
# does when a GPU build sees no GPU (/api/health says which).
ARG INTEL_GPU=0
RUN case "${INTEL_GPU}" in \
        1) gpu="intel-opencl-icd" ;; \
        0) gpu="" ;; \
        *) echo "INTEL_GPU must be 0 or 1, not '${INTEL_GPU}'" >&2; exit 1 ;; \
    esac \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ${gpu} \
    && rm -rf /var/lib/apt/lists/*

# Non-root. UID 1000 matches the usual first user on the host, so files the
# app writes into the mounted data/ stay owned by that user.
ARG UID=1000
RUN useradd --create-home --uid "${UID}" --user-group app

WORKDIR /app
# The exact environment the tests run in. torch and torchvision go first,
# at their locked versions, from PyTorch's CPU index alone, so pip never
# fetches CUDA wheels; --no-deps leaves their dependencies to the locked
# install, from PyPI.
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir --no-deps \
        --index-url https://download.pytorch.org/whl/cpu \
        $(grep -E '^(torch|torchvision)==' requirements.lock.txt)
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
