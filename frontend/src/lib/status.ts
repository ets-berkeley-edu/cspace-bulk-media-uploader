import type { Handling, Perms, Row, TenantInfo } from "../types";

export interface Badge {
  text: string;
  cls: string;
}

/** The Status column, as in the design's UI mockup: upload state first, then the row's checks and plan. */
export function rowStatus(r: Row, tenant: TenantInfo, checking = false): Badge {
  if (r.include && r.result?.state !== "Done") {
    if (r.upload.s === "uploading") return { text: `Uploading ${r.upload.pct ?? 0}%`, cls: "b-accent" };
    if (r.upload.s === "pending") return { text: "Waiting to upload", cls: "b-muted" };
    if (r.upload.s === "verifying") return { text: "Verifying…", cls: "b-accent" };
    if (r.upload.s === "failed") return { text: "Upload failed", cls: "b-danger" };
  }
  if (!r.include) return { text: "Excluded — ignored", cls: "b-accent" };
  if (r.result?.state === "Done") return { text: "Done in last run", cls: "b-ok" };
  if (r.result?.state === "Partial") {
    if (worstLevel(r) === "block") return { text: "Needs fixing", cls: "b-danger" };
    return { text: checking ? "Checking…" : "Partial — rerun finishes it", cls: checking ? "b-muted" : "b-warn" };
  }
  const needsObject = tenant.handling.find((x) => x.id === r.handling)?.object !== "none";
  if (needsObject && !r.parseOk && !r.obj) return { text: "Fix filename", cls: "b-danger" };
  if (worstLevel(r) === "block") return { text: "Needs fixing", cls: "b-danger" };
  if (checking) return { text: "Checking…", cls: "b-muted" };
  const h = tenant.handling.find((x) => x.id === r.handling);
  if (!h || h.object === "none") return { text: "Not linked", cls: "b-accent" };
  const found = r.lookups?.object?.value === r.obj ? r.lookups.object.csids.length : undefined;
  // An existing object blocks "create" (Needs fixing, above); "either" links to it, or creates it when missing
  if (found === undefined) return { text: "Not checked yet", cls: "b-muted" };
  if (h.object === "create" || (h.object === "either" && !found)) return { text: "Will create object", cls: "b-accent" };
  return { text: "Found — will link", cls: "b-ok" };
}

export function worstLevel(r: Row): "block" | "warn" | "ok" {
  if (r.checks.some((c) => c.level === "block")) return "block";
  if (r.checks.some((c) => c.level === "warn")) return "warn";
  return "ok";
}

/** Rows the next run would work on: included and not already done. */
export function hasWork(r: Row): boolean {
  return r.include && r.result?.state !== "Done";
}

export function jobCounts(rows: Row[]) {
  const work = rows.filter(hasWork);
  return {
    total: rows.length,
    disabled: rows.filter((r) => !r.include).length,
    work: work.length,
    block: work.filter((r) => worstLevel(r) === "block").length,
    warn: work.filter((r) => worstLevel(r) === "warn").length,
    uploaded: work.filter((r) => r.upload.s === "done").length,
    uploading: work.filter((r) => ["pending", "uploading", "verifying"].includes(r.upload.s)).length,
    uploadFailed: work.filter((r) => r.upload.s === "failed").length,
  };
}

/** Why the signed-in user can't use a handling option, or "" when they can (design: Permissions in the UI). */
export function handlingBlocked(h: Handling, perms: Perms): string {
  if (!perms.media) return "Your CollectionSpace account can't create Media records.";
  if (perms.mediaUpdate === false) return "Your account can't update Media records, which attaching the file needs.";
  if (h.object !== "none" && perms.readObjects === false) return "Your account can't read Object records, so it can't find objects.";
  if (h.object !== "none" && !perms.relations) return "Your account can't create relations, so it can't link to objects.";
  if (h.object === "create" && !perms.objects) return "Your account can't create Object records.";
  return "";
}
