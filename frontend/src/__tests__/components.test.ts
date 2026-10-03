import {afterEach, describe, expect, it, vi} from 'vitest'
import {flushPromises, mount} from '@vue/test-utils'
import type {Perms, Row, TenantInfo} from '../types'
import AuthorityInput from '@/components/util/AuthorityInput.vue'
import DocumentRow from '@/components/job/DocumentRow.vue'

const REF = 'urn:cspace:pahma.cspace.berkeley.edu:personauthorities:name(person):item:name(7475)\'Leslie Freund\''

afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers() })

describe('AuthorityInput', () => {
  it('searches after 3 characters and emits the refName of the chosen term', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({terms: [{refName: REF, displayName: 'Leslie Freund', source: 'person'}]}),
      {status: 200, headers: {'content-type': 'application/json'}}))
    vi.stubGlobal('fetch', fetchMock)
    const w = mount(AuthorityInput, {props: {id: 'creator', modelValue: '', field: 'creator', label: 'Creator'}})
    const input = w.find('input')
    await input.setValue('fr')
    expect(w.text()).toContain('3+ characters')
    await input.setValue('freu')
    await vi.advanceTimersByTimeAsync(300)
    expect(fetchMock).not.toHaveBeenCalled() // the CollectionSpace UI's 500 ms find delay
    await vi.advanceTimersByTimeAsync(250)
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith('/api/authorities?field=creator&q=freu', expect.anything())
    await w.find('.ac-item').trigger('mousedown')
    expect(w.emitted('update:modelValue')?.[0]).toEqual([REF])
  })

  it('uses the tenant\'s find delay and minimum length (PAHMA: 1000 ms)', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({terms: []}),
      {status: 200, headers: {'content-type': 'application/json'}}))
    vi.stubGlobal('fetch', fetchMock)
    const w = mount(AuthorityInput, {props: {id: 'creator', modelValue: '', field: 'creator', label: 'Creator', timing: {findDelayMs: 1000, minLength: 4}}})
    await w.find('input').setValue('fre')
    expect(w.text()).toContain('4+ characters')
    await w.find('input').setValue('freu')
    await vi.advanceTimersByTimeAsync(900)
    expect(fetchMock).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(150)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('shows only the display name of the stored refName, and never saves free text', async () => {
    vi.useFakeTimers()
    const w = mount(AuthorityInput, {props: {id: 'creator', modelValue: REF, field: 'creator', label: 'Creator'}})
    const input = w.find('input')
    expect((input.element as HTMLInputElement).value).toBe('Leslie Freund')
    await input.setValue('Somebody New')
    await input.trigger('blur')
    await vi.advanceTimersByTimeAsync(200)
    expect(w.emitted('update:modelValue')).toBeUndefined()
    expect((input.element as HTMLInputElement).value).toBe('Leslie Freund')
  })
})

const tenant: TenantInfo = {
  key: 'pahma', name: 'PAHMA', filenameHint: 'hint', filenamePattern: '^(?P<obj>[A-Za-z0-9][A-Za-z0-9.-]*)(?:_(?P<suffix>[A-Za-z0-9._-]+))?$', mediaTypes: [{value: 'image', label: 'image'}, {value: 'slide', label: 'slide'}], languageDefault: '', authorityFields: {},
  publish: {field: 'approvedForWeb', header: 'Restricted', invert: true},
  handling: [{id: 'link', label: 'Link to existing object', object: 'existing', id_rule: 'object'},
             {id: 'create', label: 'Create new object + link', object: 'create', id_rule: 'object'}],
}
const perms: Perms = {media: true, relations: true, objects: true, readObjects: true, authorities: true, groups: true}
function row(p: Partial<Row> = {}): Row {
  return {n: 1, file: '15-1234_a.jpg', size: 10, contentType: 'image/jpeg', handling: 'link', obj: '15-1234', objParsed: '15-1234',
    img: '15-1234_a', parseOk: true, idnum: '15-1234', date: '', restricted: false, type: [], creator: '', contributor: '',
    rightsHolder: '', description: '', copyright: '', include: true, upload: {s: 'done'}, checks: [], result: null, ...p}
}

