<template>
  <section
    id="demo-pane"
    aria-label="Demo tools"
    class="demo-pane mb-4 px-3 py-2 rounded-lg text-body-2"
    :class="{collapsed: !isOpen}"
  >
    <div class="align-center d-flex demo-head">
      <v-btn
        id="demo-toggle-btn"
        aria-controls="demo-body"
        :aria-expanded="isOpen"
        :aria-label="toggleLabel"
        class="chevron"
        :class="{open: isOpen}"
        density="comfortable"
        :icon="mdiChevronRight"
        size="small"
        :title="toggleLabel"
        variant="text"
        @click="toggle"
      />
      <strong>Demo tools</strong>
      <v-chip
        color="info"
        size="small"
        title="Only in demo builds (npm run dev, npm run build:demo) with BMU_DEMO=true on the server; never in production"
      >
        Demo build only
      </v-chip>
      <span v-if="!isOpen" id="demo-summary" class="demo-summary text-caption text-medium-emphasis text-truncate">{{ collapsedSummary }}</span>
    </div>

    <div v-show="isOpen" id="demo-body" class="mt-2">
      <v-alert
        v-if="isOff"
        id="demo-off"
        density="compact"
        type="info"
        variant="tonal"
      >
        Demo tools are off in this environment: they need the simulated CollectionSpace and
        <code>BMU_DEMO=true</code>, as in <code>./bmu up sim</code>. The check-script commands below work everywhere.
      </v-alert>
      <div v-else-if="status">
        <p id="demo-intro" class="mb-2 text-caption text-medium-emphasis">{{ intro }}</p>
        <v-alert
          v-if="status.simError"
          id="demo-sim-error"
          class="mb-2"
          density="compact"
          type="warning"
          variant="tonal"
        >
          {{ status.simError }}
        </v-alert>
        <v-alert
          v-if="message"
          id="demo-message"
          class="mb-2"
          density="compact"
          role="status"
          type="info"
          variant="tonal"
        >
          {{ message }}
        </v-alert>
        <v-alert
          v-if="error"
          id="demo-error"
          class="mb-2"
          density="compact"
          role="alert"
          type="warning"
          variant="tonal"
        >
          {{ error }}
        </v-alert>

        <div class="demo-grid my-2">
          <v-card id="demo-speeds" class="demo-box pa-3" variant="outlined">
            <h3 class="text-body-2 font-weight-bold">Slow down file transfers</h3>
            <label class="demo-row" for="demo-browser-speed-select">
              <span>Browser uploads (Create / edit job)</span>
              <select
                id="demo-browser-speed-select"
                class="native-select"
                :disabled="isBusy"
                :value="status.browserUploadMbps"
                @change="event => setBrowserSpeed(numberOf(event))"
              >
                <option v-for="speed in BROWSER_SPEEDS" :key="speed" :value="speed">{{ speedLabel(speed) }}</option>
              </select>
            </label>
            <label v-if="sim" class="demo-row" for="demo-run-speed-select">
              <span>File uploads to CollectionSpace (job runs)</span>
              <select
                id="demo-run-speed-select"
                class="native-select"
                :disabled="isBusy"
                :value="sim.upload_mbps"
                @change="event => setRunSpeed(numberOf(event))"
              >
                <option v-for="speed in RUN_SPEEDS" :key="speed" :value="speed">{{ speedLabel(speed) }}</option>
              </select>
            </label>
            <label v-if="sim" class="demo-row" for="demo-delay-select">
              <span>Added delay per create or upload (job runs)</span>
              <select
                id="demo-delay-select"
                class="native-select"
                :disabled="isBusy"
                :value="sim.delay"
                @change="event => setDelay(numberOf(event))"
              >
                <option v-for="seconds in DELAYS" :key="seconds" :value="seconds">{{ seconds ? `${seconds} s` : 'None' }}</option>
              </select>
            </label>
            <p class="text-caption text-medium-emphasis">
              A browser upload speed applies to uploads that start after you set it. Use large sample files (50 MB or
              more): the first few MB of each file fill network buffers at once, so small files jump to 100%.
            </p>
          </v-card>

          <v-card
            v-if="sim"
            id="demo-failures"
            class="demo-box pa-3"
            variant="outlined"
          >
            <h3 class="text-body-2 font-weight-bold">Make CollectionSpace fail</h3>
            <p class="text-caption text-medium-emphasis">
              Choose what should fail, then click Add failure. It applies to requests made after that.
            </p>
            <div class="demo-inline">
              <span class="demo-pair">
                <label for="demo-fail-step-select">Step</label>
                <select id="demo-fail-step-select" v-model="fail.step" class="native-select">
                  <option v-for="step in sim.steps" :key="step" :value="step">{{ step }}</option>
                </select>
              </span>
              <span class="demo-pair">
                <label for="demo-fail-status-select">With</label>
                <select id="demo-fail-status-select" v-model.number="fail.status" class="native-select">
                  <option v-for="[code, label] in STATUSES" :key="code" :value="code">{{ label }}</option>
                </select>
              </span>
              <span class="demo-pair">
                <label for="demo-fail-count-input">Times</label>
                <input
                  id="demo-fail-count-input"
                  v-model.number="fail.count"
                  class="demo-num native-input"
                  max="99"
                  min="0"
                  title="0: until cleared"
                  type="number"
                >
              </span>
            </div>
            <div class="demo-inline">
              <span class="demo-pair">
                <label for="demo-fail-match-input">Only if it mentions</label>
                <input
                  id="demo-fail-match-input"
                  v-model="fail.match"
                  class="demo-text native-input"
                  placeholder="any document"
                  title="Part of an identification number, filename, object number, group title or term"
                  type="text"
                >
              </span>
              <select
                id="demo-fail-client-select"
                v-model="fail.client"
                aria-label="Where it fails"
                class="native-select"
                title="Job runs only (the editor's checks unaffected), or every request"
              >
                <option value="worker">in job runs</option>
                <option value="any">everywhere</option>
              </select>
              <v-btn
                id="demo-add-failure-btn"
                :disabled="isBusy"
                size="small"
                variant="outlined"
                @click="addFailure"
              >
                Add failure
              </v-btn>
            </div>
            <div id="demo-failures-set" class="font-weight-medium text-caption">
              {{ sim.rules.length ? 'Failures set:' : 'No failures set.' }}
            </div>
            <ul v-if="sim.rules.length" id="demo-failure-list" class="demo-list text-caption">
              <li v-for="(rule, index) in sim.rules" :key="index">{{ ruleText(rule) }}</li>
            </ul>
            <div v-if="sim.rules.length">
              <button
                id="demo-clear-failures-btn"
                class="link-btn"
                :disabled="isBusy"
                type="button"
                @click="clearFailures"
              >
                Clear failures
              </button>
            </div>
          </v-card>

          <v-card
            v-if="sim"
            id="demo-terms"
            class="demo-box pa-3"
            variant="outlined"
          >
            <h3 class="text-body-2 font-weight-bold">Change terms in CollectionSpace</h3>
            <div class="demo-inline">
              <select
                id="demo-term-select"
                v-model="term.name"
                aria-label="Person or organization"
                class="native-select"
              >
                <optgroup label="Persons">
                  <option v-for="person in sim.people" :key="person" :value="person">{{ person }}</option>
                </optgroup>
                <optgroup label="Organizations">
                  <option v-for="org in sim.orgs" :key="org" :value="org">{{ org }}</option>
                </optgroup>
              </select>
              <select
                id="demo-term-change-select"
                v-model="term.how"
                aria-label="Change"
                class="native-select"
              >
                <option value="deleted">Delete (soft)</option>
                <option value="gone">Gone (404, as if merged)</option>
                <option value="rename">Rename to…</option>
              </select>
              <input
                v-if="term.how === 'rename'"
                id="demo-term-name-input"
                v-model="term.to"
                aria-label="New name"
                class="demo-text native-input"
                placeholder="New name"
                type="text"
              >
              <v-btn
                id="demo-term-apply-btn"
                :disabled="isBusy || (term.how === 'rename' && !term.to.trim())"
                size="small"
                variant="outlined"
                @click="changeTerm"
              >
                Apply
              </v-btn>
            </div>
            <div class="demo-inline">
              <select
                id="demo-language-select"
                v-model="language.code"
                aria-label="Language"
                class="native-select"
              >
                <option v-for="(name, code) in sim.languages" :key="code" :value="code">{{ name }} ({{ code }})</option>
              </select>
              <select
                id="demo-language-change-select"
                v-model="language.how"
                aria-label="Change"
                class="native-select"
              >
                <option value="delete">Remove</option>
                <option value="rename">Rename to…</option>
              </select>
              <input
                v-if="language.how === 'rename'"
                id="demo-language-name-input"
                v-model="language.to"
                aria-label="New name"
                class="demo-text native-input"
                placeholder="New name"
                type="text"
              >
              <v-btn
                id="demo-language-apply-btn"
                :disabled="isBusy || (language.how === 'rename' && !language.to.trim())"
                size="small"
                variant="outlined"
                @click="changeLanguage"
              >
                Apply
              </v-btn>
            </div>
            <ul v-if="termChanges.length" id="demo-term-changes" class="demo-list text-caption">
              <li v-for="change in termChanges" :key="change">{{ change }}</li>
            </ul>
            <p class="text-caption text-medium-emphasis">
              Documents using a changed term show it in the editor's checks, and a run checks again before each document.
            </p>
          </v-card>

          <v-card id="demo-reset" class="demo-box pa-3" variant="outlined">
            <h3 class="text-body-2 font-weight-bold">Reset</h3>
            <div class="demo-inline">
              <v-btn
                v-if="sim"
                id="demo-reset-sim-btn"
                :disabled="isBusy"
                size="small"
                variant="outlined"
                @click="resetSim"
              >
                Reset simulated CollectionSpace
              </v-btn>
              <v-btn
                id="demo-full-speed-btn"
                :disabled="isBusy || !status.browserUploadMbps"
                size="small"
                variant="outlined"
                @click="() => setBrowserSpeed(0)"
              >
                Browser uploads at full speed
              </v-btn>
            </div>
            <div v-if="!confirming" class="demo-inline">
              <v-btn
                id="demo-delete-all-btn"
                :disabled="isBusy"
                size="small"
                variant="outlined"
                @click="confirming = 'jobs'"
              >
                Delete all jobs…
              </v-btn>
              <v-btn
                v-if="sim"
                id="demo-reset-everything-btn"
                :disabled="isBusy"
                size="small"
                variant="outlined"
                @click="confirming = 'everything'"
              >
                Reset everything…
              </v-btn>
            </div>
            <v-alert
              v-else
              :id="`demo-${confirming === 'jobs' ? 'delete-all' : 'reset-everything'}-confirm`"
              density="compact"
              role="alert"
              type="warning"
              variant="tonal"
            >
              {{ CONFIRM_TEXT[confirming] }}
              <div class="demo-inline mt-2">
                <v-btn
                  :id="`demo-${confirming === 'jobs' ? 'delete-all' : 'reset-everything'}-confirm-btn`"
                  color="error"
                  :disabled="isBusy"
                  size="small"
                  @click="confirmed"
                >
                  {{ confirming === 'jobs' ? 'Delete all jobs' : 'Reset everything' }}
                </v-btn>
                <v-btn
                  id="demo-confirm-cancel-btn"
                  size="small"
                  variant="outlined"
                  @click="confirming = null"
                >
                  Cancel
                </v-btn>
              </div>
            </v-alert>
            <p class="text-caption text-medium-emphasis">
              Resetting the simulator also forgets the records earlier runs created in it. Reset everything puts the
              prototype back to how it starts.
            </p>
          </v-card>
        </div>

        <details
          v-if="sim"
          id="demo-objects"
          class="demo-more"
          @toggle="loadObjects"
        >
          <summary>Sample objects in the simulated CollectionSpace</summary>
          <p v-if="!objects" class="text-caption text-medium-emphasis">Loading…</p>
          <v-table
            v-else
            id="demo-objects-table"
            class="border mt-2 rounded"
            density="compact"
          >
            <thead>
              <tr>
                <th scope="col">Object number</th>
                <th scope="col">What it's for</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="object in objects" :key="object.objectNumber">
                <td>{{ object.objectNumber }}</td>
                <td>{{ object.note }}{{ object.deleted ? ' (deleted)' : '' }}{{ object.sensitivity ? ' · protected' : '' }}</td>
              </tr>
            </tbody>
          </v-table>
        </details>
      </div>
      <p v-else id="demo-loading" class="text-caption text-medium-emphasis">Loading…</p>

      <details id="demo-commands" class="demo-more">
        <summary>Check scripts and other commands</summary>
        <div v-for="(command, index) in COMMANDS" :key="command.title" class="mt-3">
          <div class="align-center d-flex">
            <strong class="mr-3">{{ command.title }}</strong>
            <button
              :id="`demo-command-${index}-copy-btn`"
              class="link-btn"
              type="button"
              @click="() => copy(command.title, command.lines)"
            >
              {{ copied === command.title ? 'Copied' : 'Copy' }}
            </button>
          </div>
          <p class="mb-1 text-caption text-medium-emphasis">{{ command.note }}</p>
          <pre class="demo-pre pa-2 rounded text-caption">{{ command.lines }}</pre>
        </div>
      </details>
    </div>
  </section>
