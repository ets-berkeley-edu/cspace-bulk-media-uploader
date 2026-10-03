import { afterEach, describe, expect, it, vi } from "vitest";
import { defineComponent } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import App from "../views/Home.vue";
import JobEditor from "../components/JobEditor.vue";
import type { Job, Me, Perms, Row, TenantInfo } from "../types";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const tenant = { key: "pahma", name: "PAHMA", filenameHint: "", filenamePattern: "^(?P<obj>[A-Za-z0-9.-]+)$", mediaTypes: [], languageDefault: "",
  authorityFields: {}, publish: { field: "approvedForWeb", header: "Restricted", invert: true },
  handling: [{ id: "none", label: "Media only", object: "none", id_rule: "image" }] } as unknown as TenantInfo;
const perms: Perms = { media: true, mediaUpdate: true, relations: true, objects: true, readObjects: true, authorities: true, groups: true };
const me: Me = { user: "admin", tenant, perms, scheduler: false };
const row: Row = { n: 1, file: "a.jpg", size: 10, contentType: "image/jpeg", handling: "none", obj: "", objParsed: "", img: "a", parseOk: true,
  idnum: "a", date: "", restricted: false, type: [], creator: "", contributor: "", rightsHolder: "", description: "", copyright: "", include: true,
  upload: { s: "done" }, checks: [], result: null };
const draft = { id: "j1", name: "Spring batch", status: "Draft", createdBy: "admin", rowCount: 1, run: 0, editingBy: "admin", editingByYou: true } as Job;
const plan = { kind: "schedule", at: Date.now() / 1000 + 3 * 86400, ahead: 2, signInExpiresFirst: false } as const;

function stub(routes: (url: string, method: string) => unknown) {
  const calls: { url: string; method: string }[] = [];
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ url, method });
    return Promise.resolve(new Response(JSON.stringify(routes(url, method) ?? {}), { status: 200, headers: { "content-type": "application/json" } }));
  }));
  return calls;
}

describe("Submit job (design: Job scheduling)", () => {
  it("the editor's button reads Submit job and submits through POST …/schedule", async () => {
    const calls = stub((url, method) => {
      if (url.endsWith("/api/jobs/j1") && method === "GET") return { job: draft, rows: [row], runs: [], created: {} };
      if (url.endsWith("/check")) return { rows: [row], counts: { block: 0, warn: 0 } };
      if (url.endsWith("/api/jobs/j1") && method === "PATCH") return draft;
      if (url.endsWith("/j1/schedule")) return { ...draft, status: "Queued", plan };
      if (url.includes("/vocabularies/")) return { terms: [] };
      if (url.endsWith("/api/failures")) return { failures: {} };
      return {};
    });
    const w = mount(JobEditor, { props: { me, jobId: "j1" }, global: { stubs: { ThumbCell: true } } });
    await flushPromises();
    const submit = w.findAll("button").find((b) => b.text() === "Submit job")!;
    expect(w.findAll("button").some((b) => b.text() === "Schedule job")).toBe(false);
    expect(submit.attributes("title")).toBe("Check the whole job again, then add it to the job queue; it runs at the next run time");
    expect(w.text()).toContain("Submit job moves it to the job queue.");
    await submit.trigger("click");
    await flushPromises();
    expect(calls.some((c) => c.url.endsWith("/j1/schedule") && c.method === "POST")).toBe(true);
    expect((w.emitted("scheduled")?.[0][0] as Job).plan).toEqual(plan);
    w.unmount();
  });

  it("after submitting, the page says when it runs, from the response's plan", async () => {
    stub((url) => {
      if (url.endsWith("/api/me")) return me;
      if (url.endsWith("/api/schedule")) return { days: [1, 2, 3, 4, 5, 6, 7], start: "19:00", end: "", timezone: "America/Los_Angeles", paused: null,
        nextRunAt: plan.at, windowOpen: false, alwaysRunTime: false };
      if (url.endsWith("/api/jobs")) return { jobs: [] };
      return {};
    });
    const Editor = defineComponent({ emits: ["scheduled"], template: "<button class='fake-submit' @click=\"$emit('scheduled', job)\">Submit job</button>",
      data: () => ({ job: { ...draft, status: "Queued", plan } }) });
    const w = mount(App, { global: { stubs: { ThumbCell: true, JobEditor: Editor } } });
    await flushPromises();
    await w.find(".fake-submit").trigger("click");
    await flushPromises();
    const notice = w.find('.msg[role="status"]').text();
    expect(notice).toMatch(/^“Spring batch” was submitted and added to the end of the queue\. It runs at the next run time, .+ at \d+:\d\d [AP]M, after 2 other jobs\./);
    expect(notice).toContain(", after 2 other jobs.");
    expect(notice).toContain("It runs with your sign-in, which is deleted when the run ends.");
    expect(w.findAll(".tab").find((b) => b.text() === "Job queue")!.classes()).toContain("active");
    w.unmount();
  });

  it("says the queue is paused, or that it starts now in development mode", async () => {
    const run = async (p: object, alwaysRunTime: boolean) => {
      stub((url) => {
        if (url.endsWith("/api/me")) return me;
        if (url.endsWith("/api/schedule")) return { days: [1, 2, 3, 4, 5, 6, 7], start: "19:00", end: "", timezone: "America/Los_Angeles", paused: null,
          nextRunAt: null, windowOpen: true, alwaysRunTime };
        if (url.endsWith("/api/jobs")) return { jobs: [] };
        return {};
      });
      const Editor = defineComponent({ emits: ["scheduled"], template: "<button class='fake-submit' @click=\"$emit('scheduled', job)\">Submit job</button>",
        data: () => ({ job: { ...draft, status: "Queued", plan: { ...plan, ...p } } }) });
      const w = mount(App, { global: { stubs: { ThumbCell: true, JobEditor: Editor } } });
      await flushPromises();
      await w.find(".fake-submit").trigger("click");
      await flushPromises();
      const text = w.find('.msg[role="status"]').text();
      w.unmount();
      return text;
    };
    expect(await run({ kind: "paused" }, false)).toContain("The queue is paused, so it waits until a BMU scheduler resumes it.");
    expect(await run({ at: Date.now() / 1000, ahead: 0 }, true)).toContain("Development setting: every moment counts as run time, so it starts now.");
  });
});

