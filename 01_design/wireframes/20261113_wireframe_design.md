# Wireframe PDF: Design

| | |
|---|---|
| Object | `01_design/wireframe.pdf`: a wireframe set of every screen |
| Type | Design document (generated PDF) |
| Date | 2026-11-13 |
| Requested | `/build_object wireframe.pdf of the project`. Audience: "me, all screens" |
| Status | **Built 2026-11-13**: automated test 26/26, PowerShell script 6/6 (pwsh 7, scp stubbed); Windows read-through pending. The user did not review this design before the build. Every choice marked *my call* is open to change |
| References | `01_design/ui_screens.md` (S01–S16, §1–5), `api_spec.md`, `config/navigation.ts`, `config/landing.ts`, `05_stage09/shots/` |

## 1. Purpose

One PDF that shows every screen of the Core SaaS scaffold on one page each. It serves as:
- a reference for building B10 (Files, Search, Users, Profile, Organization, Exports, Notifications) and B11 (Template items)
- a check that the B08/B09 pages match the spec

## 2. Decisions

| # | Decision | Source |
|---|---|---|
| W1 | **Low-fidelity grey boxes.** Greyscale, with one accent colour for status only. Real labels and texts, sample data | my call |
| W2 | **One A4 landscape page per screen.** About ¾ of the page is the screen frame. A **side panel** holds the screen ID, route, permission, API calls, states and build status | my call |
| W3 | **Built screens (B08/B09) are drawn as they look today**, from the B09 screenshots. Planned screens are drawn from `ui_screens.md` plus `api_spec.md` | my call (the question went unanswered) |
| W4 | **Status badge** on each page: `BUILT B08`, `BUILT B09`, `PLANNED B10`, `PLANNED B11`, `PLACEHOLDER` (cards waiting for B05/B07) | my call |
| W5 | **Page 1 is a cover and index. Page 2 is a screen map**: login → post-login → landing pages → feature pages, plus the email-link entry points | my call |
| W6 | **Source**: a single self-contained HTML file `05_stage10/wireframe/wireframe.html` (inline CSS, no network). The PDF is rendered with Playwright `page.pdf()` in the existing Docker image `mcr.microsoft.com/playwright:v1.65.0-noble` | my call |
| W7 | **Location**: the PDF goes in `01_design/wireframe.pdf`, a living design file next to `arch_overview.pdf`, with no date prefix. A dated copy `05_stage10/20261113_wireframe.pdf` is kept as the stage record | my call |
| W8 | **Stage folder** `05_stage10/`: the wireframe feeds B10/B11, so it lives with them | my call |

## 3. Pages (objects)

| # | Page | Screen | Route | Status |
|---|---|---|---|---|
| 1 | Cover + index | — | — | — |
| 2 | Screen map | — | — | — |
| 3 | Layouts: public card + app shell (desktop and mobile drawer) | §1 | — | BUILT B08 |
| 4 | Login (normal, error, rate limited) | S01 | `/login` | BUILT B09 |
| 5 | Forgot + reset password | S02 | `/forgot-password`, `/reset-password` | BUILT B09 |
| 6 | Verify email + unverified banner | S03 | `/verify-email` | BUILT B09 |
| 7 | Accept invite (new + existing account) | S04 | `/accept-invite` | BUILT B09 |
| 8 | Post-login spinner + no organization | S05 | `/post-login`, `/no-organization` | BUILT B09 |
| 9 | Owner landing page | S07 | `/home/owner` | BUILT B09 (2 placeholder cards) |
| 10 | Admin + manager landing pages | S07 | `/home/admin`, `/home/manager` | BUILT B09 |
| 11 | Staff + user landing pages | S07 | `/home/staff`, `/home/user` | BUILT B09 |
| 12 | Platform page | S07 | `/platform` | BUILT B09 |
| 13 | Files list + upload dialog + delete confirm | S08 | `/files` | PLANNED B10 |
| 14 | Search | S09 | `/search` | PLANNED B10 |
| 15 | Users + invitations tab + invite / roles dialogs | S10 | `/users` | PLANNED B10 |
| 16 | Profile | S11 | `/settings/profile` | PLANNED B10 |
| 17 | Organization settings | S12 | `/settings/organization` | PLANNED B10 |
| 18 | Export dialog + recent exports | S13 | dialog | PLANNED B10 |
| 19 | Notifications bell dropdown | S14 | top bar | PLANNED B10 (optional) |
| 20 | Template items list + detail/create form | S15 | `/items` | PLANNED B11 |
| 21 | Errors: 403, 404, error boundary, session-expired toast | S16 | `/403`, any | BUILT B08 |