</template>

<script setup lang="ts">
import {computed, onBeforeUnmount, onMounted, reactive, ref} from 'vue'
import {mdiChevronRight} from '@mdi/js'
import type {DemoStatus, SimSettings} from '@/lib/demo'
import {COMMANDS, demoApi, demoSummary, failureText, speedLabel, speedText} from '@/lib/demo'
import {ApiError} from '@/api'

/**
 * Demo tools (demo builds only; see lib/demo.ts): slow the transfers down, make the simulated CollectionSpace fail
 * or change its terms, reset things, and how to run the check scripts. Collapsible; remembered in this browser.
 */
const emit = defineEmits<{jobsDeleted: [message: string]}>()

const OPEN_KEY = 'bmuDemoPaneOpen'
const BROWSER_SPEEDS = [0, 10, 5, 2, 1, 0.5]
const RUN_SPEEDS = [0, 20, 5, 2, 1]
const DELAYS = [0, 1, 2, 5, 10]
const STATUSES: [number, string][] = [[500, '500 server error'], [503, '503 unavailable'], [400, '400 rejected'], [401, '401 sign-in'],
                                      [403, '403 permission'], [409, '409 account inactive'], [413, '413 file too large'], [415, '415 file type']]

const readOpen = (): boolean => {
  try {
    return localStorage.getItem(OPEN_KEY) !== '0'
  } catch {
    return true
  }
}
const isOpen = ref(readOpen())
const toggle = () => {
  isOpen.value = !isOpen.value
  try {
    localStorage.setItem(OPEN_KEY, isOpen.value ? '1' : '0')
  } catch {
    // A private window: not remembered
  }
}

