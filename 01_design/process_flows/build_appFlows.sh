#!/usr/bin/env bash
# Build 01_design/process_flows/appFlows.pdf from source/appFlows.html
# (Playwright in Docker, same renderer as the wireframes). Fails on JS errors,
# page overflow or an unexpected page count; writes PNG previews to source/shots/.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PW_IMAGE="mcr.microsoft.com/playwright:v1.65.0-noble"
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$HERE:/w" "$PW_IMAGE" bash -c \
  "cd /tmp && npm i -s playwright@1.65.0 >/dev/null 2>&1 && cp /w/source/render.mjs . && \
   node render.mjs /w/source/appFlows.html /w/appFlows.pdf /w/source/shots"
echo "[build] wrote $HERE/appFlows.pdf"
