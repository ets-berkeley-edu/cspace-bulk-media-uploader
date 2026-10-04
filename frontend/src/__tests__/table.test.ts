import {describe, expect, it} from 'vitest'
import {flushPromises, mount} from '@vue/test-utils'
import {cycleSort, tableState, tableView} from '../lib/table'
import type {Job, Row, TenantInfo} from '../types'
import JobResults from '@/components/job/JobResults.vue'
import Pagination from '@/components/util/Pagination.vue'
import SortableColumnHeader from '@/components/util/SortableColumnHeader.vue'

const items = Array.from({length: 60}, (_, i) => ({id: i, name: `doc ${i % 7}`, odd: i % 2 === 1}))
const keys = {name: (x: (typeof items)[number]) => x.name, id: (x: (typeof items)[number]) => x.id}

describe('paging, sorting and filtering (design: Large jobs)', () => {
  it('pages 25 at a time and keeps the page in range', () => {
    const st = tableState()
    let v = tableView(items, st, keys)
    expect(v.shown.map((x) => x.id)).toEqual([...Array(25).keys()])
    expect(v.pages).toBe(3)
    st.page = 3
    v = tableView(items, st, keys)
    expect(v.shown).toHaveLength(10)
    st.size = 100
    expect(tableView(items, st, keys).shown).toHaveLength(60) // page 3 of 1 is clamped
    expect(st.page).toBe(1)
  })

  it('sorts ascending, descending, then back to the original order; ties keep the original order', () => {
    const st = tableState(100)
    cycleSort(st, 'name')
    let v = tableView(items, st, keys)
    expect(v.shown.slice(0, 3).map((x) => x.id)).toEqual([0, 7, 14])
    cycleSort(st, 'name')
    v = tableView(items, st, keys)
    expect(v.shown[0].name).toBe('doc 6')
    expect(v.shown.slice(0, 2).map((x) => x.id)).toEqual([6, 13])
    cycleSort(st, 'name')
    expect(st.sort).toBeNull()
    expect(tableView(items, st, keys).shown[0].id).toBe(0)
  })

  it('filters, counting what it filtered from', () => {
    const st = tableState()
    st.filter = 'odd'
    const v = tableView(items, st, keys, (x, f) => (f === 'odd' ? x.odd : true))
    expect(v.total).toBe(30)
    expect(v.of).toBe(60)
  })

  it('the pager and sortable headings change the table state', async () => {
    const st = tableState()
    const p = mount(Pagination, {props: {state: st, total: 60, of: 80, pages: 3, start: 0, noun: 'documents', filters: [['all', 'All'], ['odd', 'Odd']]}})
    expect(p.text()).toContain('1–25 of 60 documents (filtered from 80)')
    await p.find('button[aria-label="Next page"]').trigger('click')
    expect(st.page).toBe(2)
    await p.find('select[aria-label="Documents per page"]').setValue('50')
    expect(st.size).toBe(50)
    expect(st.page).toBe(1)
    const h = mount({components: {SortableColumnHeader}, template: '<table><tr><SortableColumnHeader :state=\'st\' sort-key=\'name\' label=\'Document\'/></tr></table>', data: () => ({st})})
    await h.find('button').trigger('click')
    expect(st.sort).toBe('name')
    expect(h.find('th').attributes('aria-sort')).toBe('ascending')
  })
})

describe('results view pages its documents', () => {
  const tenant = {handling: [{id: 'link', label: 'Link to existing object', object: 'existing', id_rule: 'object'}]} as unknown as TenantInfo
  const rows = Array.from({length: 40}, (_, i) => ({n: i + 1, file: `15-${1000 + i}.jpg`, handling: 'link', include: true, checks: [], upload: {s: 'done'},
    result: {state: i < 3 ? 'Partial' : 'Done', steps: {media: {s: 'done', csid: `m${i}`}}}})) as unknown as Row[]
  it('shows 25 per page and sorts by result', async () => {
    const w = mount(JobResults, {props: {job: {id: 'j', run: 1} as Job, rows, runs: [], tenant}})
    expect(w.findAll('tbody tr')).toHaveLength(25)
    await w.findAll('.sort-col-btn').find((b) => b.text().startsWith('Result'))!.trigger('click')
    await flushPromises()
    expect(w.find('tbody tr').text()).toContain('Partial')
    await w.findAll('button[aria-label="Next page"]')[0].trigger('click')
    expect(w.findAll('tbody tr')).toHaveLength(15)
  })
})
