/**
 * A job list says it is loading until the server's first answer: it never reads as empty before then. The editor's
 * documents table is busy while the job loads and its checks are out.
 */
import {afterEach, describe, expect, it, vi} from 'vitest'
import {flushPromises, mount} from '@vue/test-utils'
import type {Job, Me, Perms, Row, TenantInfo} from '../types'
import DraftsList from '@/components/job/DraftsList.vue'
import FinishedJobs from '@/components/job/FinishedJobs.vue'
import JobEditor from '@/components/job/JobEditor.vue'
import QueueList from '@/components/job/QueueList.vue'

const tenant = {key: 'pahma', name: 'PAHMA', handling: []} as unknown as TenantInfo
const LISTS = [
  {name: 'Drafts', component: DraftsList, prefix: 'drafts'},
  {name: 'Job queue', component: QueueList, prefix: 'queue'},
  {name: 'Finished jobs', component: FinishedJobs, prefix: 'finished'}
]
const schedule = {days: [1, 2, 3, 4, 5], start: '19:00', end: '', timezone: 'America/Los_Angeles', paused: null, nextRunAt: 0, windowOpen: false, alwaysRunTime: false}
const answer = (body: unknown, status = 200) => new Response(JSON.stringify(body), {status, headers: {'content-type': 'application/json'}})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe.each(LISTS)('$name before the first answer', ({component, prefix}) => {
  it('says it is loading, not that there are no jobs', async () => {
    let respond: (r: Response) => void = () => undefined
    vi.stubGlobal('fetch', vi.fn((url: string) => (url === '/api/jobs'
      ? new Promise<Response>(resolve => { respond = resolve })
      : Promise.resolve(answer(url === '/api/schedule' ? schedule : {failures: {}})))))
    const w = mount(component, {props: {tenant}})
    await flushPromises()
    const loading = w.find(`#${prefix}-loading`)
    expect(loading.text()).toContain('Loading')
    expect(loading.attributes('aria-busy')).toBe('true')
    expect(w.find(`#${prefix}-empty`).exists()).toBe(false)
    respond(answer({jobs: []}))
    await flushPromises()
    expect(w.find(`#${prefix}-loading`).exists()).toBe(false)
    expect(w.find(`#${prefix}-empty`).exists()).toBe(true)
    w.unmount()
  })

  it('shows only the error when the first request fails', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(answer({detail: 'The server is not available'}, 503))))
    const w = mount(component, {props: {tenant}})
    await flushPromises()
    expect(w.find(`#${prefix}-error`).text()).toContain('The server is not available')
    expect(w.find(`#${prefix}-loading`).exists()).toBe(false)
    expect(w.find(`#${prefix}-empty`).exists()).toBe(false)
    w.unmount()
  })
})

describe('the editor\'s documents table', () => {
  it('is busy from opening the job until its checks have come back', async () => {
    const rows = [{n: 1, file: '15-1234_1.jpg', size: 10, contentType: 'image/jpeg', handling: 'link', obj: '15-1234', objParsed: '15-1234',
      img: '15-1234_1', parseOk: true, idnum: '15-1234', date: '', restricted: false, type: [], creator: '', contributor: '',
      rightsHolder: '', description: '', copyright: '', include: true, upload: {s: 'done'}, checks: [], result: null}] as unknown as Row[]
    const job = {id: 'j1', name: 'Spring batch', status: 'Draft', createdBy: 'admin', rowCount: 1, run: 0, editingBy: 'admin', editingByYou: true} as Job
    const perms: Perms = {media: true, mediaUpdate: true, relations: true, objects: true, readObjects: true, authorities: true, groups: true}
    const editorTenant = {...tenant, filenameHint: '', filenamePattern: '^(?P<obj>[A-Za-z0-9.-]+)(?:_(?P<suffix>[A-Za-z0-9._-]+))?$',
      mediaTypes: [], languageDefault: '', authorityFields: {}, publish: {field: 'approvedForWeb', header: 'Restricted', invert: true},
      handling: [{id: 'link', label: 'Link to existing object', object: 'existing', id_rule: 'object'}]} as unknown as TenantInfo
    const me: Me = {user: 'admin', tenant: editorTenant, perms, role: 'staff'}
    let openJob: (r: Response) => void = () => undefined
    let checked: (r: Response) => void = () => undefined
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url.endsWith('/api/jobs/j1')) return new Promise<Response>(resolve => { openJob = resolve })
      if (url.endsWith('/check')) return new Promise<Response>(resolve => { checked = resolve })
      return Promise.resolve(answer(url.includes('/vocabularies/') ? {terms: []} : {failures: {}}))
    }))
    const w = mount(JobEditor, {props: {me, jobId: 'j1'}, global: {stubs: {DocumentThumbnail: true}}})
    await flushPromises()
    const busy = () => w.find('#documents-table').attributes('aria-busy')
    expect(busy()).toBe('true')
    openJob(answer({job, rows, runs: [], created: {}}))
    await flushPromises()
    expect(w.find('#document-1').exists()).toBe(true)
    expect(busy()).toBe('true') // the rows are shown, and their checks are out
    checked(answer({rows, counts: {block: 0, warn: 0}}))
    await flushPromises()
    expect(busy()).toBe('false')
    w.unmount()
  })
})
