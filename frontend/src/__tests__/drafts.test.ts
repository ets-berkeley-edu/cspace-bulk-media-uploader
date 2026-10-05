import {afterEach, describe, expect, it, vi} from 'vitest'
import {flushPromises, mount} from '@vue/test-utils'
import type {TenantInfo} from '../types'
import DraftsList from '@/components/job/DraftsList.vue'
const tenant = {name: 'PAHMA', handling: [{id: 'link', label: 'Link to existing object', object: 'existing', id_rule: 'object'}]} as unknown as TenantInfo

afterEach(() => { vi.restoreAllMocks() })

const now = Date.now() / 1000
const jobs = [
  {id: 'a', name: 'mine', status: 'Draft', createdBy: 'admin', rowCount: 3, editingBy: 'admin', editingByYou: true, editingSince: now,
    lastSavedBy: 'admin', lastSavedAt: now, expiresAt: now + 30 * 86400},
  {id: 'b', name: 'theirs', status: 'Draft', createdBy: 'jlee', rowCount: 2, editingBy: 'jlee', editingByYou: false, editingSince: 1234,
    lastSavedBy: 'jlee', lastSavedAt: now - 28 * 86400, expiresAt: now + 2 * 86400},
  {id: 'c', name: 'queued', status: 'Queued', createdBy: 'admin', rowCount: 1},
  {id: 'd', name: 'fixing', status: 'Draft', createdBy: 'admin', rowCount: 2, run: 1, lastSavedBy: 'BMU', lastSavedAt: now,
    expiresAt: now + 30 * 86400, note: 'Sign-in expired while waiting in the queue; submit it again to run it with your sign-in.'},
]

function mockApi() {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    const body = url.endsWith('/api/jobs') ? {jobs}
      : url.endsWith('/api/jobs/d') ? {job: jobs[3], rows: [], runs: [], created: {media: 2, files: 1, objects: 1, relations: 4, unfinished: 1}}
      : {rows: [], counts: {block: url.includes('/b/') ? 1 : 0, warn: 0}}
    return Promise.resolve(new Response(JSON.stringify(body), {status: 200, headers: {'content-type': 'application/json'}}))
  }))
}

describe('Drafts tab (design: Drafts)', () => {
  it('lists only drafts, with who is editing, checks now and expiry', async () => {
    mockApi()
    const w = mount(DraftsList, {props: {tenant, staff: true}})
    await flushPromises()
    const text = w.text()
    expect(text).toContain('mine')
    expect(text).toContain('theirs')
    expect(text).not.toContain('queued')
    expect(w.find('#job-a-editing').text()).toBe('You')
    expect(w.find('#job-b-editing').text()).toBe('jlee')
    expect(text).toContain('1 needs fixing')
    expect(w.find('.expires-soon').exists()).toBe(true) // "theirs" expires within 3 days
    w.unmount()
  })

  it('offers Continue editing for your own draft, and Take over (after a warning) for someone else\'s', async () => {
    mockApi()
    const w = mount(DraftsList, {props: {tenant, staff: true}})
    await flushPromises()
    const rowOf = (name: string) => w.findAll('tbody').find((r) => r.text().includes(name))!
    await rowOf('mine').findAll('button').find((b) => b.text() === 'Continue editing')!.trigger('click')
    expect(w.emitted('open')?.[0]).toEqual(['a', 'edit'])
    const theirs = rowOf('theirs')
    expect(theirs.find('button[aria-label="Delete"]').attributes('disabled')).toBeDefined()
    await theirs.findAll('button').find((b) => b.text() === 'Take over…')!.trigger('click')
    expect(w.text()).toContain('their page becomes read-only')
    await rowOf('theirs').findAll('button').find((b) => b.text() === 'Take over and edit')!.trigger('click')
    expect(w.emitted('open')?.[1]).toEqual(['b', 'edit', 1234])
    w.unmount()
  })

  it('shows a draft\'s note, such as a sign-in that expired while it waited in the queue', async () => {
    mockApi()
    const w = mount(DraftsList, {props: {tenant, staff: true}})
    await flushPromises()
    expect(w.findAll('tr.job-row').find((r) => r.text().includes('fixing'))!.text()).toContain('Sign-in expired while waiting in the queue')
    w.unmount()
  })

  it('counts what a job\'s runs created before it is deleted, and says nothing was created for one that never ran', async () => {
    mockApi()
    const w = mount(DraftsList, {props: {tenant, staff: true}})
    await flushPromises()
    const rowOf = (name: string) => w.findAll('tbody').find((r) => r.text().includes(name))!
    await rowOf('fixing').find('button[aria-label="Delete"]').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('Its runs created 2 Media records (1 with its file), 1 Object and 4 Relations, including 1 unfinished document.')
    expect(w.text()).toContain('the BMU never deletes records')
    await w.findAll('button').find((b) => b.text() === 'Cancel')!.trigger('click')
    await rowOf('mine').find('button[aria-label="Delete"]').trigger('click')
    expect(w.text()).toContain('Delete this draft? Its 3 documents and uploaded files are removed from the BMU; it created nothing in CollectionSpace.')
    w.unmount()
  })
})


