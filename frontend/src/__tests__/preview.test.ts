import {afterEach, describe, expect, it, vi} from 'vitest'
import {flushPromises, mount} from '@vue/test-utils'
import DraftsList from '../components/DraftsList.vue'
import JobActions from '../components/JobActions.vue'
import JobDocsTable from '../components/JobDocsTable.vue'
import JobPreview from '../components/JobPreview.vue'
import {failures} from '../lib/results'
import {editBlocked, handlingBlocked} from '../lib/status'
import type {Failure, Job, Perms, Row, TenantInfo} from '../types'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

const tenant: TenantInfo = {
  key: 'pahma', name: 'PAHMA', filenameHint: 'hint', filenamePattern: '^(?P<obj>[A-Za-z0-9.-]+)$', mediaTypes: [], languageDefault: '',
  authorityFields: {}, publish: {field: 'approvedForWeb', header: 'Restricted', invert: true},
  handling: [{id: 'link', label: 'Link to existing object', object: 'existing', id_rule: 'object'},
             {id: 'none', label: 'Media only', object: 'none', id_rule: 'image'}],
}
const perms: Perms = {media: true, mediaUpdate: true, relations: true, objects: true, readObjects: true, authorities: true, groups: true}
function row(p: Partial<Row> = {}): Row {
  return {n: 1, file: '15-1234_a.jpg', size: 10, contentType: 'image/jpeg', handling: 'link', obj: '15-1234', objParsed: '15-1234',
    img: '15-1234_a', parseOk: true, idnum: '15-1234', date: '', restricted: false, type: [], creator: '', contributor: '',
    rightsHolder: '', description: '', copyright: '', include: true, upload: {s: 'done'}, checks: [], result: null, ...p}
}
const job = (p: Partial<Job> = {}) => ({id: 'j1', name: 'Spring batch', status: 'Draft', createdBy: 'jlee', rowCount: 1, run: 0, ...p}) as Job
const cells = (tr: { findAll: (s: string) => { text: () => string }[] }) => tr.findAll('td').map((c) => c.text())

function stubFetch(routes: (url: string, method: string) => unknown) {
  const calls: { url: string; method: string }[] = []
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    calls.push({url, method})
    const body = routes(url, method) ?? {}
    return Promise.resolve(new Response(JSON.stringify(body), {status: 200, headers: {'content-type': 'application/json'}}))
  }))
  return calls
}

describe('expanded job documents (design: Job lists; UI mockup jobDocsTable)', () => {
  it('Drafts and Job queue: thumbnail, document with Protected badge, handling, ID, status and the most important issue', () => {
    const rows = [
      row({n: 1, file: 'ok.jpg'}),
      row({n: 2, file: 'warn.jpg', idnum: '2-2', checks: [{level: 'warn', text: 'Media record exists'}]}),
      row({n: 3, file: 'bad.jpg', protected: {reason: 'culturally sensitive', hides: true},
        checks: [{level: 'warn', text: 'Minor'}, {level: 'block', text: 'No object 15-1234'}]}),
    ]
    const w = mount(JobDocsTable, {props: {job: job(), rows, tenant, kind: 'drafts'}, global: {stubs: {ThumbCell: true}}})
    expect(w.findAll('th').map((t) => t.text().replace(/[↕▲▼]/g, '').trim()))
      .toEqual(['Preview', 'Document', 'Handling', 'Identification number', 'Status', 'Most important issue'])
    const trs = w.findAll('tbody tr')
    expect(cells(trs[0])[1]).toContain('bad.jpg')
    expect(cells(trs[0])[1]).toContain('Protected')
    expect(cells(trs[0])[2]).toBe('Link to existing object')
    expect(cells(trs[0])[5]).toBe('Must fix: No object 15-1234')
    expect(cells(trs[1])[3]).toBe('2-2')
    expect(cells(trs[1])[5]).toBe('Warning: Media record exists')
    expect(cells(trs[2])[5]).toBe('—')
    expect(w.text()).not.toContain('most important of')
  })

  it('shows the 10 most important and says so when there are more', () => {
    const rows = Array.from({length: 12}, (_, i) => row({n: i + 1, file: `f${i + 1}.jpg`, checks: i === 11 ? [{level: 'block', text: 'x'}] : []}))
    const w = mount(JobDocsTable, {props: {job: job(), rows, tenant, kind: 'queue'}, global: {stubs: {ThumbCell: true}}})
    expect(w.findAll('tbody tr')).toHaveLength(10)
    expect(cells(w.findAll('tbody tr')[0])[1]).toBe('f12.jpg')
    expect(w.text()).toContain('Showing the 10 most important of 12 documents.')
  })

  it('a running job lists each document\'s run state', () => {
    const rows = [row({n: 1, file: 'a.jpg', result: {state: 'Done'}}), row({n: 2, file: 'b.jpg', result: {state: 'In progress'}})]
    const w = mount(JobDocsTable, {props: {job: job({status: 'Running'}), rows, tenant, kind: 'queue'}, global: {stubs: {ThumbCell: true}}})
    expect(cells(w.findAll('tbody tr')[0]).slice(1, 2).concat(cells(w.findAll('tbody tr')[0])[4])).toEqual(['b.jpg', 'In progress'])
  })

  it('Finished jobs: Result and What happened, with the failure\'s title and what to do', () => {
    const F: Failure = {title: 'File too large for CollectionSpace', level: 'row', explain: 'e', fix: 'Replace the file with a smaller one.', needs_fix: true}
    failures.value = {upload_too_large: F}
    const rows = [
      row({n: 1, file: 'done.jpg', result: {state: 'Done'}}),
      row({n: 2, file: 'big.jpg', result: {state: 'Partial', error: {code: 'upload_too_large', detail: '413', step: 'upload'},
        steps: {media: {s: 'done', csid: 'm'}, upload: {s: 'failed', code: 'upload_too_large'}}}}),
      row({n: 3, file: 'off.jpg', include: false, disabledBy: 'jdoe'}),
    ]
    const w = mount(JobDocsTable, {props: {job: job({status: 'NeedsAttention'}), rows, tenant, kind: 'history'}, global: {stubs: {ThumbCell: true}}})
    expect(w.findAll('th').map((t) => t.text().replace(/[↕▲▼]/g, '').trim()).slice(4)).toEqual(['Result', 'What happened'])
    const trs = w.findAll('tbody tr')
    expect(cells(trs[0]).slice(1)).toEqual(['big.jpg', 'Link to existing object', '15-1234', 'Partial',
      'File too large for CollectionSpace. Replace the file with a smaller one.'])
    expect(cells(trs[1])[5]).toBe('Excluded by jdoe; ignored.')
    expect(cells(trs[2])[5]).toBe('Created in CollectionSpace.')
    failures.value = {}
  })
})