const status = ref<DemoStatus | null>(null)
// The server's demo mode is off (BMU_DEMO)
const isOff = ref(false)
const isBusy = ref(false)
const message = ref('')
const error = ref('')
// Which of the Reset box's two questions is open
const confirming = ref<'jobs' | 'everything' | null>(null)
const CONFIRM_TEXT = {
  jobs: 'Delete every job in this tenant (drafts, queued and finished), except running ones? Their files are removed from the BMU; '
    + 'records already created in CollectionSpace stay.',
  everything: 'Delete every job, draft, uploaded file and audit entry in the BMU, put the job schedule back to its default, and reset the '
    + 'simulated CollectionSpace and the upload speeds? This can\'t be undone. You stay signed in.'
}
const objects = ref<{objectNumber: string, note: string, deleted: boolean, sensitivity?: unknown}[] | null>(null)
const copied = ref('')

const fail = reactive({step: 'upload', status: 500, match: '', count: 1, client: 'worker'})
const term = reactive({name: '', how: 'deleted', to: ''})
const language = reactive({code: '', how: 'delete', to: ''})

const toggleLabel = computed(() => (isOpen.value ? 'Hide demo tools' : 'Show demo tools'))
const collapsedSummary = computed(() => (isOff.value ? 'Off in this environment; commands only' : demoSummary(status.value)))
const sim = computed(() => status.value?.sim ?? null)
const intro = computed(() => `For demos and testing with the simulated CollectionSpace (${status.value?.cspaceUrl}). None of this is part of the BMU; `
  + 'production builds leave it out.'
  + (status.value?.alwaysRunTime ? ' Every moment is a run time (BMU_ALWAYS_RUN_TIME), so submitted jobs start at once.' : ''))
