# Capture: Chapter 5 screenshots and the backup demo video

Both drive the two demo conversations (`scripts/demo_scripts.py`: Wanjiru in English, Njeri in
Gĩkũyũ mode) by typing, in Chromium, against a server of their own. `fresh.sh` rebuilds its
database from the seed in a scratch folder you name, whatever `.env` says: SQLite, local audio,
Supabase blanked, the Kikuyu ASR not loaded. Gemini is off unless `--gemini-live`. Nothing outside
the scratch folder is written except the outputs below; `data/tts_cache` is copied, not used in place.

| File | What it does |
|---|---|
| `fresh.sh <scratch> [--gemini-live]` | Rebuilds `<scratch>/capture.db` from the seed and (re)starts `serve.py` on `CAPTURE_PORT` (8766) |
| `serve.py` | The server; new passwords each run in `<scratch>/logins.json` |
| `shots.mjs <scratch> [--only <regex>] [--out <dir>]` | `docs/screenshots/final-*.png`; calls `fresh.sh` itself |
| `video.mjs <scratch> [--gemini-live] [--out <file>]` | Records both conversations, then `compose.py`; writes `docs/demo/backup_demo.mp4` |
| `compose.py <scratch>/video <out.mp4> [slugs]` | Side by side, cached speech, caption bar; H.264 veryfast and AAC |
| `common.mjs` | Shared by the two drivers |

## After a WSL restart

Once, if `~/.npm/_npx` was cleared: fetch Playwright and its Chromium, and find the package.

    npx -y playwright@1.64.1 install chromium
    export PLAYWRIGHT=$(dirname "$(find ~/.npm/_npx -path '*/node_modules/playwright/package.json' | head -1)")

Before either: the classifier in `models/`, a current `frontend/dist` (`cd frontend && npm run build`),
and every line the bot says in `data/tts_cache` (`python scripts/warm_demo.py`, with no server running).
The video also needs `ffmpeg` with libx264 and the DejaVu fonts.

    node tests/browser/capture/shots.mjs /tmp/capture
    node tests/browser/capture/shots.mjs /tmp/capture --only 'njeri-10-why|wanjiru-my-sacco'
    node tests/browser/capture/video.mjs /tmp/capture                     # Gemini off
    node tests/browser/capture/video.mjs /tmp/capture --gemini-live       # the final recording

`--gemini-live` reads `GEMINI_API_KEY` from `.env` and calls Gemini on every answer, so `/present`
shows Gemini's English under Njeri's Kikuyu; it is never used by the tests. Each run stops, rather
than writing a misleading capture, on a transcript that differs from what was typed, a bot line the
script does not expect, a spoken line missing from `data/tts_cache`, a page error, or (screenshots)
sideways scrolling. The video is about 3.5 minutes and 8 MB; `docs/demo/` is not committed.

The server keeps running afterwards: `kill $(cat /tmp/capture/server.pid)`.
