/** A job's Delete in Drafts, Job queue and Finished jobs is the trash icon used for a document's delete in the editor. */
import {readFileSync} from 'node:fs'
import {resolve} from 'node:path'
import {describe, expect, it} from 'vitest'
import {mount} from '@vue/test-utils'
import type {Job} from '../types'
import FinishedJobActions from '@/components/job/FinishedJobActions.vue'
import JobActions from '@/components/job/JobActions.vue'

const job = (p: Partial<Job> = {}) => ({id: 'j1', name: 'Spring batch', status: 'Draft', createdBy: 'jlee', rowCount: 1, run: 0, ...p}) as Job
const del = (w: ReturnType<typeof mount>) => w.find('button.job-del')

describe('a job\'s Delete button', () => {
  it('is the trash icon, labelled for screen readers, with a tooltip', () => {
    for (const [j, kind] of [[job(), 'drafts'], [job({status: 'Queued'}), 'queue']] as const) {
      const b = del(mount(JobActions, {props: {job: j, kind, staff: true}}))
      expect(b.find('svg').exists()).toBe(true)
      expect(b.text()).toBe('')
      expect(b.attributes('aria-label')).toBe('Delete')
      expect(b.attributes('id')).toBe('job-j1-delete-btn')
      expect(b.attributes('title')).toBe('Delete job')
      expect(b.attributes('disabled')).toBeUndefined()
    }
  })

  it('keeps the reason as its tooltip when it can\'t be used', () => {
    const b = del(mount(JobActions, {props: {job: job({status: 'Running'}), kind: 'queue', staff: true}}))
    expect(b.attributes('disabled')).toBeDefined()
    expect(b.attributes('title')).toBe('A running job can\'t be deleted')
  })

  it('opens the in-row confirmation when clicked', async () => {
    const w = mount(JobActions, {props: {job: job(), kind: 'drafts', staff: true}})
    await del(w).trigger('click')
    expect(w.text()).toContain('Delete this draft?')
  })

  it('Finished jobs uses it in the list and in the results view', () => {
    const finished = job({status: 'NeedsAttention', run: 1})
    for (const inResults of [false, true]) {
      const w = mount(FinishedJobActions, {props: {job: finished, fixLabel: 'Reschedule', inResults}})
      const b = del(w)
      expect(b.find('svg').exists()).toBe(true)
      expect(b.attributes('aria-label')).toBe('Delete')
      expect(b.attributes('id')).toBe('job-j1-delete-btn')
      expect(w.find('#job-j1-view-results-btn').exists()).toBe(!inResults)
    }
    // Both places use the one component
    const src = readFileSync(resolve(__dirname, '../components/job/FinishedJobs.vue'), 'utf8')
    expect(src.match(/<FinishedJobActions/g)).toHaveLength(2)
  })
})
