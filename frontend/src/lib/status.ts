import type {Handling, Perms, Row, TenantInfo} from '../types'

const ORDINALS = ['first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth']

/** Which run of the job this is, or will be once it starts: 1 for a job that has never run. */
export function runNumber(job: {run?: number, status?: string}): number {
  return Math.max(1, (job.run ?? 0) + (job.status === 'Running' ? 0 : 1))
}

/** The run in words: "first run", "second run", … and "run 11" beyond the tenth. */
export function runName(job: {run?: number, status?: string}): string {
  const n = runNumber(job)
  return n <= ORDINALS.length ? `${ORDINALS[n - 1]} run` : `run ${n}`
}

/** A status's tone: a Vuetify theme colour, or neutral for the plain grey chip. */
export type Tone = 'success' | 'warning' | 'error' | 'info' | 'neutral'

export interface Badge {
  text: string;
  tone: Tone;
}

/** The Status column, as in the design's UI mockup: upload state first, then the row's checks and plan. */
export function rowStatus(r: Row, tenant: TenantInfo, checking = false): Badge {
  if (r.include && r.result?.state !== 'Done') {
    if (r.upload.s === 'uploading') return {text: `Uploading ${r.upload.pct ?? 0}%`, tone: 'info'}
    if (r.upload.s === 'pending') return {text: 'Waiting to upload', tone: 'neutral'}
    if (r.upload.s === 'verifying') return {text: 'Verifying…', tone: 'info'}
    if (r.upload.s === 'failed') return {text: 'Upload failed', tone: 'error'}
  }
  if (!r.include) return {text: 'Excluded — ignored', tone: 'info'}
  if (r.result?.state === 'Done') return {text: 'Done in last run', tone: 'success'}
  if (r.result?.state === 'Partial') {
    if (worstLevel(r) === 'block') return {text: 'Needs fixing', tone: 'error'}
    return {text: checking ? 'Checking…' : 'Partial — rerun finishes it', tone: checking ? 'neutral' : 'warning'}
  }
  const needsObject = tenant.handling.find((x) => x.id === r.handling)?.object !== 'none'
  if (needsObject && !r.parseOk && !r.obj) return {text: 'Fix filename', tone: 'error'}
  if (worstLevel(r) === 'block') return {text: 'Needs fixing', tone: 'error'}
  if (checking) return {text: 'Checking…', tone: 'neutral'}
  const h = tenant.handling.find((x) => x.id === r.handling)
  if (!h || h.object === 'none') return {text: 'Not linked', tone: 'info'}
  const found = r.lookups?.object?.value === r.obj ? r.lookups.object.csids.length : undefined
  // An existing object blocks "create" (Needs fixing, above); "either" links to it, or creates it when missing
  if (found === undefined) return {text: 'Not checked yet', tone: 'neutral'}
  if (h.object === 'create' || (h.object === 'either' && !found)) return {text: 'Will create object', tone: 'info'}
  return {text: 'Found — will link', tone: 'success'}
}

export function worstLevel(r: Row): 'block' | 'warn' | 'ok' {
  if (r.checks.some((c) => c.level === 'block')) return 'block'
  if (r.checks.some((c) => c.level === 'warn')) return 'warn'
  return 'ok'
}

/** Rows the next run would work on: included and not already done. */
export function hasWork(r: Row): boolean {
  return r.include && r.result?.state !== 'Done'
}

export function jobCounts(rows: Row[]) {
  const work = rows.filter(hasWork)
  return {
    total: rows.length,
    disabled: rows.filter((r) => !r.include).length,
    work: work.length,
    block: work.filter((r) => worstLevel(r) === 'block').length,
    warn: work.filter((r) => worstLevel(r) === 'warn').length,
    uploaded: work.filter((r) => r.upload.s === 'done').length,
    uploading: work.filter((r) => ['pending', 'uploading', 'verifying'].includes(r.upload.s)).length,
    uploadFailed: work.filter((r) => r.upload.s === 'failed').length,
  }
}

/**
 * Why the signed-in user can't create or edit jobs, or "" when they can (design: Permissions in the UI). Every
 * job creates Media records and attaches their files, so without create and update on Media the user can only
 * view jobs; the API refuses the changes too (403).
 */
export function editBlocked(perms: Perms): string {
  if (perms.media === false || perms.mediaUpdate === false) return 'Your CollectionSpace account can\'t create and update Media records.'
  return ''
}

/** The longer explanation shown instead of the editor when editBlocked (design: Permissions in the UI). */
export const EDIT_BLOCKED_EXPLAIN = 'Your CollectionSpace account can\'t create and update Media records, so it can\'t create or edit jobs. '
  + 'You can still view them in Drafts, Job queue and Finished jobs.'

/**
 * Why the signed-in user can't use a handling option, or "" when they can (design: Permissions in the UI).
 * Missing Media permissions aren't a reason here: without them the whole editor is unavailable (editBlocked).
 */
export function handlingBlocked(h: Handling, perms: Perms): string {
  if (h.object !== 'none' && perms.readObjects === false) return 'Your account can\'t read Object records, so it can\'t find objects.'
  if (h.object !== 'none' && !perms.relations) return 'Your account can\'t create relations, so it can\'t link to objects.'
  if (h.object === 'create' && !perms.objects) return 'Your account can\'t create Object records.'
  return ''
}

/** The colour of a status chip, from its tone. */
export function chipColor(tone: Tone | undefined): string | undefined {
  return tone && tone !== 'neutral' ? tone : undefined
}

/** The type of a v-alert, from a check's level. */
const ALERT_TYPE: Record<string, 'error' | 'warning' | 'info'> = {block: 'error', warn: 'warning', info: 'info'}
export function alertType(level: string): 'error' | 'warning' | 'info' {
  return ALERT_TYPE[level] ?? 'info'
}

/** A job's checks in a few words: "2 need fixing · 1 warning", or "nothing to fix". */
export function checksText(c: {block: number, warn: number}): string {
  const parts = [c.block ? `${c.block} need${c.block === 1 ? 's' : ''} fixing` : 'nothing to fix']
  if (c.warn) {
    parts.push(`${c.warn} warning${c.warn === 1 ? '' : 's'}`)
  }
  return parts.join(' · ')
}

/** The Vuetify colour of a job's checks chip. */
export function checksColor(c: {block: number, warn: number}): string {
  return c.block ? 'error' : c.warn ? 'warning' : 'success'
}

/** How a job's documents are handled, counted: "3 link to existing object, 1 media only". */
export function handlingMix(rows: Row[], tenant: TenantInfo): string {
  const counts = new Map<string, number>()
  for (const r of rows) {
    const label = tenant.handling.find(h => h.id === r.handling)?.label ?? r.handling
    counts.set(label, (counts.get(label) ?? 0) + 1)
  }
  return [...counts].map(([label, n]) => `${n} ${label.toLowerCase()}`).join(', ') || '—'
}