const termChanges = computed(() => {
  const s = sim.value
  if (!s) {
    return []
  }
  const name = (key: string) => s.term_names?.[key] ?? key
  return [
    ...Object.entries(s.term_states).map(([key, state]) => `${name(key)}: ${state === 'gone' ? 'gone (404, as if merged or purged)' : 'deleted'}`),
    ...Object.entries(s.term_renames).map(([key, to]) => `${name(key)}: renamed “${to}”`),
    ...s.deleted_languages.map(code => `language ${code}: removed`),
    ...Object.entries(s.language_renames).map(([code, to]) => `language ${code}: renamed “${to}”`)
  ]
})

const numberOf = (event: Event) => +(event.target as HTMLSelectElement).value
const ruleText = (rule: SimSettings['rules'][number]) => `${rule.step} → ${rule.effect || rule.status}${rule.match ? ` if “${rule.match}”` : ''}, `
  + (rule.count ? `${rule.left} of ${rule.count} left` : 'until cleared') + (rule.client === 'any' ? ', everywhere' : '')

const refresh = async () => {
  try {
    status.value = await demoApi.status()
    isOff.value = false
    if (!term.name && status.value.sim) {
      term.name = status.value.sim.people[0] ?? ''
    }
    if (!language.code && status.value.sim) {
      language.code = Object.keys(status.value.sim.languages)[0] ?? ''
    }
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      isOff.value = true
    } else {
      error.value = (e as Error).message
    }
  }
}

