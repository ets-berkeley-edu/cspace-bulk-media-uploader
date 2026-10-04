/** Browser uploads in the editor (design: Browser uploads): a fresh upload form for a file whose form got old while it
 *  waited its turn ("Sign"), and files over the size limit skipped before anything is sent. */
import {afterEach, describe, expect, it, vi} from 'vitest'
import {flushPromises, mount} from '@vue/test-utils'
import {FORM_MAX_AGE_MS, fileTooLargeText, formIsOld, formatBytes, splitSize, tooLargeText} from '../lib/files'
import type {Job, Me, Perms, Row, TenantInfo} from '../types'
import DocumentRow from '@/components/job/DocumentRow.vue'
import JobEditor from '@/components/job/JobEditor.vue'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

const tenant = {key: 'pahma', name: 'PAHMA', filenameHint: '', filenamePattern: '^(?P<obj>[A-Za-z0-9.-]+)(?:_(?P<suffix>[A-Za-z0-9._-]+))?$',
  mediaTypes: [], languageDefault: '', authorityFields: {}, publish: {field: 'approvedForWeb', header: 'Restricted', invert: true},
  fileTypes: ['jpg', 'tif'], fileTypesHint: 'JPEG or TIFF',
  handling: [{id: 'link', label: 'Link to existing object', object: 'existing', id_rule: 'object'}]} as unknown as TenantInfo
const perms: Perms = {media: true, mediaUpdate: true, relations: true, objects: true, readObjects: true, authorities: true, groups: true}
const draft = {id: 'j1', name: 'Spring batch', status: 'Draft', createdBy: 'admin', rowCount: 0, run: 0, editingBy: 'admin', editingByYou: true} as Job

function row(p: Partial<Row> = {}): Row {
  return {n: 1, file: '15-1234_1.tif', size: 10, contentType: 'image/tiff', handling: 'link', obj: '15-1234', objParsed: '15-1234',
    img: '15-1234_1', parseOk: true, idnum: '15-1234', date: '', restricted: false, type: [], creator: '', contributor: '',
    rightsHolder: '', description: '', copyright: '', include: true, upload: {s: 'pending'}, checks: [], result: null, ...p}
}

/** An XMLHttpRequest that waits until the test finishes it. */
class FakeXHR {
  static all: FakeXHR[] = []
  upload = {onprogress: null as null | ((e: unknown) => void)}
  onload: null | (() => void) = null
  onerror: null | (() => void) = null
  onabort: null | (() => void) = null
  status = 0
  url = ''
  constructor() { FakeXHR.all.push(this) }
  open(_method: string, url: string) { this.url = url }
  setRequestHeader() {}
  send() {}
  abort() { this.onabort?.() }
  finish() { this.status = 204; this.onload?.() }
}

