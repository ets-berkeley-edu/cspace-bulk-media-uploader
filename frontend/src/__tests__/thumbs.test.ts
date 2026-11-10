import {beforeEach, describe, expect, it} from 'vitest'
import {mount} from '@vue/test-utils'
import {fileKind} from '../lib/files'
import {thumbnailAllowed} from '../lib/roles'
import type {Row, TenantInfo} from '../types'
import JobDocsTable from '@/components/job/JobDocumentsTable.vue'
import DocumentThumbnail from '@/components/util/DocumentThumbnail.vue'
import {useContextStore} from '@/stores/context'

const signIn = (role: 'staff' | 'intern', thumbKey?: string) =>
  useContextStore().setCurrentUser({user: role === 'staff' ? 'admin' : 'intern', role, perms: {}, tenant: {}, thumbKey} as never)

const row = (p: Partial<Row> = {}): Row => ({n: 3, v: 2, file: '15-1234_a.jpg', size: 1, contentType: 'image/jpeg', handling: 'link', obj: '15-1234',
  objParsed: '15-1234', img: '15-1234_a', parseOk: true, idnum: '15-1234', date: '', restricted: false, type: [], creator: '', contributor: '',
  rightsHolder: '', description: '', copyright: '', include: true, upload: {s: 'done'}, checks: [], result: null, ...p})

