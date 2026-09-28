export interface Handling {
  id: string;
  label: string;
  object: "existing" | "create" | "none";
  id_rule: "object" | "image";
}

export interface TenantInfo {
  key: string;
  name: string;
  handling: Handling[];
  publish: { field: string; header: string; invert?: boolean; default?: boolean };
  filenameHint: string;
  mediaTypes: string[];
  languageDefault: string;
  authorityFields: Record<string, string[]>;
}

export interface Perms {
  media: boolean;
  relations: boolean;
  objects: boolean;
  readObjects: boolean;
  authorities: boolean;
}

export interface Me {
  user: string;
  tenant: TenantInfo;
  perms: Perms;
}

export type CheckLevel = "block" | "warn" | "info";
export interface Check {
  level: CheckLevel;
  text: string;
}

export interface Step {
  s: "done" | "failed" | "not run";
  csid?: string;
  run?: number;
}

export interface RowResult {
  state: "Not started" | "In progress" | "Done" | "Partial" | "Failed";
  steps?: Record<string, Step>;
  error?: { code: string; detail: string; step: string } | null;
  run?: number;
}

export interface Row {
  n: number;
  file: string;
  size: number;
  contentType: string;
  handling: string;
  obj: string;
  objParsed: string;
  img: string;
  parseOk: boolean;
  idnum: string;
  date: string;
  restricted: boolean;
  type: string;
  creator: string;
  contributor: string;
  rightsHolder: string;
  description: string;
  copyright: string;
  include: boolean;
  upload: { s: "pending" | "uploading" | "done" | "failed"; pct?: number; reason?: string };
  checks: Check[];
  result: RowResult | null;
  s3Key?: string;
  uploadForm?: { url: string; fields: Record<string, string> };
}

export type JobStatus = "Draft" | "Queued" | "Running" | "Completed" | "NeedsAttention" | "Failed";

export interface Job {
  id: string;
  tenant: string;
  name: string;
  status: JobStatus;
  createdBy: string;
  created: number;
  updated: number;
  rowCount: number;
  run: number;
  code?: string;
  note?: string;
  scheduledBy?: string;
  queuedAt?: number;
  finishedAt?: number;
  currentRow?: number;
  progress?: { total: number; done: number; failed: number };
}

export interface Term {
  refName: string;
  displayName: string;
  source: string;
}
