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
  groups: boolean;
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
  s: "done" | "failed" | "skipped" | "not run" | "not needed";
  csid?: string;
  run?: number; // the run that did it
  after?: string; // skipped: the step it depended on
  code?: string; // failed: the failure code (see Failure)
  detail?: string; // failed: technical detail (HTTP status and step)
  found?: boolean; // done: an existing record was used, not one this job created
  csid2?: string; // addToGroup: the relation in the other direction
  sameAs?: number; // addToGroup: another document already added the same object
  obj?: string; // an object step that failed: the object number it failed on
}

export interface RowResult {
  state: "Not started" | "In progress" | "Done" | "Partial" | "Failed";
  steps?: Record<string, Step>;
  error?: { code: string; detail: string; step: string } | null;
  notices?: { code: string; detail: string }[];
  run?: number;
}

/** One entry of the failure catalog (design: Finished jobs and error messages). */
export interface Failure {
  title: string;
  level: "row" | "job" | "notice" | "any";
  explain: string;
  fix: string;
  needs_fix: boolean;
}

/** Documents by result. */
export interface ResultCounts {
  done: number;
  partial: number;
  failed: number;
  notStarted: number;
  disabled: number;
}

/** One run in a job's run history. */
export interface Run {
  run: number;
  scheduledBy?: string;
  scheduledAt?: number;
  startedAt?: number;
  endedAt?: number;
  outcome: "Running" | "Completed" | "NeedsAttention" | "Failed";
  code?: string;
  counts?: ResultCounts;
  cancelledBy?: string;
  cancelledAt?: number;
  disabledBefore?: { n: number; file: string; by: string; at?: number }[];
  deletedBefore?: { n: number; file: string; by: string; at?: number }[];
}

/** What a job's runs created in CollectionSpace. */
export interface Created {
  media: number;
  files: number;
  objects: number;
  relations: number;
  groups?: number;
  unfinished: number;
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
  group?: boolean; // in the job's group (when the job creates one); on by default
  disabledBy?: string;
  disabledAt?: number;
  skipLink?: boolean; // stop linking a Partial row's Media record to an object
  replacedFor?: number; // the run whose rejected or lost file this row's file replaces
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
  // the job queue (design: The job queue)
  queuePos?: number | null;
  checksAtSchedule?: { block: number; warn: number };
  credentialExpires?: number;
  cancelRequested?: { by: string; at: number } | null;
  cancelledBy?: string;
  currentFile?: string;
  // finished jobs (design: Finished jobs and error messages)
  counts?: ResultCounts;
  runBy?: string;
  startedAt?: number;
  fixFrom?: { status: "NeedsAttention" | "Failed"; code: string; run: number } | null;
  // the job's group (design: Groups)
  groupOn?: boolean;
  groupTitle?: string;
  groupStep?: { s: "done" | "failed"; csid?: string; code?: string; detail?: string; run?: number } | null;
}

export interface Term {
  refName: string;
  displayName: string;
  source: string;
}
