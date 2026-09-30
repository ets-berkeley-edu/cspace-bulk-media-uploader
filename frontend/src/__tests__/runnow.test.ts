import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import RunNow from "../components/RunNow.vue";
import type { Job } from "../types";

const job = (over: Partial<Job>): Job => ({ id: "j", tenant: "pahma", name: "Spring batch", status: "Running", createdBy: "admin",
  created: 0, updated: 0, rowCount: 3, run: 1, ...over } as Job);

describe("RunNow: the document a running job is on (design: The job queue)", () => {
  it("names the document and the step in progress", () => {
    const w = mount(RunNow, { props: { job: job({ currentFile: "15-1234_a.jpg", currentStep: "media" }) } });
    expect(w.text()).toBe("Now: 15-1234_a.jpg, creating the Media record");
    expect(w.find(".progress").exists()).toBe(false);
  });
  it("shows an upload bar with the share and megabytes sent while the file goes to CollectionSpace", () => {
    const w = mount(RunNow, { props: { job: job({ currentFile: "1-2345_large.tif", currentStep: "upload",
      currentUpload: { sent: 43 * 1024 ** 2, total: 90 * 1024 ** 2 } }) } });
    expect(w.text()).toContain("Now: 1-2345_large.tif, uploading the file");
    expect(w.text()).toContain("47% · 43.0 MB of 90.0 MB");
    expect(w.find(".progress .up").attributes("style")).toContain("width: 47%");
    expect(w.find("[role=progressbar]").attributes("aria-valuenow")).toBe("47");
  });
  it("shows nothing between documents, and no bar before the upload has started", () => {
    expect(mount(RunNow, { props: { job: job({}) } }).text()).toBe("");
    const w = mount(RunNow, { props: { job: job({ currentFile: "a.jpg", currentStep: "upload", currentUpload: null }) } });
    expect(w.find(".progress").exists()).toBe(false);
  });
});
