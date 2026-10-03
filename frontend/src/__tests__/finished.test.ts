import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import DocumentRow from "../components/DocumentRow.vue";
import ErrorBox from "../components/ErrorBox.vue";
import FinishedJobs from "../components/FinishedJobs.vue";
import JobResults from "../components/JobResults.vue";
import {
  canReplaceFile, countsText, createdSomething, createdText, failures, fixFields, importantRows, needsFix, resultCounts, resultState,
  stepList, stepNote,
} from "../lib/results";
import type { Failure, Job, Perms, Row, Run, TenantInfo } from "../types";

afterEach(() => { vi.restoreAllMocks(); });

const F = (title: string, needs_fix: boolean): Failure => ({ title, needs_fix, level: "row", explain: `${title} explained.`, fix: `Do this for ${title}.` });
const CATALOG: Record<string, Failure> = {
  upload_too_large: F("File too large for CollectionSpace", true), object_gone: F("Object not found when the job ran", true),
  no_permission: F("Permission denied", true), server_error: F("CollectionSpace error on this document", false),
  auth: F("Sign-in failed", false), cancelled: F("Run cancelled", false), media_rejected: F("CollectionSpace rejected the Media record", true),
  unknown: F("Unexpected problem", false), value_missing: F("A value no longer exists in CollectionSpace", true),
  term_renamed: { ...F("A name changed in CollectionSpace", false), level: "notice" },
};
failures.value = CATALOG;

const tenant: TenantInfo = {
  key: "pahma", name: "PAHMA", filenameHint: "hint", filenamePattern: "^(?P<obj>[A-Za-z0-9][A-Za-z0-9.-]*)(?:_(?P<suffix>[A-Za-z0-9._-]+))?$",
  mediaTypes: [], languageDefault: "", authorityFields: {}, publish: { field: "approvedForWeb", header: "Restricted", invert: true },
  handling: [{ id: "link", label: "Link to existing object", object: "existing", id_rule: "object" }],
};
const perms: Perms = { media: true, relations: true, objects: true, readObjects: true, authorities: true, groups: true };

function row(p: Partial<Row> = {}): Row {
  return { n: 1, file: "15-1234_a.jpg", size: 10, contentType: "image/jpeg", handling: "link", obj: "15-1234", objParsed: "15-1234",
    img: "15-1234_a", parseOk: true, idnum: "15-1234", date: "", restricted: false, type: [], creator: "", contributor: "",
    rightsHolder: "", description: "", copyright: "", include: true, upload: { s: "done" }, checks: [], result: null, ...p };
}
const done = (n: number, file: string) => row({ n, file, result: { state: "Done", run: 1, steps: {
  media: { s: "done", csid: `m${n}`, run: 1 }, findObject: { s: "done", csid: "o1", run: 1, found: true }, upload: { s: "done", csid: `b${n}`, run: 1 },
  relMediaObject: { s: "done", csid: `r${n}a`, run: 1 }, relObjectMedia: { s: "done", csid: `r${n}b`, run: 1 } } } });
const tooLarge = row({ n: 2, file: "1-2345.jpg", result: { state: "Partial", run: 1, error: { code: "upload_too_large", detail: "PUT media/m2/blob returned 413", step: "upload" },
  steps: { media: { s: "done", csid: "m2", run: 1 }, findObject: { s: "done", csid: "o2", found: true, run: 1 },
    upload: { s: "failed", code: "upload_too_large", detail: "PUT media/m2/blob returned 413" },
    relMediaObject: { s: "done", csid: "r2a", run: 1 }, relObjectMedia: { s: "done", csid: "r2b", run: 1 } } } });
const gone = row({ n: 3, file: "15-1240_1.jpg", obj: "15-1240", result: { state: "Partial", run: 1, error: { code: "object_gone", detail: "no object", step: "findObject" },
  steps: { media: { s: "done", csid: "m3" }, findObject: { s: "failed", code: "object_gone", obj: "15-1240" }, upload: { s: "done", csid: "b3" },
    relMediaObject: { s: "skipped", after: "findObject" }, relObjectMedia: { s: "skipped", after: "findObject" } } } });
