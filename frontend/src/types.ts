export interface Handling {
  id: string;
  label: string;
  object: "existing" | "create" | "none";
  id_rule: "object" | "image";
}

export interface Option {
  value: string;
  label: string;
}

export interface TenantInfo {
  key: string;
  name: string;
  handling: Handling[];
  publish: { field: string; header: string; invert?: boolean; default?: boolean };
  filenameHint: string;
  filenamePattern: string; // Python regular expression with named parts (obj)
  mediaTypes: Option[];
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
  s: "done" | "failed" | "skipped" | "not run";
  csid?: string;
  run?: number;
  after?: string; // skipped: the step it depended on
  code?: string; // failed: the failure code
  detail?: string;
}

export interface RowResult {
  state: "Not started" | "In progress" | "Done" | "Partial" | "Failed";
  steps?: Record<string, Step>;
  error?: { code: string; detail: string; step: string } | null;
  run?: number;
}

export interface Row {
  n: number;
  /** Version of the row's data, bumped by every save; an older copy is never shown over a newer one. */
  v?: number;
  file: string;
  fileOriginal?: string;
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
  type: string[]; // repeating: media type values from the tenant's option list
  language?: string[]; // repeating: refNames from the languages vocabulary
  creator: string;
  contributor: string;
  rightsHolder: string;
  description: string;
  copyright: string;
  include: boolean;
  upload: { s: "pending" | "uploading" | "verifying" | "done" | "failed"; pct?: number; reason?: string };
  checks: Check[];
  /** The last CollectionSpace searches for this row (object number, identification number). */
  lookups?: { object?: Lookup; media?: Lookup; date?: { value: string; ok: boolean; group: Record<string, string> } };
  result: RowResult | null;
  s3Key?: string;
  uploadForm?: { url: string; fields: Record<string, string> };
}

export interface Lookup {
  value: string;
  csids: string[];
  at: number;
}

/** The API's answer to a change to one row: that row, rechecked, and other rows whose checks changed. */
export interface RowChange {
  row: Row;
  others: Row[];
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
  // drafts: one editor at a time; saved as you go; expiry (design: Drafts)
  editingBy?: string;
  editingSince?: number;
  editingByYou?: boolean;
  lastSavedBy?: string;
  lastSavedAt?: number;
  expiresAt?: number;
}

export interface Term {
  refName: string;
  displayName: string;
  source: string;
}
