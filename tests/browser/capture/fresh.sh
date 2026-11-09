#!/usr/bin/env bash
# Stop the capture server, rebuild its database from the seed and start it again (serve.py).
# Nothing outside <scratch> is written; data/tts_cache is copied, not used in place.
#
#   tests/browser/capture/fresh.sh <scratch> [--gemini-live]        CAPTURE_PORT, default 8766
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../../.." && pwd)
[ $# -ge 1 ] || { echo "usage: $0 <scratch> [--gemini-live]" >&2; exit 2; }
mkdir -p "$1"
scratch=$(cd "$1" && pwd)
live=${2:-}
port=${CAPTURE_PORT:-8766}
py="$root/.venv/bin/python"

if [ -f "$scratch/server.pid" ]; then
    kill "$(cat "$scratch/server.pid")" 2>/dev/null || true
    rm -f "$scratch/server.pid"
    sleep 1
fi
rm -rf "$scratch"/capture.db* "$scratch"/seed-working.db* "$scratch/uploads" "$scratch/tts_cache" \
       "$scratch/logins.json" "$scratch/server.json"
mkdir -p "$scratch/tts_cache"
if [ -d "$root/data/tts_cache" ]; then cp -a "$root/data/tts_cache/." "$scratch/tts_cache/"; fi

cd "$root"
# seed_demo.py puts --demo-db in DATABASE_URL itself; the rest keeps .env's database and bucket out.
CHAMAPRO_DB="$scratch/seed-working.db" STORAGE_BACKEND=local CHAMAPRO_UPLOADS="$scratch/uploads" \
    SUPABASE_URL= SUPABASE_SERVICE_ROLE_KEY= GEMINI_API_KEY= GOOGLE_API_KEY= \
    "$py" scripts/seed_demo.py --demo-db "$scratch/capture.db" > "$scratch/seed.log" 2>&1 \
    || { tail -5 "$scratch/seed.log" >&2; exit 1; }

nohup "$py" "$here/serve.py" "$scratch" "$port" $live > "$scratch/server.log" 2>&1 &
echo $! > "$scratch/server.pid"
for _ in $(seq 1 90); do
    if curl -fs "http://127.0.0.1:$port/api/health" > /dev/null 2>&1 && [ -f "$scratch/server.json" ]; then
        echo "capture server on http://127.0.0.1:$port (${live:-Gemini off}), database $scratch/capture.db"
        exit 0
    fi
    if ! kill -0 "$(cat "$scratch/server.pid")" 2>/dev/null; then tail -5 "$scratch/server.log" >&2; exit 1; fi
    sleep 1
done
echo "the capture server did not answer; see $scratch/server.log" >&2
exit 1