const notRun = row({ n: 4, file: "12-5678_1.jpg" });
// the worker's check just before creating the records found a deleted creator: nothing was created
const valueMissing = row({ n: 7, file: "16-4711_1.jpg", result: { state: "Failed", run: 1,
  error: { code: "value_missing", detail: "Creator “Leslie Freund”: deleted in CollectionSpace", step: "values" },
  steps: { media: { s: "skipped", after: "values" }, findObject: { s: "skipped", after: "values" }, upload: { s: "skipped", after: "media" },
    relMediaObject: { s: "skipped", after: "media" }, relObjectMedia: { s: "skipped", after: "media" },
    values: { s: "failed", code: "value_missing", detail: "Creator “Leslie Freund”: deleted in CollectionSpace", run: 1 } } } });
const disabled = row({ n: 5, file: "9-9999.jpg", include: false, disabledBy: "jdoe", disabledAt: 1 });

describe("results helpers (design: Finished jobs and error messages)", () => {
  it("counts documents by result, excluded ones apart", () => {
    const rows = [done(1, "a.jpg"), tooLarge, gone, notRun, disabled];
    expect(resultCounts(rows)).toEqual({ done: 1, partial: 2, failed: 0, notStarted: 1, disabled: 1 });
    expect(countsText(resultCounts(rows))).toBe("1 done · 2 partial · 1 not started · 1 excluded");
    expect(resultState(disabled)).toBe("Excluded");
    expect(importantRows(rows, 3).map((r) => r.n)).toEqual([2, 3, 4]);
  });

  it("reads Fix and reschedule only when something must change first", () => {
    const job = { id: "j", status: "NeedsAttention", code: "" } as Job;
    const serverErr = row({ n: 6, result: { state: "Partial", error: { code: "server_error", detail: "", step: "upload" },
      steps: { media: { s: "done", csid: "m6" }, upload: { s: "failed", code: "server_error" } } } });
    expect(needsFix(job, [serverErr], 0, CATALOG)).toBe(false);
    expect(needsFix(job, [serverErr], 1, CATALOG)).toBe(true); // a document fails a blocking check now
    expect(needsFix(job, [serverErr, tooLarge], 0, CATALOG)).toBe(true);
    expect(needsFix(job, [serverErr, { ...tooLarge, include: false }], 0, CATALOG)).toBe(false); // disabled documents don't count
    expect(needsFix({ ...job, status: "Failed", code: "auth" } as Job, [notRun], 0, CATALOG)).toBe(false);
  });

  it("knows what a document whose Media record exists may still change", () => {
    expect(fixFields(tooLarge)).toEqual({ obj: false, skipLink: false, handling: false });
    expect(canReplaceFile(tooLarge)).toBe(true);
    expect(fixFields(gone)).toEqual({ obj: true, skipLink: true, handling: false });
    expect(fixFields({ ...gone, skipLink: true })).toEqual({ obj: false, skipLink: true, handling: false });
    // "Create new object + link" found its object already there: the handling may switch to linking (option A)
    const exists = { ...gone, handling: "create", result: { state: "Partial" as const, steps: {
      media: { s: "done" as const, csid: "m1" }, createObject: { s: "failed" as const, code: "object_exists" },
      upload: { s: "done" as const, csid: "b1" }, relMediaObject: { s: "skipped" as const, after: "createObject" },
      relObjectMedia: { s: "skipped" as const, after: "createObject" } } } };
    expect(fixFields(exists)).toEqual({ obj: true, skipLink: true, handling: true });
    expect(canReplaceFile(gone)).toBe(false);
    // the document's check found the staged file gone before anything was created: a replacement is the fix
    const fileGone = { ...valueMissing, result: { ...valueMissing.result!, steps: { ...valueMissing.result!.steps!,
      values: { s: "failed" as const, code: "file_missing", run: 1 } } } };
    expect(canReplaceFile(fileGone)).toBe(true);
    expect(canReplaceFile({ ...fileGone, include: false })).toBe(false);
    expect(canReplaceFile(valueMissing)).toBe(false);
    expect(createdSomething(tooLarge)).toBe(true);
    expect(createdSomething(notRun)).toBe(false);
    // the worker stopped on it: a create may have reached CollectionSpace unrecorded, so it counts as having created something
    expect(createdSomething({ ...notRun, result: { state: "Not started" as const, steps: {}, interrupted: 1 } })).toBe(true);
    expect(createdText({ media: 2, files: 1, objects: 1, relations: 2, unfinished: 1 })).toBe("2 Media records (1 with its file), 1 Object and 2 Relations");
    // Zero counts are left out (design: Deleting a job)
    expect(createdText({ media: 0, files: 0, objects: 1, relations: 0, unfinished: 0 })).toBe("1 Object");
    expect(createdText({ media: 1, files: 0, objects: 0, relations: 0, groups: 1, unfinished: 1 })).toBe("1 Media record and the job's group");
  });
});

