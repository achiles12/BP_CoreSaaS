#!/usr/bin/env bash
# Wireframe PDF test (design: 20261113_wireframe_design.md §6).
# Re-renders via the build script (which itself fails on overflow / page count),
# then inspects the PDF with pdfjs and checks the copies + checksum.
# Writes 20261113_wireframe_test_results.md.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PW_IMAGE="mcr.microsoft.com/playwright:v1.65.0-noble"
PDF="$HERE/20261113_wireframe.pdf"
RESULTS="$HERE/20261113_wireframe_test_results.md"
PASS=0; FAIL=0; ROWS=""

check() { # check <id> <description> <command...>
  local id="$1" desc="$2"; shift 2
  if "$@" >/dev/null 2>&1; then PASS=$((PASS+1)); ROWS+="| $id | $desc | PASS |"$'\n'; echo "PASS $id $desc"
  else FAIL=$((FAIL+1)); ROWS+="| $id | $desc | **FAIL** |"$'\n'; echo "FAIL $id $desc"; fi
}

echo "== build"
check T1 "build script renders: no JS errors, no page overflows, 21 pages" bash "$HERE/20261113_wireframe_build.sh"
check T2 "PDF exists with a %PDF header" bash -c "head -c 5 '$PDF' | grep -q '%PDF-'"
check T3 "01_design/wireframe.pdf is identical to the stage copy" cmp "$PDF" "$ROOT/wireframe.pdf"  # ROOT = 01_design since the move
check T4 "SHA-256 file matches the PDF" bash -c "cd '$HERE' && sha256sum -c 20261113_wireframe.pdf.sha256"

echo "== inspect (pdfjs)"
JSON="$(docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$HERE:/w:ro" "$PW_IMAGE" bash -c \
  "cd /tmp && npm i -s pdfjs-dist@4.10.38 >/dev/null 2>&1 && cp /w/wireframe/check_pdf.mjs . && node check_pdf.mjs /w/20261113_wireframe.pdf" 2>/dev/null | tail -1)"
echo "$JSON" > "$HERE/shots/pdf_inspect.json"
py() { python3 -I -c "import json,sys; d=json.loads(sys.argv[1]); $1" "$JSON"; }

check T5 "PDF has 21 pages" py "assert d['pages']==21"
check T6 "every page is A4 landscape (842x595 pt ±2)" py "assert all(abs(w-842)<=2 and abs(h-595)<=2 for w,h in d['sizes'])"
check T7 "footer page numbers run 1..21 of 21" py "assert d['footers']==[f'{i}/21' for i in range(1,22)]"
for id in S01 S02 S03 S04 S05 S07 S08 S09 S10 S11 S12 S13 S14 S15 S16; do
  check "T8-$id" "screen $id appears in the PDF text" py "assert d['ids']['$id']"
done
check T9 "screen map page (MAP) and layouts page (§1) present" py "assert 2 in d['ids']['MAP'] and 3 in d['ids']['§1']"
check T10 "S06 listed on the cover as dropped, with no page of its own" py "assert 1 in d['ids']['S06'] and not any(h.lstrip().startswith('S06') for h in d['heads'])"
check T11 "21 PNG previews written" bash -c "[ \$(ls '$HERE'/shots/page_*.png | wc -l) -eq 21 ]"
# Since B10/B11 (2026-11-20) every screen is built: none may still say planned.
check T12 "status badges: every screen BUILT, none PLANNED" bash -c "grep -q 'status: \"built\"' '$HERE/wireframe/wireframe.html' && ! grep -q 'status: \"planned\"' '$HERE/wireframe/wireframe.html'"

TOTAL=$((PASS+FAIL))
SHA="$(cut -d' ' -f1 "$PDF.sha256" 2>/dev/null)"
cat > "$RESULTS" <<EOF
# Wireframe PDF: Test Results

| | |
|---|---|
| Run | $(date '+%Y-%m-%d %H:%M %Z') on $(hostname) |
| Script | \`01_design/wireframes/20261113_wireframe_test.sh\` |
| PDF | \`01_design/wireframes/20261113_wireframe.pdf\` → \`01_design/wireframe.pdf\` |
| SHA-256 | \`$SHA\` |
| Result | **$PASS/$TOTAL passed** |

| ID | Check | Result |
|---|---|---|
$ROWS
Previews: \`01_design/wireframes/shots/page_01.png\` … \`page_21.png\`; raw inspection: \`shots/pdf_inspect.json\`.
EOF
echo "== $PASS/$TOTAL passed (results: $RESULTS)"
[ "$FAIL" -eq 0 ]
