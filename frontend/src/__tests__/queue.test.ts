import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import QueueList from "../components/QueueList.vue";
import { ptInstant, ptParts } from "../lib/schedule";
import type { Schedule, TenantInfo } from "../types";
const tenant = { name: "PAHMA", handling: [{ id: "link", label: "Link to existing object", object: "existing", id_rule: "object" }] } as unknown as TenantInfo;

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const now = Date.now() / 1000;
// 7:00 PM Pacific, three days ahead (the day's text depends on today; lib tests cover it)
const later = (({ y, mo, d }) => ptInstant(y, mo, d, 19, 0))(ptParts(now + 3 * 86400));
const jobs = [
  { id: "r", name: "running one", status: "Running", rowCount: 4, scheduledBy: "admin", queuedAt: now - 60, progress: { total: 4, done: 1, failed: 0 }, currentFile: "1-2345.jpg",
    plan: { kind: "running", at: null, ahead: 0, signInExpiresFirst: false } },
  { id: "q1", name: "first queued", status: "Queued", rowCount: 2, scheduledBy: "jlee", queuedAt: now - 30, queuePos: 1, credentialExpires: now + 70 * 3600,
    checksAtSchedule: { block: 0, warn: 0 }, runNow: true, plan: { kind: "runNow", at: null, ahead: 0, signInExpiresFirst: false } },
  { id: "q2", name: "second queued", status: "Queued", rowCount: 1, scheduledBy: "admin", queuedAt: now - 20, queuePos: 2, credentialExpires: now + 2 * 3600,
    checksAtSchedule: { block: 0, warn: 0 }, plan: { kind: "schedule", at: later, ahead: 1, signInExpiresFirst: true } },
  { id: "q3", name: "third queued", status: "Queued", rowCount: 1, scheduledBy: "jlee", queuedAt: now - 10, queuePos: 3, credentialExpires: now + 60 * 3600,
    checksAtSchedule: { block: 0, warn: 0 }, held: { by: "mkim", at: now - 5 }, plan: { kind: "held", at: null, ahead: 0, signInExpiresFirst: false } },
  { id: "d", name: "a draft", status: "Draft", rowCount: 1 },
];
const baseSchedule: Schedule = { days: [1, 2, 3, 4, 5, 6, 7], start: "19:00", end: "", timezone: "America/Los_Angeles", paused: null,
  nextRunAt: later, windowOpen: false, alwaysRunTime: false };
let calls: { url: string; method: string; body?: string }[] = [];
/** reply: per-request override (status and body), e.g. the server's 422 */
function mockApi(schedule: Partial<Schedule> = {}, reply?: (url: string, method: string) => { status: number; body: unknown } | undefined) {
  calls = [];
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ url, method, body: init?.body as string | undefined });
    const r = reply?.(url, method);
    const body = r ? r.body : url.endsWith("/api/jobs") ? { jobs } : url.includes("/api/schedule") ? { ...baseSchedule, ...schedule }
      : url.includes("/check") ? { rows: [], counts: { block: 0, warn: url.includes("/q2/") ? 1 : 0 } } : { jobs: [] };
    return Promise.resolve(new Response(JSON.stringify(body), { status: r?.status ?? 200, headers: { "content-type": "application/json" } }));
  }));
}
const rowOf = (w: ReturnType<typeof mount>, name: string) => w.findAll("tbody tr").find((r) => r.text().includes(name))!;
const btn = (w: { findAll: ReturnType<typeof mount>["findAll"] }, text: string) => w.findAll("button").find((b) => b.text() === text);
const scheduler = { tenant, user: "admin", scheduler: true };
const viewer = { tenant, user: "vwong", scheduler: false };

