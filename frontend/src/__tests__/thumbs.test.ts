import {describe, expect, it} from 'vitest'
import {mount} from '@vue/test-utils'
import ThumbCell from '../components/ThumbCell.vue'
import {fileKind} from '../lib/files'
import type {Row} from '../types'

const row = (p: Partial<Row> = {}): Row => ({n: 3, v: 2, file: '15-1234_a.jpg', size: 1, contentType: 'image/jpeg', handling: 'link', obj: '15-1234',
  objParsed: '15-1234', img: '15-1234_a', parseOk: true, idnum: '15-1234', date: '', restricted: false, type: [], creator: '', contributor: '',
  rightsHolder: '', description: '', copyright: '', include: true, upload: {s: 'done'}, checks: [], result: null, ...p})

describe('thumbnails (design: User interface, Thumbnails)', () => {
  it('uses the local preview, else the web app\'s thumbnail; never an S3 URL', () => {
    expect(mount(ThumbCell, {props: {jobId: 'j', row: row(), preview: 'blob:local'}}).find('img').attributes('src')).toBe('blob:local')
    expect(mount(ThumbCell, {props: {jobId: 'j', row: row()}}).find('img').attributes('src')).toBe('/api/jobs/j/rows/3/thumbnail?v=2')
    expect(mount(ThumbCell, {props: {jobId: 'j', row: row({upload: {s: 'pending'}})}}).find('img').exists()).toBe(false)
  })

  it('locks a protected file\'s preview for everyone but its uploader, until CollectionSpace has it', () => {
    const p = {reason: 'NAGPRA status on the object', hides: false}
    const w = mount(ThumbCell, {props: {jobId: 'j', row: row({protected: p})}})
    expect(w.find('.thumb.locked').exists()).toBe(true)
    expect(w.find('img').exists()).toBe(false)
    const done = row({protected: p, result: {state: 'Done', steps: {upload: {s: 'done', csid: 'b1'}}}})
    expect(mount(ThumbCell, {props: {jobId: 'j', row: done}}).find('img').exists()).toBe(true) // CollectionSpace's permissions apply
  })

  it('shows a type icon for audio, video and 3D, and a larger view on click', async () => {
    expect(fileKind('a.mp3').icon).toBe('♪')
    expect(fileKind('a.mp4').label).toBe('Video')
    expect(mount(ThumbCell, {props: {jobId: 'j', row: row({file: '15-1234.wav'})}}).text()).toContain('♪')
    const w = mount(ThumbCell, {props: {jobId: 'j', row: row()}, attachTo: document.body})
    await w.find('button').trigger('click')
    expect(document.body.querySelector('.lightbox img')?.getAttribute('src')).toBe('/api/jobs/j/rows/3/thumbnail?v=2&size=large')
    w.unmount()
  })
})
