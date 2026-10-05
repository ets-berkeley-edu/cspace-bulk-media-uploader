import {afterEach, describe, expect, it, vi} from 'vitest'
import {flushPromises, mount} from '@vue/test-utils'
import type {Job, Me, Perms, Row, TenantInfo} from '../types'
import JobEditor from '@/components/job/JobEditor.vue'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

const tenant = {key: 'pahma', name: 'PAHMA', filenameHint: '', filenamePattern: '^(?P<obj>[A-Za-z0-9.-]+)$', mediaTypes: [], languageDefault: '',
  authorityFields: {}, publish: {field: 'approvedForWeb', header: 'Restricted', invert: true},
  handling: [{id: 'none', label: 'Media only', object: 'none', id_rule: 'image'}]} as unknown as TenantInfo
const perms: Perms = {media: true, mediaUpdate: true, relations: true, objects: true, readObjects: true, authorities: true, groups: true}
const me: Me = {user: 'admin', tenant, perms, role: 'staff'}
const row: Row = {n: 1, file: 'a.jpg', size: 10, contentType: 'image/jpeg', handling: 'none', obj: '', objParsed: '', img: 'a', parseOk: true,
  idnum: 'a', date: '', restricted: false, type: [], creator: '', contributor: '', rightsHolder: '', description: '', copyright: '', include: true,
  upload: {s: 'done'}, checks: [], result: null}
const draft = {id: 'j1', name: 'Spring batch', status: 'Draft', createdBy: 'admin', rowCount: 1, run: 0, editingBy: 'admin', editingByYou: true} as Job
const plan = {kind: 'schedule', at: Date.now() / 1000 + 3 * 86400, ahead: 2, signInExpiresFirst: false} as const

function stub(routes: (url: string, method: string) => unknown) {
  const calls: { url: string; method: string; body?: string }[] = []
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    calls.push({url, method, body: typeof init?.body === 'string' ? init.body : undefined})
    return Promise.resolve(new Response(JSON.stringify(routes(url, method) ?? {}), {status: 200, headers: {'content-type': 'application/json'}}))
  }))
  return calls
}

describe('Submit job (design: Job scheduling)', () => {
  it('the editor\'s button reads Submit job and submits through POST …/schedule', async () => {
    const calls = stub((url, method) => {
      if (url.endsWith('/api/jobs/j1') && method === 'GET') return {job: draft, rows: [row], runs: [], created: {}}
      if (url.endsWith('/check')) return {rows: [row], counts: {block: 0, warn: 0}}
      if (url.endsWith('/api/jobs/j1') && method === 'PATCH') return draft
      if (url.endsWith('/j1/schedule')) return {...draft, status: 'Queued', plan}
      if (url.includes('/vocabularies/')) return {terms: []}
      if (url.endsWith('/api/failures')) return {failures: {}}
      return {}
    })
    const w = mount(JobEditor, {props: {me, jobId: 'j1'}, global: {stubs: {DocumentThumbnail: true}}})
    await flushPromises()
    const submit = w.findAll('button').find((b) => b.text() === 'Submit job')!
    expect(w.findAll('button').some((b) => b.text() === 'Schedule job')).toBe(false)
    expect(submit.attributes('title')).toBe('Check the whole job again, then add it to the job queue; it runs at the next run time')
    expect(w.text()).toContain('Submit job moves it to the job queue.')
    await submit.trigger('click')
    await flushPromises()
    expect(calls.some((c) => c.url.endsWith('/j1/schedule') && c.method === 'POST')).toBe(true)
    expect((w.emitted('scheduled')?.[0][0] as Job).plan).toEqual(plan)
    w.unmount()
  })
})

describe('an intern in the editor (design: Roles)', () => {
  it('cannot submit, with the reason; nothing is switched off for lack of permissions', async () => {
    const calls = stub((url, method) => {
      if (url.endsWith('/api/jobs/j1') && method === 'GET') return {job: {...draft, editingBy: 'kim', internOpen: true}, rows: [row], runs: [], created: {}}
      if (url.endsWith('/check')) return {rows: [row], counts: {block: 0, warn: 0}}
      if (url.includes('/vocabularies/')) return {terms: []}
      if (url.endsWith('/api/failures')) return {failures: {}}
      return {}
    })
    const none: Perms = {media: false, mediaUpdate: false, relations: false, objects: false, readObjects: false, authorities: false, groups: false}
    const w = mount(JobEditor, {props: {me: {...me, user: 'kim', role: 'intern', perms: none}, jobId: 'j1'}, global: {stubs: {DocumentThumbnail: true}}})
    await flushPromises()
    const submit = w.findAll('button').find((b) => b.text() === 'Submit job')!
    expect(submit.attributes('disabled')).toBeDefined()
    expect(submit.attributes('title')).toBe('Only staff can submit a job. A staff member submits it when the draft is ready.')
    await submit.trigger('click')
    expect(calls.some((c) => c.url.endsWith('/j1/schedule'))).toBe(false)
    // the group box is offered although the intern's own account can't create groups: they act for the submitter
    expect(w.find('#group-on').attributes('disabled')).toBeUndefined()
    expect(w.text()).not.toContain('Your account can\'t create groups.')
    expect(w.text()).not.toContain('(no permission)')
    w.unmount()
  })
})

