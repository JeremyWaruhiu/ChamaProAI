#!/bin/sh
# The Space's entrypoint: private models first (the API needs them to start), then the
# English weights in the background, then the API on the port Hugging Face proxies.
# The API itself loads Paza, then warms Paza, English Whisper, the classifier and the
# voices in the background (api/main.py lifespan).
set -e
cd "$HOME/app"
python space/fetch_models.py
python space/fetch_models.py --public &
# One process: the models are loaded once, in it. --proxy-headers: the scheme and the
# member's address come from Hugging Face's proxy (FORWARDED_ALLOW_IPS, set in the image).
exec uvicorn chamapro.api.main:app --host 0.0.0.0 --port 7860 --proxy-headers