describe('DocumentRow', () => {
  it('shows Needs fixing for blocking checks and locks rows that created records', () => {
    let w = mount({components: {DocumentRow}, template: '<table><DocumentRow v-bind=\'p\'/></table>',
      data: () => ({p: {row: row({checks: [{level: 'block', text: 'No object'}]}), tenant, perms, expanded: false, readonly: false}})})
    expect(w.text()).toContain('Needs fixing')
    w = mount({components: {DocumentRow}, template: '<table><DocumentRow v-bind=\'p\'/></table>',
      data: () => ({p: {row: row({result: {state: 'Partial', steps: {media: {s: 'done', csid: 'm1'}}}}), tenant, perms, expanded: true, readonly: false}})})
    expect(w.text()).toContain('already created records')
    expect(w.find('select').attributes('disabled')).toBeDefined()
  })
})

function mountRow(p: Record<string, unknown>) {
  return mount({components: {DocumentRow}, template: '<table><DocumentRow v-bind=\'p\'/></table>',
    data: () => ({p: {row: row(), tenant, perms, expanded: true, readonly: false, ...p}})})
}

describe('DocumentRow checks', () => {
  it('labels checks Must fix and Warning, and flags warnings in the Status column', () => {
    const w = mountRow({row: row({checks: [{level: 'warn', text: 'A Media record with ID 15-1234 already exists'}],
      lookups: {object: {value: '15-1234', csids: ['c1'], at: 0}}})})
    expect(w.text()).toContain('Warning: A Media record')
    expect(w.text()).toContain('Found — will link')
    expect(w.find('[title="This document has warnings"]').exists()).toBe(true)
    expect(mountRow({row: row({checks: [{level: 'block', text: 'No object'}]})}).text()).toContain('Must fix: No object')
  })

  it('disables handling options the user has no permission for', () => {
    const w = mountRow({perms: {...perms, objects: false}})
    const create = w.findAll('option').find((o) => o.attributes('value') === 'create')!
    expect(create.attributes('disabled')).toBeDefined()
    expect(create.text()).toContain('(no permission)')
  })

  it('shows upload progress, then Verifying, before the checks', () => {
    expect(mountRow({row: row({upload: {s: 'uploading', pct: 40}}), uploadingHere: true}).text()).toContain('Uploading 40%')
    expect(mountRow({row: row({upload: {s: 'verifying'}}), uploadingHere: true}).text()).toContain('Verifying…')
    expect(mountRow({row: row(), checking: true}).text()).toContain('Checking…')
  })

  it('shows the Group box only when the job creates a group; documents without an object can\'t join', async () => {
    expect(mountRow({row: row()}).find('input[aria-label$="in the job\'s group"]').exists()).toBe(false)
    const w = mountRow({row: row(), groupOn: true})
    const box = w.find('input[aria-label="15-1234_a.jpg in the job\'s group"]')
    expect((box.element as HTMLInputElement).checked).toBe(true)
    await box.setValue(false)
    expect(w.findComponent(DocumentRow).emitted('edit')?.[0]).toEqual([expect.anything(), {group: false}])
    const mediaOnly = mountRow({row: row({handling: 'mediaonly'}), groupOn: true,
      tenant: {...tenant, handling: [...tenant.handling, {id: 'mediaonly', label: 'Media only', object: 'none', id_rule: 'image'}]}})
    expect((mediaOnly.find('input[aria-label="15-1234_a.jpg in the job\'s group"]').element as HTMLInputElement).disabled).toBe(true)
  })

  it('Exclude is checked for an excluded document, and checking it excludes the document', async () => {
    const w = mountRow({row: row()})
    const box = w.find('input[aria-label="Exclude 15-1234_a.jpg from the job"]')
    expect((box.element as HTMLInputElement).checked).toBe(false)
    await box.setValue(true)
    expect(w.findComponent(DocumentRow).emitted('edit')?.[0]).toEqual([expect.anything(), {include: false}])
    const excluded = mountRow({row: row({include: false})})
    expect((excluded.find('input[aria-label="Exclude 15-1234_a.jpg from the job"]').element as HTMLInputElement).checked).toBe(true)
    expect(excluded.text()).toContain('Excluded — ignored')
    await excluded.find('input[aria-label="Exclude 15-1234_a.jpg from the job"]').setValue(false)
    expect(excluded.findComponent(DocumentRow).emitted('edit')?.[0]).toEqual([expect.anything(), {include: true}])
  })

  it('in a running job\'s preview, Status shows each document\'s run state', () => {
    const busy = mountRow({row: row({result: {state: 'In progress', steps: {}}}), runView: true, readonly: true})
    expect(busy.text()).toContain('In progress')
    expect(busy.text()).not.toContain('▶')
    expect(busy.find('.v-chip .v-progress-circular').exists()).toBe(true) // a spinning ring, not a play/expand triangle
    expect(mountRow({row: row(), runView: true, readonly: true}).text()).toContain('Not started')
    expect(mountRow({row: row({result: {state: 'Partial', steps: {media: {s: 'done', csid: 'm'}}}}), runView: true, readonly: true}).text()).toContain('Partial')
  })

  it('puts the identification number before the object number and Language last, marked PRESET while it holds the default', () => {
    const eng = 'urn:cspace:pahma.cspace.berkeley.edu:vocabularies:name(languages):item:name(eng)\'English\''
    const t = {...tenant, languageDefault: eng}
    const w = mountRow({tenant: t, row: row({language: [eng]})})
    const labels = w.findAll('.detail-grid .field-label').map((x) => x.text())
    const at = (name: string) => labels.findIndex((l) => l.startsWith(name))
    expect(at('Identification number')).toBeLessThan(at('Object number'))
    expect(at('Description')).toBeLessThan(at('Copyright statement'))
    expect(at('Language')).toBe(labels.length - 1)
    expect(labels[at('Language')]).toContain('PRESET')
    const chosen = mountRow({tenant: t, row: row({language: [eng], touched: ['language']})})
    expect(chosen.text()).not.toContain('PRESET')
  })
  it('marks fields filled from the row\'s handling presets PRESET, until the user edits them', () => {
    const org = 'urn:cspace:pahma.cspace.berkeley.edu:orgauthorities:name(organization):item:name(Hearst)\'Hearst Museum\''
    const t: TenantInfo = {...tenant, handling: [{...tenant.handling[0], presets: {type: ['slide'], contributor: org, copyright: '© Regents'}},
      tenant.handling[1]]}
    const presetOf = (w: ReturnType<typeof mountRow>) => w.findAll('.field-preset > .field-label').map((x) => x.text().replace('PRESET', '').trim())
    const filled = row({type: ['slide'], contributor: org, copyright: '© Regents'})
    expect(presetOf(mountRow({tenant: t, row: filled}))).toEqual(['Media type', 'Contributor', 'Copyright statement'])
    expect(presetOf(mountRow({tenant: t, row: {...filled, touched: ['contributor']}}))).toEqual(['Media type', 'Copyright statement'])
    expect(presetOf(mountRow({tenant: t, row: {...filled, handling: 'create'}}))).toEqual([]) // not this handling's presets
  })
  it('warns that deleting the job\'s last document deletes the job', async () => {
    const w = mountRow({last: true})
    await w.find('button[aria-label="Delete document"]').trigger('click')
    expect(w.text()).toContain('This is the job\'s last document, so the job is deleted too.')
    const other = mountRow({})
    await other.find('button[aria-label="Delete document"]').trigger('click')
    expect(other.text()).not.toContain('last document')
  })
  it('offers Retry and Remove for a failed upload, or one this page isn\'t sending', async () => {
    const failed = mountRow({row: row({upload: {s: 'failed'}})})
    expect(failed.text()).toContain('Upload failed')
    await failed.findAll('button').find((b) => b.text() === 'Retry')!.trigger('click')
    expect(failed.findComponent(DocumentRow).emitted('retry')).toHaveLength(1)
    await failed.findAll('button').find((b) => b.text() === 'Remove')!.trigger('click')
    expect(failed.text()).toContain('Remove this document?')
    await failed.findAll('button').find((b) => b.text() === 'Remove')!.trigger('click')
    expect(failed.findComponent(DocumentRow).emitted('remove')).toHaveLength(1)
    const stalled = mountRow({row: row({upload: {s: 'pending'}})})
    expect(stalled.text()).toContain('Upload not finished')
    expect(stalled.findAll('button').some((b) => b.text() === 'Retry')).toBe(true)
    expect(mountRow({row: row({upload: {s: 'pending'}}), uploadingHere: true}).text()).toContain('Waiting to upload')
  })
  it('warns that removing a failed upload that is the job\'s last document deletes the job', async () => {
    const last = mountRow({row: row({upload: {s: 'failed'}}), last: true})
    await last.findAll('button').find((b) => b.text() === 'Remove')!.trigger('click')
    expect(last.text()).toContain('Remove this document? This is the job\'s last document, so the job is deleted too.')
    const other = mountRow({row: row({upload: {s: 'failed'}})})
    await other.findAll('button').find((b) => b.text() === 'Remove')!.trigger('click')
    expect(other.text()).not.toContain('last document')
  })
})

