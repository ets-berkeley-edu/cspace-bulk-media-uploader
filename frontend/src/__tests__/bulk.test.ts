import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import BulkPanel from "../components/BulkPanel.vue";
import { applyAllTargets, bulkCheck, includeTargets } from "../lib/bulk";
import type { Perms, Row, TenantInfo } from "../types";

function row(p: Partial<Row> = {}): Row {
  return { n: 1, file: "15-1234_a.jpg", size: 10, contentType: "image/jpeg", handling: "link", obj: "15-1234", objParsed: "15-1234",
    img: "15-1234_a", parseOk: true, idnum: "15-1234", date: "", restricted: false, type: [], creator: "", contributor: "",
    rightsHolder: "", description: "", copyright: "", include: true, upload: { s: "done" }, checks: [], result: null, ...p };
}
const partial = (n: number) => row({ n, result: { state: "Partial", steps: { media: { s: "done", csid: "m" } } } });

describe("bulk rules (design: Bulk-change panel)", () => {
  it("asks for a change first, then allows it when every target can take it", () => {
    expect(bulkCheck([row()], {}, false)).toMatchObject({ ok: false, picked: false, why: "Choose a change first." });
    expect(bulkCheck([row(), row({ n: 2 })], { restricted: true }, false).ok).toBe(true);
  });

  it("greys out with a reason when any target can't take the change", () => {
    const v = bulkCheck([row(), partial(2), row({ n: 3, include: false })], { restricted: true }, false);
    expect(v.ok).toBe(false);
    expect(v.why).toContain("2 of the 3 selected documents can’t take this change");
    expect(v.why).toContain("1 already created its records in CollectionSpace");
    expect(v.why).toContain("1 is excluded from the job (include it first)");
  });

  it("treats a value a document already has as no change, even on a locked row", () => {
    expect(bulkCheck([row(), partial(2)], { restricted: false }, false))
      .toMatchObject({ ok: false, neutral: true, why: "Nothing to change: the selected documents already have these values." });
    expect(bulkCheck([row({ restricted: false }), partial(2)], { restricted: true }, false).ok).toBe(false);
    expect(bulkCheck([row({ restricted: true }), { ...partial(2), restricted: true }], { restricted: true }, false).neutral).toBe(true);
  });

  it("keeps the handling of a Failed row whose object step ran", () => {
    const failed = row({ result: { state: "Failed", steps: { media: { s: "failed" }, findObject: { s: "done", csid: "o" } } } });
    expect(bulkCheck([failed], { handling: "create" }, false).why).toContain("keeps its handling");
    expect(bulkCheck([failed], { restricted: true }, false).ok).toBe(true);
  });

  it("doesn't lock a Failed row that created only an Object: everything but its handling can change", () => {
    const objOnly = row({ n: 5, result: { state: "Failed", steps: { createObject: { s: "done", csid: "o1" }, media: { s: "failed", code: "x" } } } });
    expect(applyAllTargets([row(), objOnly]).map((r) => r.n)).toEqual([1, 5]);
    expect(bulkCheck([objOnly], { restricted: true, creator: "c" }, false).ok).toBe(true);
    expect(bulkCheck([row(), objOnly], { restricted: true }, true).ok).toBe(true);
    expect(bulkCheck([objOnly], { handling: "create" }, false).why).toContain("keeps its handling");
  });

  it("lets a Partial row take only what the rerun still needs (its group; its handling after object_exists)", () => {
    const p = row({ n: 6, group: false, result: { state: "Partial", steps: { media: { s: "done", csid: "m" } } } });
    expect(bulkCheck([p], { group: true }, false, new Set(["link"])).ok).toBe(true);
    expect(bulkCheck([p], { handling: "create" }, false).why).toContain("already created its records");
    const exists = row({ n: 7, handling: "create", result: { state: "Partial", steps: { media: { s: "done", csid: "m" },
      createObject: { s: "failed", code: "object_exists" } } } });
    expect(bulkCheck([exists], { handling: "link" }, false).ok).toBe(true);
    expect(bulkCheck([exists], { handling: "link", restricted: true }, false).ok).toBe(false);
  });

  it("Apply to all skips Done, Partial and disabled rows", () => {
    const rows = [row(), partial(2), row({ n: 3, include: false }), row({ n: 4, result: { state: "Done" } })];
    expect(applyAllTargets(rows).map((r) => r.n)).toEqual([1]);
    expect(includeTargets(rows, false).map((r) => r.n)).toEqual([1, 2]);
  });
});