describe("Job queue (design: The job queue)", () => {
  it("shows the running job first with its progress, then queued jobs in order, with sign-in and check changes", async () => {
    mockApi();
    const w = mount(QueueList, { props: scheduler });
    await flushPromises();
    const names = w.findAll("tbody tr").map((r) => r.text());
    expect(names[0]).toContain("running one");
    expect(names[0]).toContain("1 done · 0 failed · 3 to go");
    expect(names[0]).toContain("1-2345.jpg");
    expect(names[1]).toContain("first queued");
    expect(names[2]).toContain("second queued");
    expect(w.text()).not.toContain("a draft");
    expect(rowOf(w, "second queued").text()).toContain("⚠ sign-in expires in ~2 h");
    expect(rowOf(w, "second queued").text()).toContain("Changed since submitted");
    w.unmount();
  });

  it("moves a queued job, asks before Edit and Cancel run", async () => {
    mockApi();
    const w = mount(QueueList, { props: scheduler });
    await flushPromises();
    await rowOf(w, "second queued").find('button[aria-label="Move second queued up"]').trigger("click");
    await flushPromises();
    expect(calls.find((c) => c.url.endsWith("/q2/move"))?.body).toBe(JSON.stringify({ toIndex: 0 }));
    await btn(rowOf(w, "first queued"), "Edit")!.trigger("click");
    expect(w.text()).toContain("deletes its saved sign-in");
    await btn(rowOf(w, "running one"), "Cancel run")!.trigger("click");
    expect(w.text()).toContain("finishes the document it’s on");
    w.unmount();
  });

  it("sorting only changes the view: moving is off until the sort is cleared", async () => {
    mockApi();
    const w = mount(QueueList, { props: scheduler });
    await flushPromises();
    await w.findAll(".sort-btn").find((b) => b.text().startsWith("Job"))!.trigger("click");
    const names = w.findAll("tbody tr").map((r) => r.text());
    expect(names[1]).toContain("first queued"); // alphabetical: first, second
    expect(w.text()).toContain("Sorted view. The queue still runs in its own order");
    expect(rowOf(w, "second queued").find('button[aria-label="Move second queued up"]').attributes("disabled")).toBeDefined();
    await btn(w, "clear the sort")!.trigger("click");
    expect(rowOf(w, "second queued").find('button[aria-label="Move second queued up"]').attributes("disabled")).toBeUndefined();
    w.unmount();
  });

  it("sorted by Order ascending is the queue order, so jobs can still be moved; descending turns moving off", async () => {
    mockApi();
    const w = mount(QueueList, { props: scheduler });
    await flushPromises();
    const orderBtn = () => w.findAll(".sort-btn").find((b) => b.text().startsWith("Order"))!;
    const up = () => rowOf(w, "second queued").find('button[aria-label="Move second queued up"]');
    await orderBtn().trigger("click"); // ascending
    expect(w.text()).not.toContain("Sorted view");
    expect(up().attributes("disabled")).toBeUndefined();
    await orderBtn().trigger("click"); // descending
    expect(w.text()).toContain("Sorted view. The queue still runs in its own order");
    expect(up().attributes("disabled")).toBeDefined();
    w.unmount();
  });
});

describe("Job queue: sorting by Status (design: User interface, every table is sortable)", () => {
  const queuedJob = (id: string, pos: number, kind: string, held = false) => ({ id, name: `job ${id}`, status: "Queued", rowCount: 1,
    scheduledBy: "admin", queuedAt: now - 100 + pos, queuePos: pos, credentialExpires: now + 60 * 3600, checksAtSchedule: { block: 0, warn: 0 },
    ...(held ? { held: { by: "mkim", at: now - 5 } } : {}), plan: { kind, at: null, ahead: 0, signInExpiresFirst: false } });
  const list = [jobs[0], queuedJob("a", 1, "schedule"), queuedJob("h", 2, "held", true), queuedJob("b", 3, "runNow"), queuedJob("p", 4, "paused")];
  const order = (w: ReturnType<typeof mount>) => w.findAll("tbody tr").map((r) => r.text().match(/running one|job \w/)?.[0]);

  it("the Status heading sorts Running, then queued jobs waiting their turn, then paused, then held; again to reverse, then queue order", async () => {
    mockApi({}, (url) => (url.endsWith("/api/jobs") ? { status: 200, body: { jobs: list } } : undefined));
    const w = mount(QueueList, { props: scheduler });
    await flushPromises();
    expect(order(w)).toEqual(["running one", "job a", "job h", "job b", "job p"]);
    const status = () => w.findAll(".sort-btn").find((b) => b.text().startsWith("Status"))!;
    await status().trigger("click");
    expect(order(w)).toEqual(["running one", "job a", "job b", "job p", "job h"]); // ties keep queue order
    expect(w.text()).toContain("Sorted view. The queue still runs in its own order");
    expect(rowOf(w, "job b").find('button[aria-label="Move job b up"]').attributes("disabled")).toBeDefined();
    await status().trigger("click");
    expect(order(w)).toEqual(["running one", "job h", "job p", "job a", "job b"]); // running jobs stay first
    await status().trigger("click");
    expect(order(w)).toEqual(["running one", "job a", "job h", "job b", "job p"]);
    expect(w.text()).not.toContain("Sorted view");
    w.unmount();
  });
});