describe('job actions (design: Drafts; The job queue; UI mockup actionsFor)', () => {
  const texts = (w: ReturnType<typeof mount>) => w.findAll('button').map((b) => b.text())
  it('in a draft\'s preview: Edit and Delete, or Take over when someone else is editing; never Save draft or Submit job', () => {
    expect(texts(mount(JobActions, {props: {job: job(), kind: 'drafts', inPreview: true}}))).toEqual(['Edit', 'Delete'])
    expect(texts(mount(JobActions, {props: {job: job({editingBy: 'jlee', editingSince: 5}), kind: 'drafts', inPreview: true}})))
      .toEqual(['Take over…', 'Delete'])
    expect(texts(mount(JobActions, {props: {job: job(), kind: 'drafts'}}))).toEqual(['Preview', 'Edit', 'Delete'])
  })

  it('in the queue: Edit and Delete for a queued job, Cancel run for a running one', () => {
    expect(texts(mount(JobActions, {props: {job: job({status: 'Queued'}), kind: 'queue', inPreview: true}}))).toEqual(['Edit', 'Delete'])
    const run = mount(JobActions, {props: {job: job({status: 'Running'}), kind: 'queue', inPreview: true, scheduler: true}})
    expect(texts(run)).toEqual(['Cancel run', 'Delete'])
    expect(run.findAll('button')[1].attributes('disabled')).toBeDefined()
  })

  it('Cancel run: for BMU schedulers and whoever submitted the job; others see why not (design: Job scheduling)', () => {
    const cancel = (w: ReturnType<typeof mount>) => w.findAll('button').find((b) => b.text() === 'Cancel run')!
    const running = job({status: 'Running', scheduledBy: 'jlee'})
    const other = mount(JobActions, {props: {job: running, kind: 'queue', user: 'admin', scheduler: false}})
    expect(cancel(other).attributes('disabled')).toBeDefined()
    expect(cancel(other).attributes('title')).toBe('Only a BMU scheduler or the person who submitted the job can cancel its run.')
    const submitter = mount(JobActions, {props: {job: running, kind: 'queue', user: 'jlee', scheduler: false}})
    expect(cancel(submitter).attributes('disabled')).toBeUndefined()
    const sched = mount(JobActions, {props: {job: running, kind: 'queue', user: 'admin', scheduler: true}})
    expect(cancel(sched).attributes('disabled')).toBeUndefined()
    expect(cancel(sched).attributes('title')).toBe('Stop after the document in progress')
  })

  it('without Media create and update: Edit, Take over and Delete are off, with the reason', () => {
    const why = editBlocked({...perms, mediaUpdate: false})
    expect(why).toContain('can\'t create and update Media records')
    const w = mount(JobActions, {props: {job: job(), kind: 'drafts', editWhy: why}})
    for (const t of ['Edit', 'Delete']) {
      const b = w.findAll('button').find((x) => x.text() === t)!
      expect(b.attributes('disabled')).toBeDefined()
      expect(b.attributes('title')).toBe(why)
    }
    expect(w.findAll('button').find((x) => x.text() === 'Preview')!.attributes('disabled')).toBeUndefined()
    const q = mount(JobActions, {props: {job: job({status: 'Queued'}), kind: 'queue', editWhy: why}})
    expect(q.findAll('button').find((x) => x.text() === 'Edit')!.attributes('disabled')).toBeDefined()
  })
})

