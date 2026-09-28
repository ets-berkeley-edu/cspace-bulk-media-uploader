import type { Check, Job, Me, Row, RowChange, Term } from "./types";

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
  job: (id: string) => request<{ job: Job; rows: Row[] }>("GET", `/api/jobs/${id}`),
  renameJob: (id: string, name: string) => request<Job>("PATCH", `/api/jobs/${id}`, { name }),
  deleteJob: (id: string) => request("DELETE", `/api/jobs/${id}`),
  addFiles: (id: string, files: { name: string; size: number; type: string }[]) =>
    request<{ rows: Row[] }>("POST", `/api/jobs/${id}/files`, { files }),
  uploaded: (id: string, n: number) => request<RowChange>("POST", `/api/jobs/${id}/rows/${n}/uploaded`),
  uploadFailed: (id: string, n: number) => request<RowChange>("POST", `/api/jobs/${id}/rows/${n}/upload-failed`),
  editRow: (id: string, n: number, changes: Partial<Row>) => request<RowChange>("PATCH", `/api/jobs/${id}/rows/${n}`, changes),
  deleteRow: (id: string, n: number) => request<{ ok: boolean; others: Row[] }>("DELETE", `/api/jobs/${id}/rows/${n}`),
  /** Check rows against CollectionSpace: the given rows, or (no rows) any whose lookups are stale. */
  check: (id: string, rows?: number[]) =>
    request<{ rows: Row[]; counts: { block: number; warn: number } }>("POST", `/api/jobs/${id}/check`, rows ? { rows } : {}),
  schedule: (id: string) => request<Job>("POST", `/api/jobs/${id}/schedule`),
  terms: (field: string, q: string) =>
    request<{ terms: Term[] }>("GET", `/api/authorities?field=${encodeURIComponent(field)}&q=${encodeURIComponent(q)}`),
};

export type { Check };
