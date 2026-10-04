/**
 * Finished jobs: results per document, the failure catalog's wording, and whether a job needs a fix before
 * it can be rerun (design: Finished jobs and error messages; Fixing a job after a run).
 */
import {ref} from 'vue'
import {api} from '../api'
import type {Created, Failure, Handling, Job, ResultCounts, Row, Step} from '../types'
import type {Tone} from './status'

// ---- the failure catalog, loaded once and shared ----------------------------------------------------
export const failures = ref<Record<string, Failure>>({})
let loading: Promise<void> | null = null
export function loadFailures(): Promise<void> {
  loading ??= api.failures().then((r) => { failures.value = r.failures }).catch(() => { loading = null })
  return loading
}

const UNKNOWN: Failure = {
  title: 'Unexpected problem', level: 'any', needs_fix: false,
  explain: 'Something went wrong that the BMU doesn\'t have a specific message for.',
  fix: 'Reschedule the job. If it happens again, contact support with the technical detail.',
}
/** The catalog entry for a code; an unrecognized code reads as "Unexpected problem". */
export function failureOf(code: string | undefined | null, catalog: Record<string, Failure> = failures.value): Failure {
  return (code && catalog[code]) || catalog.unknown || UNKNOWN
}

// ---- results --------------------------------------------------------------------------------------
export type ResultState = 'Done' | 'Partial' | 'Failed' | 'Not started' | 'In progress' | 'Excluded';

/** A document's result as the results view shows it: excluded documents that still had work read "Excluded". */
export function resultState(r: Row): ResultState {
  const s = r.result?.state ?? 'Not started'
  if (!r.include && s !== 'Done') return 'Excluded'
  return s
}

export const RESULT_TONE: Record<ResultState, Tone> = {
  Done: 'success', Partial: 'warning', Failed: 'error', 'Not started': 'info', 'In progress': 'info', Excluded: 'neutral',
}

export function resultCounts(rows: Row[]): ResultCounts {
  const c: ResultCounts = {done: 0, partial: 0, failed: 0, notStarted: 0, disabled: 0}
  for (const r of rows) {
    const s = resultState(r)
    if (s === 'Done') c.done++
    else if (s === 'Partial') c.partial++
    else if (s === 'Failed') c.failed++
    else if (s === 'Excluded') c.disabled++
    else c.notStarted++
  }
  return c
}

export function countsText(c: ResultCounts | undefined): string {
  if (!c) return '—'
  const parts: string[] = []
  if (c.done) parts.push(`${c.done} done`)
  if (c.partial) parts.push(`${c.partial} partial`)
  if (c.failed) parts.push(`${c.failed} failed`)
  if (c.notStarted) parts.push(`${c.notStarted} not started`)
  if (c.disabled) parts.push(`${c.disabled} excluded`)
  return parts.join(' · ') || 'no documents'
}

export const OUTCOME: Record<string, {text: string, tone: Tone}> = {
  Completed: {text: 'Completed', tone: 'success'},
  NeedsAttention: {text: 'Needs attention', tone: 'warning'},
  Failed: {text: 'Failed', tone: 'error'},
  Running: {text: 'Running', tone: 'info'},
}

/** The failure codes recorded on a document's steps (its first error first). */
export function rowCodes(r: Row): string[] {
  const codes = Object.values(r.result?.steps ?? {}).filter((s) => s.s === 'failed' && s.code).map((s) => s.code!)
  const first = r.result?.error?.code
  return [...new Set(first ? [first, ...codes] : codes)]
}

/**
 * Design: the button reads "Fix and reschedule" when any included document (or the job) has a failure that needs
 * a change before it can succeed, or any document fails a blocking check now; "Reschedule" when every failure
 * only needs another run.
 */
export function needsFix(job: Job, rows: Row[], blockingNow: number, catalog: Record<string, Failure> = failures.value): boolean {
  if (job.code && failureOf(job.code, catalog).needs_fix) return true
  if (blockingNow > 0) return true
  return rows.some((r) => r.include && r.result?.state !== 'Done' && rowCodes(r).some((c) => failureOf(c, catalog).needs_fix))
}

const RANK: Record<ResultState, number> = {Failed: 0, Partial: 1, 'In progress': 2, 'Not started': 3, Excluded: 4, Done: 5}
/** The documents that matter most, problems first (the expanded job row shows 10). */
export function importantRows(rows: Row[], n = 10): Row[] {
  return rows.map((r, i) => ({r, i})).sort((a, b) => RANK[resultState(a.r)] - RANK[resultState(b.r)] || a.i - b.i)
    .slice(0, n).map((x) => x.r)
}

// ---- steps ----------------------------------------------------------------------------------------
// In the order a document's steps run. "values": the worker checks the document's values against CollectionSpace
// again just before creating its records (failure value_missing; see backend worker.plan_steps).
export const STEP_LABEL: Record<string, string> = {
  values: 'Check the document in CollectionSpace', media: 'Create Media record', findObject: 'Find object', createObject: 'Create object', findOrCreateObject: 'Find or create object',
  upload: 'Upload file (creates the Blob)', relMediaObject: 'Relate Media → Object', relObjectMedia: 'Relate Object → Media',
  addToGroup: 'Add object to the job\'s group',
}
export const STEP_MARK: Record<Step['s'], string> = {done: '✓', failed: '✗', skipped: '–', 'not run': '·', 'not needed': '○'}

