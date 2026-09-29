import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import DraftsList from "../components/DraftsList.vue";

afterEach(() => { vi.restoreAllMocks(); });

const now = Date.now() / 1000;
const jobs = [
  { id: "a", name: "mine", status: "Draft", createdBy: "admin", rowCount: 3, editingBy: "admin", editingByYou: true, editingSince: now,
    lastSavedBy: "admin", lastSavedAt: now, expiresAt: now + 30 * 86400 },
  { id: "b", name: "theirs", status: "Draft", createdBy: "jlee", rowCount: 2, editingBy: "jlee", editingByYou: false, editingSince: 1234,
    lastSavedBy: "jlee", lastSavedAt: now - 28 * 86400, expiresAt: now + 2 * 86400 },
  { id: "c", name: "queued", status: "Queued", createdBy: "admin", rowCount: 1 },
];

function mockApi() {
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    const body = url.endsWith("/api/jobs") ? { jobs } : { rows: [], counts: { block: url.includes("/b/") ? 1 : 0, warn: 0 } };
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }));
  }));
}

describe("Drafts tab (design: Drafts)", () => {
  it("lists only drafts, with who is editing, checks now and expiry", async () => {
    mockApi();
    const w = mount(DraftsList);
    await flushPromises();
    const text = w.text();
    expect(text).toContain("mine");
    expect(text).toContain("theirs");
    expect(text).not.toContain("queued");
    expect(text).toContain("🔒 You");
    expect(text).toContain("🔒 jlee");
    expect(text).toContain("1 needs fixing");
    expect(w.find(".soon").exists()).toBe(true); // "theirs" expires within 3 days
    w.unmount();
  });

  it("offers Continue editing for your own draft, and Take over (after a warning) for someone else's", async () => {
    mockApi();
    const w = mount(DraftsList);
    await flushPromises();
    const rowOf = (name: string) => w.findAll("tbody tr").find((r) => r.text().includes(name))!;
    await rowOf("mine").findAll("button").find((b) => b.text() === "Continue editing")!.trigger("click");
    expect(w.emitted("open")?.[0]).toEqual(["a", "edit"]);
    const theirs = rowOf("theirs");
    expect(theirs.findAll("button").find((b) => b.text() === "Delete")!.attributes("disabled")).toBeDefined();
    await theirs.findAll("button").find((b) => b.text() === "Take over…")!.trigger("click");
    expect(w.text()).toContain("their page becomes read-only");
    await rowOf("theirs").findAll("button").find((b) => b.text() === "Take over and edit")!.trigger("click");
    expect(w.emitted("open")?.[1]).toEqual(["b", "edit", 1234]);
    w.unmount();
  });
});
