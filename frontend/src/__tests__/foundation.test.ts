/** The Vuetify foundation: axios set up for the BMU API, the screen reader and focus helpers, and the theme. */
import axios from 'axios'
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest'
import {createPinia, setActivePinia} from 'pinia'
import {mount} from '@vue/test-utils'
import {nextTick} from 'vue'
import {ApiError, api, request} from '@/api'
import {getMyProfile, logIn} from '@/api/auth'
import {alertScreenReader, putFocusNextTick} from '@/lib/utils'
import vuetify from '@/plugins/vuetify'
import {useContextStore} from '@/stores/context'

type Call = {url: string, init: RequestInit}
let calls: Call[] = []
const headersOf = (call: Call) => call.init.headers as Record<string, string>

function mockApi(status = 200, body: unknown = {}) {
  calls = []
  vi.stubGlobal('fetch', vi.fn((url: string, init: RequestInit) => {
    calls.push({url, init})
    return Promise.resolve(new Response(JSON.stringify(body), {status, headers: {'content-type': 'application/json'}}))
  }))
}

/** The error a request failed with */
const failure = (p: Promise<unknown>): Promise<ApiError> => p.then(() => {
  throw new Error('The request was expected to fail')
}, (e: ApiError) => e)

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('axios for the BMU API', () => {
  it('sends X-BMU on every request without the caller asking, for every method', async () => {
    mockApi()
    await api.jobs()
    await api.createJob('a job')
    await api.deleteJob('j1')
    await api.putThumbnail('j1', 1, new Blob(['x'], {type: 'image/jpeg'}))
    await axios.get('/api/anything')
    expect(calls.map(c => c.init.method)).toEqual(['GET', 'POST', 'DELETE', 'POST', 'GET'])
    calls.forEach(c => expect(headersOf(c)['X-BMU']).toBe('1'))
  })

  it('sends JSON bodies as JSON, and the thumbnail as the JPEG it is', async () => {
    mockApi()
    await api.createJob('a job')
    await api.putThumbnail('j1', 1, new Blob(['x'], {type: 'image/jpeg'}))
    expect(headersOf(calls[0])['Content-Type']).toContain('application/json')
    expect(calls[0].init.body).toBe('{"name":"a job"}')
    expect(headersOf(calls[1])['Content-Type']).toBe('image/jpeg')
    expect(calls[1].init.body).toBeInstanceOf(Blob)
  })

  it('marks a background refresh, and only that, with X-BMU-Poll', async () => {
    mockApi(200, {jobs: []})
    await api.jobs(true)
    await api.jobs()
    expect(headersOf(calls[0])['X-BMU-Poll']).toBe('1')
    expect(headersOf(calls[1])['X-BMU-Poll']).toBeUndefined()
  })

  it('returns the response body', async () => {
    mockApi(200, {jobs: [{id: 'j1'}]})
    expect(await api.jobs()).toEqual({jobs: [{id: 'j1'}]})
  })

  it('rejects with an ApiError holding the status, the API\'s message and its detail', async () => {
    mockApi(422, {detail: {message: 'This job has no documents.', code: 'empty'}})
    const error = await failure(request('POST', '/api/jobs/j1/schedule'))
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(422)
    expect(error.message).toBe('This job has no documents.')
    expect(error.detail).toEqual({message: 'This job has no documents.', code: 'empty'})

    mockApi(409, {detail: 'Someone else is editing this job.'})
    expect((await failure(request('GET', '/api/x'))).message).toBe('Someone else is editing this job.')
    mockApi(422, {detail: [{loc: ['body', 'name'], msg: 'field required'}]})
    expect((await failure(request('GET', '/api/x'))).message).toBe('Some values aren\'t valid.')
    mockApi(500, {})
    expect((await failure(request('GET', '/api/x'))).message).toBe('Request failed (500)')
  })

  it('tells the app when the session has ended, but not when sign-in or the sign-in check answers 401', async () => {
    const heard: string[] = []
    const listener = (e: Event) => heard.push((e as CustomEvent<string>).detail)
    window.addEventListener('bmu-signed-out', listener)
    mockApi(401, {detail: 'You were signed out after 30 minutes without activity.'})
    await getMyProfile().catch(() => undefined)
    await logIn('u', 'p').catch(() => undefined)
    expect(heard).toEqual([])
    await api.jobs().catch(() => undefined)
    await request('GET', '/api/dates/parse?text=1920').catch(() => undefined)
    expect(heard).toEqual(Array(2).fill('You were signed out after 30 minutes without activity.'))
    window.removeEventListener('bmu-signed-out', listener)
  })

  it('passes on an error with no response (the network) as it is', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))))
    const error = await failure(api.jobs())
    expect(error).not.toBeInstanceOf(ApiError)
    expect(error.message).toBe('Failed to fetch')
  })
})

describe('screen reader and focus helpers (from BOA)', () => {
  it('alertScreenReader puts the message in the store, politely by default, and clears it after five seconds', async () => {
    vi.useFakeTimers()
    const store = useContextStore()
    alertScreenReader('Job submitted.')
    await nextTick()
    expect(store.screenReaderAlert).toEqual({message: 'Job submitted.', politeness: 'polite'})
    vi.advanceTimersByTime(5000)
    expect(store.screenReaderAlert.message).toBe('')
  })

  it('a persistent or assertive alert stays, and says so', async () => {
    vi.useFakeTimers()
    const store = useContextStore()
    alertScreenReader('Loading.', true, 'assertive')
    await nextTick()
    vi.advanceTimersByTime(60000)
    expect(store.screenReaderAlert).toEqual({message: 'Loading.', politeness: 'assertive'})
  })

  it('putFocusNextTick focuses the element once it exists, or a selector inside it', async () => {
    vi.useFakeTimers()
    Element.prototype.scrollIntoView = vi.fn()
    putFocusNextTick('late-button')
    await nextTick()
    vi.advanceTimersByTime(500)
    document.body.innerHTML = '<button id="late-button">Go</button><div id="box"><input class="first"></div>'
    vi.advanceTimersByTime(500)
    expect(document.activeElement?.id).toBe('late-button')
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1)

    putFocusNextTick('box', {cssSelector: 'input.first', scroll: false})
    await nextTick()
    vi.advanceTimersByTime(500)
    expect(document.activeElement?.className).toContain('first')
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledTimes(1)
    document.body.innerHTML = ''
  })

  it('putFocusNextTick gives up quietly when the element never appears', async () => {
    vi.useFakeTimers()
    putFocusNextTick('never')
    await nextTick()
    vi.advanceTimersByTime(10000)
    expect(vi.getTimerCount()).toBe(0)
  })
})

describe('Vuetify', () => {
  it('renders a Vuetify component with the BOA defaults', () => {
    const w = mount({template: '<v-btn id="go" color="primary">Go</v-btn>'}, {global: {plugins: [vuetify]}})
    const button = w.find('button#go')
    expect(button.classes()).toContain('v-btn')
    expect(button.classes()).toContain('bg-primary')
    expect(button.attributes('style')).toContain('text-transform: none')
  })

  it('has BOA\'s primary colour in its light theme, and a dark theme', () => {
    expect(vuetify.theme.themes.value.light.colors.primary.toLowerCase()).toBe('#37769a')
    expect(vuetify.theme.themes.value.dark.dark).toBe(true)
  })
})
