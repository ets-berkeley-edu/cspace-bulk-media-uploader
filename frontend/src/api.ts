import type { Check, Created, Failure, Job, Me, Row, RowChange, Run, Term } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail: unknown = null) {
    super(message);
  }
}

function messageOf(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message);
  if (Array.isArray(detail)) return "Some values aren't valid.";
  return `Request failed (${status})`;
}

/** JSON request to the BMU API. The session is an httpOnly cookie; X-BMU guards against cross-site requests. */
export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: { "X-BMU": "1", ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) {
    const detail = data?.detail ?? null;
    throw new ApiError(res.status, messageOf(detail, res.status), detail);
  }
  return data as T;
}

export const api = {
  me: () => request<Me>("GET", "/api/me"),
  login: (username: string, password: string) => request<Me>("POST", "/api/login", { username, password }),
  logout: () => request("POST", "/api/logout"),
  jobs: () => request<{ jobs: Job[] }>("GET", "/api/jobs"),
  createJob: (name: string) => request<Job>("POST", "/api/jobs", { name }),
  job: (id: string) => request<{ job: Job; rows: Row[]; runs: Run[]; created: Created }>("GET", `/api/jobs/${id}`),
  /** Fix and reschedule (or Reschedule): a job that needs attention or failed moves to Drafts, locked to you. */
  fix: (id: string) => request<Job>("POST", `/api/jobs/${id}/fix`),
  /** The failure catalog: title, explanation and what to do for each failure code. */
  failures: () => request<{ failures: Record<string, Failure> }>("GET", "/api/failures"),
  /** Retry a document's upload that failed or never finished: a new staged key for the same file. */
  retryUpload: (id: string, n: number, f: { name: string; size: number; type: string }) =>
    request<{ row: Row; uploadForm: { url: string; fields: Record<string, string> } }>("POST", `/api/jobs/${id}/rows/${n}/retry-upload`, f),
  replaceFile: (id: string, n: number, f: { name: string; size: number; type: string }) =>
    request<{ row: Row; uploadForm: { url: string; fields: Record<string, string> } }>("POST", `/api/jobs/${id}/rows/${n}/replace-file`, f),
  /** The job header: name, and the job's group. Turning the group on or off returns the rows whose checks changed. */
  patchJob: (id: string, fields: { name?: string; groupOn?: boolean; groupTitle?: string }) =>
    request<Job & { rows?: Row[] }>("PATCH", `/api/jobs/${id}`, fields),
  deleteJob: (id: string) => request("DELETE", `/api/jobs/${id}`),
  /** Become the draft's editor; with takeOverSince, take over from the editor the user was warned about. */
  openJob: (id: string, takeOverSince?: number) =>
    request<Job>("POST", `/api/jobs/${id}/open`, takeOverSince !== undefined ? { takeOverSince } : {}),
  closeJob: (id: string) => request("POST", `/api/jobs/${id}/close`),
  /** The job queue: move a queued job (0 = next to run), take it back to Drafts to edit, cancel a run. */
  moveJob: (id: string, toIndex: number) => request<{ jobs: Job[] }>("POST", `/api/jobs/${id}/move`, { toIndex }),
  editQueued: (id: string) => request<Job>("POST", `/api/jobs/${id}/edit`),
  cancelRun: (id: string) => request<Job>("POST", `/api/jobs/${id}/cancel`),
  saveDraft: (id: string) => request<Job>("POST", `/api/jobs/${id}/save`),
  addFiles: (id: string, files: { name: string; size: number; type: string }[]) =>
    request<{ rows: Row[] }>("POST", `/api/jobs/${id}/files`, { files }),
  uploaded: (id: string, n: number) => request<RowChange>("POST", `/api/jobs/${id}/rows/${n}/uploaded`),
  uploadFailed: (id: string, n: number) => request<RowChange>("POST", `/api/jobs/${id}/rows/${n}/upload-failed`),
  editRow: (id: string, n: number, changes: Partial<Row>) => request<RowChange>("PATCH", `/api/jobs/${id}/rows/${n}`, changes),
  /** The bulk-change panel: the same changes to many rows, never applied partially. */
  bulk: (id: string, rows: number[], changes: Partial<Row>) =>
    request<{ rows: Row[] }>("POST", `/api/jobs/${id}/rows/bulk`, { rows, changes }),
  deleteRow: (id: string, n: number) => request<{ ok: boolean; others: Row[]; jobStatus?: string }>("DELETE", `/api/jobs/${id}/rows/${n}`),
  /** Check rows against CollectionSpace: the given rows, or (no rows) any whose lookups are stale. */
  check: (id: string, rows?: number[]) =>
    request<{ rows: Row[]; counts: { block: number; warn: number } }>("POST", `/api/jobs/${id}/check`, rows ? { rows } : {}),
  schedule: (id: string) => request<Job>("POST", `/api/jobs/${id}/schedule`),
  /** CollectionSpace's date parser (structureddates), for the preview under the Date field. */
  parseDate: (text: string) =>
    request<{ ok: boolean; group: Record<string, string> }>("GET", `/api/dates/parse?text=${encodeURIComponent(text)}`),
  vocabulary: (name: string) => request<{ terms: Term[] }>("GET", `/api/vocabularies/${name}`),
  terms: (field: string, q: string) =>
    request<{ terms: Term[] }>("GET", `/api/authorities?field=${encodeURIComponent(field)}&q=${encodeURIComponent(q)}`),
};

export type { Check };
