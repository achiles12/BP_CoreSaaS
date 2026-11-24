// Render appFlows.html → appFlows.pdf + PNG previews (copy of the wireframe renderer).
// Runs inside mcr.microsoft.com/playwright:v1.65.0-noble with /w = 01_design/process_flows.
// Usage: node render.mjs <html> <pdf-out> <shots-dir>
// Exit 1 if a page overflows its A4 sheet or the page count is unexpected.
import { chromium } from "playwright";
import { pathToFileURL } from "node:url";
import { mkdirSync } from "node:fs";

const [html, pdfOut, shotsDir] = process.argv.slice(2);
const EXPECTED_PAGES = 14; // cover + system map + 12 flows (F5 dropped)
const log = (...a) => console.log("[render]", ...a);

const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1123, height: 794 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  await page.goto(pathToFileURL(html).href);
  await page.waitForSelector("section.page");
  if (errors.length) throw new Error("JS errors in appFlows.html: " + errors.join(" | "));

  // Overflow check: the stage and side panel clip (overflow:hidden), so content
  // that does not fit would silently vanish from the PDF. Compare scroll vs client size.
  const report = await page.$$eval("section.page", (pages) =>
    pages.map((p, i) => {
      const over = [];
      for (const sel of [".stage", ".panel"]) {
        const el = p.querySelector(sel);
        if (el && (el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1))
          over.push(`${sel} ${el.scrollWidth}x${el.scrollHeight} > ${el.clientWidth}x${el.clientHeight}`);
      }
      return { n: i + 1, id: p.dataset.id, title: p.querySelector(".stitle")?.textContent, over };
    }),
  );
  let bad = 0;
  for (const r of report) {
    log(`page ${String(r.n).padStart(2)} ${r.id.padEnd(4)} ${r.title}${r.over.length ? "  OVERFLOW: " + r.over.join("; ") : ""}`);
    if (r.over.length) bad++;
  }
  if (report.length !== EXPECTED_PAGES) throw new Error(`expected ${EXPECTED_PAGES} pages, got ${report.length}`);
  if (bad) throw new Error(`${bad} page(s) overflow`);

  // PNG preview of every sheet (visual check, also used by the test).
  mkdirSync(shotsDir, { recursive: true });
  const sheets = await page.$$("section.page");
  for (let i = 0; i < sheets.length; i++)
    await sheets[i].screenshot({ path: `${shotsDir}/page_${String(i + 1).padStart(2, "0")}.png` });

  await page.emulateMedia({ media: "print" });
  await page.pdf({ path: pdfOut, format: "A4", landscape: true, printBackground: true, margin: { top: 0, right: 0, bottom: 0, left: 0 } });
  log(`wrote ${pdfOut} (${report.length} pages) and ${sheets.length} previews in ${shotsDir}`);
} catch (e) {
  console.error("[render] FAILED:", e.message);
  process.exitCode = 1;
} finally {
  await browser.close();
}
