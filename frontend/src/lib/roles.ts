import type {Job, Me, Perms} from '@/types'

/**
 * The two BMU roles (design: Roles). Staff do everything. An intern creates drafts and edits the drafts that are
 * open to interns; everything else is view-only for them. The server enforces all of it; these say why a control
 * is off.
 */
export const STAFF_ONLY_WHY = 'Only staff can do this.'
export const STAFF_DRAFT_WHY = 'This draft is for staff only.'
export const RAN_DELETE_WHY = 'This job has already run, so only staff can delete it.'
export const STAFF_EDITING_WHY = 'A staff member is editing this draft. Only staff can take it over.'

export const isStaff = (me: Pick<Me, 'role'>): boolean => me.role === 'staff'

/** Why this user can't change a queued, running or finished job: '' for staff. */
export const staffOnly = (me: Pick<Me, 'role'>): string => (isStaff(me) ? '' : STAFF_ONLY_WHY)

/** Why this user can't edit the draft: '' for staff, and for an intern when the draft is open to interns. */
export const draftBlocked = (job: Pick<Job, 'internOpen'>, staff: boolean): string => (staff || job.internOpen ? '' : STAFF_DRAFT_WHY)

/** Why this user can't take the draft over from whoever has it open: an intern can't take over from staff. */
export const takeOverBlocked = (job: Pick<Job, 'internOpen' | 'editingRole'>, staff: boolean): string => (
  draftBlocked(job, staff) || (!staff && (job.editingRole ?? 'staff') === 'staff' ? STAFF_EDITING_WHY : ''))

/** Why this user can't delete the draft: an intern deletes only a draft that has never run. */
export const draftDeleteBlocked = (job: Pick<Job, 'internOpen' | 'run' | 'fixFrom'>, staff: boolean): string => (
  draftBlocked(job, staff) || (!staff && (job.run || job.fixFrom) ? RAN_DELETE_WHY : ''))

export const INTERN_SUBMIT_WHY = 'Only staff can submit a job. A staff member submits it when the draft is ready.'

const EVERY_PERMISSION: Perms = {media: true, mediaUpdate: true, relations: true, objects: true, readObjects: true, authorities: true,
  groups: true, readMedia: true, readPersons: true, readOrgs: true, readDates: true}

/**
 * The permissions the editor's controls go by. An intern's account has none, and the intern acts for the staff
 * member who will submit the draft, so nothing is switched off for them on that account (design: Roles).
 */
export const permsFor = (me: Pick<Me, 'role' | 'perms'>): Perms => (isStaff(me) ? me.perms : EVERY_PERMISSION)

/** "Open to interns" or "Staff only": whether interns may edit the draft. */
export const accessLabel = (job: Pick<Job, 'internOpen'>): string => (job.internOpen ? 'Open to interns' : 'Staff only')

export const HAND_OVER_CONFIRM = 'Hand this draft over to staff? You won\'t be able to edit it afterwards unless a staff member opens it to interns again.'

/**
 * Why a draft can't be submitted from the Drafts list or its preview, or '' when it can: the server checks the
 * whole job again whatever this says. counts: the draft's latest checks; undefined while they are running.
 */
export function listSubmitBlocked(job: Pick<Job, 'rowCount' | 'editingBy' | 'editingByYou' | 'groupOn' | 'groupTitle'>,
  counts?: { block: number; warn: number } | null): string {
  if (job.editingBy && !job.editingByYou) return `${job.editingBy} is editing this draft`
  if (!job.rowCount) return 'This draft has no documents'
  if (!counts) return 'Checking against CollectionSpace…'
  if (counts.block) return `Fix or exclude the ${counts.block === 1 ? 'document' : `${counts.block} documents`} marked Needs fixing first: open the draft with Edit`
  if (job.groupOn && !job.groupTitle?.trim()) return 'Enter a group title, or turn off the job\'s group: open the draft with Edit'
  return ''
}

/** What the Submit confirmation says: how much is submitted, who prepared it, and whose sign-in it runs under. */
export function submitConfirmText(job: Pick<Job, 'name' | 'rowCount' | 'createdBy' | 'createdByRole' | 'lastSavedBy'>,
  counts?: { block: number; warn: number } | null): string {
  const n = job.rowCount ?? 0
  const warn = counts?.warn ?? 0
  const docs = `It has ${n === 1 ? '1 document' : `${n} documents`}${warn ? `, ${warn} with warnings` : ''}.`
  const by = job.createdBy ? ` Created by ${job.createdBy}${job.createdByRole ? ` (${job.createdByRole})` : ''}` : ''
  const saved = job.lastSavedBy ? `${by ? ';' : ''} ${by ? 'l' : 'L'}ast saved by ${job.lastSavedBy}` : ''
  return `Submit “${job.name || 'Untitled job'}”? ${docs}${by}${saved}${by || saved ? '.' : ''} `
    + 'The whole job is checked again, and it runs with your sign-in, which is deleted when the run ends.'
}