describe("the job's Group title (user decision: never derived from the job name)", () => {
  it("starts empty and required; the buttons fill it once and renaming the job doesn't change it", async () => {
    let job: Job = { ...draft, groupOn: true, groupTitle: "" } as Job;
    const patches: Record<string, unknown>[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      let body: unknown = {};
      if (url.endsWith("/api/jobs/j1") && method === "GET") body = { job, rows: [row], runs: [], created: {} };
      else if (url.endsWith("/check")) body = { rows: [row], counts: { block: 0, warn: 0 } };
      else if (url.endsWith("/api/jobs/j1") && method === "PATCH") {
        const f = JSON.parse(String(init?.body));
        patches.push(f);
        job = { ...job, ...f };
        body = job;
      } else if (url.includes("/vocabularies/")) body = { terms: [] };
      else if (url.endsWith("/api/failures")) body = { failures: {} };
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }));
    }));
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(Date.UTC(2026, 8, 30, 20, 1, 2))); // 1:01:02 PM Pacific
    try {
      const w = mount(JobEditor, { props: { me, jobId: "j1" }, global: { stubs: { ThumbCell: true } } });
      await flushPromises();
      const title = w.find('input[aria-label="Group title"]');
      const btn = (t: string) => w.findAll("button").find((b) => b.text() === t)!;
      expect((title.element as HTMLInputElement).value).toBe("");
      expect(btn("Submit job").attributes("title")).toBe("Enter a group title, or turn off the job's group");
      const nameInput = w.find('input[placeholder="e.g. 2026 spring accession batch"]');
      await nameInput.setValue("Spring  batch #2");
      await btn("Use the job name").trigger("click");
      await flushPromises();
      expect(patches.at(-1)).toEqual({ groupTitle: "Spring  batch #2" }); // exactly as typed
      expect((title.element as HTMLInputElement).value).toBe("Spring  batch #2");
      await nameInput.setValue("Renamed");
      await nameInput.trigger("change");
      await flushPromises();
      expect(patches.at(-1)).toEqual({ name: "Renamed" });
      expect((title.element as HTMLInputElement).value).toBe("Spring  batch #2");
      await btn("Use a timestamp").trigger("click");
      await flushPromises();
      expect(patches.at(-1)).toEqual({ groupTitle: "bmu-2026-09-30-13-01-02" });
      expect((title.element as HTMLInputElement).value).toBe("bmu-2026-09-30-13-01-02");
      w.unmount();
    } finally {
      vi.useRealTimers();
    }
  });
});
