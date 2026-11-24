// Inspect the rendered wireframe PDF (05_stage10/20261113_wireframe_design.md §6).
// Runs in the Playwright image with pdfjs-dist installed. Prints one JSON line:
// {pages, sizes:[[w,h]...], ids:{S01:[pageNo...]...}, firstLines:[...]} for the bash test to assert on.
import { getDocument } from "pdfjs-dist/legacy/build/pdf.mjs";
import { readFileSync } from "node:fs";

const file = process.argv[2];
const doc = await getDocument({ data: new Uint8Array(readFileSync(file)), verbosity: 0 }).promise;
const IDS = ["MAP", "§1", "S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09", "S10", "S11", "S12", "S13", "S14", "S15", "S16"];
const out = { pages: doc.numPages, sizes: [], ids: Object.fromEntries(IDS.map((i) => [i, []])), heads: [], footers: [] };

for (let n = 1; n <= doc.numPages; n++) {
  const page = await doc.getPage(n);
  const [, , w, h] = page.view;
  out.sizes.push([Math.round(w), Math.round(h)]);
  const text = (await page.getTextContent()).items.map((i) => i.str).join(" ").replace(/\s+/g, " ");
  for (const id of IDS) if (text.includes(id)) out.ids[id].push(n);
  out.heads.push(text.slice(0, 60));
  const m = text.match(/page (\d+) of (\d+)/);
  out.footers.push(m ? `${m[1]}/${m[2]}` : null);
}
console.log(JSON.stringify(out));
