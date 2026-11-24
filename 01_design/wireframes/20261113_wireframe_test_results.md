# Wireframe PDF: Test Results

| | |
|---|---|
| Run | 2026-11-20 18:22 +08 on andor |
| Script | `01_design/wireframes/20261113_wireframe_test.sh` |
| PDF | `01_design/wireframes/20261113_wireframe.pdf` → `01_design/wireframe.pdf` |
| SHA-256 | `f20c77a4b83b333c4fe9ab00a41edfe64f829797a818f70c53b51d54dbc8ae78` |
| Result | **26/26 passed** |

| ID | Check | Result |
|---|---|---|
| T1 | build script renders: no JS errors, no page overflows, 21 pages | PASS |
| T2 | PDF exists with a %PDF header | PASS |
| T3 | 01_design/wireframe.pdf is identical to the stage copy | PASS |
| T4 | SHA-256 file matches the PDF | PASS |
| T5 | PDF has 21 pages | PASS |
| T6 | every page is A4 landscape (842x595 pt ±2) | PASS |
| T7 | footer page numbers run 1..21 of 21 | PASS |
| T8-S01 | screen S01 appears in the PDF text | PASS |
| T8-S02 | screen S02 appears in the PDF text | PASS |
| T8-S03 | screen S03 appears in the PDF text | PASS |
| T8-S04 | screen S04 appears in the PDF text | PASS |
| T8-S05 | screen S05 appears in the PDF text | PASS |
| T8-S07 | screen S07 appears in the PDF text | PASS |
| T8-S08 | screen S08 appears in the PDF text | PASS |
| T8-S09 | screen S09 appears in the PDF text | PASS |
| T8-S10 | screen S10 appears in the PDF text | PASS |
| T8-S11 | screen S11 appears in the PDF text | PASS |
| T8-S12 | screen S12 appears in the PDF text | PASS |
| T8-S13 | screen S13 appears in the PDF text | PASS |
| T8-S14 | screen S14 appears in the PDF text | PASS |
| T8-S15 | screen S15 appears in the PDF text | PASS |
| T8-S16 | screen S16 appears in the PDF text | PASS |
| T9 | screen map page (MAP) and layouts page (§1) present | PASS |
| T10 | S06 listed on the cover as dropped, with no page of its own | PASS |
| T11 | 21 PNG previews written | PASS |
| T12 | status badges: every screen BUILT, none PLANNED | PASS |

Previews: `01_design/wireframes/shots/page_01.png` … `page_21.png`; raw inspection: `shots/pdf_inspect.json`.
