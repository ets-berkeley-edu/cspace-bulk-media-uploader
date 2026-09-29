import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import QueueList from "../components/QueueList.vue";
import type { TenantInfo } from "../types";
const tenant = { name: "PAHMA", handling: [{ id: "link", label: "Link to existing object", object: "existing", id_rule: "object" }] } as unknown as TenantInfo;

afterEach(() => { vi.restoreAllMocks(); });

const now = Date.now() / 1000;
const jobs = [
  { id: "r", name: "running one", status: "Running", rowCount: 4, scheduledBy: "admin", queuedAt: now - 60, progress: { total: 4, done: 1, failed: 0 }, currentFile: "1-2345.jpg" },
  { id: "q1", name: "first queued", status: "Queued", rowCount: 2, scheduledBy: "jlee", queuedAt: now - 30, queuePos: 1, credentialExpires: now + 70 * 3600,
    checksAtSchedule: { block: 0, warn: 0 } },
  { id: "q2", name: "second queued", status: "Queued", rowCount: 1, scheduledBy: "admin", queuedAt: now - 20, queuePos: 2, credentialExpires: now + 2 * 3600,
    checksAtSchedule: { block: 0, warn: 0 } },
  { id: "d", name: "a draft", status: "Draft", rowCount: 1 },
];
let calls: { url: string; body?: string }[] = [];
function mockApi() {
  calls = [];
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    calls.push({ url, body: init?.body as string | undefined });
    const body = url.endsWith("/api/jobs") ? { jobs } : url.includes("/check") ? { rows: [], counts: { block: 0, warn: url.includes("/q2/") ? 1 : 0 } } : { jobs: [] };
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }));
  }));
}
const rowOf = (w: ReturnType<typeof mount>, name: string) => w.findAll("tbody tr").find((r) => r.text().includes(name))!;

describe("Job queue (design: The job queue)", () => {
  it("shows the running job first with its progress, then queued jobs in order, with sign-in and check changes", async () => {
    mockApi();
    const w = mount(QueueList, { props: { tenant } });
    await flushPromises();
    const names = w.findAll("tbody tr").map((r) => r.text());
    expect(names[0]).toContain("running one");
    expect(names[0]).toContain("1 done · 0 failed · 3 to go");
    expect(names[0]).toContain("1-2345.jpg");
    expect(names[1]).toContain("first queued");
    expect(names[2]).toContain("second queued");
    expect(w.text()).not.toContain("a draft");
    expect(rowOf(w, "second queued").text()).toContain("⚠ sign-in expires in ~2 h");
    expect(rowOf(w, "second queued").text()).toContain("Changed since scheduled");
    w.unmount();
  });

  it("moves a queued job, asks before Edit and Cancel run", async () => {
    mockApi();
    const w = mount(QueueList, { props: { tenant } });
    await flushPromises();
    await rowOf(w, "second queued").find('button[aria-label="Move second queued up"]').trigger("click");
    await flushPromises();
    expect(calls.find((c) => c.url.endsWith("/q2/move"))?.body).toBe(JSON.stringify({ toIndex: 0 }));
    await rowOf(w, "first queued").findAll("button").find((b) => b.text() === "Edit")!.trigger("click");
    expect(w.text()).toContain("deletes its saved sign-in");
    await rowOf(w, "running one").findAll("button").find((b) => b.text() === "Cancel run")!.trigger("click");
    expect(w.text()).toContain("finishes the document it’s on");
    w.unmount();
  });

  it("sorting only changes the view: moving is off until the sort is cleared", async () => {
    mockApi();
    const w = mount(QueueList, { props: { tenant } });
    await flushPromises();
    await w.findAll(".sort-btn").find((b) => b.text().startsWith("Job"))!.trigger("click");
    const names = w.findAll("tbody tr").map((r) => r.text());
    expect(names[1]).toContain("first queued"); // alphabetical: first, second
    expect(w.text()).toContain("Sorted view. The queue still runs in its own order");
    expect(rowOf(w, "second queued").find('button[aria-label="Move second queued up"]').attributes("disabled")).toBeDefined();
    await w.findAll("button").find((b) => b.text() === "clear the sort")!.trigger("click");
    expect(rowOf(w, "second queued").find('button[aria-label="Move second queued up"]').attributes("disabled")).toBeUndefined();
    w.unmount();
  });
});
