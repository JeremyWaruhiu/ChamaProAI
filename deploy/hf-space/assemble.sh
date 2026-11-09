#!/usr/bin/env bash
# Stage the Hugging Face Space repo: this folder's Space files at the root, plus the
# project source the image builds from, and nothing else. Run from anywhere:
#
#   deploy/hf-space/assemble.sh [OUT]       # OUT defaults to build/hf-space
#
# Then build it locally (docker build OUT) or push it (README "Deployment").
# What goes in is a list of paths, filtered by .gitignore: never .env, data/, models/,
# docs/, node_modules or a build.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
out="${1:-$root/build/hf-space}"

case "$out" in /|"$root"|"$HOME") echo "refusing to use $out" >&2; exit 1 ;; esac
rm -rf "$out"
mkdir -p "$out/space"

cp "$here/README.md" "$here/Dockerfile" "$out/"
cp "$here/start.sh" "$here/fetch_models.py" "$out/space/"
printf '%s\n' '**/__pycache__/' '**/*.pyc' > "$out/.dockerignore"

# Files git tracks, plus new files it does not ignore (listed, so you can see them),
# as they are in the working tree: what you would commit, committed or not.
cd "$root"
paths=(requirements.lock.txt pyproject.toml alembic.ini results/summary.json src scripts frontend)
untracked="$(git ls-files --others --exclude-standard -- "${paths[@]}")"
if [ -n "$untracked" ]; then
    echo "including files git does not track yet:" >&2
    echo "$untracked" | sed 's/^/    /' >&2
fi
{
    git ls-files --cached --others --exclude-standard -- "${paths[@]}"
} | grep -v -E '(^|/)(__pycache__|node_modules|dist)/' \
  | while IFS= read -r f; do
        [ -f "$f" ] || continue                 # deleted in the working tree
        mkdir -p "$out/$(dirname "$f")"
        cp "$f" "$out/$f"
    done

echo "Space repo staged in $out ($(du -sh "$out" | cut -f1), $(find "$out" -type f | wc -l) files)"
