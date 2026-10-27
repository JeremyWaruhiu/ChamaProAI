#!/usr/bin/env bash
# Put the running container on a public https URL for an online demo.
#
#   docker compose up -d                 # first: the app on localhost:8000
#   scripts/demo_tunnel.sh               # then: prints https://<random>.trycloudflare.com
#
# A Cloudflare quick tunnel: free, no account, nothing to configure. The URL
# is new on every run and lasts until Ctrl-C. Anyone with it reaches the
# sign-in page, so share it only with the audience and stop it afterwards.
# Install cloudflared first: README "Online demo".
set -euo pipefail

PORT="${PORT:-8000}"
LOCAL="http://localhost:${PORT}"

die() { echo "demo_tunnel: $*" >&2; exit 1; }

command -v cloudflared >/dev/null || die "cloudflared is not installed (README \"Online demo\")"
command -v curl >/dev/null || die "curl is not installed"

# 1. The container is up and Docker calls it healthy.
if command -v docker >/dev/null; then
    cid="$(docker ps -q --filter label=com.docker.compose.project=chamapro | head -n1)"
    [[ -n "$cid" ]] || die "no ChamaPro container is running; start one: docker compose up -d"
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")"
    [[ "$health" == healthy ]] || die "the container is $health, not healthy yet; watch it with: docker compose ps"
fi

# 2. The API answers on the port the tunnel will use.
body="$(curl -fsS --max-time 5 "${LOCAL}/api/health")" || die "nothing answers on ${LOCAL}/api/health"
echo "health: ${body}"
curl -fsS --max-time 5 -o /dev/null "${LOCAL}/" || die "${LOCAL}/ does not serve the dashboard"

# 3. The tunnel. cloudflared logs the URL it was given; show it once, clearly.
log="$(mktemp -t chamapro-tunnel.XXXXXX)"
trap 'rm -f "$log"' EXIT
echo "starting the tunnel (cloudflared log: ${log}); Ctrl-C ends it"
shown=""
cloudflared tunnel --no-autoupdate --url "$LOCAL" 2>&1 | tee "$log" | while IFS= read -r line; do
    if [[ -z "$shown" && "$line" =~ (https://[a-z0-9-]+\.trycloudflare\.com) ]]; then
        shown=1
        url="${BASH_REMATCH[1]}"
        printf '\n  Public demo URL: %s\n' "$url"
        printf '  Local fallback:  %s\n' "$LOCAL"
        printf '  It changes on every run. Keep this window open and the laptop awake.\n\n'
    elif [[ "$line" == *ERR* ]]; then
        echo "$line"
    fi
done