S06 (org picker) was dropped (B04 D1). The cover lists it as dropped and gives it no page.

## 4. Side panel fields (each screen page)

| Field | Content |
|---|---|
| ID + title | e.g. `S08 Files` |
| Route | path and query |
| Access | permission key, or "public" / "signed in" |
| API | endpoints from `api_spec.md` |
| States | loading, empty, error, 403, 429… |
| Status | badge per W4, plus the batch |
| Notes | open points for the builder |

## 5. Flow (build)

```
wireframe.html ──(Playwright Docker, page.pdf A4 landscape, printBackground)──▶ 05_stage10/20261113_wireframe.pdf
                                                                         └─copy─▶ 01_design/wireframe.pdf
```
Script: `05_stage10/20261113_wireframe_build.sh` (render + copy + checks). The renderer is `05_stage10/wireframe/render.mjs`.

## 6. Tests

`05_stage10/20261113_wireframe_test.sh` (results in `20261113_wireframe_test_results.md`):
- The PDF exists and has a `%PDF` header. Page count = 21.
- Each screen ID S01–S05 and S07–S16 appears in the extracted text.
- No page overflows: each `.page` element is at most one A4 landscape height (checked in the renderer before printing).
- PNG previews of pages 1–3 are written to `05_stage10/shots/` for a visual check.
- The SHA-256 is recorded for the Windows check.

**Manual (Windows):** `20261113_wireframe_manual_test.md` + `.ps1`. The script copies the PDF with `scp`, checks its hash and opens it. A checklist then confirms that each page reads correctly.

## 7. Build notes (2026-11-13)

- **Results:** `20261113_wireframe_test.sh` 26/26 (`20261113_wireframe_test_results.md`), with PNG previews in `shots/`. The PowerShell script ran 6/6 in the `mcr.microsoft.com/powershell:7.4` container, with a stub standing in for `scp`. The real scp copy is checked on the Windows PC.
- **Callouts** are inline numbered dots placed next to the element they describe. Absolute coordinates drifted, so they were dropped after the first render.
- **Overflow guard:** `render.mjs` fails the build if any page's stage or side panel would clip content. This caught page 19 on the first render.
- **The PDF is not byte-reproducible.** Chromium writes a creation date into it, so every build gets a new SHA-256. The `.sha256` file is rewritten with each build, and the Windows script compares against it.
- **Rebuild after a UI change:** edit `wireframe/wireframe.html`, then run `bash 05_stage10/20261113_wireframe_build.sh` (about 20 s). When B10/B11 pages are built, switch their `status` from `planned` to `built` and redraw them from the real pages.
- **Tools:** pdfjs-dist 4.10.38 (test only, installed inside the Playwright container on each run).

## Update 2026-11-20 (after B10/B11)

- **Moved:** the wireframe files now live in `01_design/wireframes/` (was `05_stage10/`). The build script copies the PDF to `01_design/wireframe.pdf`; paths in the scripts were updated.
- **All screens built:** S08–S15 flipped to BUILT (B10/B11) and redrawn from the running app where the build differs from the spec: S08 "Mine only" instead of an uploader filter; S09 type chips, grouped results; S10 no role filter; S11 "Save name", other sessions only; S12 single card, owner-only note; S13 real dialog steps, last 5 exports; S14 export notifications only, 30 s count; S15 no history panel (user decision D1). Landing cards (S07) drawn live; no "soon" badges.
- **Test:** T12 now requires that no screen is still `planned`.