describe('whether interns may edit the draft, in the editor (design: Roles)', () => {
  const routes = (j: Job) => (url: string, method: string) => {
    if (url.endsWith('/api/jobs/j1') && method === 'GET') return {job: j, rows: [row], runs: [], created: {}}
    if (url.endsWith('/check')) return {rows: [row], counts: {block: 0, warn: 0}}
    if (url.endsWith('/intern-access')) return {...j, internOpen: !j.internOpen}
    if (url.includes('/vocabularies/')) return {terms: []}
    if (url.endsWith('/api/failures')) return {failures: {}}
    return {}
  }

  it('staff tick or untick "Open to interns"', async () => {
    const calls = stub(routes(draft))
    const w = mount(JobEditor, {props: {me, jobId: 'j1'}, global: {stubs: {DocumentThumbnail: true}}})
    await flushPromises()
    const box = w.find('#intern-open')
    expect((box.element as HTMLInputElement).checked).toBe(false)
    expect(w.find('#intern-open-hint').text()).toBe('Only staff can edit this draft.')
    expect(w.find('#hand-over-btn').exists()).toBe(false)
    await box.setValue(true)
    await flushPromises()
    expect(calls.some((c) => c.url === '/api/jobs/j1/intern-access' && c.method === 'POST')).toBe(true)
    expect(w.find('#intern-open-hint').text()).toBe('Interns can edit this draft.')
    w.unmount()
  })

  it('Submit for review… is off in the editor while a document needs fixing, and staff see who sent a draft', async () => {
    const bad: Row = {...row, checks: [{level: 'block', text: 'No object 20-1 in CollectionSpace.'}]}
    stub((url, method) => {
      if (url.endsWith('/api/jobs/j1') && method === 'GET') return {job: {...draft, editingBy: 'kim', internOpen: true}, rows: [bad], runs: [], created: {}}
      if (url.endsWith('/check')) return {rows: [bad], counts: {block: 1, warn: 0}}
      if (url.includes('/vocabularies/')) return {terms: []}
      if (url.endsWith('/api/failures')) return {failures: {}}
      return {}
    })
    const w = mount(JobEditor, {props: {me: {...me, user: 'kim', role: 'intern'}, jobId: 'j1'}, global: {stubs: {DocumentThumbnail: true}}})
    await flushPromises()
    expect(w.find('#hand-over-btn').text()).toBe('Submit for review…')
    expect(w.find('#hand-over-btn').attributes('disabled')).toBeDefined()
    expect(w.find('#hand-over-btn').attributes('title')).toBe('Fix or exclude the documents marked Needs fixing first')
    w.unmount()

    stub(routes({...draft, review: {by: 'kim', at: 1791000000}} as Job))
    const staffView = mount(JobEditor, {props: {me, jobId: 'j1'}, global: {stubs: {DocumentThumbnail: true}}})
    await flushPromises()
    expect(staffView.find('#review-note').text()).toContain('kim sent this draft for review on ')
    expect(staffView.find('#review-note').text()).toContain('To send it back, tick “Open to interns”.')
    staffView.unmount()
  })

  it('an intern submits the draft for review after confirming, and the editor is told', async () => {
    const calls = stub(routes({...draft, name: 'Box 3', editingBy: 'kim', internOpen: true} as Job))
    const w = mount(JobEditor, {props: {me: {...me, user: 'kim', role: 'intern'}, jobId: 'j1'}, global: {stubs: {DocumentThumbnail: true}}})
    await flushPromises()
    expect(w.find('#intern-open').exists()).toBe(false)
    await w.find('#hand-over-btn').trigger('click')
    expect(w.find('#hand-over-confirm').text()).toContain('Submit this draft for review?')
    expect(calls.some((c) => c.url.endsWith('/review'))).toBe(false)
    await w.find('#hand-over-confirm-btn').trigger('click')
    await flushPromises()
    expect(calls.some((c) => c.url === '/api/jobs/j1/review' && c.method === 'POST')).toBe(true)
    expect(w.emitted('handedOver')![0]).toEqual(['Box 3'])
    w.unmount()
  })
})

