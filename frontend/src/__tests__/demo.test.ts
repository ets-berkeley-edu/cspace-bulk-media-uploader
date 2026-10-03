/** Demo tools pane (demo builds only): collapsible, off when the server's demo mode is off, and its controls. */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest'
import {flushPromises, mount} from '@vue/test-utils'
import DemoPane from '../components/DemoPane.vue'
import {COMMANDS, DEMO_BUILD, type DemoStatus, demoSummary, failureText} from '../lib/demo'

const sim = {
  delay: 0, upload_mbps: 0, rules: [], term_states: {}, term_renames: {}, deleted_languages: [], language_renames: {},
  steps: ['media', 'upload', 'termRead'], people: ['Leslie Freund'], orgs: ['Phoebe A. Hearst Museum of Anthropology'],
  languages: {spa: 'Spanish'}, term_names: {LeslieFreund1: 'Leslie Freund'},
}
const status = (p: Partial<DemoStatus> = {}): DemoStatus => ({browserUploadMbps: 0, cspaceUrl: 'http://localhost:8180', alwaysRunTime: false,
  sim: {...sim}, simError: '', ...p})

let calls: { url: string; method: string; body: unknown }[] = []
function stub(routes: (url: string, method: string) => { status?: number; body: unknown }) {
  calls = []
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    calls.push({url, method, body: init?.body ? JSON.parse(init.body as string) : undefined})
    const r = routes(url, method)
    return Promise.resolve(new Response(JSON.stringify(r.body), {status: r.status ?? 200, headers: {'content-type': 'application/json'}}))
  }))
}
beforeEach(() => { try { localStorage.clear() } catch { /* none */ } })
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('Demo tools', () => {
  it('is in this build (tests run in a non-production mode) and has the check-script commands', () => {
    expect(DEMO_BUILD).toBe(true)
    expect(COMMANDS.map((c) => c.lines).join('\n')).toContain('check_cspace.py --roles')
    expect(COMMANDS[0].lines).toContain('read -rs CSPACE_PASSWORD') // never a password on the command line
  })

  it('collapses to one line with a summary, and remembers it', async () => {
    stub(() => ({body: status({browserUploadMbps: 2})}))
    const w = mount(DemoPane)
    await flushPromises()
    expect(w.find('#demoBody').isVisible()).toBe(true)
    await w.find('button.chevron').trigger('click')
    expect(w.find('#demoBody').attributes('style')).toContain('display: none')
    expect(w.find('.demo-summary').text()).toContain('Browser uploads: 2 MB/s')
    expect(localStorage.getItem('bmuDemoPaneOpen')).toBe('0')
    expect(mount(DemoPane).find('button.chevron').attributes('aria-expanded')).toBe('false')
  })

  it('says so when the server\'s demo mode is off', async () => {
    stub(() => ({status: 404, body: {detail: 'Not Found'}}))
    const w = mount(DemoPane)
    await flushPromises()
    expect(w.text()).toContain('Demo tools are off in this environment')
    expect(w.text()).toContain('Check scripts and other commands')
  })

  it('sets the browser upload speed and the simulator\'s run speed', async () => {
    stub((url) => ({body: url.includes('browser-upload') ? {browserUploadMbps: 1} : url.includes('/sim/') ? sim : status()}))
    const w = mount(DemoPane)
    await flushPromises()
    const [browser, runSpeed] = w.findAll('select')
    await browser.setValue('1')
    await flushPromises()
    expect(calls.find((c) => c.url === '/api/_demo/browser-upload')?.body).toEqual({mbps: 1})
    await runSpeed.setValue('5')
    await flushPromises()
    expect(calls.find((c) => c.url === '/api/_demo/sim/slow')?.body).toEqual({params: {seconds: 0, upload_mbps: 5}})
    expect(w.text()).toContain('File uploads to CollectionSpace in job runs: 5 MB/s.')
  })

  it('deletes all jobs only after confirming, and tells the app', async () => {
    stub((url) => ({body: url.includes('delete-all') ? {deleted: 3, skipped: ['Running one']} : status()}))
    const w = mount(DemoPane)
    await flushPromises()
    await w.findAll('button').find((b) => b.text() === 'Delete all jobs…')!.trigger('click')
    expect(calls.some((c) => c.url.includes('delete-all'))).toBe(false)
    await w.findAll('button').find((b) => b.text() === 'Delete all jobs')!.trigger('click')
    await flushPromises()
    expect(w.emitted('jobsDeleted')![0][0]).toBe('Demo tools deleted 3 jobs. Kept 1 running: Running one.')
  })

  it('names changed terms by their display names, and says what a failure does', async () => {
    stub(() => ({body: status({sim: {...sim, term_renames: {LeslieFreund1: 'L. Freund'}}})}))
    const w = mount(DemoPane)
    await flushPromises()
    expect(w.text()).toContain('Leslie Freund: renamed “L. Freund”')
    expect(failureText('upload', 500, 1)).toBe('The next “upload” request fails with 500.')
    expect(failureText('media', 503, 3)).toBe('The next 3 “media” requests fail with 503.')
    expect(failureText('relation', 403, 0)).toBe('Every “relation” request fails with 403 until you clear failures.')
  })

  it('summarizes failures and term changes', () => {
    const s = status({sim: {...sim, delay: 2, rules: [{step: 'upload', match: '', status: 500, effect: '', count: 1, left: 1, client: 'worker'}],
      term_renames: {leslie: 'L. Freund'}}})
    expect(demoSummary(s)).toBe('Browser uploads: full speed · Run uploads: full speed · 2 s delay per create · 1 failure set · 1 term change')
  })
})