describe("Job queue: scheduling (design: Job scheduling; UI mockup scheduleBannerHtml, runsAtCell)", () => {
  it("everyone sees the schedule banner and each job's Runs at", async () => {
    mockApi();
    const w = mount(QueueList, { props: viewer });
    await flushPromises();
    expect(w.find(".sched-banner").text()).toMatch(/^Jobs run every day at 7:00 PM \(Pacific time\)\. Next run time: .+ at 7:00 PM\.$/);
    expect(w.findAll("th").map((t) => t.text().replace(/[↕▲▼]/g, "").trim())).toContain("Runs at");
    expect(rowOf(w, "running one").find(".runs-at").text()).toBe("Running");
    expect(rowOf(w, "first queued").find(".runs-at").text()).toContain("Next, as soon as the running job ends");
    expect(rowOf(w, "first queued").find(".runs-at").text()).toContain("Run now");
    expect(rowOf(w, "second queued").find(".runs-at").text()).toMatch(/7:00 PM · after 1 job/);
    expect(rowOf(w, "second queued").find(".runs-at").text()).toContain("⚠ sign-in expires before its run time");
    expect(rowOf(w, "third queued").find(".runs-at").text()).toContain("Held by mkim");
    w.unmount();
  });

  it("a non-scheduler can't change the schedule, the order or a job's run time, nor cancel another's run", async () => {
    mockApi();
    const w = mount(QueueList, { props: viewer });
    await flushPromises();
    expect(w.text()).toContain("Only BMU schedulers can change the schedule or the order of the queue.");
    for (const t of ["Schedule settings…", "Pause queue…", "Run now", "Undo Run now", "Set run time…", "Hold", "Release"]) expect(btn(w, t)).toBeUndefined();
    expect(w.find(".order-btns").exists()).toBe(false);
    expect(rowOf(w, "second queued").attributes("draggable")).toBe("false");
    const cancel = btn(rowOf(w, "running one"), "Cancel run")!;
    expect(cancel.attributes("disabled")).toBeDefined();
    expect(cancel.attributes("title")).toBe("Only a BMU scheduler or the person who submitted the job can cancel its run.");
    w.unmount();
  });

  it("the submitter may cancel their own run without the role", async () => {
    mockApi();
    const w = mount(QueueList, { props: { tenant, user: "admin", scheduler: false } });
    await flushPromises();
    expect(btn(rowOf(w, "running one"), "Cancel run")!.attributes("disabled")).toBeUndefined();
    w.unmount();
  });

  it("shows the paused banner and the development setting", async () => {
    mockApi({ paused: { by: "jlee", at: now - 600, reason: "CollectionSpace upgrade" }, alwaysRunTime: true });
    const w = mount(QueueList, { props: scheduler });
    await flushPromises();
    expect(w.find(".banner.warn").text()).toMatch(/^The queue is paused by jlee since .+: CollectionSpace upgrade\. No job starts until a BMU scheduler resumes it\.$/);
    expect(w.text()).toContain("Development setting: every moment counts as run time.");
    expect(btn(w, "Pause queue…")).toBeUndefined();
    await btn(w, "Resume queue")!.trigger("click");
    await flushPromises();
    expect(calls.some((c) => c.url.endsWith("/api/schedule/resume") && c.method === "POST")).toBe(true);
    expect(w.text()).toContain("You resumed the queue.");
    w.unmount();
  });

  it("a scheduler edits the schedule; the server's 422 message shows in the panel", async () => {
    mockApi({}, (url, method) => (url.endsWith("/api/schedule") && method === "PUT"
      ? { status: 422, body: { detail: "Run days can't be more than 3 days apart." } } : undefined));
    const w = mount(QueueList, { props: scheduler });
    await flushPromises();
    await btn(w, "Schedule settings…")!.trigger("click");
    const panel = () => w.find(".sched-panel");
    const days = panel().findAll("input.sched-day");
    expect(panel().findAll(".days label").map((l) => l.text())).toEqual(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]);
    for (const i of [0, 2, 4, 6]) await days[i].setValue(false); // leave Mon, Wed, Fri
    await panel().find("#schedStart").setValue("20:30");
    await panel().find("input.sched-end-on").setValue(true);
    await panel().find("input.sched-end").setValue("05:00");
    await btn(panel(), "Save")!.trigger("click");
    await flushPromises();
    expect(JSON.parse(calls.find((c) => c.method === "PUT")!.body!)).toEqual({ days: [1, 3, 5], start: "20:30", end: "05:00" });
    expect(panel().find(".msg-block").text()).toBe("Run days can't be more than 3 days apart.");
    await btn(panel(), "Cancel")!.trigger("click");
    expect(w.find(".sched-panel").exists()).toBe(false);
    w.unmount();
  });

  it("a scheduler saves a schedule and sees it summarised", async () => {
    mockApi({}, (url, method) => (url.endsWith("/api/schedule") && method === "PUT"
      ? { status: 200, body: { ...baseSchedule, days: [1, 2, 3, 4, 5], end: "06:00" } } : undefined));
    const w = mount(QueueList, { props: scheduler });
    await flushPromises();
    await btn(w, "Schedule settings…")!.trigger("click");
    await btn(w.find(".sched-panel"), "Save")!.trigger("click");
    await flushPromises();
    expect(w.text()).toContain("Schedule saved. Jobs run weekdays at 7:00 PM (Pacific time); no new jobs start after 6:00 AM.");
    w.unmount();
  });

  it("pausing needs a reason", async () => {
    mockApi();
    const w = mount(QueueList, { props: scheduler });
    await flushPromises();
    await btn(w, "Pause queue…")!.trigger("click");
    await btn(w.find(".sched-panel"), "Pause")!.trigger("click");
    expect(w.find(".sched-panel").text()).toContain("Enter a reason, so others know why the queue is paused.");
    await w.find("#pauseReason").setValue("Server maintenance");
    await btn(w.find(".sched-panel"), "Pause")!.trigger("click");
    await flushPromises();
    expect(calls.find((c) => c.url.endsWith("/api/schedule/pause"))?.body).toBe(JSON.stringify({ reason: "Server maintenance" }));
    expect(w.text()).toContain("You paused the queue.");
    w.unmount();
  });

  it("per-job controls: Run now / Undo, Hold / Release, Set run time… in Pacific time", async () => {
    mockApi({}, (url) => (url.endsWith("/q2/run-at") && calls.filter((c) => c.url.endsWith("/run-at")).length > 1
      ? { status: 422, body: { detail: "The latest run time is when the job's saved sign-in expires." } } : undefined));
    const w = mount(QueueList, { props: scheduler });
    await flushPromises();
    await btn(rowOf(w, "first queued"), "Undo Run now")!.trigger("click");
    await flushPromises();
    expect(calls.find((c) => c.url.endsWith("/q1/run-now"))?.body).toBe(JSON.stringify({ on: false }));
    await btn(rowOf(w, "second queued"), "Run now")!.trigger("click");
    await flushPromises();
    expect(calls.find((c) => c.url.endsWith("/q2/run-now"))?.body).toBe(JSON.stringify({ on: true }));
    await btn(rowOf(w, "third queued"), "Release")!.trigger("click");
    await btn(rowOf(w, "second queued"), "Hold")!.trigger("click");
    await flushPromises();
    expect(calls.filter((c) => c.url.includes("/hold")).map((c) => [c.url.split("/")[3], c.body]))
      .toEqual([["q3", JSON.stringify({ on: false })], ["q2", JSON.stringify({ on: true })]]);

    await btn(rowOf(w, "second queued"), "Set run time…")!.trigger("click");
    const input = rowOf(w, "second queued").find('input[type="datetime-local"]');
    expect(input.attributes("min")).toMatch(/^\d{4}-\d\d-\d\dT\d\d:\d\d$/);
    expect(input.attributes("max")).toMatch(/^\d{4}-\d\d-\d\dT\d\d:\d\d$/);
    await input.setValue("2026-12-01T19:00");
    await btn(rowOf(w, "second queued"), "Save")!.trigger("click");
    await flushPromises();
    // 7:00 PM Pacific on Dec 1 is 03:00 UTC on Dec 2 (PST), whatever the browser's zone
    expect(calls.find((c) => c.url.endsWith("/q2/run-at"))?.body).toBe(JSON.stringify({ at: Date.UTC(2026, 11, 2, 3, 0) / 1000 }));
    // a second try the server refuses: its message shows under the field
    await btn(rowOf(w, "second queued"), "Set run time…")!.trigger("click");
    await rowOf(w, "second queued").find('input[type="datetime-local"]').setValue("2027-01-01T19:00");
    await btn(rowOf(w, "second queued"), "Save")!.trigger("click");
    await flushPromises();
    expect(rowOf(w, "second queued").find(".msg-block").text()).toBe("The latest run time is when the job's saved sign-in expires.");
    w.unmount();
  });
});
