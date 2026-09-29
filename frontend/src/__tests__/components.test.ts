import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import AuthorityInput from "../components/AuthorityInput.vue";
import DocumentRow from "../components/DocumentRow.vue";
import type { Perms, Row, TenantInfo } from "../types";

const REF = "urn:cspace:pahma.cspace.berkeley.edu:personauthorities:name(person):item:name(7475)'Leslie Freund'";

afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

describe("AuthorityInput", () => {
  it("searches after 3 characters and emits the refName of the chosen term", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ terms: [{ refName: REF, displayName: "Leslie Freund", source: "person" }] }),
      { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    const w = mount(AuthorityInput, { props: { modelValue: "", field: "creator", label: "Creator" } });
    const input = w.find("input");
    await input.setValue("fr");
    expect(w.text()).toContain("3+ characters");
    await input.setValue("freu");
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    expect(fetchMock).toHaveBeenCalledWith("/api/authorities?field=creator&q=freu", expect.anything());
    await w.find(".ac-item").trigger("mousedown");
    expect(w.emitted("update:modelValue")?.[0]).toEqual([REF]);
  });

  it("shows only the display name of the stored refName, and never saves free text", async () => {
    vi.useFakeTimers();
    const w = mount(AuthorityInput, { props: { modelValue: REF, field: "creator", label: "Creator" } });
    const input = w.find("input");
    expect((input.element as HTMLInputElement).value).toBe("Leslie Freund");
    await input.setValue("Somebody New");
    await input.trigger("blur");
    await vi.advanceTimersByTimeAsync(200);
    expect(w.emitted("update:modelValue")).toBeUndefined();
    expect((input.element as HTMLInputElement).value).toBe("Leslie Freund");
  });
});

const tenant: TenantInfo = {
  key: "pahma", name: "PAHMA", filenameHint: "hint", filenamePattern: "^(?P<obj>[A-Za-z0-9][A-Za-z0-9.-]*?)(?:_(?P<suffix>[A-Za-z0-9-]+))?$", mediaTypes: [{ value: "image", label: "image" }, { value: "slide", label: "slide" }], languageDefault: "", authorityFields: {},
  publish: { field: "approvedForWeb", header: "Restricted", invert: true },
  handling: [{ id: "link", label: "Link to existing object", object: "existing", id_rule: "object" },
             { id: "create", label: "Create new object + link", object: "create", id_rule: "object" }],
};
const perms: Perms = { media: true, relations: true, objects: true, readObjects: true, authorities: true };
function row(p: Partial<Row> = {}): Row {
  return { n: 1, file: "15-1234_a.jpg", size: 10, contentType: "image/jpeg", handling: "link", obj: "15-1234", objParsed: "15-1234",
    img: "15-1234_a", parseOk: true, idnum: "15-1234", date: "", restricted: false, type: [], creator: "", contributor: "",
    rightsHolder: "", description: "", copyright: "", include: true, upload: { s: "done" }, checks: [], result: null, ...p };
}

describe("DocumentRow", () => {
  it("shows Needs fixing for blocking checks and locks rows that created records", () => {
    let w = mount({ components: { DocumentRow }, template: "<table><tbody><DocumentRow v-bind='p'/></tbody></table>",
      data: () => ({ p: { row: row({ checks: [{ level: "block", text: "No object" }] }), tenant, perms, expanded: false, readonly: false } }) });
    expect(w.text()).toContain("Needs fixing");
    w = mount({ components: { DocumentRow }, template: "<table><tbody><DocumentRow v-bind='p'/></tbody></table>",
      data: () => ({ p: { row: row({ result: { state: "Partial", steps: { media: { s: "done", csid: "m1" } } } }), tenant, perms, expanded: true, readonly: false } }) });
    expect(w.text()).toContain("already created records");
    expect(w.find("select").attributes("disabled")).toBeDefined();
  });
});

function mountRow(p: Record<string, unknown>) {
  return mount({ components: { DocumentRow }, template: "<table><tbody><DocumentRow v-bind='p'/></tbody></table>",
    data: () => ({ p: { row: row(), tenant, perms, expanded: true, readonly: false, ...p } }) });
}

describe("DocumentRow checks", () => {
  it("labels checks Must fix and Warning, and flags warnings in the Status column", () => {
    const w = mountRow({ row: row({ checks: [{ level: "warn", text: "A Media record with ID 15-1234 already exists" }],
      lookups: { object: { value: "15-1234", csids: ["c1"], at: 0 } } }) });
    expect(w.text()).toContain("Warning: A Media record");
    expect(w.text()).toContain("Found — will link");
    expect(w.find('[title="This document has warnings"]').exists()).toBe(true);
    expect(mountRow({ row: row({ checks: [{ level: "block", text: "No object" }] }) }).text()).toContain("Must fix: No object");
  });

  it("disables handling options the user has no permission for", () => {
    const w = mountRow({ perms: { ...perms, objects: false } });
    const create = w.findAll("option").find((o) => o.attributes("value") === "create")!;
    expect(create.attributes("disabled")).toBeDefined();
    expect(create.text()).toContain("(no permission)");
  });

  it("shows upload progress, then Verifying, before the checks", () => {
    expect(mountRow({ row: row({ upload: { s: "uploading", pct: 40 } }) }).text()).toContain("Uploading 40%");
    expect(mountRow({ row: row({ upload: { s: "verifying" } }) }).text()).toContain("Verifying…");
    expect(mountRow({ row: row(), checking: true }).text()).toContain("Checking…");
  });
});

import RepeatingSelect from "../components/RepeatingSelect.vue";

describe("RepeatingSelect (design: repeating media type and language)", () => {
  const options = [{ value: "still_image", label: "still image" }, { value: "document", label: "document" }];

  it("shows labels, stores values, and adds or removes values", async () => {
    const w = mount(RepeatingSelect, { props: { modelValue: ["still_image"], options, label: "Media type", word: "type" } });
    expect(w.find("select option:checked").text()).toBe("still image");
    await w.find("button.link").trigger("click"); // + Add an additional type
    const selects = w.findAll("select");
    expect(selects).toHaveLength(2);
    expect(selects[1].find('option[value="still_image"]').attributes("disabled")).toBeDefined(); // no repeats
    await selects[1].setValue("document");
    expect(w.emitted("update:modelValue")?.at(-1)).toEqual([["still_image", "document"]]);
    await w.setProps({ modelValue: ["still_image", "document"] });
    await w.findAll("button.x-btn")[0].trigger("click");
    expect(w.emitted("update:modelValue")?.at(-1)).toEqual([["document"]]);
  });

  it("keeps a stored value that isn't among the options, showing its display name", () => {
    const ref = "urn:cspace:pahma.cspace.berkeley.edu:vocabularies:name(languages):item:name(eng)'English'";
    const w = mount(RepeatingSelect, { props: { modelValue: [ref], options: [], label: "Language", word: "language" } });
    expect(w.find("select option:checked").text()).toBe("English");
  });
});
