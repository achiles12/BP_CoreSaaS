#!/usr/bin/env bash
# Build the wireframe PDF (design: 20261113_wireframe_design.md §5).
#   wireframe/wireframe.html --Playwright (Docker)--> 20261113_wireframe.pdf --copy--> 01_design/wireframe.pdf
# Also writes PNG previews to shots/ and a SHA-256 file for the Windows check.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PW_IMAGE="mcr.microsoft.com/playwright:v1.65.0-noble"
PDF="20261113_wireframe.pdf"

echo "[build] rendering with $PW_IMAGE"
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$HERE:/w" "$PW_IMAGE" bash -c \
  "cd /tmp && npm i -s playwright@1.65.0 >/dev/null 2>&1 && cp /w/wireframe/render.mjs . && \
   node render.mjs /w/wireframe/wireframe.html /w/$PDF /w/shots"

# The wireframes live in 01_design/wireframes/ since 2026-11-13; ROOT is 01_design.
cp "$HERE/$PDF" "$ROOT/wireframe.pdf"
( cd "$HERE" && sha256sum "$PDF" > "$PDF.sha256" )
echo "[build] copied to 01_design/wireframe.pdf"
echo "[build] sha256 $(cut -d' ' -f1 "$HERE/$PDF.sha256")"
