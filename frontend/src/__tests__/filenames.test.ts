import {describe, expect, it} from 'vitest'
import {mount} from '@vue/test-utils'
import DocumentRow from '../components/DocumentRow.vue'
import {filenameProblems, idLabel, objectLabel} from '../lib/filenames'
import type {Perms, Row, TenantInfo} from '../types'

const tenant: TenantInfo = {
  key: 'pahma', name: 'PAHMA', filenameHint: 'Object number, optionally followed by _ and a suffix',
  filenamePattern: '^(?P<obj>[A-Za-z0-9][A-Za-z0-9.-]*)(?:_(?P<suffix>[A-Za-z0-9._-]+))?$',
  mediaTypes: [], languageDefault: '', authorityFields: {}, publish: {field: 'approvedForWeb', header: 'Restricted', invert: true},
  handling: [{id: 'link', label: 'Link to existing object', object: 'existing', id_rule: 'object'},
             {id: 'mediaonly', label: 'Media only', object: 'none', id_rule: 'image'}],
}
const perms: Perms = {media: true, relations: true, objects: true, readObjects: true, authorities: true, groups: true}
function row(p: Partial<Row> = {}): Row {
  return {n: 1, file: '15-1234_a.jpg', fileOriginal: '15-1234_a.jpg', size: 10, contentType: 'image/jpeg', handling: 'link',
    obj: '15-1234', objParsed: '15-1234', img: '15-1234_a', parseOk: true, idnum: '15-1234', date: '', restricted: false, type: [],
    creator: '', contributor: '', rightsHolder: '', description: '', copyright: '', include: true, upload: {s: 'done'}, checks: [], result: null, ...p}
}

describe('filename rules (design: Editable numbers and names)', () => {
  it('accepts a safe name that matches the tenant\'s pattern and keeps the extension', () => {
    expect(filenameProblems(tenant, '1-2345_3.jpg', 'IMG 4411.jpg', [])).toEqual([])
  })
  it.each([
    ['1-2345 3.jpg', 'Remove spaces'], ['1-2345_3.png', 'Keep the extension .jpg'], ['1-2345_3', 'Keep the file extension'],
    ['a/b.jpg', 'Remove slashes'], ['a..b.jpg', 'double dot'], ['.x.jpg', 'can\'t start with a dot'], ['a!.jpg', 'Use only letters'],
    ['_x.jpg', 'PAHMA\'s filename pattern'], ['15-1234_B.JPG', 'already has this name'],
  ])('rejects %s', (name, why) => {
    expect(filenameProblems(tenant, name, 'x.jpg', ['15-1234_b.jpg']).join(' ')).toContain(why)
  })
  it('labels numbers parsed, derived or edited', () => {
    expect(objectLabel(row()).text).toBe('(parsed)')
    expect(objectLabel(row({obj: '1-2345'}))).toMatchObject({edited: true, reset: '15-1234'})
    expect(idLabel(row({obj: '1-2345', idnum: '1-2345'}), tenant).text).toBe('(from the edited object number)')
    expect(idLabel(row({idnum: 'MY-ID'}), tenant)).toMatchObject({text: '(edited — differs from parsed value 15-1234)', reset: '15-1234'})
  })
})

describe('DocumentRow filename field', () => {
  function mountRow(r: Row) {
    return mount({components: {DocumentRow}, template: '<table><tbody><DocumentRow v-bind=\'p\'/></tbody></table>',
      data: () => ({p: {row: r, tenant, perms, expanded: true, readonly: false, otherNames: ['1-2345_1.jpg']}})})
  }
  it('shows problems as you type and renames only once the name passes', async () => {
    const w = mountRow(row({file: 'IMG 4411.jpg', fileOriginal: 'IMG 4411.jpg', parseOk: false, obj: '', objParsed: '', idnum: ''}))
    expect(w.text()).toContain('Fix filename')
    const input = w.find('input[aria-label="Filename"]')
    await input.setValue('1-2345_1.jpg')
    expect(w.text()).toContain('Another document in this job already has this name')
    await input.trigger('blur')
    expect(w.findComponent(DocumentRow).emitted('edit')).toBeUndefined()
    await input.setValue('1-2345_3.jpg')
    await input.trigger('blur')
    expect(w.findComponent(DocumentRow).emitted('edit')?.[0]).toEqual([{file: '1-2345_3.jpg'}])
  })
  it('marks a renamed document and offers the original name back', async () => {
    const w = mountRow(row({file: '1-2345_3.jpg', fileOriginal: 'IMG 4411.jpg'}))
    expect(w.text()).toContain('Renamed')
    expect(w.text()).toContain('(renamed — original IMG 4411.jpg)')
    await w.findAll('button').find((b) => b.text() === 'Use original filename')!.trigger('click')
    expect(w.findComponent(DocumentRow).emitted('edit')?.[0]).toEqual([{file: 'IMG 4411.jpg'}])
  })
})