describe('a job\'s confirmations in a list', () => {
  it('open in a full-width row under the job, with the job\'s buttons off meanwhile', async () => {
    mockApi()
    const w = mount(DraftsList, {props: {tenant, staff: true}})
    await flushPromises()
    const job = w.find('#job-a')
    const confirmRow = job.find('tr.job-confirm-row')
    expect(confirmRow.attributes('style')).toContain('display: none')
    await job.find('#job-a-delete-btn').trigger('click')
    await flushPromises()
    expect(confirmRow.attributes('style') ?? '').not.toContain('display: none')
    expect(confirmRow.find('td').attributes('colspan')).toBe('8')
    expect(confirmRow.find('#job-a-delete-confirm').text()).toContain('Delete this draft?')
    expect(job.find('tr.job-row').text()).not.toContain('Delete this draft?')
    for (const id of ['#job-a-preview-btn', '#job-a-edit-btn', '#job-a-delete-btn']) expect(job.find(id).attributes('disabled')).toBeDefined()
    await job.find('#job-a-delete-cancel-btn').trigger('click')
    await flushPromises()
    expect(confirmRow.attributes('style')).toContain('display: none')
    expect(job.find('#job-a-edit-btn').attributes('disabled')).toBeUndefined()
    w.unmount()
  })

  it('Delete says Deleting… until the server answers', async () => {
    let answer: (r: Response) => void = () => undefined
    const json = (body: unknown) => new Response(JSON.stringify(body), {status: 200, headers: {'content-type': 'application/json'}})
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === 'DELETE') return new Promise<Response>(resolve => { answer = resolve })
      return Promise.resolve(json(url.endsWith('/api/jobs') ? {jobs} : {rows: [], counts: {block: 0, warn: 0}}))
    }))
    const w = mount(DraftsList, {props: {tenant, staff: true}})
    await flushPromises()
    await w.find('#job-a-delete-btn').trigger('click')
    await w.find('#job-a-delete-confirm-btn').trigger('click')
    await flushPromises()
    expect(w.find('#job-a-delete-confirm-btn').text()).toBe('Deleting…')
    expect(w.find('#job-a-delete-confirm-btn').attributes('disabled')).toBeDefined()
    answer(json({}))
    await flushPromises()
    expect(w.find('#job-a-delete-confirm').exists()).toBe(false)
    w.unmount()
  })
})

describe('expanded job documents (design: every table sorts)', () => {
  it('sorts the listed documents by a column heading', async () => {
    const JobDetails = (await import('@/components/job/JobDetails.vue')).default
    const mk = (n: number, file: string) => ({n, file, handling: 'link', include: true, checks: [], upload: {s: 'done'}, result: null}) as never
    const w = mount(JobDetails, {props: {job: {id: 'j', name: 'x', status: 'Queued', rowCount: 2} as never, rows: [mk(1, 'b.jpg'), mk(2, 'a.jpg')],
      tenant, kind: 'queue'}, global: {stubs: {DocumentThumbnail: true}}})
    const names = () => w.findAll('tbody tr').map((t) => t.findAll('td')[1].text())
    expect(names()).toEqual(['b.jpg', 'a.jpg'])
    await w.find('button[aria-label="Sort by Document"]').trigger('click')
    expect(names()).toEqual(['a.jpg', 'b.jpg'])
  })
})
