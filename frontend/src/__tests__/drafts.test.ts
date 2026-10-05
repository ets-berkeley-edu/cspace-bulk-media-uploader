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
    expect(job.find('#job-a-preview-btn').exists()).toBe(false) // the rows have no Preview button
    for (const id of ['#job-a-edit-btn', '#job-a-delete-btn']) expect(job.find(id).attributes('disabled')).toBeDefined()
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

describe('staff actions on a draft in the list (design: Roles)', () => {
  const draft = {id: 'e', name: 'Box 3', status: 'Draft', createdBy: 'kim', createdByRole: 'intern', internOpen: true, rowCount: 2,
    lastSavedBy: 'lee', lastSavedAt: now, expiresAt: now + 30 * 86400}
  let calls: { url: string; method: string; body: unknown }[] = []
  const stub = (routes: (url: string, method: string) => { status?: number; body: unknown } | undefined, counts: {block: number; warn: number; creator?: number} = {block: 0, warn: 1}) => {
    calls = []
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      calls.push({url, method, body: init?.body ? JSON.parse(init.body as string) : undefined})
      const r = routes(url, method) ?? (url.endsWith('/api/jobs') ? {body: {jobs: [draft]}} : {body: {rows: [], counts}})
      return Promise.resolve(new Response(JSON.stringify(r.body), {status: r.status ?? 200, headers: {'content-type': 'application/json'}}))
    }))
  }

  it('Submit… asks first, saying how much, who prepared it and whose sign-in it runs under; then submits', async () => {
    stub((url) => (url.endsWith('/e/schedule') ? {body: {...draft, status: 'Queued'}} : undefined))
    const w = mount(DraftsList, {props: {tenant, staff: true}})
    await flushPromises()
    expect(w.find('#job-e-access').text()).toBe('Open to interns')
    await w.find('#job-e-submit-btn').trigger('click')
    expect(calls.some((c) => c.url.endsWith('/schedule'))).toBe(false)
    expect(w.find('#job-e-submit-confirm').text()).toContain('Submit “Box 3”? It has 2 documents, 1 with warnings. Created by kim (intern); last saved by lee. '
      + 'The whole job is checked again, and it runs with your sign-in, which is deleted when the run ends.')
    await w.find('#job-e-submit-cancel-btn').trigger('click')
    expect(w.find('#job-e-submit-confirm').exists()).toBe(false)
    await w.find('#job-e-submit-btn').trigger('click')
    await w.find('#job-e-submit-confirm-btn').trigger('click')
    await flushPromises()
    expect(calls.filter((c) => c.url === '/api/jobs/e/schedule' && c.method === 'POST')).toHaveLength(1)
    expect((w.emitted('submitted')![0][0] as {status: string}).status).toBe('Queued')
    w.unmount()
  })

  it('Submit… is off, with the reason, while a document needs fixing', async () => {
    stub(() => undefined, {block: 2, warn: 0})
    const w = mount(DraftsList, {props: {tenant, staff: true}})
    await flushPromises()
    const b = w.find('#job-e-submit-btn')
    expect(b.attributes('disabled')).toBeDefined()
    expect(b.attributes('title')).toBe('Fix or exclude the 2 documents marked Needs fixing first: open the draft with Edit')
    w.unmount()
  })

  it('shows the server\'s reason when the fresh check refuses the submit, and checks the drafts again', async () => {
    stub((url) => (url.endsWith('/e/schedule') ? {status: 409, body: {detail: {message: '1 documents need fixing first.', rows: [2]}}} : undefined))
    const w = mount(DraftsList, {props: {tenant, staff: true}})
    await flushPromises()
    await w.find('#job-e-submit-btn').trigger('click')
    await w.find('#job-e-submit-confirm-btn').trigger('click')
    await flushPromises()
    expect(w.find('#drafts-error').text()).toBe('1 documents need fixing first.')
    expect(w.emitted('submitted')).toBeUndefined()
    expect(calls.filter((c) => c.url.endsWith('/e/check')).length).toBe(2)
    w.unmount()
  })

  it('Submit for review… is off for an intern, with the reason, while a document needs fixing', async () => {
    stub(() => undefined, {block: 1, warn: 0, creator: 2})
    const w = mount(DraftsList, {props: {tenant}})
    await flushPromises()
    const b = w.find('#job-e-hand-over-btn')
    expect(b.attributes('disabled')).toBeDefined()
    expect(b.attributes('title')).toBe('Fix or exclude the document marked Needs fixing first')
    w.unmount()
  })

  it('a document that needs an Object creator does not stop Submit for review', async () => {
    stub(() => undefined, {block: 0, warn: 0, creator: 2})
    const w = mount(DraftsList, {props: {tenant}})
    await flushPromises()
    expect(w.find('#job-e-hand-over-btn').attributes('disabled')).toBeUndefined()
    w.unmount()
  })

  it('marks a draft that was sent for review, and lists it first', async () => {
    const waiting = {...draft, id: 'w', name: 'Waiting', internOpen: false, lastSavedAt: 1, review: {by: 'kim', at: 1791000000}}
    stub((url) => (url.endsWith('/api/jobs') ? {body: {jobs: [{...draft, lastSavedAt: 50}, waiting]}} : undefined))
    const w = mount(DraftsList, {props: {tenant, staff: true}})
    await flushPromises()
    expect(w.find('#job-w-review').text()).toContain('Needs review · sent by kim, ')
    expect(w.find('#job-e-review').exists()).toBe(false)
    const names = w.findAll('[id$="-name"]').map((n) => n.text())
    expect(names.indexOf('Waiting')).toBeLessThan(names.indexOf('Box 3')) // although it was saved longer ago
    w.unmount()
  })

  it('the setting is changed with one click, and the list says what happened', async () => {
    stub((url) => (url.endsWith('/intern-access') ? {body: {...draft, internOpen: false}} : undefined))
    const w = mount(DraftsList, {props: {tenant, staff: true}})
    await flushPromises()
    const b = w.find('#job-e-access-btn')
    expect(b.text()).toBe('Make staff only')
    await b.trigger('click')
    await flushPromises()
    expect(calls.find((c) => c.url === '/api/jobs/e/intern-access')!.body).toEqual({open: false})
    expect(w.find('#drafts-message').text()).toBe('“Box 3” is now staff only.')
    w.unmount()
  })

  it('an intern submits a draft for review after confirming, and has no Submit or setting', async () => {
    stub((url) => (url.endsWith('/review') ? {body: {...draft, internOpen: false, review: {by: 'kim', at: 1}}} : undefined))
    const w = mount(DraftsList, {props: {tenant}})
    await flushPromises()
    expect(w.find('#job-e-submit-btn').exists()).toBe(false)
    expect(w.find('#job-e-access-btn').exists()).toBe(false)
    await w.find('#job-e-hand-over-btn').trigger('click')
    expect(w.find('#job-e-handover-confirm').text()).toContain('You won\'t be able to edit it afterwards unless a staff member opens it to interns again.')
    expect(w.find('#job-e-hand-over-btn').text()).toBe('Submit for review…')
    expect(calls.some((c) => c.url.endsWith('/review'))).toBe(false)
    await w.find('#job-e-handover-confirm-btn').trigger('click')
    await flushPromises()
    expect(calls.some((c) => c.url === '/api/jobs/e/review' && c.method === 'POST')).toBe(true)
    expect(w.find('#drafts-message').text()).toBe('“Box 3” was sent to staff for review.')
    w.unmount()
  })
})
