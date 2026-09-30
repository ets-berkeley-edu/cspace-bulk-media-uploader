/** The expand/collapse toggle for job and document rows: a 20px SVG triangle in a 30px button, rotated when open. */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { mount } from "@vue/test-utils";
import ChevronIcon from "../components/ChevronIcon.vue";
import DocumentRow from "../components/DocumentRow.vue";
import type { Perms, Row, TenantInfo } from "../types";

const tenant = { key: "pahma", name: "PAHMA", filenameHint: "", filenamePattern: "^(?P<obj>[A-Za-z0-9.-]+)$", mediaTypes: [],
  languageDefault: "", authorityFields: {}, publish: { field: "approvedForWeb", header: "Restricted", invert: true },
  handling: [{ id: "link", label: "Link to existing object", object: "existing", id_rule: "object" }] } as unknown as TenantInfo;
const perms: Perms = { media: true, mediaUpdate: true, relations: true, objects: true, readObjects: true, authorities: true, groups: true };
const row = { n: 1, file: "15-1234_1.jpg", size: 10, contentType: "image/jpeg", handling: "link", obj: "15-1234", objParsed: "15-1234",
  img: "15-1234_1", parseOk: true, idnum: "15-1234", date: "", restricted: false, type: [], creator: "", contributor: "",
  rightsHolder: "", description: "", copyright: "", include: true, upload: { s: "done" }, checks: [], result: null } as unknown as Row;

function mountRow(expanded: boolean) {
  return mount({ components: { DocumentRow }, template: "<table><tbody><DocumentRow v-bind='p'/></tbody></table>",
    data: () => ({ p: { row, tenant, perms, expanded, readonly: false } }) });
}

describe("the expand/collapse toggle", () => {
  it("is an SVG, hidden from screen readers, not a text character", () => {
    const svg = mount(ChevronIcon).find("svg");
    expect(svg.attributes("aria-hidden")).toBe("true");
    expect(svg.attributes("width")).toBe("20");
  });

  it("on a document row, keeps its label and expanded state and has no text", () => {
    for (const open of [false, true]) {
      const b = mountRow(open).find('button[aria-label="Show details"]');
      expect(b.classes()).toContain("chevron");
      expect(b.classes().includes("open")).toBe(open);
      expect(b.attributes("aria-expanded")).toBe(String(open));
      expect(b.find("svg.chev-icon").exists()).toBe(true);
      expect(b.text()).toBe("");
    }
  });

  it("no component still uses the small ▸ character for a row toggle", () => {
    for (const f of ["JobEditor", "DocumentRow", "DraftsList", "QueueList", "FinishedJobs"]) {
      const src = readFileSync(resolve(__dirname, `../components/${f}.vue`), "utf8");
      expect(src).not.toContain(">▸</button>");
      expect(src).toContain("<ChevronIcon />");
    }
  });

  it("is a 30px button with a 20px icon that rotates when open", () => {
    const css = readFileSync(resolve(__dirname, "../style.css"), "utf8");
    expect(css).toMatch(/\.chevron \{[^}]*width: 30px; height: 30px;/);
    expect(css).toMatch(/\.chevron \.chev-icon \{ width: 20px; height: 20px;/);
    expect(css).toMatch(/\.chevron\.open \.chev-icon \{ transform: rotate\(90deg\); \}/);
  });
});
