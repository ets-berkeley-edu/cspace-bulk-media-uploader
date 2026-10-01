export interface Handling {
  id: string;
  label: string;
  object: "existing" | "create" | "either" | "none"; // either: link to the object, or create it if missing
  id_rule: "object" | "image";
  /** Field presets (design: Handling per document): type and language are lists, contributor a refName. */
  presets?: Partial<Record<"type" | "contributor" | "copyright" | "language", string | string[]>>;
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
  /** File extensions the BMU accepts, and how to name them (design: Supported file types). */
  fileTypes?: string[];
  /** Autocomplete timing from the tenant's UI profile. */
  autocomplete?: { findDelayMs: number; minLength: number };
  fileTypesHint?: string;
  authorityFields: Record<string, string[]>;
  sensitivity?: { summary: string; explain: string[] };
}

export interface Perms {
  media: boolean;
  relations: boolean;
  objects: boolean;
  readObjects: boolean;
  authorities: boolean;
  groups: boolean;
  mediaUpdate?: boolean; // attaching the file (PUT media/{csid}/blob)
  readMedia?: boolean;
  readPersons?: boolean;
  readOrgs?: boolean;
  readDates?: boolean;
}

export interface Me {
  user: string;
  tenant: TenantInfo;
  perms: Perms;
  /** Has the tenant's BMU_Scheduler role: may change the schedule and the job queue (design: Job scheduling). */
  scheduler?: boolean;
  /** The largest file the BMU accepts, in bytes; the page skips larger files before adding them (design: Browser uploads). */
  maxFileBytes?: number;
}

/** A tenant's run times (design: Job scheduling). days: ISO weekdays (1 = Mon … 7 = Sun); times "HH:MM", Pacific. */
export interface Schedule {
  days: number[];
  start: string;
  end: string; // "" = no end: new jobs may start any time after the start
  timezone: string;
  paused: { by: string; at: number; reason: string } | null;
  updatedBy?: string | null;
  updatedAt?: number | null;
  nextRunAt: number | null; // the next scheduled start at or after now
  windowOpen: boolean;
  alwaysRunTime: boolean; // development setting: every moment counts as run time
}

/** When a queued job is planned to start (design: Job scheduling). */
export interface JobPlan {
  kind: "running" | "held" | "paused" | "runNow" | "at" | "schedule";
  at: number | null; // planned start: its runAt, or the next start for "schedule"
  ahead: number; // not-held queued jobs picked before it
  signInExpiresFirst: boolean;
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
  /** The run in which the worker stopped while on this document: a create may have reached CollectionSpace. */
  interrupted?: number;
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
  codeDetail?: string; // the technical detail of a job-level code
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
  /** Fields the user has edited; presets (such as the default language) no longer apply to them. */
  touched?: string[];
  /** The date the browser read from the file's EXIF when it was added, if any (the Date field says so). */
  dateExif?: string;
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
  /** Set automatically from the linked Object (design: Protected files); users never set or clear it. */
  protected?: { reason: string; hides: boolean } | null;
  softSignals?: string[]; // Object-level signals that only warn
  restrictedAuto?: boolean; // Restricted was turned on because the file is protected
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
  code?: string; // a job-level failure code (see Failure)
  codeDetail?: string; // its technical detail, e.g. "Document 1, step media: POST media returned 401"
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
  /** The step in progress on currentRow (a key of STEP_LABEL), and while its file is sent, the bytes sent so far. */
  currentStep?: string;
  currentUpload?: { sent: number; total: number } | null;
  // job scheduling (design: Job scheduling)
  runNow?: boolean;
  runAt?: number | null;
  held?: { by: string; at: number } | null;
  plan?: JobPlan | null;
  // finished jobs (design: Finished jobs and error messages)
  counts?: ResultCounts;
  runBy?: string;
  startedAt?: number;
  fixFrom?: { status: "NeedsAttention" | "Failed"; code: string; codeDetail?: string; run: number } | null;
  // the job's group (design: Groups)
  groupOn?: boolean;
  groupTitle?: string;
  groupStep?: { s: "done" | "failed"; csid?: string; code?: string; detail?: string; run?: number } | null;
  protectedCount?: number; // documents that are protected files (a draft then expires after 7 days)
}

export interface Term {
  refName: string;
  displayName: string;
  source: string;
}
