/** A job list says it is loading until the server's first answer: it never reads as empty before then. */
import {afterEach, describe, expect, it, vi} from 'vitest'
import {flushPromises, mount} from '@vue/test-utils'
import type {TenantInfo} from '../types'
import DraftsList from '@/components/job/DraftsList.vue'
import FinishedJobs from '@/components/job/FinishedJobs.vue'
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
