import { describe, expect, it } from "vitest";
import { displayName, isRefName } from "../lib/refname";
import { formatBytes, mapLimit } from "../lib/files";
import { jobCounts, rowStatus } from "../lib/status";
import type { TenantInfo } from "../types";

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
  it("maps a few at a time, keeping the order", async () => {
    let running = 0, most = 0;
    const out = await mapLimit([5, 1, 3, 2], 2, async (x) => {
      running++; most = Math.max(most, running);
      await new Promise((r) => setTimeout(r, x));
      running--;
      return x * 10;
    });
    expect(out).toEqual([50, 10, 30, 20]);
    expect(most).toBe(2);
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

describe("status by object behavior", () => {
  const tenant = { handling: [
    { id: "link", label: "Link to existing object", object: "existing", id_rule: "object" },
    { id: "linkorcreate", label: "Link to object (create if missing)", object: "either", id_rule: "object" },
    { id: "create", label: "Create new object + link", object: "create", id_rule: "object" },
  ] } as unknown as TenantInfo;
  const row = (handling: string, csids: string[] | null) => ({ n: 1, file: "1-2_a.jpg", size: 1, contentType: "", handling, obj: "1-2",
    objParsed: "1-2", img: "", parseOk: true, idnum: "1-2", date: "", restricted: false, type: [], creator: "", contributor: "",
    rightsHolder: "", description: "", copyright: "", include: true, upload: { s: "done" as const }, checks: [], result: null,
    lookups: csids ? { object: { value: "1-2", csids, at: 0 } } : undefined });
  it("says whether the object will be found or created", () => {
    expect(rowStatus(row("linkorcreate", ["o1"]), tenant).text).toBe("Found — will link");
    expect(rowStatus(row("linkorcreate", []), tenant).text).toBe("Will create object");
    expect(rowStatus(row("create", []), tenant).text).toBe("Will create object");
    expect(rowStatus(row("link", ["o1"]), tenant).text).toBe("Found — will link");
    expect(rowStatus(row("create", null), tenant).text).toBe("Not checked yet");
  });
});
