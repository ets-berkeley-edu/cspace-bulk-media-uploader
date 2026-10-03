/**
 * Runs before every test file. The tests stand in for the BMU API by stubbing fetch(url, init), so here axios is
 * given an adapter that sends each request through fetch in that shape. Everything else is the app's own axios
 * setup (initializeAxios): the X-BMU header, ApiError and the signed-out event are tested as the app uses them.
 */
import axios, {AxiosError} from 'axios'
import type {AxiosResponse, InternalAxiosRequestConfig} from 'axios'
import {initializeAxios} from '@/lib/axios-utils'

axios.defaults.adapter = async (config: InternalAxiosRequestConfig): Promise<AxiosResponse> => {
  const res = await fetch(config.url as string, {
    method: (config.method || 'get').toUpperCase(),
    credentials: 'same-origin',
    headers: config.headers.toJSON() as Record<string, string>,
    body: config.data
  })
  const response: AxiosResponse = {
    data: await res.text(),
    status: res.status,
    statusText: res.statusText,
    headers: Object.fromEntries(res.headers.entries()),
    config
  }
  if (res.status >= 200 && res.status < 300) {
    return response
  }
  throw new AxiosError(`Request failed with status code ${res.status}`, AxiosError.ERR_BAD_REQUEST, config, null, response)
}

initializeAxios(axios)

// What Vuetify's layout components and the colour scheme choice need from a browser, which jsdom doesn't have.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = globalThis.ResizeObserver || ResizeObserverStub
window.matchMedia = window.matchMedia || ((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addEventListener: () => {},
  removeEventListener: () => {},
  addListener: () => {},
  removeListener: () => {},
  dispatchEvent: () => false
}) as MediaQueryList)
// Vuetify places a menu using the visual viewport.
globalThis.visualViewport = globalThis.visualViewport || Object.assign(new EventTarget(), {
  height: 768, offsetLeft: 0, offsetTop: 0, pageLeft: 0, pageTop: 0, scale: 1, width: 1024, onresize: null, onscroll: null, onscrollend: null
}) as VisualViewport
