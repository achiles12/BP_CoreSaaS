import { describe, expect, it } from "vitest";

import { formatBytes, formatDate, formatDateTime, mimeLabel } from "./format";

describe("format", () => {
  it.each([
    [0, "0 B"],
    [1023, "1023 B"],
    [1536, "1.5 KB"],
    [86_000, "84 KB"],
    [1_258_291, "1.2 MB"],
    [5 * 1024 ** 3, "5 GB"],
  ])("formatBytes(%i) = %s", (n, s) => expect(formatBytes(n)).toBe(s));

  it.each([
    ["application/pdf", "PDF"],
    ["image/png", "Image"],
    ["application/vnd.openxmlformats-officedocument.wordprocessingml.document", "Word"],
    ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "Excel"],
    ["text/plain", "Text"],
    ["text/csv", "CSV"],
    ["application/zip", "Zip"],
    ["application/x-unknown", "File"],
  ])("mimeLabel(%s) = %s", (m, s) => expect(mimeLabel(m)).toBe(s));

  it("formats dates as YYYY-MM-DD and date-times with minutes", () => {
    expect(formatDate("2026-11-20T08:30:00Z")).toMatch(/^2026-11-2[01]$/);
    expect(formatDateTime("2026-11-20T08:30:00Z")).toMatch(/^2026-11-2[01] \d\d:\d\d$/);
    expect(formatDate(null)).toBe("—");
  });
});