const run = async (what: () => Promise<unknown>, done: string) => {
  isBusy.value = true
  error.value = ''
  message.value = ''
  try {
    await what()
    message.value = done
    await refresh()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    isBusy.value = false
  }
}

const setBrowserSpeed = (mbps: number) => run(
  () => demoApi.browserUpload(mbps),
  `Browser uploads: ${speedText(mbps)}, for uploads that start from now on.`
)
const setRunSpeed = (mbps: number) => run(
  () => demoApi.sim('slow', {seconds: sim.value?.delay ?? 0, upload_mbps: mbps}),
  `File uploads to CollectionSpace in job runs: ${speedText(mbps)}.`
)
const setDelay = (seconds: number) => run(
  () => demoApi.sim('slow', {seconds, upload_mbps: sim.value?.upload_mbps ?? 0}),
  seconds ? `Each create and upload in a run now takes ${seconds} s longer.` : 'No added delay in runs.'
)
const addFailure = () => run(() => demoApi.sim('fail', {...fail}), failureText(fail.step, fail.status, fail.count))
const clearFailures = () => run(() => demoApi.sim('clear-failures'), 'No failures set.')
const changeTerm = () => run(() => (term.how === 'rename'
  ? demoApi.sim('rename-term', {name: term.name, to: term.to})
  : demoApi.sim('delete-term', {name: term.name, how: term.how})), `“${term.name}” changed in CollectionSpace.`)
