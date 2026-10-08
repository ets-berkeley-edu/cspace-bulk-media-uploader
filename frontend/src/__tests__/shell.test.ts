/** The app's frame: sign-in, the app bar and its menu, the tabs as routes, and light and dark mode. */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest'
import {defineComponent, nextTick} from 'vue'
import {mountApp, settle, tabOf} from './app'
import router from '@/router'
import vuetify from '@/plugins/vuetify'
import {redirectAfterLogin} from '@/auth'
import {useContextStore} from '@/stores/context'
import {useJobEditSessionStore} from '@/stores/job-edit-session'
import type {Job, Me, Perms, Row, TenantInfo} from '@/types'

const tenant = {key: 'pahma', name: 'PAHMA', filenameHint: 'hint', filenamePattern: '^(?P<obj>[A-Za-z0-9.-]+)$', mediaTypes: [], languageDefault: '',
  authorityFields: {}, publish: {field: 'approvedForWeb', header: 'Restricted', invert: true},
  handling: [{id: 'link', label: 'Link to existing object', object: 'existing', id_rule: 'object'},
    {id: 'none', label: 'Media only', object: 'none', id_rule: 'image'}]} as unknown as TenantInfo
const perms: Perms = {media: true, mediaUpdate: true, relations: true, objects: true, readObjects: true, authorities: true, groups: true}
const me: Me = {user: 'admin', tenant, perms, role: 'staff'}
const row: Row = {n: 1, file: '15-1234_a.jpg', size: 10, contentType: 'image/jpeg', handling: 'link', obj: '15-1234', objParsed: '15-1234',
  img: '15-1234_a', parseOk: true, idnum: '15-1234', date: '', restricted: false, type: [], creator: '', contributor: '',
  rightsHolder: '', description: '', copyright: '', include: true, upload: {s: 'done'}, checks: [], result: null}
const job = (p: Partial<Job> = {}) => ({id: 'j1', name: 'Spring batch', status: 'Draft', createdBy: 'jlee', rowCount: 1, run: 0, ...p}) as Job
const plan = {kind: 'schedule', at: Date.now() / 1000 + 3 * 86400, ahead: 2, signInExpiresFirst: false} as const
const schedule = {days: [1, 2, 3, 4, 5, 6, 7], start: '19:00', end: '', timezone: 'America/Los_Angeles', paused: null,
  nextRunAt: plan.at, windowOpen: false, alwaysRunTime: false}

type Reply = unknown | {status: number, body: unknown}
let calls: {url: string, method: string, body?: string}[] = []
let signedIn: Me | null = null
let env: {label: string, realCollectionSpace: boolean, tenants?: {key: string, name: string}[]} =
  {label: 'Local · simulated CollectionSpace', realCollectionSpace: false}

/** A stand-in BMU API. routes answers first; then sign-in, the environment and empty lists. */
function stubApi(routes: (url: string, method: string) => Reply | undefined = () => undefined) {
  calls = []
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    calls.push({url, method, body: init?.body as string | undefined})
    let reply = routes(url, method)
    if (reply === undefined) {
      if (url === '/api/env') reply = env
      else if (url === '/api/me') reply = signedIn || {status: 401, body: {detail: 'Please sign in'}}
      else if (url === '/api/logout') { signedIn = null; reply = {} }
      else if (url === '/api/schedule') reply = schedule
      else if (url.endsWith('/api/jobs')) reply = {jobs: []}
      else if (url.includes('/vocabularies/')) reply = {terms: []}
      else if (url.endsWith('/api/failures')) reply = {failures: {}}
      else reply = {}
    }
    const r = reply && typeof reply === 'object' && 'status' in reply && 'body' in reply ? reply as {status: number, body: unknown} : {status: 200, body: reply}
    return Promise.resolve(new Response(JSON.stringify(r.body), {status: r.status, headers: {'content-type': 'application/json'}}))
  }))
}
const inBody = (selector: string) => document.body.querySelector<HTMLElement>(selector)
const EditorStub = {props: ['jobId'], template: '<div class="editor-stub">editing {{ jobId }}</div>'}

