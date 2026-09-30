/** Deleting a document while its file is still uploading stops the upload at once (design: Deleting a row). */
import { afterEach, describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import BulkPanel from "../components/BulkPanel.vue";
import DocumentRow from "../components/DocumentRow.vue";
import { UploadCancelled, uploadToS3 } from "../lib/files";
import type { Perms, Row, TenantInfo } from "../types";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

class FakeXHR {
  static last: FakeXHR;
  upload = { onprogress: null as null | ((e: unknown) => void) };
  onload: null | (() => void) = null;
  onerror: null | (() => void) = null;
  onabort: null | (() => void) = null;
  status = 0;
  aborted = false;
  sent = false;
  constructor() { FakeXHR.last = this; }
  open() {}
  send() { this.sent = true; }
  abort() { this.aborted = true; this.onabort?.(); }
}

describe("uploadToS3 with an abort signal", () => {
  const form = { url: "http://s3", fields: { key: "k" } };
  const file = new File(["x"], "a.jpg", { type: "image/jpeg" });

  it("aborts the request and rejects with UploadCancelled, not a failure", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    const stop = new AbortController();
    const p = uploadToS3(form, file, () => undefined, stop.signal);
    expect(FakeXHR.last.sent).toBe(true);
    stop.abort();
    await expect(p).rejects.toBeInstanceOf(UploadCancelled);
    expect(FakeXHR.last.aborted).toBe(true);
  });

  it("sends nothing when the document was deleted before its upload began", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    FakeXHR.last = undefined as unknown as FakeXHR;
    const stop = new AbortController();
    stop.abort();
    await expect(uploadToS3(form, file, () => undefined, stop.signal)).rejects.toBeInstanceOf(UploadCancelled);
    expect(FakeXHR.last).toBeUndefined();
  });
});

const tenant = { key: "pahma", name: "PAHMA", filenameHint: "", filenamePattern: "^(?P<obj>[A-Za-z0-9.-]+)(?:_(?P<suffix>[A-Za-z0-9._-]+))?$",
  mediaTypes: [], languageDefault: "", authorityFields: {}, publish: { field: "approvedForWeb", header: "Restricted", invert: true },
  handling: [{ id: "link", label: "Link to existing object", object: "existing", id_rule: "object" }] } as unknown as TenantInfo;
const perms: Perms = { media: true, mediaUpdate: true, relations: true, objects: true, readObjects: true, authorities: true, groups: true };
const row = (p: Partial<Row> = {}): Row => ({ n: 1, file: "1-2345_large.tif", size: 10, contentType: "image/tiff", handling: "link",
  obj: "1-2345", objParsed: "1-2345", img: "1-2345_large", parseOk: true, idnum: "1-2345", date: "", restricted: false, type: [],
  creator: "", contributor: "", rightsHolder: "", description: "", copyright: "", include: true, upload: { s: "done" }, checks: [],
  result: null, ...p });

describe("the delete confirmations for documents still uploading", () => {
  it("a row says its upload is stopped", async () => {
    const w = mount({ components: { DocumentRow }, template: "<table><tbody><DocumentRow v-bind='p'/></tbody></table>",
      data: () => ({ p: { row: row({ upload: { s: "uploading", pct: 40 } }), tenant, perms, expanded: false, readonly: false, uploadingHere: true } }) });
    await w.find('button[aria-label="Delete document"]').trigger("click");
    expect(w.text()).toContain("Delete “1-2345_large.tif”? Its upload is stopped and anything already sent is removed; nothing in CollectionSpace is touched.");
  });

  it("a row whose upload is done still says its uploaded file is removed", async () => {
    const w = mount({ components: { DocumentRow }, template: "<table><tbody><DocumentRow v-bind='p'/></tbody></table>",
      data: () => ({ p: { row: row(), tenant, perms, expanded: false, readonly: false } }) });
    await w.find('button[aria-label="Delete document"]').trigger("click");
    expect(w.text()).toContain("Its uploaded file is removed; nothing in CollectionSpace is touched.");
  });

  it("Delete selected says which uploads are stopped", async () => {
    const rows = [row({ upload: { s: "uploading", pct: 10 } }), row({ n: 2, file: "3-1001_1.jpg" }), row({ n: 3, upload: { s: "pending" } })];
    const w = mount(BulkPanel, { props: { rows, selected: new Set([1, 2, 3]), tenant, perms, readonly: false, busy: false } });
    await w.findAll("button").find((b) => b.text() === "Delete selected")!.trigger("click");
    expect(w.text()).toContain("Their uploaded files are removed; nothing in CollectionSpace is touched. 2 uploads still in progress are stopped.");
    const one = mount(BulkPanel, { props: { rows: [row({ upload: { s: "uploading", pct: 10 } }), row({ n: 2 })], selected: new Set([1]), tenant, perms, readonly: false, busy: false } });
    await one.findAll("button").find((b) => b.text() === "Delete selected")!.trigger("click");
    expect(one.text()).toContain("Delete 1 selected document from this job permanently? Its upload is stopped and anything already sent is removed; nothing in CollectionSpace is touched.");
  });
});
