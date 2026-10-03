/** Deleting documents in the editor (design: Deleting a row): the Delete column, and Delete selected in the panel. */
import {afterEach, describe, expect, it, vi} from 'vitest'
import {flushPromises, mount} from '@vue/test-utils'
import type {Job, Me, Perms, Row, TenantInfo} from '../types'
import BulkPanel from '@/components/job/BulkPanel.vue'
import DocumentRow from '@/components/job/DocumentRow.vue'
import JobEditor from '@/components/job/JobEditor.vue'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

const tenant = {key: 'pahma', name: 'PAHMA', filenameHint: '', filenamePattern: '^(?P<obj>[A-Za-z0-9.-]+)(?:_(?P<suffix>[A-Za-z0-9._-]+))?$',
  mediaTypes: [], languageDefault: '', authorityFields: {}, publish: {field: 'approvedForWeb', header: 'Restricted', invert: true},
  handling: [{id: 'link', label: 'Link to existing object', object: 'existing', id_rule: 'object'}]} as unknown as TenantInfo
const perms: Perms = {media: true, mediaUpdate: true, relations: true, objects: true, readObjects: true, authorities: true, groups: true}
const me: Me = {user: 'admin', tenant, perms, scheduler: false}

function row(p: Partial<Row> = {}): Row {
  return {n: 1, file: '15-1234_1.jpg', size: 10, contentType: 'image/jpeg', handling: 'link', obj: '15-1234', objParsed: '15-1234',
    img: '15-1234_1', parseOk: true, idnum: '15-1234', date: '', restricted: false, type: [], creator: '', contributor: '',
    rightsHolder: '', description: '', copyright: '', include: true, upload: {s: 'done'}, checks: [], result: null, ...p}
}
const created = (p: Partial<Row> = {}) => row({result: {state: 'Partial', steps: {media: {s: 'done', csid: 'm1'}}}, ...p})
const interrupted = (p: Partial<Row> = {}) => row({result: {state: 'Not started', steps: {}, interrupted: 1}, ...p})

function mountRow(p: Record<string, unknown>) {
  return mount({components: {DocumentRow}, template: '<table><DocumentRow v-bind=\'p\'/></table>',
    data: () => ({p: {row: row(), tenant, perms, expanded: false, readonly: false, ...p}})})
}
const trash = (w: ReturnType<typeof mount>) => w.find('button[aria-label="Delete document"]')
const button = (w: ReturnType<typeof mount>, text: string) => w.findAll('button').find((b) => b.text() === text)

describe('the Delete column of a document row', () => {
  it('is a trash button at the end of the row, for included and excluded documents alike', () => {
    for (const r of [row(), row({include: false})]) {
      const w = mountRow({row: r})
      const b = trash(w)
      expect(b.exists()).toBe(true)
      expect(b.element.tagName).toBe('BUTTON')
      expect(b.attributes('disabled')).toBeUndefined()
      expect(b.attributes('title')).toBe('Delete document')
      expect(b.find('svg').exists()).toBe(true)
      const cells = w.findAll('tr')[0].findAll('td')
      expect(cells[cells.length - 1].find('button[aria-label="Delete document"]').exists()).toBe(true) // after Exclude
      expect(cells[cells.length - 2].find('input[aria-label^="Exclude"]').exists()).toBe(true)
    }
  })

  it('is disabled, with the reason, for a document that created records or that the last run stopped on', () => {
    const made = trash(mountRow({row: created()}))
    expect(made.attributes('disabled')).toBeDefined()
    expect(made.attributes('title')).toBe('This document already created records in CollectionSpace, so it can\'t be deleted; use Exclude instead.')
    const stopped = trash(mountRow({row: interrupted()}))
    expect(stopped.attributes('disabled')).toBeDefined()
    expect(stopped.attributes('title')).toBe('The last run stopped while working on this document, so it may have created a record in CollectionSpace. '
      + 'It can\'t be deleted; use Exclude instead.')
  })

  it('isn\'t there in read-only views (previews, results, running jobs)', () => {
    const w = mountRow({readonly: true})
    expect(trash(w).exists()).toBe(false)
    expect(w.find('td.del-col').exists()).toBe(false)
    expect(trash(mountRow({readonly: true, runView: true, row: row({result: {state: 'In progress', steps: {}}})})).exists()).toBe(false)
  })

  it('asks inline before deleting, and says when it\'s the job\'s last document', async () => {
    const w = mountRow({})
    await trash(w).trigger('click')
    const confirm = w.find('tr.del-confirm')
    expect(confirm.text()).toContain('Delete “15-1234_1.jpg”? Its uploaded file is removed; nothing in CollectionSpace is touched.')
    expect(confirm.text()).not.toContain('last document')
    expect(confirm.find('td').attributes('colspan')).toBe('10')
    await button(w, 'Cancel')!.trigger('click')
    expect(w.find('tr.del-confirm').exists()).toBe(false)
    expect(w.findComponent(DocumentRow).emitted('remove')).toBeUndefined()
    await trash(w).trigger('click')
    await button(w, 'Delete')!.trigger('click')
    expect(w.findComponent(DocumentRow).emitted('remove')).toHaveLength(1)
    expect(w.find('tr.del-confirm').exists()).toBe(false)

    const last = mountRow({last: true, row: row({include: false})})
    await trash(last).trigger('click')
    expect(last.find('tr.del-confirm').text()).toContain('Delete “15-1234_1.jpg”? Its uploaded file is removed; nothing in CollectionSpace is touched. '
      + 'This is the job\'s last document, so the job is deleted too.')
  })

  it('has one Delete control: the expanded details keep only the note for documents that can\'t be deleted', () => {
    const w = mountRow({expanded: true})
    expect(w.findAll('button').filter((b) => b.text() === 'Delete document')).toHaveLength(0)
    expect(w.text()).not.toContain('Permanent, unlike Exclude')
    expect(mountRow({expanded: true, row: created()}).text()).toContain('already created records in CollectionSpace, so it can\'t be deleted from the job')
    expect(mountRow({expanded: true, row: interrupted()}).text()).toContain('The last run stopped while working on this document')
  })

  it('spans the detail row over every column, with the Group and Delete columns', () => {
    const span = (p: Record<string, unknown>) => mountRow({expanded: true, ...p}).find('tr.detail td').attributes('colspan')
    expect(span({})).toBe('10')
    expect(span({groupOn: true})).toBe('11')
    expect(span({readonly: true})).toBe('9')
    expect(span({readonly: true, groupOn: true})).toBe('10')
  })
})

