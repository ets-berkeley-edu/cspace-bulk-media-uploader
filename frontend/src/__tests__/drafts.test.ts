import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import DraftsList from "../components/DraftsList.vue";
import type { TenantInfo } from "../types";
const tenant = { name: "PAHMA", handling: [{ id: "link", label: "Link to existing object", object: "existing", id_rule: "object" }] } as unknown as TenantInfo;

afterEach(() => { vi.restoreAllMocks(); });

const now = Date.now() / 1000;
const jobs = [
  { id: "a", name: "mine", status: "Draft", createdBy: "admin", rowCount: 3, editingBy: "admin", editingByYou: true, editingSince: now,
    lastSavedBy: "admin", lastSavedAt: now, expiresAt: now + 30 * 86400 },
  { id: "b", name: "theirs", status: "Draft", createdBy: "jlee", rowCount: 2, editingBy: "jlee", editingByYou: false, editingSince: 1234,
    lastSavedBy: "jlee", lastSavedAt: now - 28 * 86400, expiresAt: now + 2 * 86400 },
  { id: "c", name: "queued", status: "Queued", createdBy: "admin", rowCount: 1 },
  { id: "d", name: "fixing", status: "Draft", createdBy: "admin", rowCount: 2, run: 1, lastSavedBy: "BMU", lastSavedAt: now,
    expiresAt: now + 30 * 86400, note: "Sign-in expired while waiting in the queue; schedule it again to run it with your sign-in." },
];

function mockApi() {
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    const body = url.endsWith("/api/jobs") ? { jobs }
      : url.endsWith("/api/jobs/d") ? { job: jobs[3], rows: [], runs: [], created: { media: 2, files: 1, objects: 1, relations: 4, unfinished: 1 } }
      : { rows: [], counts: { block: url.includes("/b/") ? 1 : 0, warn: 0 } };
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }));
  }));
}

describe("Drafts tab (design: Drafts)", () => {
  it("lists only drafts, with who is editing, checks now and expiry", async () => {
    mockApi();
    const w = mount(DraftsList, { props: { tenant } });
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
    const w = mount(DraftsList, { props: { tenant } });
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

  it("shows a draft's note, such as a sign-in that expired while it waited in the queue", async () => {
    mockApi();
    const w = mount(DraftsList, { props: { tenant } });
    await flushPromises();
    expect(w.findAll("tbody tr").find((r) => r.text().includes("fixing"))!.text()).toContain("⚠ Sign-in expired while waiting in the queue");
    w.unmount();
  });

  it("counts what a job's runs created before it is deleted, and says nothing was created for one that never ran", async () => {
    mockApi();
    const w = mount(DraftsList, { props: { tenant } });
    await flushPromises();
    const rowOf = (name: string) => w.findAll("tbody tr").find((r) => r.text().includes(name))!;
    await rowOf("fixing").findAll("button").find((b) => b.text() === "Delete")!.trigger("click");
    await flushPromises();
    expect(w.text()).toContain("Its runs created 2 Media records (1 with its file), 1 Object and 4 Relations, including 1 unfinished document.");
    expect(w.text()).toContain("the BMU never deletes records");
    await w.findAll("button").find((b) => b.text() === "Cancel")!.trigger("click");
    await rowOf("mine").findAll("button").find((b) => b.text() === "Delete")!.trigger("click");
    expect(w.text()).toContain("Delete this draft? Its 3 documents and uploaded files are removed from the BMU; it created nothing in CollectionSpace.");
    w.unmount();
  });
});


describe("expanded job documents (design: every table sorts)", () => {
  it("sorts the listed documents by a column heading", async () => {
    const JobDocs = (await import("../components/JobDocs.vue")).default;
    const mk = (n: number, file: string) => ({ n, file, handling: "link", include: true, checks: [], upload: { s: "done" }, result: null }) as never;
    const w = mount(JobDocs, { props: { job: { id: "j", name: "x", status: "Queued", rowCount: 2 } as never, rows: [mk(1, "b.jpg"), mk(2, "a.jpg")],
      tenant, kind: "queue" }, global: { stubs: { ThumbCell: true } } });
    const names = () => w.findAll("tbody tr").map((t) => t.findAll("td")[1].text());
    expect(names()).toEqual(["b.jpg", "a.jpg"]);
    await w.find('button[aria-label="Sort by Document"]').trigger("click");
    expect(names()).toEqual(["a.jpg", "b.jpg"]);
  });
});