type Call = { url: string; method: string; body?: unknown };
/** The API for one draft. formReply: the reply to an upload-form request (a promise the test resolves, to hold it). */
function stub(rows: Row[] = [], formReply?: (n: number) => Promise<unknown>) {
  const calls: Call[] = []
  FakeXHR.all = []
  vi.stubGlobal('XMLHttpRequest', FakeXHR)
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const body = init?.body && typeof init.body === 'string' ? JSON.parse(init.body) : undefined
    calls.push({url, method, body})
    let out: unknown = {}
    const n = Number(url.match(/\/rows\/(\d+)\//)?.[1])
    if (url.endsWith('/api/jobs/j1') && method === 'GET') out = {job: draft, rows, runs: [], created: {}}
    else if (url.endsWith('/api/jobs/j1/files')) {
      out = {rows: (body as { files: { name: string; size: number }[] }).files.map((f, i) =>
        row({n: i + 1, file: f.name, size: f.size, s3Key: `k${i + 1}`, uploadForm: {url: 'http://s3/first', fields: {key: `k${i + 1}`}}}))}
    } else if (url.endsWith('/upload-form')) out = await (formReply?.(n) ?? {uploadForm: {url: 'http://s3/fresh', fields: {key: `k${n}`}}})
    else if (url.endsWith('/uploaded')) out = {row: row({n, upload: {s: 'done'}}), others: []}
    else if (url.endsWith('/check')) out = {rows: [], counts: {block: 0, warn: 0}}
    else if (/\/rows\/\d+$/.test(url) && method === 'DELETE') out = {ok: true, others: []}
    else if (url.includes('/vocabularies/')) out = {terms: []}
    else if (url.endsWith('/api/failures')) out = {failures: {}}
    return new Response(JSON.stringify(out), {status: 200, headers: {'content-type': 'application/json'}})
  }))
  return calls
}
const editor = async (me: Partial<Me> = {}) => {
  const w = mount(JobEditor, {props: {me: {user: 'admin', tenant, perms, scheduler: false, ...me}, jobId: 'j1'}, global: {stubs: {DocumentThumbnail: true}}})
  await flushPromises()
  return w
}
const tif = (name: string, size = 5) => new File(['x'.repeat(size)], name, {type: 'image/tiff'})
/** Let the page finish what it can: reading the files (FileReader) takes a few turns of the event loop. */
async function settle() {
  for (let i = 0; i < 10; i++) {
    await new Promise((r) => setTimeout(r, 0))
    await flushPromises()
  }
}
async function choose(w: ReturnType<typeof mount>, files: File[], selector = 'input[type=file][multiple]') {
  const input = w.find(selector)
  Object.defineProperty(input.element, 'files', {value: files, configurable: true})
  await input.trigger('change')
  await settle()
}
/** A clock the test moves: the forms' age is measured with Date.now. */
function clock() {
  const c = {t: 1_000_000_000}
  vi.spyOn(Date, 'now').mockImplementation(() => c.t)
  return c
}
const formCalls = (calls: Call[]) => calls.filter((c) => c.url.endsWith('/upload-form'))

describe('a fresh upload form for a file that waited its turn (design: Browser uploads, Sign)', () => {
  it('a form older than the safety margin is replaced just before the file is sent', async () => {
    const c = clock()
    const calls = stub()
    const w = await editor()
    await choose(w, ['15-1234_1.tif', '15-1234_2.tif', '15-1234_3.tif', '15-1234_4.tif'].map((n, i) => tif(n, 5 + i)))
    expect(FakeXHR.all.map((x) => x.url)).toEqual(['http://s3/first', 'http://s3/first', 'http://s3/first']) // 3 at a time
    c.t += FORM_MAX_AGE_MS + 60_000 // the first three took a while
    FakeXHR.all[0].finish()
    await flushPromises()
    expect(formCalls(calls)).toEqual([{url: '/api/jobs/j1/rows/4/upload-form', method: 'POST', body: {size: 8}}])
    expect(FakeXHR.all).toHaveLength(4)
    expect(FakeXHR.all[3].url).toBe('http://s3/fresh')
    w.unmount()
  })

  it('a form that is still fresh is used as it is', async () => {
    const c = clock()
    const calls = stub()
    const w = await editor()
    await choose(w, ['15-1234_1.tif', '15-1234_2.tif', '15-1234_3.tif', '15-1234_4.tif'].map((n) => tif(n)))
    c.t += FORM_MAX_AGE_MS - 60_000
    FakeXHR.all[0].finish()
    await flushPromises()
    expect(formCalls(calls)).toEqual([])
    expect(FakeXHR.all[3].url).toBe('http://s3/first')
    w.unmount()
  })

  it('a document deleted while its fresh form is on its way isn\'t uploaded', async () => {
    const c = clock()
    let release: (v: unknown) => void = () => undefined
    const calls = stub([], () => new Promise((resolve) => { release = resolve }))
    const w = await editor()
    await choose(w, ['15-1234_1.tif', '15-1234_2.tif', '15-1234_3.tif', '15-1234_4.tif'].map((n) => tif(n)))
    c.t += FORM_MAX_AGE_MS + 1
    FakeXHR.all[0].finish()
    await flushPromises()
    expect(formCalls(calls)).toHaveLength(1) // row 4 is waiting for its new form
    const del = w.findAll('button[aria-label="Delete document"]')
    await del[del.length - 1].trigger('click')
    await w.findAll('button').find((b) => b.text() === 'Delete')!.trigger('click')
    await flushPromises()
    expect(calls.some((x) => x.method === 'DELETE' && x.url.endsWith('/rows/4'))).toBe(true)
    release({uploadForm: {url: 'http://s3/fresh', fields: {key: 'k4'}}})
    await flushPromises()
    expect(FakeXHR.all).toHaveLength(3) // nothing sent for row 4
    expect(calls.some((x) => x.url.endsWith('/rows/4/upload-failed'))).toBe(false) // and it isn't a failure
    w.unmount()
  })

  it('formIsOld: older than the margin, which leaves most of the 15 minutes a form lasts', () => {
    expect(FORM_MAX_AGE_MS).toBe(5 * 60 * 1000)
    expect(formIsOld(0, FORM_MAX_AGE_MS)).toBe(false)
    expect(formIsOld(0, FORM_MAX_AGE_MS + 1)).toBe(true)
  })
})

