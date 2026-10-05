import type {CheckCounts, Handling, Perms, Row, TenantInfo} from '../types'

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
export type Tone = 'success' | 'warning' | 'error' | 'info' | 'neutral' | 'creator'

/** Design (Roles, Three kinds of result): not a mistake in the job, so not "Needs fixing" and not its colour. */
export const NEEDS_CREATOR = 'Needs an Object creator'

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
  if (!r.include && r.heldFor === 'creator') return {text: 'Excluded — needs an Object creator', tone: 'creator'}
  if (!r.include) return {text: 'Excluded — ignored', tone: 'info'}
  if (r.result?.state === 'Done') return {text: 'Done in last run', tone: 'success'}
  if (r.result?.state === 'Partial') {
    if (worstLevel(r) === 'block') return {text: 'Needs fixing', tone: 'error'}
    if (worstLevel(r) === 'creator') return {text: NEEDS_CREATOR, tone: 'creator'}
    return {text: checking ? 'Checking…' : 'Partial — rerun finishes it', tone: checking ? 'neutral' : 'warning'}
  }
  const needsObject = tenant.handling.find((x) => x.id === r.handling)?.object !== 'none'
  if (needsObject && !r.parseOk && !r.obj) return {text: 'Fix filename', tone: 'error'}
  if (worstLevel(r) === 'block') return {text: 'Needs fixing', tone: 'error'}
  if (worstLevel(r) === 'creator') return {text: NEEDS_CREATOR, tone: 'creator'}
  if (checking) return {text: 'Checking…', tone: 'neutral'}
  const h = tenant.handling.find((x) => x.id === r.handling)
  if (!h || h.object === 'none') return {text: 'Not linked', tone: 'info'}
  const found = r.lookups?.object?.value === r.obj ? r.lookups.object.csids.length : undefined
  // An existing object blocks "create" (Needs fixing, above); "either" links to it, or creates it when missing
  if (found === undefined) return {text: 'Not checked yet', tone: 'neutral'}
  if (h.object === 'create' || (h.object === 'either' && !found)) return {text: 'Will create object', tone: 'info'}
  return {text: 'Found — will link', tone: 'success'}
}

export function worstLevel(r: Row): 'block' | 'creator' | 'warn' | 'ok' {
  if (r.checks.some((c) => c.level === 'block')) return 'block'
  if (r.checks.some((c) => c.level === 'creator')) return 'creator'
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
    creator: work.filter((r) => worstLevel(r) === 'creator').length,
    held: rows.filter((r) => r.heldFor === 'creator').length,
    warn: work.filter((r) => worstLevel(r) === 'warn').length,
    uploaded: work.filter((r) => r.upload.s === 'done').length,
    uploading: work.filter((r) => ['pending', 'uploading', 'verifying'].includes(r.upload.s)).length,
    uploadFailed: work.filter((r) => r.upload.s === 'failed').length,
  }
}

/**
 * Why the signed-in user can't use a handling option, or "" when they can (design: Permissions in the UI).
 * Missing Media permissions aren't a reason here: staff can't sign in without them (design: Roles). A handling
 * that creates the object is offered to a user who can't create Objects, with a note (handlingNote): they prepare
 * the document for a colleague who can.
 */
export function handlingBlocked(h: Handling, perms: Perms): string {
  if (h.object !== 'none' && perms.readObjects === false) return 'Your account can\'t read Object records, so it can\'t find objects.'
  if (h.object !== 'none' && !perms.relations) return 'Your account can\'t create relations, so it can\'t link to objects.'
  return ''
}

/** What an option in the handling list says after its label for this user. */
export function handlingNote(h: Handling, perms: Perms): string {
  if (handlingBlocked(h, perms)) return ' (no permission)'
  return h.object === 'create' && !perms.objects ? ' (needs an Object creator)' : ''
}

/** The colour of a status chip, from its tone. */
export function chipColor(tone: Tone | undefined): string | undefined {
  return tone && tone !== 'neutral' ? tone : undefined
}

/** The type of a v-alert, from a check's level. */
const ALERT_TYPE: Record<string, 'error' | 'warning' | 'info'> = {block: 'error', warn: 'warning', info: 'info', creator: 'info'}
export function alertType(level: string): 'error' | 'warning' | 'info' {
  return ALERT_TYPE[level] ?? 'info'
}

/** The colour of a check's alert when it isn't its type's own: "Needs an Object creator" has its own. */
export function alertColor(level: string): string | undefined {
  return level === 'creator' ? 'creator' : undefined
}

/** What a check's message starts with. */
export const CHECK_PREFIX: Record<string, string> = {block: 'Must fix: ', creator: `${NEEDS_CREATOR}: `, warn: 'Warning: ', info: ''}

/** "3 need an Object creator", "1 needs an Object creator". */
export const creatorText = (n: number): string => `${n} need${n === 1 ? 's' : ''} an Object creator`

/**
 * A job's checks in a few words: "2 need fixing · 3 need an Object creator · 1 warning", or "nothing to fix".
 * Someone who can create Objects reads "3 new Objects" instead, so they see which drafts wait for them.
 */
export function checksText(c: CheckCounts): string {
  const parts = [c.block ? `${c.block} need${c.block === 1 ? 's' : ''} fixing` : 'nothing to fix']
  if (c.creator) {
    parts.push(creatorText(c.creator))
  } else if (c.newObjects) {
    parts.push(`${c.newObjects} new Object${c.newObjects === 1 ? '' : 's'}`)
  }
  if (c.held) {
    parts.push(`${c.held} left out for an Object creator`)
  }
  if (c.warn) {
    parts.push(`${c.warn} warning${c.warn === 1 ? '' : 's'}`)
  }
  return parts.join(' · ')
}

/** The Vuetify colour of a job's checks chip. */
export function checksColor(c: CheckCounts): string {
  return c.block ? 'error' : c.creator || c.held ? 'creator' : c.warn ? 'warning' : 'success'
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
