import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import DocumentRow from "../components/DocumentRow.vue";
import { portalOf } from "../lib/portal";
import type { Perms, Row, TenantInfo } from "../types";

const tenant = {
  key: "pahma", name: "PAHMA", filenameHint: "", filenamePattern: "^(?P<obj>.+)$", mediaTypes: [], languageDefault: "", authorityFields: {},
  publish: { field: "approvedForWeb", header: "Restricted", invert: true },
  handling: [{ id: "link", label: "Link to existing object", object: "existing", id_rule: "object" },
             { id: "mediaonly", label: "Media only", object: "none", id_rule: "image" }],
} as TenantInfo;
const perms: Perms = { media: true, relations: true, objects: true, readObjects: true, authorities: true, groups: true };
const row = (p: Partial<Row> = {}): Row => ({ n: 1, file: "12-2001.jpg", size: 1, contentType: "image/jpeg", handling: "link", obj: "12-2001",
  objParsed: "12-2001", img: "12-2001", parseOk: true, idnum: "12-2001", date: "", restricted: false, type: [], creator: "", contributor: "",
  rightsHolder: "", description: "", copyright: "", include: true, upload: { s: "done" }, checks: [], result: null, ...p });

describe("Public portal column (design: How the UI shows them)", () => {
  it("combines the object's sensitivity and the image's own setting", () => {
    expect(portalOf(row(), tenant).text).toBe("Public");
    expect(portalOf(row({ restricted: true }), tenant).text).toBe("Hidden: image restricted");
    const hr = row({ protected: { reason: "culturally sensitive object in the Human Remains department", hides: true } });
    expect(portalOf(hr, tenant)).toMatchObject({ text: "Hidden: object sensitive" });
    expect(portalOf({ ...hr, handling: "mediaonly" }, tenant).text).toBe("Public"); // not linked to that object
    expect(portalOf(row({ protected: { reason: "NAGPRA status on the object", hides: false } }), tenant).text).toBe("Public");
  });
});

describe("protected files in the document table", () => {
  const mountRow = (r: Row, preview?: string) => mount({ components: { DocumentRow }, template: "<table><tbody><DocumentRow v-bind='p'/></tbody></table>",
    data: () => ({ p: { row: r, tenant, perms, expanded: false, readonly: false, preview } }) });
  it("shows a Protected badge and, without the local preview, a locked placeholder", () => {
    const w = mountRow(row({ restricted: true, protected: { reason: "NAGPRA status on the object", hides: false } }));
    expect(w.text()).toContain("🔒 Protected");
    expect(w.find(".thumb.locked").exists()).toBe(true);
    expect(w.text()).toContain("Hidden: image restricted");
    const own = mountRow(row({ protected: { reason: "x", hides: false } }), "blob:preview");
    expect(own.find(".thumb img").exists()).toBe(true); // the person who added it sees their own preview
    expect(mountRow(row()).text()).not.toContain("Protected");
  });
});
