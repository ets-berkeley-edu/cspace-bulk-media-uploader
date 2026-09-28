import { describe, expect, it } from "vitest";
import { displayName, isRefName } from "../lib/refname";
import { exifDateFromBytes, formatBytes } from "../lib/files";
import { jobCounts } from "../lib/status";

describe("refName", () => {
  it("shows only the display name", () => {
    const ref = "urn:cspace:pahma.cspace.berkeley.edu:personauthorities:name(person):item:name(7475)'Leslie Freund'";
    expect(displayName(ref)).toBe("Leslie Freund");
    expect(isRefName(ref)).toBe(true);
    expect(displayName("")).toBe("");
    expect(displayName("plain")).toBe("plain");
  });
});

describe("files", () => {
  it("finds an EXIF date in file bytes", () => {
    const bytes = new TextEncoder().encode("xxExif\u0000\u0000..2025:06:14 11:22:33..");
    expect(exifDateFromBytes(bytes)).toBe("2025-06-14");
    expect(exifDateFromBytes(new Uint8Array([1, 2, 3]))).toBe("");
  });
  it("formats sizes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(3 * 1024 * 1024)).toBe("3.0 MB");
  });
});

describe("job counts", () => {
  const base = { n: 1, file: "a.jpg", size: 1, contentType: "", handling: "link", obj: "1", objParsed: "1", img: "", parseOk: true,
    idnum: "1", date: "", restricted: false, type: [], creator: "", contributor: "", rightsHolder: "", description: "", copyright: "",
    include: true, upload: { s: "done" as const }, checks: [], result: null };
  it("counts only rows with work left, and uploads still on their way", () => {
    const c = jobCounts([
      { ...base, checks: [{ level: "block", text: "x" }] },
      { ...base, n: 2, checks: [{ level: "warn", text: "y" }] },
      { ...base, n: 3, include: false, checks: [{ level: "block", text: "ignored" }] },
      { ...base, n: 4, upload: { s: "verifying" } },
      { ...base, n: 5, result: { state: "Done" } },
    ]);
    expect(c).toMatchObject({ total: 5, disabled: 1, work: 3, block: 1, warn: 1, uploading: 1, uploaded: 2 });
  });
});
