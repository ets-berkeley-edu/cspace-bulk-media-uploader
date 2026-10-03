/** Which environment this is (BMU_ENV_LABEL): shown on the sign-in page, in the header and in the tab's title, with
 *  a warning style when the CollectionSpace is a real server. */
import {afterEach, describe, expect, it, vi} from 'vitest'
import {flushPromises, mount} from '@vue/test-utils'
import App from '../views/Home.vue'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

function stub(env: unknown, me: unknown | null) {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    const [status, body] = url === '/api/env' ? [200, env] : url === '/api/me' ? (me ? [200, me] : [401, {detail: 'Please sign in'}]) : [200, {jobs: []}]
    return Promise.resolve(new Response(JSON.stringify(body), {status, headers: {'content-type': 'application/json'}}))
  }))
}

describe('the environment label', () => {
  it('is on the sign-in page and in the tab title, as a warning when CollectionSpace is real', async () => {
    stub({label: 'Local · PAHMA QA', realCollectionSpace: true}, null)
    const w = mount(App)
    await flushPromises()
    const badge = w.find('.env-badge')
    expect(badge.text()).toBe('Local · PAHMA QA')
    expect(badge.classes()).toContain('b-warn')
    expect(badge.attributes('title')).toContain('real CollectionSpace')
    expect(document.title).toBe('BMU · Local · PAHMA QA')
  })

  it('isn\'t shown when no label is set', async () => {
    stub({label: '', realCollectionSpace: false}, null)
    const w = mount(App)
    await flushPromises()
    expect(w.find('.env-badge').exists()).toBe(false)
  })
})