const changeLanguage = () => run(() => (language.how === 'rename'
  ? demoApi.sim('rename-language', {code: language.code, to: language.to})
  : demoApi.sim('delete-language', {code: language.code})), `Language ${language.code} changed in CollectionSpace.`)
const resetSim = () => run(
  () => demoApi.sim('reset'),
  'The simulated CollectionSpace is reset: its records, terms, failures and speeds are back to the start.'
)

const deleteAllJobs = () => run(async () => {
  const r = await demoApi.deleteAllJobs()
  const kept = r.skipped.length ? ` Kept ${r.skipped.length} running: ${r.skipped.join(', ')}.` : ''
  emit('jobsDeleted', `Demo tools deleted ${r.deleted} job${r.deleted === 1 ? '' : 's'}.${kept}`)
}, 'Jobs deleted.')

const resetEverything = () => run(async () => {
  await demoApi.resetEverything()
  emit('jobsDeleted', 'Demo tools reset everything: no jobs, drafts, files or audit entries, and the schedule is back to its default.')
}, 'Everything is reset: the prototype is as it starts.')

const confirmed = () => {
  const what = confirming.value
  confirming.value = null
  return what === 'jobs' ? deleteAllJobs() : resetEverything()
}

const loadObjects = async (event: Event) => {
  if ((event.target as HTMLDetailsElement).open && !objects.value) {
    try {
      objects.value = (await demoApi.objects()).objects
    } catch (e) {
      error.value = (e as Error).message
    }
  }
}

const copy = async (title: string, text: string) => {
  try {
    await navigator.clipboard.writeText(text)
    copied.value = title
    setTimeout(() => {
      if (copied.value === title) {
        copied.value = ''
      }
    }, 1500)
  } catch {
    // The clipboard isn't allowed: the text can still be selected
  }
}

let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  refresh()
  // Failures get used up during runs
  timer = setInterval(() => {
    if (isOpen.value && !isBusy.value) {
      refresh()
    }
  }, 10000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<style scoped>
.demo-pane {
  background-color: rgb(var(--v-theme-surface));
  border: 1px dashed rgba(var(--v-theme-on-surface), 0.38);
}
.demo-head {
  gap: 8px;
  margin-left: -6px;
  min-width: 0;
}
.demo-summary {
  min-width: 0;
}
.demo-grid {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
}
.demo-box {
  border-color: rgba(var(--v-theme-on-surface), 0.2);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
/* A long button label wraps inside a narrow box. */
.demo-box :deep(.v-btn) {
  height: auto;
  min-height: 28px;
  padding-bottom: 4px;
  padding-top: 4px;
}
.demo-box :deep(.v-btn__content) {
  white-space: normal;
}
.demo-row {
  align-items: center;
  display: flex;
  gap: 8px;
  justify-content: space-between;
}
.demo-inline {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
/* A label stays with its control when the line wraps. */
.demo-pair {
  align-items: center;
  display: inline-flex;
  gap: 4px;
  white-space: nowrap;
}
.demo-num {
  width: 64px;
}
.demo-text {
  width: 160px;
}
.demo-list {
  padding-left: 18px;
}
.demo-more {
  margin-top: 8px;
}
.demo-more summary {
  cursor: pointer;
  font-weight: 600;
}
.demo-pre {
  background-color: rgba(var(--v-theme-on-surface), 0.06);
  overflow-x: auto;
  white-space: pre;
}
</style>