describe('the job\'s Group title (user decision: never derived from the job name)', () => {
  it('starts empty and required; the buttons fill it once and renaming the job doesn\'t change it', async () => {
    let job: Job = {...draft, groupOn: true, groupTitle: ''} as Job
    const patches: Record<string, unknown>[] = []
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      let body: unknown = {}
      if (url.endsWith('/api/jobs/j1') && method === 'GET') body = {job, rows: [row], runs: [], created: {}}
      else if (url.endsWith('/check')) body = {rows: [row], counts: {block: 0, warn: 0}}
      else if (url.endsWith('/api/jobs/j1') && method === 'PATCH') {
        const f = JSON.parse(String(init?.body))
        patches.push(f)
        job = {...job, ...f}
        body = job
      } else if (url.includes('/vocabularies/')) body = {terms: []}
      else if (url.endsWith('/api/failures')) body = {failures: {}}
      return Promise.resolve(new Response(JSON.stringify(body), {status: 200, headers: {'content-type': 'application/json'}}))
    }))
    vi.useFakeTimers({toFake: ['Date']})
    vi.setSystemTime(new Date(Date.UTC(2026, 8, 30, 20, 1, 2))) // 1:01:02 PM Pacific
    try {
      const w = mount(JobEditor, {props: {me, jobId: 'j1'}, global: {stubs: {DocumentThumbnail: true}}})
      await flushPromises()
      const title = w.find('input[aria-label="Group title"]')
      const btn = (t: string) => w.findAll('button').find((b) => b.text() === t)!
      expect((title.element as HTMLInputElement).value).toBe('')
      expect(btn('Submit job').attributes('title')).toBe('Enter a group title, or turn off the job\'s group')
      const nameInput = w.find('input[placeholder="e.g. 2026 spring accession batch"]')
      await nameInput.setValue('Spring  batch #2')
      await btn('Use the job name').trigger('click')
      await flushPromises()
      expect(patches.at(-1)).toEqual({groupTitle: 'Spring  batch #2'}) // exactly as typed
      expect((title.element as HTMLInputElement).value).toBe('Spring  batch #2')
      await nameInput.setValue('Renamed')
      await nameInput.trigger('change')
      await flushPromises()
      expect(patches.at(-1)).toEqual({name: 'Renamed'})
      expect((title.element as HTMLInputElement).value).toBe('Spring  batch #2')
      await btn('Use a timestamp').trigger('click')
      await flushPromises()
      expect(patches.at(-1)).toEqual({groupTitle: 'bmu-2026-09-30-13-01-02'})
      expect((title.element as HTMLInputElement).value).toBe('bmu-2026-09-30-13-01-02')
      w.unmount()
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('three kinds of result in the editor (design: Roles)', () => {
  const linked = {...tenant, handling: [...tenant.handling, {id: 'linkorcreate', label: 'Link to object (create if missing)', object: 'either', id_rule: 'object'}]} as unknown as TenantInfo
  const waiting: Row = {...row, n: 2, file: '20-1.jpg', handling: 'linkorcreate', obj: '20-1',
    checks: [{level: 'creator', text: 'No object 20-1 in CollectionSpace, so this document needs a new Object, and your account can\'t create Object records.'}]}
  const routes = (rows: Row[], job: Job = draft) => (url: string, method: string) => {
    if (url.endsWith('/api/jobs/j1') && method === 'GET') return {job, rows, runs: [], created: {}}
    if (url.endsWith('/check')) return {rows, counts: {block: 0, warn: 0, creator: 1}}
    if (url.endsWith('/api/jobs/j1') && method === 'PATCH') return job
    if (url.endsWith('/j1/schedule')) return {...job, status: 'Queued', plan}
    if (url.includes('/vocabularies/')) return {terms: []}
    if (url.endsWith('/api/failures')) return {failures: {}}
    return {}
  }

  it('a document that needs an Object creator stops Submit; the job is submitted whole by someone who can create Objects', async () => {
    const calls = stub(routes([row, waiting]))
    const limited: Me = {user: 'limited', tenant: linked, perms: {...perms, objects: false}, role: 'staff'}
    const w = mount(JobEditor, {props: {me: limited, jobId: 'j1'}, global: {stubs: {DocumentThumbnail: true}}})
    await flushPromises()
    expect(w.find('#creator-note').text()).toContain('1 document needs a new Object, which your account can\'t create, so you can\'t submit this job.')
    expect(w.find('#creator-note').text()).toContain('Leave the draft for a colleague who can create Objects')
    expect(w.find('#document-counts').text()).toContain('nothing to fix · 1 needs an Object creator')
    expect(w.find('#submit-job-btn').attributes('disabled')).toBeDefined()
    expect(w.find('#submit-job-btn').attributes('title')).toContain('leave the draft for a colleague who can create Objects')
    expect(w.findAll('button').some((b) => b.text().startsWith('Submit without'))).toBe(false) // no submitting only the rest
    expect(calls.some((c) => c.url.endsWith('/j1/schedule'))).toBe(false)
    w.unmount()
  })

  it('a missing permission to create groups is said once, beside the group, and stops only Submit', async () => {
    const inGroup: Row = {...row, n: 2, file: '15-1.jpg', handling: 'linkorcreate', obj: '15-1'}
    stub(routes([inGroup], {...draft, groupOn: true, groupTitle: 'Batch 4'} as Job))
    const noGroups: Me = {user: 'limited', tenant: linked, perms: {...perms, groups: false}, role: 'staff'}
    const w = mount(JobEditor, {props: {me: noGroups, jobId: 'j1'}, global: {stubs: {DocumentThumbnail: true}}})
    await flushPromises()
    expect(w.find('#group-account-problem').text()).toContain('Contact your CollectionSpace administrator')
    expect(w.find('#group-on').attributes('disabled')).toBeUndefined() // the group can still be set up for a colleague
    expect(w.find('#submit-job-btn').attributes('disabled')).toBeDefined()
    expect(w.text()).not.toContain('Needs fixing')
    w.unmount()
  })

  it('an intern is told a new Object is needed, as information for whoever submits', async () => {
    const forIntern: Row = {...waiting, checks: [{level: 'creator', text: 'This document needs a new Object. The staff member who submits the job must be able to create Objects.'}]}
    stub(routes([row, forIntern], {...draft, editingBy: 'kim', internOpen: true} as Job))
    const intern: Me = {user: 'kim', tenant: linked, perms: {...perms, media: false, relations: false, objects: false, groups: false}, role: 'intern'}
    const w = mount(JobEditor, {props: {me: intern, jobId: 'j1'}, global: {stubs: {DocumentThumbnail: true}}})
    await flushPromises()
    expect(w.find('#creator-note').text()).toContain('The staff member who submits this job must be able to create Objects.')
    w.unmount()
  })
})

describe('"With problems" (design: Roles, Three kinds of result)', () => {
  it('does not count a document that needs an Object creator: it has its own filter', async () => {
    const linked = {...tenant, handling: [...tenant.handling, {id: 'linkorcreate', label: 'Link to object (create if missing)', object: 'either', id_rule: 'object'}]} as unknown as TenantInfo
    const waiting: Row = {...row, n: 2, file: '20-1.jpg', handling: 'linkorcreate', obj: '20-1', checks: [{level: 'creator', text: 'This document needs a new Object.'}]}
    const warned: Row = {...row, n: 3, file: 'b.jpg', checks: [{level: 'warn', text: 'A Media record with ID b already exists in CollectionSpace.'}]}
    stub((url, method) => {
      if (url.endsWith('/api/jobs/j1') && method === 'GET') return {job: draft, rows: [row, waiting, warned], runs: [], created: {}}
      if (url.endsWith('/check')) return {rows: [row, waiting, warned], counts: {block: 0, warn: 1, creator: 1}}
      if (url.includes('/vocabularies/')) return {terms: []}
      if (url.endsWith('/api/failures')) return {failures: {}}
      return {}
    })
    const limited: Me = {user: 'limited', tenant: linked, perms: {...perms, objects: false}, role: 'staff'}
    const w = mount(JobEditor, {props: {me: limited, jobId: 'j1'}, global: {stubs: {DocumentThumbnail: true}}})
    await flushPromises()
    const options = w.findAll('option').map((o) => o.text())
    expect(options).toContain('With problems (1)')
    expect(options).toContain('Need an Object creator (1)')
    expect(w.find('#show-problems-btn').exists()).toBe(true) // for the warning
    w.unmount()
  })
})
