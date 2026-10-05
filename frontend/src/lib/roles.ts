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
