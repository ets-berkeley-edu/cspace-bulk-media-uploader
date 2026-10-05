import {afterEach, describe, expect, it, vi} from 'vitest'
import {flushPromises, mount} from '@vue/test-utils'
import {failures} from '../lib/results'
import {RAN_DELETE_WHY, STAFF_DRAFT_WHY, STAFF_EDITING_WHY, STAFF_ONLY_WHY, staffOnly} from '../lib/roles'
import {handlingBlocked} from '../lib/status'
import type {Failure, Job, Perms, Row, TenantInfo} from '../types'
import DraftsList from '@/components/job/DraftsList.vue'
import JobActions from '@/components/job/JobActions.vue'
import JobDocsTable from '@/components/job/JobDocumentsTable.vue'
import JobPreview from '@/components/job/JobPreview.vue'

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
    const w = mount(JobDocsTable, {props: {job: job(), rows, tenant, kind: 'drafts'}, global: {stubs: {DocumentThumbnail: true}}})
    expect(w.findAll('th').map((t) => t.text()))
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
    const w = mount(JobDocsTable, {props: {job: job(), rows, tenant, kind: 'queue'}, global: {stubs: {DocumentThumbnail: true}}})
    expect(w.findAll('tbody tr')).toHaveLength(10)
    expect(cells(w.findAll('tbody tr')[0])[1]).toBe('f12.jpg')
    expect(w.text()).toContain('Showing the 10 most important of 12 documents.')
  })

  it('a running job lists each document\'s run state', () => {
    const rows = [row({n: 1, file: 'a.jpg', result: {state: 'Done'}}), row({n: 2, file: 'b.jpg', result: {state: 'In progress'}})]
    const w = mount(JobDocsTable, {props: {job: job({status: 'Running'}), rows, tenant, kind: 'queue'}, global: {stubs: {DocumentThumbnail: true}}})
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
    const w = mount(JobDocsTable, {props: {job: job({status: 'NeedsAttention'}), rows, tenant, kind: 'history'}, global: {stubs: {DocumentThumbnail: true}}})
    expect(w.findAll('th').map((t) => t.text()).slice(4)).toEqual(['Result', 'What happened'])
    const trs = w.findAll('tbody tr')
    expect(cells(trs[0]).slice(1)).toEqual(['big.jpg', 'Link to existing object', '15-1234', 'Partial',
      'File too large for CollectionSpace. Replace the file with a smaller one.'])
    expect(cells(trs[1])[5]).toBe('Excluded by jdoe; ignored.')
    expect(cells(trs[2])[5]).toBe('Created in CollectionSpace.')
    failures.value = {}
  })
})

