import axios from 'axios'
import {ApiError} from './lib/axios-utils'
import type {Check, Created, Failure, Job, Me, Row, RowChange, Run, Schedule, Term} from './types'

/**
 * JSON request to the BMU API, through axios: X-BMU, and what a failed request rejects with, are set up once in
 * lib/axios-utils.ts (initializeAxios).
 * poll: a background refresh, which doesn't count as activity for the idle sign-out.
 */
export async function request<T>(method: string, path: string, body?: unknown, poll = false): Promise<T> {
  const response = await axios.request<T>({method, url: path, data: body, headers: poll ? {'X-BMU-Poll': '1'} : {}})
  return response.data
}

/** Send the thumbnail the browser made; the server rewrites it, and stores none for a protected file. */
async function putThumbnail(id: string, n: number, jpeg: Blob): Promise<{ stored: boolean }> {
  const response = await axios.post<{ stored: boolean }>(`/api/jobs/${id}/rows/${n}/thumbnail`, jpeg, {headers: {'Content-Type': 'image/jpeg'}})
  return response.data
}

export const thumbnailUrl = (id: string, n: number, v = 0, large = false) =>
  `/api/jobs/${id}/rows/${n}/thumbnail?v=${v}${large ? '&size=large' : ''}`

export const api = {
  putThumbnail,
  me: () => request<Me>('GET', '/api/me'),
  /** Which environment this is (no sign-in needed): its label, and whether its CollectionSpace is a real server. */
  env: () => request<{ label: string; realCollectionSpace: boolean }>('GET', '/api/env'),
  login: (username: string, password: string) => request<Me>('POST', '/api/login', {username, password}),
  logout: () => request('POST', '/api/logout'),
  jobs: (poll = false) => request<{ jobs: Job[] }>('GET', '/api/jobs', undefined, poll),
  createJob: (name: string) => request<Job>('POST', '/api/jobs', {name}),
  job: (id: string, poll = false) => request<{ job: Job; rows: Row[]; runs: Run[]; created: Created }>('GET', `/api/jobs/${id}`, undefined, poll),
  /** Fix and reschedule (or Reschedule): a job that needs attention or failed moves to Drafts, locked to you. */
  fix: (id: string) => request<Job>('POST', `/api/jobs/${id}/fix`),
  /** The failure catalog: title, explanation and what to do for each failure code. */
  failures: () => request<{ failures: Record<string, Failure> }>('GET', '/api/failures'),
  /** Retry a document's upload that failed or never finished: a new staged key for the same file. */
  retryUpload: (id: string, n: number, f: { name: string; size: number; type: string }) =>
    request<{ row: Row; uploadForm: { url: string; fields: Record<string, string> } }>('POST', `/api/jobs/${id}/rows/${n}/retry-upload`, f),
  replaceFile: (id: string, n: number, f: { name: string; size: number; type: string }) =>
    request<{ row: Row; uploadForm: { url: string; fields: Record<string, string> } }>('POST', `/api/jobs/${id}/rows/${n}/replace-file`, f),
  /** The job header: name, and the job's group. Turning the group on or off returns the rows whose checks changed. */
  patchJob: (id: string, fields: { name?: string; groupOn?: boolean; groupTitle?: string }) =>
    request<Job & { rows?: Row[] }>('PATCH', `/api/jobs/${id}`, fields),
  deleteJob: (id: string) => request('DELETE', `/api/jobs/${id}`),
  /** Become the draft's editor; with takeOverSince, take over from the editor the user was warned about. */
  openJob: (id: string, takeOverSince?: number) =>
    request<Job>('POST', `/api/jobs/${id}/open`, takeOverSince !== undefined ? {takeOverSince} : {}),
  closeJob: (id: string) => request('POST', `/api/jobs/${id}/close`),
  /** The job queue: move a queued job (0 = next to run), take it back to Drafts to edit, cancel a run. */
  moveJob: (id: string, toIndex: number) => request<{ jobs: Job[] }>('POST', `/api/jobs/${id}/move`, {toIndex}),
  editQueued: (id: string) => request<Job>('POST', `/api/jobs/${id}/edit`),
  cancelRun: (id: string) => request<Job>('POST', `/api/jobs/${id}/cancel`),
  saveDraft: (id: string) => request<Job>('POST', `/api/jobs/${id}/save`),
  addFiles: (id: string, files: { name: string; size: number; type: string; exifDate?: string; orientation?: string }[]) =>
    request<{ rows: Row[] }>('POST', `/api/jobs/${id}/files`, {files}),
  uploaded: (id: string, n: number) => request<RowChange>('POST', `/api/jobs/${id}/rows/${n}/uploaded`),
  /** A fresh presigned POST for a document's file that hasn't been sent yet (its first form may have expired while it
   *  waited its turn); size is the file's, which must be the document's. The row isn't changed. */
  uploadForm: (id: string, n: number, size: number) =>
    request<{ uploadForm: { url: string; fields: Record<string, string> } }>('POST', `/api/jobs/${id}/rows/${n}/upload-form`, {size}),
  uploadFailed: (id: string, n: number) => request<RowChange>('POST', `/api/jobs/${id}/rows/${n}/upload-failed`),
  editRow: (id: string, n: number, changes: Partial<Row>) => request<RowChange>('PATCH', `/api/jobs/${id}/rows/${n}`, changes),
  /** The bulk-change panel: the same changes to many rows, never applied partially. */
  bulk: (id: string, rows: number[], changes: Partial<Row>) =>
    request<{ rows: Row[] }>('POST', `/api/jobs/${id}/rows/bulk`, {rows, changes}),
  deleteRow: (id: string, n: number) => request<{ ok: boolean; others: Row[]; jobStatus?: string }>('DELETE', `/api/jobs/${id}/rows/${n}`),
  /** Delete selected: deletes every listed document that may be deleted; the others are skipped, each with why. */
  deleteRows: (id: string, rows: number[]) =>
    request<{ deleted: number[]; skipped: { n: number; file: string; code: 'created' | 'changed' | 'missing'; reason: string }[];
      others: Row[]; jobStatus?: string }>('POST', `/api/jobs/${id}/rows/delete`, {rows}),
  /** Check rows against CollectionSpace: the given rows, or (no rows) any whose lookups are stale. */
  check: (id: string, rows?: number[]) =>
    request<{ rows: Row[]; counts: { block: number; warn: number } }>('POST', `/api/jobs/${id}/check`, rows ? {rows} : {}),
  /** Submit job: check the whole job again and add it to the queue; the job comes back with its plan. */
  schedule: (id: string) => request<Job>('POST', `/api/jobs/${id}/schedule`),
  /** Job scheduling (design: Job scheduling): the tenant's run times, pause, and per-job run controls (schedulers). */
  getSchedule: (poll = false) => request<Schedule>('GET', '/api/schedule', undefined, poll),
  putSchedule: (s: { days: number[]; start: string; end: string }) => request<Schedule>('PUT', '/api/schedule', s),
  pauseQueue: (reason: string) => request<Schedule>('POST', '/api/schedule/pause', {reason}),
  resumeQueue: () => request<Schedule>('POST', '/api/schedule/resume'),
  runNow: (id: string, on: boolean) => request<{ job: Job }>('POST', `/api/jobs/${id}/run-now`, {on}),
  runAt: (id: string, at: number | null) => request<{ job: Job }>('POST', `/api/jobs/${id}/run-at`, {at}),
  hold: (id: string, on: boolean) => request<{ job: Job }>('POST', `/api/jobs/${id}/hold`, {on}),
  /** CollectionSpace's date parser (structureddates), for the preview under the Date field. */
  parseDate: (text: string) =>
    request<{ ok: boolean; group: Record<string, string> }>('GET', `/api/dates/parse?text=${encodeURIComponent(text)}`),
  vocabulary: (name: string) => request<{ terms: Term[] }>('GET', `/api/vocabularies/${name}`),
  terms: (field: string, q: string) =>
    request<{ terms: Term[]; total?: number; more?: boolean; message?: string }>('GET', `/api/authorities?field=${encodeURIComponent(field)}&q=${encodeURIComponent(q)}`),
}

export {ApiError}
export type {Check}