describe('files over the size limit (design: Browser uploads)', () => {
  it('the messages name the files and the limit', () => {
    const limit = 2 * 1024 ** 3
    expect(formatBytes(limit)).toBe('2 GB')
    expect(formatBytes(1.5 * 1024 ** 3)).toBe('1.50 GB')
    expect(tooLargeText(['a.tif', 'b.tif'], limit)).toBe('Skipped 2 files over the 2 GB limit: a.tif, b.tif.')
    expect(tooLargeText(['a.tif'], limit)).toBe('Skipped 1 file over the 2 GB limit: a.tif.')
    expect(tooLargeText(['1', '2', '3', '4', '5', '6', '7'], limit)).toBe('Skipped 7 files over the 2 GB limit: 1, 2, 3, 4, 5, and 2 more.')
    expect(fileTooLargeText('a.tif', limit)).toBe('“a.tif” is over the 2 GB limit, so it can\'t be uploaded. Choose a smaller version of the file.')
    const split = splitSize([{size: limit}, {size: limit + 1}], limit)
    expect(split.ok).toEqual([{size: limit}])
    expect(split.tooLarge).toEqual([{size: limit + 1}])
    expect(splitSize([{size: limit + 1}], undefined).ok).toHaveLength(1) // no limit known: the server decides
  })

  it('the editor skips them before asking the server, like files of other types, and adds the rest', async () => {
    const calls = stub()
    const w = await editor({maxFileBytes: 10})
    await choose(w, [tif('15-1234_1.tif', 5), tif('15-1234_big.tif', 20), new File(['x'], 'notes.docx'), tif('15-1234_huge.tif', 30)])
    expect(w.find('#editor-message').text()).toBe('1 file skipped: notes.docx. The BMU accepts JPEG or TIFF. '
      + 'Skipped 2 files over the 10 B limit: 15-1234_big.tif, 15-1234_huge.tif.')
    expect(calls.find((c) => c.url.endsWith('/files'))!.body).toEqual({files: [expect.objectContaining({name: '15-1234_1.tif', size: 5})]})
    w.unmount()
  })

  it('nothing is sent when every file is over the limit', async () => {
    const calls = stub()
    const w = await editor({maxFileBytes: 10})
    await choose(w, [tif('15-1234_big.tif', 20)])
    expect(w.find('#editor-message').text()).toBe('Skipped 1 file over the 10 B limit: 15-1234_big.tif.')
    expect(calls.some((c) => c.url.endsWith('/files') || c.method === 'POST' && c.url.endsWith('/api/jobs'))).toBe(false)
    w.unmount()
  })

  it('Replace file and Retry upload say so, and send nothing', async () => {
    const failed = row({upload: {s: 'failed'}})
    const calls = stub([failed])
    const w = await editor({maxFileBytes: 10})
    w.findComponent(DocumentRow).vm.$emit('replace', failed, tif('15-1234_1.tif', 20))
    await flushPromises()
    expect(w.find('#editor-message').text()).toBe('“15-1234_1.tif” is over the 10 B limit, so it can\'t be uploaded. Choose a smaller version of the file.')
    w.findComponent(DocumentRow).vm.$emit('retry', failed)
    await flushPromises()
    await choose(w, [tif('15-1234_1.tif', 30)], 'input[type=file][aria-hidden=true]')
    expect(w.find('#editor-message').text()).toContain('“15-1234_1.tif” is over the 10 B limit')
    expect(calls.some((c) => c.url.endsWith('/replace-file') || c.url.endsWith('/retry-upload'))).toBe(false)
    expect(FakeXHR.all).toHaveLength(0)
    w.unmount()
  })
})