describe('Delete selected in the bulk-change panel', () => {
  const panel = (rows: Row[], selected: number[], p: Record<string, unknown> = {}) =>
    mount(BulkPanel, {props: {rows, selected: new Set(selected), tenant, perms, readonly: false, busy: false, ...p}})

  it('is enabled only when a selected document can be deleted', async () => {
    const rows = [row(), created({n: 2}), row({n: 3, include: false})]
    expect(button(panel(rows, []), 'Delete selected')!.attributes('disabled')).toBeDefined()
    expect(button(panel(rows, [2]), 'Delete selected')!.attributes('disabled')).toBeDefined()
    expect(button(panel(rows, [3]), 'Delete selected')!.attributes('disabled')).toBeUndefined() // excluded documents too
    expect(button(panel(rows, [1], {readonly: true}), 'Delete selected')!.attributes('disabled')).toBeDefined()
    expect(button(panel(rows, [1], {busy: true}), 'Delete selected')!.attributes('disabled')).toBeDefined()
  })

  it('confirms with the counts, then sends the selected documents', async () => {
    const rows = [row(), created({n: 2}), row({n: 3, include: false}), interrupted({n: 4}), row({n: 5})]
    const w = panel(rows, [1, 2, 3, 4])
    await button(w, 'Delete selected')!.trigger('click')
    const box = w.find('.bulk-confirm')
    expect(box.text().replace(/\s+/g, ' ')).toContain('Delete 2 selected documents from this job permanently? Their uploaded files are removed; '
      + 'nothing in CollectionSpace is touched. 2 selected documents already created records in CollectionSpace and will stay (use Exclude for those).')
    expect(box.text()).not.toContain('every document')
    await button(w, 'Cancel')!.trigger('click')
    expect(w.find('.bulk-confirm').exists()).toBe(false)
    expect(w.emitted('delete')).toBeUndefined()
    await button(w, 'Delete selected')!.trigger('click')
    await button(w, 'Delete 2 documents')!.trigger('click')
    expect(w.emitted('delete')?.[0]).toEqual([[1, 2, 3, 4]])
    expect(w.find('.bulk-confirm').exists()).toBe(false)
  })

  it('uses the singular for one, and says when the job would be deleted', async () => {
    const one = panel([row(), created({n: 2})], [1, 2])
    await button(one, 'Delete selected')!.trigger('click')
    expect(one.find('.bulk-confirm').text().replace(/\s+/g, ' ')).toContain('Delete 1 selected document from this job permanently? Its uploaded file '
      + 'is removed; nothing in CollectionSpace is touched. 1 selected document already created records in CollectionSpace and will stay')
    expect(button(one, 'Delete 1 document')).toBeDefined()
    const all = panel([row(), row({n: 2, include: false})], [1, 2])
    await button(all, 'Delete selected')!.trigger('click')
    expect(all.find('.bulk-confirm').text()).toContain('That\'s every document in the job, so the job is deleted too.')
    expect(all.find('.bulk-confirm').text()).not.toContain('will stay')
  })
})