describe('job actions (design: Drafts; The job queue; UI mockup actionsFor)', () => {
  const label = (b: { text: () => string; attributes: (n: string) => string | undefined }) => b.text() || b.attributes('aria-label')
  const texts = (w: ReturnType<typeof mount>) => w.findAll('button').map(label)
  it('for a draft, in the list and in its preview: Edit, Submit…, the intern setting and Delete, or Take over when someone else is editing; no Preview button', () => {
    expect(texts(mount(JobActions, {props: {job: job(), kind: 'drafts', staff: true}}))).toEqual(['Edit', 'Submit…', 'Open to interns', 'Delete'])
    expect(texts(mount(JobActions, {props: {job: job({editingBy: 'jlee', editingSince: 5}), kind: 'drafts', staff: true}})))
      .toEqual(['Take over…', 'Submit…', 'Open to interns', 'Delete'])
    expect(texts(mount(JobActions, {props: {job: job(), kind: 'drafts', staff: true}}))).toEqual(['Edit', 'Submit…', 'Open to interns', 'Delete'])
    // an intern: no Submit, no setting; Submit for review on a draft that is open to interns
    expect(texts(mount(JobActions, {props: {job: job({internOpen: true}), kind: 'drafts'}}))).toEqual(['Edit', 'Submit for review…', 'Delete'])
    expect(texts(mount(JobActions, {props: {job: job(), kind: 'drafts'}}))).toEqual(['Edit', 'Delete'])
  })

  it('in the queue: Edit and Delete for a queued job, Cancel run for a running one', () => {
    expect(texts(mount(JobActions, {props: {job: job({status: 'Queued'}), kind: 'queue', staff: true}}))).toEqual(['Edit', 'Move to Drafts…', 'Delete'])
    const run = mount(JobActions, {props: {job: job({status: 'Running'}), kind: 'queue', staff: true}})
    expect(texts(run)).toEqual(['Cancel run', 'Delete'])
    expect(run.findAll('button')[1].attributes('disabled')).toBeDefined()
  })

  it('Move to Drafts… takes a queued job out of the queue after a confirmation, without opening it', async () => {
    const calls = stubFetch(() => job({status: 'Draft'}))
    const w = mount(JobActions, {props: {job: job({status: 'Queued'}), kind: 'queue', staff: true}})
    await w.find('#job-j1-to-drafts-btn').trigger('click')
    expect(w.find('#job-j1-todrafts-confirm').text()).toContain('out of the queue and deletes its saved sign-in')
    expect(calls).toHaveLength(0)
    await w.find('#job-j1-todrafts-confirm-btn').trigger('click')
    await flushPromises()
    expect(calls).toEqual([{url: '/api/jobs/j1/to-drafts', method: 'POST'}])
    expect(w.emitted('done')![0]).toEqual(['Moved “Spring batch” to Drafts.'])
    expect(w.emitted('open')).toBeUndefined()
    // an intern: off, with the reason
    const intern = mount(JobActions, {props: {job: job({status: 'Queued'}), kind: 'queue', editWhy: 'Only staff can do this.'}})
    expect(intern.find('#job-j1-to-drafts-btn').attributes('disabled')).toBeDefined()
  })

  it('Cancel run: for staff, for any job; an intern sees why not (design: Roles)', () => {
    const cancel = (w: ReturnType<typeof mount>) => w.findAll('button').find((b) => b.text() === 'Cancel run')!
    const running = job({status: 'Running', scheduledBy: 'jlee'})
    const intern = mount(JobActions, {props: {job: running, kind: 'queue', user: 'jlee', staff: false}})
    expect(cancel(intern).attributes('disabled')).toBeDefined()
    expect(cancel(intern).attributes('title')).toBe('Only staff can cancel a run.')
    const sched = mount(JobActions, {props: {job: running, kind: 'queue', user: 'admin', staff: true}})
    expect(cancel(sched).attributes('disabled')).toBeUndefined()
    expect(cancel(sched).attributes('title')).toBe('Stop after the document in progress')
  })

  it('an intern: Edit and Delete are on for a draft that is open to interns, off for a staff-only one', () => {
    const btn = (w: ReturnType<typeof mount>, t: string) => w.findAll('button').find((x) => label(x) === t)!
    const open = mount(JobActions, {props: {job: job({internOpen: true}), kind: 'drafts', staff: false}})
    for (const t of ['Edit', 'Delete']) {
      expect(btn(open, t).attributes('disabled')).toBeUndefined()
    }
    const closed = mount(JobActions, {props: {job: job({internOpen: false}), kind: 'drafts', staff: false}})
    for (const t of ['Edit', 'Delete']) {
      expect(btn(closed, t).attributes('disabled')).toBeDefined()
      expect(btn(closed, t).attributes('title')).toBe(STAFF_DRAFT_WHY)
    }
    expect(closed.findAll('button').some((x) => x.text() === 'Preview')).toBe(false) // the full preview opens from the expanded row
    // staff are never limited by the setting
    const staff = mount(JobActions, {props: {job: job({internOpen: false}), kind: 'drafts', staff: true}})
    expect(btn(staff, 'Edit').attributes('disabled')).toBeUndefined()
  })

  it('an intern edits but does not delete a draft that has run, and takes over from interns only', () => {
    const btn = (w: ReturnType<typeof mount>, t: string) => w.findAll('button').find((x) => label(x) === t)!
    const ran = mount(JobActions, {props: {job: job({internOpen: true, run: 1}), kind: 'drafts', staff: false}})
    expect(btn(ran, 'Edit').attributes('disabled')).toBeUndefined()
    expect(btn(ran, 'Delete').attributes('title')).toBe(RAN_DELETE_WHY)
    const byStaff = mount(JobActions, {props: {job: job({internOpen: true, editingBy: 'jlee', editingRole: 'staff'}), kind: 'drafts', staff: false}})
    expect(btn(byStaff, 'Take over…').attributes('disabled')).toBeDefined()
    expect(btn(byStaff, 'Take over…').attributes('title')).toBe(STAFF_EDITING_WHY)
    const byIntern = mount(JobActions, {props: {job: job({internOpen: true, editingBy: 'kim', editingRole: 'intern'}), kind: 'drafts', staff: false}})
    expect(btn(byIntern, 'Take over…').attributes('disabled')).toBeUndefined()
  })

  it('an intern changes nothing in the job queue: Edit and Delete are off, with the reason', () => {
    expect(staffOnly({role: 'staff'})).toBe('')
    const why = staffOnly({role: 'intern'})
    expect(why).toBe(STAFF_ONLY_WHY)
    const q = mount(JobActions, {props: {job: job({status: 'Queued', internOpen: true}), kind: 'queue', editWhy: why, staff: false}})
    for (const t of ['Edit', 'Delete']) {
      const b = q.findAll('button').find((x) => label(x) === t)!
      expect(b.attributes('disabled')).toBeDefined()
      expect(b.attributes('title')).toBe(why)
    }
  })
})