beforeEach(() => {
  signedIn = me
  env = {label: 'Local · simulated CollectionSpace', realCollectionSpace: false}
  window.localStorage.clear()
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('signing in', () => {
  it('nobody signed in: any page leads to the sign-in page, and signing in returns to the page asked for', async () => {
    signedIn = null
    stubApi((url, method) => {
      if (url === '/api/login' && method === 'POST') { signedIn = me; return me }
    })
    const w = await mountApp('/queue')
    expect(router.currentRoute.value.path).toBe('/login')
    expect(router.currentRoute.value.query.redirect).toBe('/queue')
    expect(w.find('#page-title').text()).toBe('Bulk Media Uploader')
    expect(w.text()).toContain('Your password is used only for your uploads and is deleted when they finish.')
    await w.find('#username').setValue(' admin ')
    await w.find('#password').setValue('secret')
    await w.find('form').trigger('submit')
    await settle()
    expect(calls.find(c => c.url === '/api/login')!.body).toBe('{"username":"admin","password":"secret"}')
    expect(router.currentRoute.value.path).toBe('/queue')
    expect(w.find('#btn-main-menu').text()).toBe('admin')
    expect(tabOf(w, 'Job queue').classes()).toContain('v-tab--selected')
    w.unmount()
  })

  it('a refused sign-in shows the reason, clears the password, and stays on the page', async () => {
    signedIn = null
    stubApi(url => (url === '/api/login' ? {status: 401, body: {detail: 'The username or password is not right.'}} : undefined))
    const w = await mountApp('/')
    await w.find('#username').setValue('admin')
    await w.find('#password').setValue('wrong')
    await w.find('form').trigger('submit')
    await settle()
    expect(w.find('#sign-in-error').text()).toBe('The username or password is not right.')
    expect(w.find('#sign-in-error').attributes('role')).toBe('alert')
    expect((w.find('#password').element as HTMLInputElement).value).toBe('')
    expect(router.currentRoute.value.path).toBe('/login')
    w.unmount()
  })

  it('asks for both fields without calling the API', async () => {
    signedIn = null
    stubApi()
    const w = await mountApp('/')
    await w.find('form').trigger('submit')
    await settle()
    expect(w.find('#sign-in-error').text()).toBe('Enter your CollectionSpace username and password.')
    expect(calls.some(c => c.url === '/api/login')).toBe(false)
    w.unmount()
  })

  it('only returns to one of the app\'s own pages after signing in', () => {
    expect(redirectAfterLogin('/drafts')).toBe('/drafts')
    expect(redirectAfterLogin('https://example.org/')).toBe('/')
    expect(redirectAfterLogin('//example.org/')).toBe('/')
    expect(redirectAfterLogin(undefined)).toBe('/')
  })

  it('already signed in: the sign-in page goes to the app, and / is Create / edit job', async () => {
    stubApi()
    const w = await mountApp('/login', {JobEditor: EditorStub})
    expect(router.currentRoute.value.path).toBe('/job')
    expect(w.find('.editor-stub').exists()).toBe(true)
    w.unmount()
  })
})

describe('choosing the museum (design: One deployment for several museums)', () => {
  const museums = [{key: 'pahma', name: 'PAHMA'}, {key: 'bampfa', name: 'BAMPFA'}]
  const bampfaMe = {...me, tenant: {...tenant, key: 'bampfa', name: 'BAMPFA'}} as Me

  it('with one museum there is nothing to choose, and the sign-in sends none', async () => {
    signedIn = null
    env = {...env, tenants: [museums[0]]}
    stubApi((url, method) => {
      if (url === '/api/login' && method === 'POST') { signedIn = me; return me }
    })
    const w = await mountApp('/')
    expect(w.find('#museum').exists()).toBe(false)
    await w.find('#username').setValue('admin')
    await w.find('#password').setValue('secret')
    await w.find('form').trigger('submit')
    await settle()
    expect(calls.find(c => c.url === '/api/login')!.body).toBe('{"username":"admin","password":"secret"}')
    w.unmount()
  })

  it('with several, the list asks for one first, signs in there, and shows it in the header', async () => {
    signedIn = null
    env = {...env, tenants: museums}
    stubApi((url, method) => {
      if (url === '/api/login' && method === 'POST') { signedIn = bampfaMe; return bampfaMe }
    })
    const w = await mountApp('/')
    const select = w.find('#museum')
    expect(select.findAll('option').map(o => o.text())).toEqual(['Choose your museum', 'PAHMA', 'BAMPFA'])
    expect((select.element as HTMLSelectElement).value).toBe('')
    await w.find('#username').setValue('admin')
    await w.find('#password').setValue('secret')
    await w.find('form').trigger('submit')
    await settle()
    expect(w.find('#sign-in-error').text()).toBe('Choose your museum.')
    expect(calls.some(c => c.url === '/api/login')).toBe(false)
    await select.setValue('bampfa')
    await w.find('#password').setValue('secret')
    await w.find('form').trigger('submit')
    await settle()
    expect(JSON.parse(calls.find(c => c.url === '/api/login')!.body!)).toEqual({username: 'admin', password: 'secret', tenant: 'bampfa'})
    expect(w.find('#tenant-name').text()).toBe('BAMPFA')
    expect(window.localStorage.getItem('bmu-museum')).toBe('bampfa')
    w.unmount()
  })

  it('the last museum chosen in this browser is chosen again, if the BMU still serves it', async () => {
    signedIn = null
    env = {...env, tenants: museums}
    window.localStorage.setItem('bmu-museum', 'bampfa')
    stubApi()
    let w = await mountApp('/')
    expect((w.find('#museum').element as HTMLSelectElement).value).toBe('bampfa')
    w.unmount()
    window.localStorage.setItem('bmu-museum', 'ucjeps')
    w = await mountApp('/')
    expect((w.find('#museum').element as HTMLSelectElement).value).toBe('')
    w.unmount()
  })
})

describe('the environment label', () => {
  it('is on the sign-in page and in the browser title, as a warning when CollectionSpace is real', async () => {
    signedIn = null
    env = {label: 'Local · PAHMA QA', realCollectionSpace: true}
    stubApi()
    const w = await mountApp('/')
    const chip = w.find('#environment-label')
    expect(chip.text()).toBe('Local · PAHMA QA')
    expect(chip.classes()).toContain('bg-warning')
    expect(chip.attributes('title')).toContain('real CollectionSpace')
    expect(document.title).toBe('Sign in | BMU · Local · PAHMA QA')
    w.unmount()
  })

  it('is in the app bar when signed in, without the warning for the simulator', async () => {
    stubApi()
    const w = await mountApp('/drafts')
    const chip = w.find('#app-bar #environment-label')
    expect(chip.text()).toBe('Local · simulated CollectionSpace')
    expect(chip.classes()).not.toContain('bg-warning')
    expect(chip.attributes('title')).toContain('nothing reaches a real server')
    expect(document.title).toBe('Drafts | BMU · Local · simulated CollectionSpace')
    w.unmount()
  })

  it('isn\'t shown when no label is set', async () => {
    signedIn = null
    env = {label: '', realCollectionSpace: false}
    stubApi()
    const w = await mountApp('/')
    expect(w.find('#environment-label').exists()).toBe(false)
    expect(document.title).toBe('Sign in | BMU')
    w.unmount()
  })
})

describe('the signed-in page', () => {
  it('shows the tenant and the user, and each tab is a page with its own address and heading', async () => {
    stubApi()
    const w = await mountApp('/', {JobEditor: EditorStub})
    expect(w.find('#tenant-name').text()).toBe('PAHMA')
    expect(w.find('#btn-main-menu').attributes('aria-label')).toBe('Signed in as admin. Menu')
    expect(w.findAll('.v-tab').map(t => t.text())).toEqual(['Create / edit job', 'Drafts', 'Job queue', 'Finished jobs'])
    expect(w.find('#skip-to-content-link').attributes('href')).toBe('#content')
    for (const [text, path] of [['Drafts', '/drafts'], ['Job queue', '/queue'], ['Finished jobs', '/finished'], ['Create / edit job', '/job']]) {
      await router.push(tabOf(w, text).attributes('href')!)
      await settle()
      expect(router.currentRoute.value.path).toBe(path)
      expect(w.find('#page-title').text()).toBe(text)
      expect(tabOf(w, text).classes()).toContain('v-tab--selected')
    }
    w.unmount()
  })

  it('an address that isn\'t a page says so', async () => {
    stubApi()
    const w = await mountApp('/no/such/page')
    expect(router.currentRoute.value.path).toBe('/404')
    expect(w.find('#page-title').text()).toBe('Page not found')
    w.unmount()
  })

  it('Sign out ends the session and returns to the sign-in page', async () => {
    stubApi()
    const w = await mountApp('/drafts')
    await w.find('#btn-main-menu').trigger('click')
    await settle()
    inBody('#menu-item-sign-out')!.click()
    await settle()
    expect(calls.some(c => c.url === '/api/logout' && c.method === 'POST')).toBe(true)
    expect(router.currentRoute.value.path).toBe('/login')
    expect(useContextStore().currentUser).toBeNull()
    expect(w.find('#btn-sign-in').exists()).toBe(true)
    w.unmount()
  })

  it('a session that ended while working returns to the sign-in page with the reason', async () => {
    stubApi()
    const w = await mountApp('/drafts')
    signedIn = null
    window.dispatchEvent(new CustomEvent('bmu-signed-out', {detail: 'You were signed out after 30 minutes without activity.'}))
    await settle()
    expect(router.currentRoute.value.path).toBe('/login')
    expect(w.find('#sign-in-notice').text()).toBe('You were signed out after 30 minutes without activity.')
    expect(w.find('#sign-in-notice').attributes('role')).toBe('status')
    w.unmount()
  })

  it('an intern can start a job, and the header says they are an intern', async () => {
    signedIn = {...me, role: 'intern', perms: {media: false, relations: false, objects: false, readObjects: false, authorities: false, groups: false}}
    stubApi()
    const w = await mountApp('/')
    expect(w.find('#btn-new-job').attributes('disabled')).toBeUndefined()
    expect(w.find('#user-role').text()).toBe('Intern')
    expect(w.find('#user-role').attributes('title')).toContain('drafts that are open to interns')
    expect(w.find('.dropzone').exists()).toBe(true)
    w.unmount()
  })

  it('staff see no role chip', async () => {
    stubApi()
    const w = await mountApp('/')
    expect(w.find('#user-role').exists()).toBe(false)
    w.unmount()
  })
})

describe('the job being worked on, across the tabs', () => {
  const routes = (url: string) => {
    if (url.endsWith('/api/jobs')) return {jobs: [job({id: 'd1', name: 'My draft', editingBy: 'admin', editingByYou: true}), job({id: 'd2', name: 'Other draft'})]}
    if (url.endsWith('/check')) return {rows: [row], counts: {block: 0, warn: 0}}
    if (url.endsWith('/api/jobs/d1')) return {job: job({id: 'd1', name: 'My draft', editingBy: 'admin', editingByYou: true}), rows: [row], runs: [], created: {}}
    if (url.endsWith('/api/jobs/d2')) return {job: job({id: 'd2', name: 'Other draft'}), rows: [row], runs: [], created: {}}
  }

  it('previewing a draft doesn\'t close the draft open in Create / edit job, and Back returns to the list', async () => {
    stubApi(routes)
    const w = await mountApp('/drafts', {JobEditor: EditorStub})
    const rowOf = (name: string) => w.findAll('tbody').find(r => r.text().includes(name))!
    await rowOf('My draft').findAll('button').find(b => b.text() === 'Continue editing')!.trigger('click')
    await settle()
    expect(router.currentRoute.value.path).toBe('/job/d1')
    expect(w.find('.editor-stub').text()).toBe('editing d1')
    await router.push('/drafts')
    await settle()
    // the rows have no Preview button: expand the job and use "Open full preview"
    expect(rowOf('Other draft').findAll('button').some(b => b.text() === 'Preview')).toBe(false)
    await rowOf('Other draft').find('[id$="-toggle-btn"]').trigger('click')
    await settle()
    await rowOf('Other draft').findAll('button').find(b => b.text() === 'Open full preview')!.trigger('click')
    await settle()
    expect(w.text()).toContain('← Back to Drafts')
    expect(router.currentRoute.value.path).toBe('/drafts')
    expect(calls.some(c => c.url.endsWith('/close'))).toBe(false)
    expect(useJobEditSessionStore().jobId).toBe('d1')
    await w.findAll('button').find(b => b.text() === '← Back to Drafts')!.trigger('click')
    await settle()
    expect(w.text()).toContain('Other draft')
    expect(w.text()).not.toContain('← Back to Drafts')
    w.unmount()
  })

  it('Create / edit job stays alive behind the other tabs', async () => {
    stubApi()
    let created = 0
    const Editor = defineComponent({created() { created++ }, template: '<div class="editor-stub">editor</div>'})
    const w = await mountApp('/job', {JobEditor: Editor})
    await router.push('/queue')
    await settle()
    expect(w.find('.editor-stub').exists()).toBe(false)
    await router.push('/job')
    await settle()
    expect(w.find('.editor-stub').exists()).toBe(true)
    expect(created).toBe(1)
    w.unmount()
  })

  it('after submitting, the Job queue page says when the job runs, from the response\'s plan', async () => {
    stubApi()
    const Editor = defineComponent({emits: ['scheduled'],
      data: () => ({job: job({status: 'Queued', plan})}), template: '<button class="fake-submit" @click="$emit(\'scheduled\', job)">Submit job</button>'})
    const w = await mountApp('/job', {JobEditor: Editor})
    await w.find('.fake-submit').trigger('click')
    await settle()
    const notice = w.find('#notice')
    expect(notice.attributes('role')).toBe('status')
    expect(notice.text()).toMatch(/^“Spring batch” was submitted and added to the end of the queue\. It runs at the next run time, .+ at \d+:\d\d [AP]M, after 2 other jobs\./)
    expect(notice.text()).toContain('It runs with your sign-in, which is deleted when the run ends.')
    expect(router.currentRoute.value.path).toBe('/queue')
    expect(tabOf(w, 'Job queue').classes()).toContain('v-tab--selected')
    w.unmount()
  })

  it('says the queue is paused, or that it starts now in development mode', async () => {
    const run = async (p: object, alwaysRunTime: boolean) => {
      stubApi(url => (url === '/api/schedule' ? {...schedule, nextRunAt: null, windowOpen: true, alwaysRunTime} : undefined))
      const Editor = defineComponent({emits: ['scheduled'],
        data: () => ({job: job({status: 'Queued', plan: {...plan, ...p}})}), template: '<button class="fake-submit" @click="$emit(\'scheduled\', job)">Submit job</button>'})
      const w = await mountApp('/job', {JobEditor: Editor})
      await w.find('.fake-submit').trigger('click')
      await settle()
      const text = w.find('#notice').text()
      w.unmount()
      return text
    }
    expect(await run({kind: 'paused'}, false)).toContain('The queue is paused, so it waits until a staff member resumes it.')
    expect(await run({at: Date.now() / 1000, ahead: 0}, true)).toContain('Development setting: every moment counts as run time, so it starts now.')
  })

  it('the open draft is in the address, so a reload or a bookmark reopens it (with the real editor)', async () => {
    stubApi(routes)
    const w = await mountApp('/job/d1', {DocumentThumbnail: true})
    expect(router.currentRoute.value.path).toBe('/job/d1')
    expect(useJobEditSessionStore().jobId).toBe('d1')
    expect((w.find('#job-name').element as HTMLInputElement).value).toBe('My draft')
    expect(w.text()).toContain('15-1234_a.jpg')
    expect(calls.some(c => c.url === '/api/jobs/d1' && c.method === 'GET')).toBe(true)
    w.unmount()
  })

  it('the tab leads back to the open draft, and an address without it doesn\'t close it', async () => {
    stubApi(routes)
    const w = await mountApp('/job/d1', {JobEditor: EditorStub})
    expect(w.find('.editor-stub').text()).toBe('editing d1')
    await router.push('/drafts')
    await settle()
    expect(tabOf(w, 'Create / edit job').attributes('href')).toBe('/job/d1')
    await router.push('/job')
    await settle()
    expect(router.currentRoute.value.path).toBe('/job/d1')
    expect(w.find('.editor-stub').text()).toBe('editing d1')
    expect(calls.some(c => c.url.endsWith('/close'))).toBe(false)
    w.unmount()
  })

  it('an address that names another draft opens it and leaves the one that was open', async () => {
    stubApi(routes)
    const w = await mountApp('/job/d1', {JobEditor: EditorStub})
    await router.push('/job/d2')
    await settle()
    expect(w.find('.editor-stub').text()).toBe('editing d2')
    expect(calls.some(c => c.url === '/api/jobs/d1/close' && c.method === 'POST')).toBe(true)
    w.unmount()
  })

  it('a job created in the editor gets its address, without a new entry in the browser\'s history', async () => {
    stubApi()
    const Editor = defineComponent({emits: ['opened'], template: '<button class="fake-create" @click="$emit(\'opened\', \'n7\')">create</button>'})
    const w = await mountApp('/job', {JobEditor: Editor})
    const replace = vi.spyOn(router, 'replace')
    await w.find('.fake-create').trigger('click')
    await settle()
    expect(router.currentRoute.value.path).toBe('/job/n7')
    expect(replace).toHaveBeenCalledWith('/job/n7')
    expect(useJobEditSessionStore().jobId).toBe('n7')
    w.unmount()
  })

  it('an address whose job isn\'t there says so and starts a new job', async () => {
    stubApi(url => (url.endsWith('/api/jobs/gone') ? {status: 404, body: {detail: 'No such job'}} : undefined))
    const w = await mountApp('/job/gone', {DocumentThumbnail: true})
    expect(router.currentRoute.value.path).toBe('/job')
    expect(useJobEditSessionStore().jobId).toBeNull()
    expect(w.find('#notice').text()).toContain('The job at that address isn\'t there')
    expect((w.find('#job-name').element as HTMLInputElement).value).toBe('')
    w.unmount()
  })

  it('New job leaves the open draft, so others can edit it', async () => {
    stubApi()
    const w = await mountApp('/drafts', {JobEditor: EditorStub})
    useJobEditSessionStore().jobId = 'd1'
    await w.find('#btn-new-job').trigger('click')
    await settle()
    expect(calls.some(c => c.url === '/api/jobs/d1/close' && c.method === 'POST')).toBe(true)
    expect(router.currentRoute.value.path).toBe('/job')
    expect(w.find('.editor-stub').text()).toBe('editing')
    w.unmount()
  })
})

describe('light and dark mode (as Damien does it)', () => {
  const systemPrefersDark = (dark: boolean) => vi.spyOn(window, 'matchMedia').mockImplementation((query: string) => ({matches: dark, media: query} as MediaQueryList))
  const isDark = () => vuetify.theme.global.current.value.dark

  it('starts from the system setting', async () => {
    stubApi()
    systemPrefersDark(true)
    let w = await mountApp('/drafts')
    expect(isDark()).toBe(true)
    expect(w.find('.v-application').classes()).toContain('v-theme--dark')
    w.unmount()
    systemPrefersDark(false)
    w = await mountApp('/drafts')
    expect(isDark()).toBe(false)
    w.unmount()
  })

  it('the menu\'s item switches it and the choice is remembered in this browser, over the system setting', async () => {
    stubApi()
    systemPrefersDark(false)
    let w = await mountApp('/drafts')
    await w.find('#btn-main-menu').trigger('click')
    await settle()
    expect(inBody('#menu-item-dark-mode')!.textContent).toContain('Dark mode')
    inBody('#menu-item-dark-mode')!.click()
    await nextTick()
    expect(isDark()).toBe(true)
    expect(window.localStorage.getItem('prefersDarkMode')).toBe('true')
    w.unmount()
    w = await mountApp('/drafts')
    expect(isDark()).toBe(true)
    w.unmount()
    window.localStorage.setItem('prefersDarkMode', 'false')
    systemPrefersDark(true)
    w = await mountApp('/login')
    expect(isDark()).toBe(false)
    w.unmount()
  })
})