const tenant: TenantInfo = {
  key: "pahma", name: "PAHMA", filenameHint: "hint", filenamePattern: "^(?P<obj>[A-Za-z0-9][A-Za-z0-9.-]*)(?:_(?P<suffix>[A-Za-z0-9._-]+))?$", mediaTypes: [{ value: "image", label: "image" }, { value: "slide", label: "slide" }], languageDefault: "", authorityFields: {},
  publish: { field: "approvedForWeb", header: "Restricted", invert: true },
  handling: [{ id: "link", label: "Link to existing object", object: "existing", id_rule: "object" },
             { id: "create", label: "Create new object + link", object: "create", id_rule: "object" }],
};
const perms: Perms = { media: true, relations: true, objects: false, readObjects: true, authorities: true, groups: true };

describe("BulkPanel", () => {
  it("applies to the selected rows only when every one can take the change", async () => {
    const rows = [row(), partial(2)];
    const w = mount(BulkPanel, { props: { rows, selected: new Set([1, 2]), tenant, perms, readonly: false, busy: false } });
    const [handling, publish] = w.findAll("select");
    expect(handling.find('option[value="create"]').attributes("disabled")).toBeDefined(); // no permission
    await publish.setValue("yes");
    const applySel = w.findAll("button").find((b) => b.text() === "Apply to selected")!;
    expect(applySel.attributes("disabled")).toBeDefined();
    expect(w.text()).toContain("already created its records");
    await w.setProps({ selected: new Set([1]) });
    expect(applySel.attributes("disabled")).toBeUndefined();
    await applySel.trigger("click");
    expect(w.emitted("apply")?.[0]).toEqual([[1], { restricted: true }]);
  });

  it("offers Apply to all when nothing is selected, and Exclude selected for selected rows", async () => {
    const w = mount(BulkPanel, { props: { rows: [row(), row({ n: 2 })], selected: new Set<number>(), tenant, perms, readonly: false, busy: false } });
    await w.findAll("select")[1].setValue("yes");
    const all = w.findAll("button").find((b) => b.text() === "Apply to all")!;
    expect(all.attributes("disabled")).toBeUndefined();
    await all.trigger("click");
    expect(w.emitted("apply")?.[0]).toEqual([[1, 2], { restricted: true }]);
    await w.setProps({ selected: new Set([2]) });
    await w.findAll("button").find((b) => b.text() === "Exclude selected")!.trigger("click");
    expect(w.emitted("include")?.[0]).toEqual([[2], false]);
  });
});

describe("bulk repeating fields", () => {
  it("replaces a document's media types with the chosen one", async () => {
    const rows = [row({ type: ["image", "slide"] }), row({ n: 2, type: ["slide"] })];
    expect(bulkCheck(rows, { type: ["slide"] }, false).ok).toBe(true);   // row 1 changes
    expect(bulkCheck([rows[1]], { type: ["slide"] }, false).neutral).toBe(true); // already exactly that
    const w = mount(BulkPanel, { props: { rows, selected: new Set([1, 2]), tenant, perms, readonly: false, busy: false } });
    await w.find('select[aria-label="Media type for selected"]').setValue("slide");
    await w.findAll("button").find((b) => b.text() === "Apply to selected")!.trigger("click");
    expect(w.emitted("apply")?.[0]).toEqual([[1, 2], { type: ["slide"] }]);
  });
});

describe("bulk Group (design: Groups)", () => {
  const linking = new Set(["link", "create"]);
  const mk = (n: number, p: Partial<Row> = {}) => ({ n, file: `${n}.jpg`, handling: "link", include: true, group: true, result: null, ...p }) as unknown as Row;
  it("can't put documents without an object into the group, and never takes an object out once added", () => {
    expect(bulkCheck([mk(1), mk(2, { handling: "mediaonly", group: false })], { group: true }, false, linking).why)
      .toContain("1 of the 2 selected documents can’t take this change: 1 isn't linked to an object, so it can't join the group");
    const added = mk(3, { result: { state: "Partial", steps: { media: { s: "done", csid: "m" }, addToGroup: { s: "done", csid: "g" } } } });
    expect(bulkCheck([added], { group: false }, false, linking).why).toContain("already has its object in the group");
    expect(bulkCheck([mk(4)], { group: false }, false, linking).ok).toBe(true);
  });
});