describe('permissions (design: Permissions in the UI)', () => {
  it('handling options carry no reason about Media permissions: staff can\'t sign in without them', () => {
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
    const w = mount(JobPreview, {props: {jobId: 'j1', from: 'drafts', tenant, staff: true}, global: {stubs: {DocumentThumbnail: true}}})
    await flushPromises()
    expect(w.text()).toContain('← Back to Drafts')
    expect(w.text()).toContain('Read-only preview.')
    expect(w.text()).toContain('Must fix: No object 15-1234')
    expect(w.text()).toContain('This draft has 1 document that needs fixing before it can be submitted.')
    const buttons = w.find('#preview-actions').findAll('button').map((b) => b.text() || b.attributes('aria-label'))
    expect(buttons).toEqual(['Edit', 'Submit…', 'Open to interns', 'Delete'])
    expect(w.text()).not.toContain('Save draft')
    expect(w.text()).not.toContain('Submit job')
    // one document needs fixing, so Submit… is off with the reason
    const submit = w.find('#job-j1-submit-btn')
    expect(submit.attributes('disabled')).toBeDefined()
    expect(submit.attributes('title')).toBe('Fix or exclude the document marked Needs fixing first: open the draft with Edit')
    expect(calls.some((c) => c.url.endsWith('/j1/check'))).toBe(true)
    await w.find('#preview-actions').findAll('button')[0].trigger('click')
    expect(w.emitted('open')?.[0].slice(0, 2)).toEqual(['j1', 'edit'])
    await w.findAll('button').find((b) => b.text() === '← Back to Drafts')!.trigger('click')
    expect(w.emitted('back')).toHaveLength(1)
    w.unmount()
  })

  it('a running job\'s preview offers Cancel run, and shows each document\'s run state', async () => {
    const rows = [row({n: 1, file: 'a.jpg', result: {state: 'In progress'}})]
    stubFetch(() => ({job: job({status: 'Running', progress: {total: 1, done: 0, failed: 0}}), rows, runs: [], created: {}}))
    const w = mount(JobPreview, {props: {jobId: 'j1', from: 'queue', tenant, user: 'admin', staff: true}, global: {stubs: {DocumentThumbnail: true}}})
    await flushPromises()
    expect(w.text()).toContain('← Back to Job queue')
    expect(w.find('#preview-actions').findAll('button').map((b) => b.text() || b.attributes('aria-label'))).toEqual(['Cancel run', 'Delete'])
    expect(w.text()).toContain('Run state')
    await w.find('#preview-actions').findAll('button')[0].trigger('click')
    expect(w.text()).toContain('Stop this run?')
    w.unmount()
  })
})
