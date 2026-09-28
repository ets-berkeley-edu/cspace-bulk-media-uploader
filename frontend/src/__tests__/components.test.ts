import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import AuthorityInput from "../components/AuthorityInput.vue";
import DocumentRow from "../components/DocumentRow.vue";
import type { Row, TenantInfo } from "../types";

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
  key: "pahma", name: "PAHMA", filenameHint: "hint", mediaTypes: ["image"], languageDefault: "", authorityFields: {},
  publish: { field: "approvedForWeb", header: "Restricted", invert: true },
  handling: [{ id: "link", label: "Link to existing object", object: "existing", id_rule: "object" }],
};
function row(p: Partial<Row> = {}): Row {
  return { n: 1, file: "15-1234_a.jpg", size: 10, contentType: "image/jpeg", handling: "link", obj: "15-1234", objParsed: "15-1234",
    img: "15-1234_a", parseOk: true, idnum: "15-1234", date: "", restricted: false, type: "", creator: "", contributor: "",
    rightsHolder: "", description: "", copyright: "", include: true, upload: { s: "done" }, checks: [], result: null, ...p };
}

describe("DocumentRow", () => {
  it("shows Needs fixing for blocking checks and locks rows that created records", () => {
    let w = mount({ components: { DocumentRow }, template: "<table><tbody><DocumentRow v-bind='p'/></tbody></table>",
      data: () => ({ p: { row: row({ checks: [{ level: "block", text: "No object" }] }), tenant, expanded: false, readonly: false } }) });
    expect(w.text()).toContain("Needs fixing");
    w = mount({ components: { DocumentRow }, template: "<table><tbody><DocumentRow v-bind='p'/></tbody></table>",
      data: () => ({ p: { row: row({ result: { state: "Partial", steps: { media: { s: "done", csid: "m1" } } } }), tenant, expanded: true, readonly: false } }) });
    expect(w.text()).toContain("already created records");
    expect(w.find("select").attributes("disabled")).toBeDefined();
  });
});
