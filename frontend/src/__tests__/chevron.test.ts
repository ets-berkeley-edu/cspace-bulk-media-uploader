/** The expand/collapse toggle for job and document rows: a 20px SVG triangle in a 30px button, rotated when open. */
import {readFileSync} from 'node:fs'
import {resolve} from 'node:path'
import {describe, expect, it} from 'vitest'
import {mount} from '@vue/test-utils'
import type {Perms, Row, TenantInfo} from '../types'
import DocumentRow from '@/components/job/DocumentRow.vue'

const tenant = {key: 'pahma', name: 'PAHMA', filenameHint: '', filenamePattern: '^(?P<obj>[A-Za-z0-9.-]+)$', mediaTypes: [],
  languageDefault: '', authorityFields: {}, publish: {field: 'approvedForWeb', header: 'Restricted', invert: true},
  handling: [{id: 'link', label: 'Link to existing object', object: 'existing', id_rule: 'object'}]} as unknown as TenantInfo
const perms: Perms = {media: true, mediaUpdate: true, relations: true, objects: true, readObjects: true, authorities: true, groups: true}
const row = {n: 1, file: '15-1234_1.jpg', size: 10, contentType: 'image/jpeg', handling: 'link', obj: '15-1234', objParsed: '15-1234',
  img: '15-1234_1', parseOk: true, idnum: '15-1234', date: '', restricted: false, type: [], creator: '', contributor: '',
  rightsHolder: '', description: '', copyright: '', include: true, upload: {s: 'done'}, checks: [], result: null} as unknown as Row

function mountRow(expanded: boolean) {
  return mount({components: {DocumentRow}, template: '<table><DocumentRow v-bind=\'p\'/></table>',
    data: () => ({p: {row, tenant, perms, expanded, readonly: false}})})
}

describe('the expand/collapse toggle', () => {
  it('on a document row, keeps its label and expanded state and has no text', () => {
    for (const open of [false, true]) {
      const b = mountRow(open).find('button[aria-label="Show details"]')
      expect(b.classes()).toContain('chevron')
      expect(b.classes().includes('open')).toBe(open)
      expect(b.attributes('aria-expanded')).toBe(String(open))
      expect(b.find('svg').exists()).toBe(true)
      expect(b.text()).toBe('')
    }
  })

  it('no component still uses the small ▸ character for a row toggle', () => {
    // Every screen uses a Vuetify icon button
    for (const f of ['job/JobEditor', 'job/DocumentRow', 'job/DraftsList', 'job/QueueList', 'job/FinishedJobs', 'demo/DemoPane']) {
      const src = readFileSync(resolve(__dirname, `../components/${f}.vue`), 'utf8')
      expect(src).not.toContain('▸')
      expect(src).toContain(':icon="mdiChevronRight"')
    }
  })

  it('rotates the icon when open, without animation for people who ask for less motion', () => {
    const css = readFileSync(resolve(__dirname, '../assets/styles/bmu-global.css'), 'utf8')
    expect(css).toMatch(/\.chevron\.open \.v-icon \{\s*transform: rotate\(90deg\);/)
    expect(css).toMatch(/prefers-reduced-motion: reduce\) \{\s*\.chevron \.v-icon \{\s*transition: none;/)
  })
})
