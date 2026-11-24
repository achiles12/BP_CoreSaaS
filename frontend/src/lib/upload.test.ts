// Upload helper (B10 D5; review focus 1).
import { beforeEach, describe, expect, it, vi } from "vitest";

import { makeMe } from "@/test/fixtures";

import { uploadFile, validateFile } from "./upload";

const presign = vi.fn();
const confirm = vi.fn();
vi.mock("@/api/generated/endpoints/files/files", () => ({
  presignUpload: (...a: unknown[]) => presign(...a),
  confirmUpload: (...a: unknown[]) => confirm(...a),
}));

function file(name: string, type: string, size: number): File {
  const f = new File([new Uint8Array(Math.min(size, 16))], name, { type });
  Object.defineProperty(f, "size", { value: size });
  return f;
}

// Minimal XHR double: records the request, lets the test drive events.
class FakeXHR {
  static last: FakeXHR;
  method = "";
  url = "";
  headers: Record<string, string> = {};
  body: unknown;
  status = 0;
  upload: {
    onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null;
  } = {
    onprogress: null,
  };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  aborted = false;
  constructor() {
    FakeXHR.last = this;
  }
  open(m: string, u: string) {
    this.method = m;
    this.url = u;
  }
  setRequestHeader(k: string, v: string) {
    this.headers[k] = v;
  }
  send(b: unknown) {
    this.body = b;
  }
  abort() {
    this.aborted = true;
    this.onabort?.();
  }
}

describe("validateFile", () => {
  it.each([
    [file("a.pdf", "application/pdf", 10), null],
    [file("e.txt", "text/plain", 0), "is empty"],
    [file("big.pdf", "application/pdf", 51 * 1024 * 1024), "larger than 50 MB"],
    [file("notes.md", "", 10), "type is not allowed"],
    [file("x.exe", "application/x-msdownload", 10), "type is not allowed"],
  ])("%s -> %s", (f, msg) => {
    const out = validateFile(f as File, 50);
    if (msg === null) expect(out).toBeNull();
    else expect(out).toContain(msg);
  });
});

describe("uploadFile", () => {
  const me = makeMe();
  beforeEach(() => {
    presign.mockReset().mockResolvedValue({
      file_id: "f1",
      upload_url: "http://rustfs:9000/b/k?sig",
      headers: { "Content-Type": "application/pdf" },
      expires_in: 900,
    });
    confirm.mockReset().mockResolvedValue({ id: "f1", name: "a.pdf", status: "active" });
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
  });

  it("presign -> PUT with the signed headers -> confirm, reporting progress", async () => {
    const progress = vi.fn();
    const f = file("a.pdf", "application/pdf", 1000);
    const p = uploadFile(f, { me, onProgress: progress });
    await vi.waitFor(() => expect(FakeXHR.last?.method).toBe("PUT"));
    expect(presign).toHaveBeenCalledWith(
      { name: "a.pdf", mime_type: "application/pdf", size_bytes: 1000 },
      expect.objectContaining({ headers: { "X-Tenant": "acme" } }),
    );
    const x = FakeXHR.last;
    expect(x.url).toBe("http://rustfs:9000/b/k?sig");
    expect(x.headers).toEqual({ "Content-Type": "application/pdf" });
    expect(x.body).toBe(f);
    x.upload.onprogress?.({ lengthComputable: true, loaded: 500, total: 1000 });
    x.status = 200;
    x.onload?.();
    await expect(p).resolves.toMatchObject({ id: "f1" });
    expect(progress).toHaveBeenCalledWith(50);
    expect(progress).toHaveBeenLastCalledWith(100);
    expect(confirm).toHaveBeenCalledWith("f1", expect.anything());
  });

  it("a failed PUT rejects and never confirms", async () => {
    const p = uploadFile(file("a.pdf", "application/pdf", 10), { me, onProgress: () => {} });
    await vi.waitFor(() => expect(FakeXHR.last?.method).toBe("PUT"));
    FakeXHR.last.status = 403;
    FakeXHR.last.onload?.();
    await expect(p).rejects.toThrow(/storage refused/i);
    expect(confirm).not.toHaveBeenCalled();
  });

  it("abort cancels the PUT", async () => {
    const ctl = new AbortController();
    const p = uploadFile(file("a.pdf", "application/pdf", 10), {
      me,
      onProgress: () => {},
      signal: ctl.signal,
    });
    await vi.waitFor(() => expect(FakeXHR.last?.method).toBe("PUT"));
    ctl.abort();
    await expect(p).rejects.toThrow(/cancelled/i);
    expect(FakeXHR.last.aborted).toBe(true);
    expect(confirm).not.toHaveBeenCalled();
  });
});