describe("a value that no longer exists when the job ran (value_missing)", () => {
  it("lists the value check first and names it in the skipped steps", () => {
    expect(stepList(valueMissing).map((s) => s.label)).toEqual(["Check the document in CollectionSpace", "Create Media record", "Find object",
      "Upload file (creates the Blob)", "Relate Media → Object", "Relate Object → Media"]);
    expect(stepNote("media", valueMissing.result!.steps!.media!)).toBe("skipped: needs check the document in CollectionSpace");
    expect(stepNote("upload", valueMissing.result!.steps!.upload!)).toBe("skipped: needs create Media record");
  });

  it("is a failed document that created nothing and needs a fix", () => {
    expect(resultState(valueMissing)).toBe("Failed");
    expect(resultCounts([valueMissing, done(1, "a.jpg")])).toEqual({ done: 1, partial: 0, failed: 1, notStarted: 0, disabled: 0 });
    expect(createdSomething(valueMissing)).toBe(false); // it can be deleted
    expect(fixFields(valueMissing)).toEqual({ obj: false, skipLink: false, handling: false });
    expect(needsFix({ id: "j", status: "NeedsAttention", code: "" } as Job, [valueMissing], 0, CATALOG)).toBe(true);
  });

  it("shows the failure and a renamed term's notice in the results", () => {
    const renamed = { ...done(8, "3-1001.jpg") };
    renamed.result = { ...renamed.result!, notices: [{ code: "term_renamed", detail: "Creator “Leslie Freund” → “Leslie F. Freund”" }] };
    const job = { id: "j", name: "batch", status: "NeedsAttention", run: 1, code: "" } as Job;
    const w = mount(JobResults, { props: { job, rows: [valueMissing, renamed], runs: [], tenant } });
    const [bad, good] = w.findAll("tbody tr").map((r) => r.text());
    expect(bad).toContain("✗ Check the document in CollectionSpace");
    expect(bad).toContain("A value no longer exists in CollectionSpace.");
    expect(good).toContain("A name changed in CollectionSpace.");
  });
});

describe("ErrorBox", () => {
  it("shows the title, explanation and what to do, with the technical detail on request", async () => {
    const w = mount(ErrorBox, { props: { code: "upload_too_large", detail: "PUT media/m2/blob returned 413" } });
    expect(w.text()).toContain("File too large for CollectionSpace.");
    expect(w.text()).toContain("What to do: Do this for File too large");
    expect(w.text()).not.toContain("413");
    await w.find("button").trigger("click");
    expect(w.text()).toContain("returned 413");
    expect(mount(ErrorBox, { props: { code: "something_new" } }).text()).toContain("Unexpected problem");
  });
});

