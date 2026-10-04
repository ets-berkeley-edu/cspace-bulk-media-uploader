/**
 * Runs before every test file. The tests stand in for the BMU API by stubbing fetch(url, init), so here axios is
 * given an adapter that sends each request through fetch in that shape. Everything else is the app's own axios
 * setup (initializeAxios): the X-BMU header, ApiError and the signed-out event are tested as the app uses them.
 */
import axios, {AxiosError} from 'axios'
import type {AxiosResponse, InternalAxiosRequestConfig} from 'axios'
import {config} from '@vue/test-utils'
import {createPinia, setActivePinia} from 'pinia'
import {beforeEach} from 'vitest'
import {initializeAxios} from '@/lib/axios-utils'
import vuetify from '@/plugins/vuetify'

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

// Every component under test may use Vuetify's components.
config.global.plugins = [vuetify]
// A component mounted on its own still finds the stores (the screen reader's alerts are in one).
beforeEach(() => setActivePinia(createPinia()))
// v-lazy draws its content when it scrolls into view. A test has no view, and reads the page at once: draw it at once.
config.global.stubs = {VLazy: {template: '<div><slot /></div>'}}