describe('permissions (design: Permissions in the UI)', () => {
  it('editing needs create and update on Media; handling options no longer carry that reason', () => {
    expect(editBlocked(perms)).toBe('')
    expect(editBlocked({...perms, media: false})).not.toBe('')
    expect(handlingBlocked(tenant.handling[0], {...perms, media: false})).toBe('')
    expect(handlingBlocked(tenant.handling[0], {...perms, relations: false})).toContain('can\'t create relations')
  })

  it('Drafts: Edit and Delete are off when the account can\'t edit jobs', async () => {
    stubFetch((url) => (url.endsWith('/api/jobs') ? {jobs: [job()]} : {rows: [], counts: {block: 0, warn: 0}}))
    const w = mount(DraftsList, {props: {tenant, editWhy: 'No Media permissions.'}})
    await flushPromises()
    expect(w.findAll('button').find((b) => b.text() === 'Edit')!.attributes('title')).toBe('No Media permissions.')
    w.unmount()
  })
})

describe('JobPreview (design: Drafts; UI mockup renderPreview)', () => {
  it('shows a read-only draft inside its tab with its checks and only the actions that apply', async () => {
    const rows = [row({n: 1, file: 'bad.jpg', checks: [{level: 'block', text: 'No object 15-1234'}]}), row({n: 2, file: 'ok.jpg'})]
    const calls = stubFetch((url) => (url.endsWith('/check') ? {rows, counts: {block: 1, warn: 0}} : {job: job({rowCount: 2}), rows, runs: [], created: {}}))
    const w = mount(JobPreview, {props: {jobId: 'j1', from: 'drafts', tenant}, global: {stubs: {ThumbCell: true}}})
    await flushPromises()
    expect(w.text()).toContain('← Back to Drafts')
    expect(w.text()).toContain('Read-only preview.')
    expect(w.text()).toContain('Must fix: No object 15-1234')
    expect(w.text()).toContain('This draft has 1 document that needs fixing before it can be submitted.')
    const buttons = w.find('.schedule-bar').findAll('button').map((b) => b.text())
    expect(buttons).toEqual(['Edit', 'Delete'])
    expect(w.text()).not.toContain('Save draft')
    expect(w.text()).not.toContain('Submit job')
    expect(calls.some((c) => c.url.endsWith('/j1/check'))).toBe(true)
    await w.find('.schedule-bar').findAll('button')[0].trigger('click')
    expect(w.emitted('open')?.[0].slice(0, 2)).toEqual(['j1', 'edit'])
    await w.findAll('button').find((b) => b.text() === '← Back to Drafts')!.trigger('click')
    expect(w.emitted('back')).toHaveLength(1)
    w.unmount()
  })

  it('a running job\'s preview offers Cancel run, and shows each document\'s run state', async () => {
    const rows = [row({n: 1, file: 'a.jpg', result: {state: 'In progress'}})]
    stubFetch(() => ({job: job({status: 'Running', progress: {total: 1, done: 0, failed: 0}}), rows, runs: [], created: {}}))
    const w = mount(JobPreview, {props: {jobId: 'j1', from: 'queue', tenant, user: 'admin', scheduler: true}, global: {stubs: {ThumbCell: true}}})
    await flushPromises()
    expect(w.text()).toContain('← Back to Job queue')
    expect(w.find('.schedule-bar').findAll('button').map((b) => b.text())).toEqual(['Cancel run', 'Delete'])
    expect(w.text()).toContain('Run state')
    await w.find('.schedule-bar').findAll('button')[0].trigger('click')
    expect(w.text()).toContain('Stop this run?')
    w.unmount()
  })
})
