import { describe, expect, it } from "vitest";
import { displayName, isRefName } from "../lib/refname";
import { exifDateFromBytes, formatBytes } from "../lib/files";

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