import RepeatingSelect from '@/components/util/RepeatingSelect.vue'

describe('RepeatingSelect (design: repeating media type and language)', () => {
  const options = [{value: 'still_image', label: 'still image'}, {value: 'document', label: 'document'}]

  it('shows labels, stores values, and adds or removes values', async () => {
    const w = mount(RepeatingSelect, {props: {id: 'pick', modelValue: ['still_image'], options, label: 'Media type', word: 'type'}})
    expect(w.find('select option:checked').text()).toBe('still image')
    await w.find('button.link').trigger('click') // + Add an additional type
    const selects = w.findAll('select')
    expect(selects).toHaveLength(2)
    expect(selects[1].find('option[value="still_image"]').attributes('disabled')).toBeDefined() // no repeats
    await selects[1].setValue('document')
    expect(w.emitted('update:modelValue')?.at(-1)).toEqual([['still_image', 'document']])
    await w.setProps({modelValue: ['still_image', 'document']})
    await w.findAll('button.x-btn')[0].trigger('click')
    expect(w.emitted('update:modelValue')?.at(-1)).toEqual([['document']])
  })

  it('keeps a stored value that isn\'t among the options, showing its display name', () => {
    const ref = 'urn:cspace:pahma.cspace.berkeley.edu:vocabularies:name(languages):item:name(eng)\'English\''
    const w = mount(RepeatingSelect, {props: {id: 'pick', modelValue: [ref], options: [], label: 'Language', word: 'language'}})
    expect(w.find('select option:checked').text()).toBe('English')
  })
})

describe('SortTh', () => {
  it('shows its hover description on the column heading', async () => {
    const {default: SortTh} = await import('../components/SortTh.vue')
    const {tableState} = await import('../lib/table')
    const w = mount({components: {SortTh}, template: '<table><thead><tr><SortTh v-bind=\'p\'/></tr></thead></table>',
      data: () => ({p: {state: tableState(), sortKey: 'include', label: 'Exclude', title: 'To exclude a document from a job, check the box.'}})})
    const th = w.find('th')
    expect(th.text()).toContain('Exclude')
    expect(th.attributes('title')).toBe('To exclude a document from a job, check the box.')
  })
})