describe('the editor deletes documents', () => {
  const draft = {id: 'j1', name: 'Spring batch', status: 'Draft', createdBy: 'admin', rowCount: 3, run: 0, editingBy: 'admin', editingByYou: true} as Job

  function stub(job: Job, rows: Row[], onDelete: (body: { rows: number[] }) => unknown) {
    const calls: { url: string; method: string; body?: unknown }[] = []
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({url, method, body})
      let out: unknown = {}
      if (url.endsWith('/api/jobs/j1') && method === 'GET') out = {job, rows, runs: [], created: {}}
      else if (url.endsWith('/check')) out = {rows, counts: {block: 0, warn: 0}}
      else if (url.endsWith('/rows/delete')) out = onDelete(body)
      else if (/\/rows\/\d+$/.test(url) && method === 'DELETE') out = {ok: true, others: []}
      else if (url.includes('/vocabularies/')) out = {terms: []}
      else if (url.endsWith('/api/failures')) out = {failures: {}}
      return Promise.resolve(new Response(JSON.stringify(out), {status: 200, headers: {'content-type': 'application/json'}}))
    }))
    return calls
  }
  const editor = async () => {
    const w = mount(JobEditor, {props: {me, jobId: 'j1'}, global: {stubs: {DocumentThumbnail: true, ThumbCell: true}}})
    await flushPromises()
    return w
  }

  it('has a Delete column, labelled for screen readers, only while the job can be edited', async () => {
    stub(draft, [row(), row({n: 2, file: '3-1001_1.jpg'})], () => ({}))
    const w = await editor()
    const heads = w.findAll('thead th')
    expect(heads[heads.length - 1].find('.sr-only').text()).toBe('Delete')
    expect(w.findAll('tbody tr')[0].findAll('td')).toHaveLength(heads.length)
    w.unmount()
    stub({...draft, status: 'Queued'} as Job, [row()], () => ({}))
    const ro = await editor()
    expect(ro.find('th.del-col').exists()).toBe(false)
    expect(ro.find('button[aria-label="Delete document"]').exists()).toBe(false)
    ro.unmount()
  })

  it('deletes one document from its row after confirming', async () => {
    const calls = stub(draft, [row(), row({n: 2, file: '3-1001_1.jpg', include: false})], () => ({}))
    const w = await editor()
    await w.findAll('button[aria-label="Delete document"]')[1].trigger('click')
    await button(w, 'Delete')!.trigger('click')
    await flushPromises()
    expect(calls.some((c) => c.method === 'DELETE' && c.url.endsWith('/api/jobs/j1/rows/2'))).toBe(true)
    expect(w.text()).not.toContain('3-1001_1.jpg')
    w.unmount()
  })

  it('says how many were deleted and how many stayed, and clears them from the selection', async () => {
    const rows = [row(), created({n: 2, file: '1-2345_01_b.jpg'}), row({n: 3, file: '3-1001_1.jpg'}), row({n: 4, file: '12-5678_1.jpg'})]
    const calls = stub(draft, rows, (b) => ({deleted: b.rows.filter((n) => n !== 2), others: [],
      skipped: [{n: 2, file: '1-2345_01_b.jpg', code: 'created', reason: 'It already created records in CollectionSpace.'}]}))
    const w = await editor()
    for (const f of ['15-1234_1.jpg', '1-2345_01_b.jpg', '3-1001_1.jpg']) await w.find(`input[aria-label="Select ${f}"]`).setValue(true)
    await button(w, 'Delete selected')!.trigger('click')
    await button(w, 'Delete 2 documents')!.trigger('click')
    await flushPromises()
    expect(calls.find((c) => c.url.endsWith('/rows/delete'))!.body).toEqual({rows: [1, 2, 3]})
    expect(w.find('#editor-message').text()).toBe('Deleted 2 documents. 1 couldn\'t be deleted because it already created records in CollectionSpace.')
    expect(w.text()).not.toContain('15-1234_1.jpg')
    expect(w.text()).toContain('1-2345_01_b.jpg')
    expect(w.find('.sel-banner').text()).toContain('1 selected') // only the one that stayed
    w.unmount()
  })

  it('with every document deleted, the job is deleted, as when its last document is deleted', async () => {
    const rows = [row(), row({n: 2, file: '3-1001_1.jpg', include: false})]
    const calls = stub(draft, rows, () => ({deleted: [1, 2], skipped: [], others: [], jobStatus: 'Deleted'}))
    const w = await editor()
    await w.find('input[aria-label="Select all documents on this page"]').setValue(true)
    await button(w, 'Delete selected')!.trigger('click')
    expect(w.find('.bulk-confirm').text()).toContain('That\'s every document in the job, so the job is deleted too.')
    await button(w, 'Delete 2 documents')!.trigger('click')
    await flushPromises()
    expect(w.find('#editor-message').text()).toBe('That was the job\'s last document, so the job was deleted.')
    expect(w.text()).toContain('No documents yet.')
    expect(w.find('.sel-banner').exists()).toBe(false)
    // what's added next goes to a new job, not the deleted one
    const name = w.find('input[placeholder^=\'e.g.\']')
    await name.setValue('Next batch')
    await name.trigger('change')
    await flushPromises()
    expect(calls.filter((c) => c.method === 'POST' && c.url.endsWith('/api/jobs'))).toHaveLength(1)
    w.unmount()
  })
})