const STEP_ORDER = Object.keys(STEP_LABEL)
const stepRank = (k: string) => (STEP_ORDER.includes(k) ? STEP_ORDER.indexOf(k) : STEP_ORDER.length)

/** A document's recorded steps in the order they run (a step added in a later run, like the value check, keeps its place). */
export function stepList(r: Row): { key: string; label: string; step: Step }[] {
  return Object.entries(r.result?.steps ?? {}).sort(([a], [b]) => stepRank(a) - stepRank(b))
    .map(([key, step]) => ({key, label: STEP_LABEL[key] ?? key, step}))
}

export function stepNote(key: string, st: Step): string {
  if (st.s === 'skipped' && st.after === 'group') return 'skipped: the job\'s group couldn\'t be created'
  if (st.s === 'skipped') {
    const needs = STEP_LABEL[st.after ?? ''] ?? st.after ?? ''
    return `skipped: needs ${needs.charAt(0).toLowerCase()}${needs.slice(1)}` // "check values in CollectionSpace"
  }
  if (st.s === 'done' && st.sameAs) return `added by document ${st.sameAs}`
  if (st.s === 'not needed') return key === 'addToGroup' ? 'not needed: left out of the group' : 'not needed: you stopped linking this document'
  if (st.s === 'not run') return 'not run'
  if (st.s === 'done' && st.found) return OBJ_STEPS.includes(key) ? 'found' : 'existing'
  return ''
}

/**
 * "2 Media records (1 with its file), 1 Object and 2 Relations" for the job-deletion warning; zero counts are
 * left out, so a job that only created an Object reads "1 Object" (design: Deleting a job; UI mockup createdSummary).
 */
export function createdText(c: Created): string {
  const n = (k: number, one: string, many: string) => `${k} ${k === 1 ? one : many}`
  const parts: string[] = []
  if (c.media) parts.push(n(c.media, 'Media record', 'Media records') + (c.files ? ` (${c.files} with ${c.files === 1 ? 'its file' : 'their files'})` : ''))
  if (c.objects) parts.push(n(c.objects, 'Object', 'Objects'))
  if (c.groups) parts.push('the job\'s group')
  if (c.relations) parts.push(n(c.relations, 'Relation', 'Relations'))
  if (!parts.length) return 'no records'
  return parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}` : parts[0]
}

// ---- fixing a job after a run: what each document may still change (mirrors backend rows.fix_fields) ------
const FINISHED_STEP = ['done', 'not needed']
const OBJ_STEPS = ['findObject', 'createObject', 'findOrCreateObject']
const REL_STEPS = ['relMediaObject', 'relObjectMedia']
const openSteps = (r: Row, names: string[]) =>
  names.filter((n) => r.result?.steps?.[n] && !FINISHED_STEP.includes(r.result.steps[n].s))

/** The document's Media record exists in CollectionSpace (Partial, or Done). */
export function mediaCreated(r: Row): boolean {
  return r.result?.steps?.media?.s === 'done'
}

/** A Failed document whose object step already ran keeps its object: its handling and object number are fixed. */
export function objectStepRan(r: Row): boolean {
  return OBJ_STEPS.some((n) => r.result?.steps?.[n]?.s === 'done')
}

/** Created anything in CollectionSpace (finding an existing object doesn't count), so it can't be deleted. */
export function createdSomething(r: Row): boolean {
  // A document the worker was on when a run stopped may have created a record whose CSID wasn't recorded.
  if (r.result?.state === 'In progress' || r.result?.interrupted) return true
  return Object.entries(r.result?.steps ?? {}).some(([k, s]) => k !== 'findObject' && !!s.csid && !s.found && !s.sameAs)
}

/**
 * What a document whose Media record exists may still change: only what the rerun needs. After object_exists
 * ("Create new object + link" found the object already there) that includes the handling, but only to one that
 * links to an existing object (RELINK_OBJECT).
 */
export function fixFields(r: Row): { obj: boolean; skipLink: boolean; handling: boolean } {
  const steps = r.result?.steps ?? {}
  const failed = (names: string[]) => names.filter((n) => steps[n]?.s === 'failed').map((n) => steps[n].code ?? '')
  const obj = failed(OBJ_STEPS)
  const rel = failed(REL_STEPS)
  return {
    obj: obj.some((c) => ['object_gone', 'object_ambiguous', 'object_rejected', 'object_exists'].includes(c)) && !r.skipLink,
    skipLink: openSteps(r, REL_STEPS).length > 0
      && (obj.some((c) => ['object_gone', 'object_ambiguous', 'object_exists'].includes(c)) || rel.includes('no_permission')),
    handling: obj.includes('object_exists') && !r.skipLink,
  }
}

/** The object behaviors a document can switch to after object_exists: those that link to the existing object. */
export const RELINK_OBJECT: Handling['object'][] = ['existing', 'either']

/** The document's check found its staged file gone, or not what its name says, before anything was created. */
export function fileCheckFailed(r: Row): boolean {
  const check = r.result?.steps?.values
  return !mediaCreated(r) && check?.s === 'failed' && ['file_missing', 'file_type_rejected'].includes(check.code ?? '')
}

/** A replacement file is for a document whose file didn't reach CollectionSpace: its Media record exists and the
 *  upload hasn't succeeded, or its check failed on the file before anything was created (mirrors rows.can_replace_file). */
export function canReplaceFile(r: Row): boolean {
  return r.include && ((mediaCreated(r) && openSteps(r, ['upload']).length > 0) || fileCheckFailed(r))
}