describe("JobResults", () => {
  const job = { id: "j", name: "batch", status: "NeedsAttention", run: 2, runBy: "jdoe", finishedAt: 1, code: "" } as Job;
  const runs: Run[] = [
    { run: 1, outcome: "Failed", code: "auth", scheduledBy: "agarcia", counts: { done: 0, partial: 0, failed: 0, notStarted: 5, disabled: 0 } },
    { run: 2, outcome: "NeedsAttention", scheduledBy: "jdoe", disabledBefore: [{ n: 5, file: "9-9999.jpg", by: "jdoe" }] },
  ];
  it("lists runs newest first and filters documents by result", async () => {
    const w = mount(JobResults, { props: { job, rows: [done(1, "a.jpg"), tooLarge, gone, notRun, disabled], runs, tenant } });
    const history = w.findAll(".runs .msg").map((m) => m.text());
    expect(history[0]).toContain("Run 2: Needs attention");
    expect(history[0]).toContain("9-9999.jpg excluded by jdoe");
    expect(history[1]).toContain("Run 1: Failed — Sign-in failed");
    expect(w.findAll("tbody tr")).toHaveLength(5);
    await w.find("select").setValue("partial");
    expect(w.findAll("tbody tr").map((r) => r.text()).join()).toContain("1-2345.jpg");
    expect(w.findAll("tbody tr")).toHaveLength(2);
    await w.find("select").setValue("excluded");
    expect(w.text()).toContain("Excluded by jdoe");
  });

  it("every job-level failure offers its technical detail (design: technical detail shown on request)", async () => {
    const cases: [string, string][] = [
      ["auth", "Document 1, step media: POST media returned 401 Unauthorized"],
      ["unknown", "Unexpected ClientError ProvisionedThroughputExceededException in UpdateItem at document 3, step upload"],
      ["cancelled", "Cancel requested by agarcia, 2026-09-30 08:02 Pacific time"],
    ];
    for (const [code, codeDetail] of cases) {
      const w = mount(JobResults, { props: { job: { ...job, status: "Failed", code, codeDetail }, rows: [notRun], runs: [], tenant } });
      const box = w.findComponent(ErrorBox);
      expect(box.props("detail")).toBe(codeDetail);
      await box.find("button.link").trigger("click");
      expect(box.text()).toContain(`${code} · ${codeDetail}`);
    }
    // a job that ended before codeDetail was stored still shows who cancelled it
    const old = mount(JobResults, { props: { job: { ...job, code: "cancelled", cancelledBy: "jdoe" }, rows: [notRun], runs: [], tenant } });
    expect(old.findComponent(ErrorBox).props("detail")).toBe("Cancel requested by jdoe");
  });
});

describe("DocumentRow after a run", () => {
  const mountRow = (r: Row) => mount({ components: { DocumentRow }, template: "<table><tbody><DocumentRow v-bind='p'/></tbody></table>",
    data: () => ({ p: { row: r, tenant, perms, expanded: true, readonly: false } }) });

  it("a Partial document offers only what the rerun needs: a replacement file", () => {
    const w = mountRow(tooLarge);
    expect(w.text()).toContain("Media record was already created in CollectionSpace (m2)");
    expect(w.text()).toContain("File too large for CollectionSpace");
    expect(w.findAll("button").some((b) => b.text() === "Replace file…")).toBe(true);
    expect(w.find('input[aria-label="Object number"]').exists()).toBe(false);
    expect(w.find('textarea').exists()).toBe(false);
    expect(w.text()).toContain("can't be deleted from the job");
  });

  it("an object not found at run time: a new object number or stop linking", async () => {
    const w = mountRow(gone);
    expect((w.find('input[aria-label="Object number"]').element as HTMLInputElement).disabled).toBe(false);
    const stop = w.findAll("label").find((l) => l.text().includes("Stop linking"))!;
    await stop.find("input").setValue(true);
    expect(w.findComponent(DocumentRow).emitted("edit")?.[0]).toEqual([{ skipLink: true }]);
  });

  it("a Failed document whose object step ran keeps its object number and handling", () => {
    const failed = row({ n: 7, result: { state: "Failed", error: { code: "media_rejected", detail: "POST media returned 400", step: "media" },
      steps: { media: { s: "failed", code: "media_rejected" }, createObject: { s: "done", csid: "o7" }, upload: { s: "skipped", after: "media" } } } });
    const w = mountRow(failed);
    expect(w.text()).toContain("CollectionSpace rejected the Media record");
    expect((w.find('input[aria-label="Object number"]').element as HTMLInputElement).disabled).toBe(true);
    expect((w.find('select[aria-label="Handling"]').element as HTMLSelectElement).disabled).toBe(true);
    expect(w.find("textarea").exists()).toBe(true); // other fields can change
  });
});

