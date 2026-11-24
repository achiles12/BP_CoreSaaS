# Wireframe PDF: Manual Check on the Windows PC

| | |
|---|---|
| Object | `01_design/wireframe.pdf` (21 pages, A4 landscape) |
| Server | dev host, LAN IP **192.168.50.113** (SSH) |
| Client | Windows 10/11, PowerShell 5.1 or 7, a PDF viewer (Edge works) |
| Files | `20261113_wireframe_manual_test.ps1` (same folder) |
| Design | `20261113_wireframe_design.md` |

The automated test (`20261113_wireframe_test.sh`, 26/26) already checks the page count, the page size, every screen ID and the overflow. This manual check covers two things a script cannot:
- the file arrives intact on another machine and opens in a normal viewer
- the drawings read correctly to a human

## 0. Preconditions (server)

```bash
cd /prj/coruscant/daffy
bash 01_design/wireframes/20261113_wireframe_test.sh     # expect 26/26; it also rebuilds the PDF and the .sha256
```

## 1. Copy and verify (PowerShell)

```powershell
powershell -ExecutionPolicy Bypass -File .\20261113_wireframe_manual_test.ps1 -SshUser <your-login>
```

| ID | Check | Expected |
|---|---|---|
| W1, W2 | scp copies the PDF and its `.sha256` | both copied to `%TEMP%\daffy-wireframe\` |
| W3 | SHA-256 | the same as on the server |
| W4 | header | `%PDF-` |
| W5 | page count | 21 |
| W6 | size | 100 KB – 10 MB (about 0.8 MB) |

Expected: **6/6 passed**, then the PDF opens. If you get "scp is not recognized", enable *Settings → Optional features → OpenSSH Client*.

## 2. Read-through checklist (PDF viewer)

| # | Page | Check |
|---|---|---|
| R1 | all | 21 pages, landscape. Nothing is cut off at the right or bottom edge. The footer reads "page N of 21" |
| R2 | 1 | The index lists every screen S01–S16, with S06 marked **DROPPED**. Every screen is **BUILT** (green); the legend explains BUILT and PLACEHOLDER (only "Recent activity") |
| R3 | 2 | The screen map shows login → post-login → six landing pages → feature pages, and the email links into reset / verify / accept invite. All boxes are green (built); the legend says "Planned (none left)" |
| R4 | 3 | Public layout, desktop app shell and mobile drawer. Callouts 1–4 sit next to the dev bar, org name, sidebar and ☰ |
| R5 | 4–8 | Built pages (S01–S05) look like the running app. Optional: compare them side by side with `http://192.168.50.113:3200/login` and the B09 manual test |
| R6 | 9–12 | Landing pages: the owner, admin, manager, staff, user and platform cards match the table in `05_stage09/20261113_b09_manual_test.md` §0. Placeholder cards show a purple dashed "arrives in Bxx" pill |
| R7 | 13–20 | Pages carry a green **BUILT B10** / **BUILT B11** badge and match the running app (e.g. S15 has no History panel, S10 no Role filter). Each side panel lists route, access, API, states and notes, and every numbered dot matches a note |
| R8 | 21 | 403, 404, error boundary and session-expired toast |
| R9 | any | Zoom to 200 %: the text stays sharp (vector, not a picture) and can be selected and searched (Ctrl+F "S08" finds page 13) |

## 3. Results

| Section | Result | Notes |
|---|---|---|
| §1 script (6 checks) | | |
| R1–R3 structure, index, map | | |
| R4–R8 page content | | |
| R9 text quality | | |

Feedback on content (missing states, wrong labels, layout ideas for B10): ____________

Tested by: ____________ Date: ____________ Viewer: ____________