describe('thumbnails (design: User interface, Thumbnails)', () => {
  beforeEach(() => signIn('staff'))

  it('uses the local preview, else the web app\'s thumbnail; never an S3 URL', () => {
    expect(mount(DocumentThumbnail, {props: {jobId: 'j', row: row(), preview: 'blob:local'}}).find('img').attributes('src')).toBe('blob:local')
    expect(mount(DocumentThumbnail, {props: {jobId: 'j', row: row()}}).find('img').attributes('src')).toBe('/api/jobs/j/rows/3/thumbnail?v=2')
    expect(mount(DocumentThumbnail, {props: {jobId: 'j', row: row({upload: {s: 'pending'}})}}).find('img').exists()).toBe(false)
  })

  it('locks a protected file\'s preview for everyone but its uploader, until CollectionSpace has it', () => {
    const p = {reason: 'NAGPRA status on the object', hides: false}
    const w = mount(DocumentThumbnail, {props: {jobId: 'j', row: row({protected: p})}})
    expect(w.find('.thumb.locked').exists()).toBe(true)
    expect(w.find('img').exists()).toBe(false)
    const done = row({protected: p, result: {state: 'Done', steps: {upload: {s: 'done', csid: 'b1'}}}})
    expect(mount(DocumentThumbnail, {props: {jobId: 'j', row: done}}).find('img').exists()).toBe(true) // CollectionSpace's permissions apply
  })

  it('shows a type icon for audio, video and 3D, and a larger view on click', async () => {
    expect(fileKind('a.mp3').icon).toBe('♪')
    expect(fileKind('a.mp4').label).toBe('Video')
    expect(mount(DocumentThumbnail, {props: {jobId: 'j', row: row({file: '15-1234.wav'})}}).text()).toContain('♪')
    const w = mount(DocumentThumbnail, {props: {jobId: 'j', row: row()}, attachTo: document.body})
    await w.find('button').trigger('click')
    expect(document.body.querySelector('.lightbox img')?.getAttribute('src')).toBe('/api/jobs/j/rows/3/thumbnail?v=2&size=large')
    w.unmount()
  })

  it('doesn\'t ask again for a thumbnail that failed while the document\'s v and upload state stay the same', async () => {
    const w = mount(DocumentThumbnail, {props: {jobId: 'j', row: row()}})
    await w.find('img').trigger('error')
    expect(w.find('img').exists()).toBe(false)
    await w.setProps({row: row()}) // a refresh: a new row object, nothing changed
    await w.setProps({row: row()})
    expect(w.find('img').exists()).toBe(false)
  })

  it('asks again once the thumbnail is stored (a new v), as for a TIFF whose thumbnail is still being made', async () => {
    const w = mount(DocumentThumbnail, {props: {jobId: 'j', row: row({file: '15-1234_a.tif', contentType: 'image/tiff'})}})
    await w.find('img').trigger('error')
    expect(w.find('img').exists()).toBe(false)
    await w.setProps({row: row({file: '15-1234_a.tif', contentType: 'image/tiff', v: 3})})
    expect(w.find('img').attributes('src')).toBe('/api/jobs/j/rows/3/thumbnail?v=3')
  })

  it('asks again when the file reaches CollectionSpace, for its derivative', async () => {
    const running = row({result: {state: 'In progress', steps: {upload: {s: 'sending'}}}})
    const w = mount(DocumentThumbnail, {props: {jobId: 'j', row: running}})
    await w.find('img').trigger('error')
    expect(w.find('img').exists()).toBe(false)
    await w.setProps({row: row({result: {state: 'Done', steps: {upload: {s: 'done', csid: 'b1'}}}})})
    expect(w.find('img').exists()).toBe(true)
  })

  it('staff get every thumbnail, whether the job is open to interns or not (design: Roles)', () => {
    const done = row({result: {state: 'Done', steps: {upload: {s: 'done', csid: 'b1'}}}})
    for (const internOpen of [false, true]) {
      expect(mount(DocumentThumbnail, {props: {jobId: 'j', row: row(), internOpen}}).find('img').exists()).toBe(true)
      expect(mount(DocumentThumbnail, {props: {jobId: 'j', row: done, internOpen}}).find('img').exists()).toBe(true)
    }
  })

  it('an intern\'s page doesn\'t ask for what the server always refuses an intern: a staff-only job, or a file in CollectionSpace', () => {
    signIn('intern')
    const done = row({result: {state: 'Done', steps: {upload: {s: 'done', csid: 'b1'}}}})
    const staffOnly = mount(DocumentThumbnail, {props: {jobId: 'j', row: row(), internOpen: false}})
    expect(staffOnly.find('img').exists()).toBe(false)
    expect(staffOnly.text()).toContain(fileKind('a.jpg').icon) // the same tile as a thumbnail that failed
    expect(mount(DocumentThumbnail, {props: {jobId: 'j', row: done, internOpen: true}}).find('img').exists()).toBe(false)
    expect(mount(DocumentThumbnail, {props: {jobId: 'j', row: row(), internOpen: true}}).find('img').attributes('src'))
      .toBe('/api/jobs/j/rows/3/thumbnail?v=2')
  })

  it('the rule matches the server\'s (app.get_thumbnail), and asks nothing without a signed-in user', () => {
    const staff = {role: 'staff' as const}
    const intern = {role: 'intern' as const}
    expect(thumbnailAllowed(staff, {internOpen: false}, true)).toBe(true)
    expect(thumbnailAllowed(staff, {}, false)).toBe(true)
    expect(thumbnailAllowed(intern, {internOpen: true}, false)).toBe(true)
    expect(thumbnailAllowed(intern, {internOpen: true}, true)).toBe(false)
    expect(thumbnailAllowed(intern, {internOpen: false}, false)).toBe(false)
    expect(thumbnailAllowed(intern, {}, false)).toBe(false)
    expect(thumbnailAllowed(null, {internOpen: true}, false)).toBe(false)
  })

  it('Finished jobs: an intern\'s expanded staff-only job asks for no thumbnail; staff\'s asks for each', () => {
    const tenant = {key: 'pahma', name: 'PAHMA', handling: [{id: 'link', label: 'Link to existing object', object: 'existing', id_rule: 'object'}]} as unknown as TenantInfo
    const rows = [1, 2].map((n) => row({n, result: {state: 'Done', steps: {upload: {s: 'done', csid: `b${n}`}}}}))
    const job = {id: 'j1', name: 'Spring batch', status: 'Completed', createdBy: 'admin', rowCount: 2, run: 1, internOpen: false} as never
    expect(mount(JobDocsTable, {props: {job, rows, tenant, kind: 'history'}}).findAll('img')).toHaveLength(2)
    signIn('intern')
    expect(mount(JobDocsTable, {props: {job, rows, tenant, kind: 'history'}}).findAll('img')).toHaveLength(0)
  })

  it('puts the session\'s key in the address, so the browser keeps a thumbnail only for that session', async () => {
    signIn('staff', 'abc123')
    const w = mount(DocumentThumbnail, {props: {jobId: 'j', row: row()}, attachTo: document.body})
    expect(w.find('img').attributes('src')).toBe('/api/jobs/j/rows/3/thumbnail?v=2&k=abc123')
    await w.find('button').trigger('click')
    expect(document.body.querySelector('.lightbox img')?.getAttribute('src')).toBe('/api/jobs/j/rows/3/thumbnail?v=2&size=large&k=abc123')
    w.unmount()
  })
})
