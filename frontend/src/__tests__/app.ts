/** Mounts the whole app for a test, as main.ts starts it: the environment and the user first, then the pages. */
import {createPinia, setActivePinia} from 'pinia'
import {flushPromises, mount} from '@vue/test-utils'
import type {Component} from 'vue'
import App from '@/App.vue'
import vuetify from '@/plugins/vuetify'
import router from '@/router'
import {useContextStore} from '@/stores/context'

let mounted: ReturnType<typeof mount> | undefined

/** Lets everything a click or a navigation started finish: requests, then the pages they lead to. */
export async function settle() {
  for (let i = 0; i < 5; i++) {
    await flushPromises()
    await new Promise(resolve => setTimeout(resolve, 2))
  }
}

export async function mountApp(path = '/', stubs: Record<string, Component | boolean> = {}) {
  // The pages are loaded when first visited. Load them all now and give them to the router, as it does itself on a
  // first visit, so that a test's navigation finishes within settle().
  for (const record of router.getRoutes()) {
    const page = record.components?.default
    if (typeof page === 'function' && !('__vccOpts' in page)) {
      const loaded = await (page as () => Promise<{default: Component}>)()
      record.components!.default = loaded.default
    }
  }
  // One app at a time: the router is shared, so an app left over from a failed test would follow this one's pages.
  mounted?.unmount()
  const pinia = createPinia()
  setActivePinia(pinia)
  await useContextStore().init()
  // The router is shared by the tests in a file: leave the last test's page first, so this one's guards run.
  await router.replace('/login?reset')
  await router.replace(path)
  const wrapper = mount(App, {attachTo: document.body, global: {plugins: [pinia, vuetify, router], stubs}})
  mounted = wrapper
  await settle()
  return wrapper
}

/** A tab of the signed-in page, by its text. */
export const tabOf = (wrapper: Awaited<ReturnType<typeof mountApp>>, text: string) => wrapper.findAll('.v-tab').find(t => t.text() === text)!