describe("Finished jobs tab", () => {
  const jobs = [
    { id: "a", name: "needs a fix", status: "NeedsAttention", run: 1, rowCount: 2, finishedAt: 20, runBy: "jdoe", counts: { done: 1, partial: 1, failed: 0, notStarted: 0, disabled: 0 } },
    { id: "b", name: "sign-in failed", status: "Failed", code: "auth", run: 1, rowCount: 1, finishedAt: 10, counts: { done: 0, partial: 0, failed: 0, notStarted: 1, disabled: 0 } },
    { id: "c", name: "all done", status: "Completed", run: 1, rowCount: 1, finishedAt: 5, expiresAt: 2e9, counts: { done: 1, partial: 0, failed: 0, notStarted: 0, disabled: 0 } },
    { id: "d", name: "a draft", status: "Draft", run: 0, rowCount: 1 },
  ];
  let calls: string[] = [];
  function mockApi() {
    calls = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${url}`);
      let body: unknown = {};
      if (url === "/api/jobs") body = { jobs };
      else if (url === "/api/failures") body = { failures: CATALOG };
      else if (url.endsWith("/check")) body = { rows: [], counts: { block: 0, warn: 0 } };
      else if (url === "/api/jobs/a") body = { job: jobs[0], rows: [done(1, "a.jpg"), tooLarge], runs: [], created: { media: 2, files: 1, objects: 0, relations: 4, unfinished: 1 } };
      else if (url === "/api/jobs/b") body = { job: jobs[1], rows: [notRun], runs: [], created: { media: 0, files: 0, objects: 0, relations: 0, unfinished: 0 } };
      else if (url.endsWith("/fix")) body = { ...jobs[0], status: "Draft" };
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }));
    }));
  }
  const rowOf = (w: ReturnType<typeof mount>, name: string) => w.findAll("tbody tr").find((r) => r.text().includes(name))!;

  it("shows outcomes newest first with Fix and reschedule or Reschedule", async () => {
    mockApi();
    const w = mount(FinishedJobs, { props: { tenant } });
    await flushPromises();
    const text = w.findAll("tbody tr").map((r) => r.text());
    expect(text[0]).toContain("needs a fix");
    expect(text.join()).not.toContain("a draft");
    expect(rowOf(w, "needs a fix").text()).toContain("1 done · 1 partial");
    expect(rowOf(w, "needs a fix").text()).toContain("Fix and reschedule");
    expect(rowOf(w, "sign-in failed").text()).toContain("Sign-in failed");
    expect(rowOf(w, "sign-in failed").text()).toContain("Reschedule");
    expect(rowOf(w, "sign-in failed").text()).not.toContain("Fix and reschedule");
    expect(rowOf(w, "all done").text()).toContain("Removed");
    w.unmount();
  });

  it("warns what stays in CollectionSpace before deleting, and Fix moves the job to Drafts", async () => {
    mockApi();
    const w = mount(FinishedJobs, { props: { tenant } });
    await flushPromises();
    await rowOf(w, "needs a fix").findAll("button").find((b) => b.text() === "Delete")!.trigger("click");
    await flushPromises();
    expect(w.text()).toContain("Its runs created 2 Media records (1 with its file) and 4 Relations, including 1 unfinished document");
    expect(w.text()).toContain("They stay in CollectionSpace");
    await w.findAll("button").find((b) => b.text() === "Cancel")!.trigger("click");
    await rowOf(w, "needs a fix").findAll("button").find((b) => b.text() === "Fix and reschedule")!.trigger("click");
    await flushPromises();
    expect(calls).toContain("POST /api/jobs/a/fix");
    expect(w.emitted("open")?.[0]).toEqual(["a"]);
    w.unmount();
  });
});
