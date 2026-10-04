<template>
  <div id="job-preview">
    <button
      id="preview-back-btn"
      class="link-btn mb-2"
      type="button"
      @click="() => emit('back')"
    >
      {{ backLabel }}
    </button>
    <v-alert
      v-if="gone"
      id="preview-gone"
      density="compact"
      type="info"
      variant="tonal"
    >
      {{ gone }}
    </v-alert>
    <p v-else-if="!job" id="preview-loading" class="text-medium-emphasis">{{ error || 'Loading…' }}</p>
    <template v-else>
      <h2 id="preview-title" class="align-center d-flex flex-wrap mb-1 text-h6">
        <span class="mr-2">{{ job.name || 'Untitled job' }}</span>
        <v-chip id="preview-status" :color="isRunning ? 'success' : isDraft ? 'warning' : 'info'" size="small">{{ statusText }}</v-chip>
      </h2>
      <div id="preview-summary" class="mb-2 text-body-2 text-medium-emphasis">
        Read-only preview.
        <span v-if="isRunning && job.progress">
          {{ job.progress.done }} done · {{ job.progress.failed }} failed · {{ job.progress.total - job.progress.done - job.progress.failed }} to go.
        </span>
        <span v-else-if="isChecking" aria-busy="true">Checking against CollectionSpace…</span>
        <span v-else-if="checkedAt">
          Checks were re-run against CollectionSpace at {{ formatTime(checkedAt) }}.
          <button
            id="preview-check-again-btn"
            class="link-btn"
            type="button"
            @click="check"
          >
            Check again
          </button>
        </span>
      </div>
      <CurrentDocument v-if="isRunning" class="current-document mb-2" :job="job" />
      <v-alert
        v-if="!inTab"
        id="preview-moved"
        class="mb-2"
        density="compact"
        type="info"
        variant="tonal"
      >
        This job is now {{ job.status === 'NeedsAttention' ? 'Needs attention' : job.status }}, so it's no longer in
        {{ from === 'drafts' ? 'Drafts' : 'the job queue' }}.
      </v-alert>
      <v-alert
        v-if="error"
        id="preview-error"
        class="mb-2"
        density="compact"
        type="error"
        variant="tonal"
      >
        {{ error }}
      </v-alert>
      <dl id="preview-facts" class="job-facts mb-3 text-body-2">
        <div><dt>Documents</dt><dd>{{ rows.length }}</dd></div>
        <div><dt>Handling</dt><dd>{{ handlingMix(rows, tenant) }}</dd></div>
        <div><dt>Group title</dt><dd>{{ job.groupOn ? job.groupTitle || '—' : 'None' }}</dd></div>
        <div><dt>Created by</dt><dd>{{ job.createdBy }}</dd></div>
        <template v-if="isDraft">
          <div><dt>Last saved</dt><dd>{{ formatTime(job.lastSavedAt) }} by {{ job.lastSavedBy || '—' }}</dd></div>
          <div><dt>Being edited</dt><dd>{{ editingText }}</dd></div>
          <div><dt>Expires</dt><dd>{{ expires }}</dd></div>
        </template>
        <template v-else>
          <div><dt>Submitted</dt><dd>{{ formatTime(job.queuedAt) }} by {{ job.scheduledBy || '—' }}</dd></div>
          <div v-if="job.checksAtSchedule"><dt>At submission</dt><dd>{{ checksText(job.checksAtSchedule) }}</dd></div>
        </template>
        <div v-if="!isRunning && checkedAt">
          <dt>Checks now</dt>
          <dd><v-chip id="preview-checks" :color="checksColor(counts)" size="small">{{ checksText(counts) }}</v-chip></dd>
        </div>
      </dl>
      <v-alert
        v-if="job.note"
        id="preview-note"
        class="mb-2"
        density="compact"
        type="warning"
        variant="tonal"
      >
        {{ job.note }}
      </v-alert>
      <v-alert
        v-if="counts.block && job.status === 'Queued'"
        id="preview-changed"
        class="mb-2"
        density="compact"
        role="alert"
        type="error"
        variant="tonal"
      >
        Something changed in CollectionSpace since this job was submitted: {{ counts.block }} document{{ counts.block === 1 ? ' now needs' : 's now need' }} fixing.
        Edit the job to fix {{ counts.block === 1 ? 'it' : 'them' }} before it runs.
      </v-alert>
      <v-alert
        v-if="counts.block && isDraft"
        id="preview-needs-fixing"
        class="mb-2"
        density="compact"
        type="info"
        variant="tonal"
      >
        This draft has {{ counts.block }} document{{ counts.block === 1 ? '' : 's' }} that need{{ counts.block === 1 ? 's' : '' }} fixing before it can be submitted.
      </v-alert>

      <Pagination
        :filters="filters"
        id-prefix="preview-"
        noun="documents"
        :of="view.of"
        :pages="view.pages"
        :start="view.start"
        :state="table"
        :total="view.total"
      />
      <v-table id="preview-table" class="border my-2 preview-table rounded" density="compact">
        <thead>
          <tr>
            <th class="thumb-col" scope="col"><span class="sr-only">Preview</span></th>
            <SortableColumnHeader
              id-prefix="preview-"
              label="Document"
              sort-key="file"
              :state="table"
            />
            <SortableColumnHeader
              id-prefix="preview-"
              label="Handling"
              sort-key="handling"
              :state="table"
            />
            <SortableColumnHeader
              id-prefix="preview-"
              label="Identification number"
              sort-key="id"
              :state="table"
            />
            <SortableColumnHeader
              id-prefix="preview-"
              label="Object"
              sort-key="obj"
              :state="table"
            />
            <SortableColumnHeader
              id-prefix="preview-"
              label="Date"
              sort-key="date"
              :state="table"
            />
            <SortableColumnHeader
              v-if="isRunning"
              id-prefix="preview-"
              label="Run state"
              sort-key="run"
              :state="table"
            />
            <SortableColumnHeader
              id-prefix="preview-"
              label="Checks now"
              sort-key="checks"
              :state="table"
            />
          </tr>
        </thead>
        <tbody>
          <tr v-if="!view.shown.length">
            <td id="preview-no-documents" class="py-5 text-center text-medium-emphasis" :colspan="isRunning ? 8 : 7">
              {{ rows.length ? 'No documents match this filter.' : 'No documents.' }}
            </td>
          </tr>
          <tr
            v-for="row in view.shown"
            :id="`preview-document-${row.n}`"
            :key="row.n"
            :class="{'text-medium-emphasis': !row.include}"
          >
            <td class="thumb-col"><DocumentThumbnail :job-id="job.id" :row="row" /></td>
            <td>
              {{ row.file }}
              <v-chip
                v-if="!row.include"
                class="ml-1"
                color="info"
                size="x-small"
              >
                Excluded
              </v-chip>
              <v-chip
                v-if="row.protected"
                class="ml-1"
                color="error"
                :prepend-icon="mdiLock"
                size="x-small"
                :title="`Protected file: ${row.protected.reason}`"
              >
                Protected
              </v-chip>
            </td>
            <td>{{ handlingLabel(row) }}</td>
            <td>{{ row.idnum || '—' }}</td>
            <td>{{ isLinked(row) ? row.obj || '—' : '—' }}</td>
            <td>{{ row.date || '—' }}</td>
            <td v-if="isRunning">
              <v-chip :id="`preview-document-${row.n}-run-state`" :color="chipColor(RUN_TONE[runState(row)] ?? 'neutral')" size="small">{{ runState(row) }}</v-chip>
            </td>
            <td :id="`preview-document-${row.n}-checks`">
              <v-chip v-if="row.result?.state === 'Done'" color="success" size="small">Done in last run</v-chip>
              <template v-else-if="shownChecks(row).length">
                <div
                  v-for="(problem, index) in shownChecks(row)"
                  :key="index"
                  class="check-line"
                  :class="problem.level === 'block' ? 'text-error' : 'text-warning'"
                >
                  <strong>{{ problem.level === 'block' ? 'Must fix:' : 'Warning:' }}</strong> {{ problem.text }}
                </div>
              </template>
              <v-chip v-else color="success" size="small">OK</v-chip>
            </td>
          </tr>
        </tbody>
      </v-table>
      <Pagination
        bottom
        id-prefix="preview-"
        noun="documents"
        :of="view.of"
        :pages="view.pages"
        :start="view.start"
        :state="table"
        :total="view.total"
      />
      <v-sheet
        v-if="inTab"
        id="preview-actions"
        border
        class="mt-3 pa-3"
        rounded
      >
        <JobActions
          :edit-why="editWhy"
          in-preview
          :job="job"
          :kind="from"
          :scheduler="scheduler"
          :user="user"
          @done="done"
          @error="text => error = text"
          @open="(id, mode, since) => emit('open', id, mode, since)"
        />
      </v-sheet>
    </template>
  </div>
</template>

<script setup lang="ts">
import type {PropType} from 'vue'
import {computed, onBeforeUnmount, onMounted, ref} from 'vue'
import {mdiLock} from '@mdi/js'
import type {Job, Row, TenantInfo} from '@/types'
import CurrentDocument from '@/components/job/CurrentDocument.vue'
import JobActions from '@/components/job/JobActions.vue'
import DocumentThumbnail from '@/components/util/DocumentThumbnail.vue'
import Pagination from '@/components/util/Pagination.vue'
import SortableColumnHeader from '@/components/util/SortableColumnHeader.vue'
import {formatTime} from '@/lib/files'
import type {Tone} from '@/lib/status'
import {checksColor, checksText, chipColor, handlingMix, worstLevel} from '@/lib/status'
import {tableState, tableView} from '@/lib/table'
import {ApiError, api} from '@/api'

/**
 * A job's read-only preview, inside the Drafts or Job queue page it was opened from (design: Drafts, scheduling
 * and the job queue). It never touches the draft open in Create / edit job. Checks are re-run against
 * CollectionSpace when it opens (Check again repeats them); a running job's documents show their run state,
 * refreshed while it runs. The actions are only those that apply; there is nothing to save or submit here.
 */
const props = defineProps({
  // Why this user can't create or edit jobs (design: Permissions in the UI); '' when they can.
  editWhy: {
    default: '',
    required: false,
    type: String
  },
  // The page it was opened from.
  from: {
    required: true,
    type: String as PropType<'drafts' | 'queue'>
  },
  jobId: {
    required: true,
    type: String
  },
  // For Cancel run (design: Job scheduling).
  scheduler: {
    required: false,
    type: Boolean
  },
  tenant: {
    required: true,
    type: Object as PropType<TenantInfo>
  },
  user: {
    default: undefined,
    required: false,
    type: String
  }
})
const emit = defineEmits<{back: [], open: [id: string, mode: 'edit' | 'preview', takeOverSince?: number]}>()

const LEVEL_RANK = {block: 0, warn: 1, ok: 2} as const
const RUN_RANK: Record<string, number> = {'In progress': 0, Failed: 1, Partial: 1, 'Not started': 2, Done: 3}
const RUN_TONE: Record<string, Tone> = {'In progress': 'info', Done: 'success', Partial: 'warning', Failed: 'error', 'Not started': 'neutral'}

const job = ref<Job | null>(null)
const rows = ref<Row[]>([])
const error = ref('')
const gone = ref('')
const isChecking = ref(false)
const checkedAt = ref<number | null>(null)
const table = tableState()
let timer: ReturnType<typeof setInterval> | undefined

const backLabel = computed(() => (props.from === 'drafts' ? '← Back to Drafts' : '← Back to Job queue'))
const isRunning = computed(() => job.value?.status === 'Running')
const isDraft = computed(() => job.value?.status === 'Draft')
/** Still in the page it was opened from: a draft in Drafts, a queued or running job in Job queue. */
const inTab = computed(() => !!job.value && (props.from === 'drafts' ? isDraft.value : ['Queued', 'Running'].includes(job.value.status)))
const statusText = computed(() => {
  const j = job.value!
  return j.status === 'Queued' && (j.run ?? 0) > 0 ? `Queued — rerun (run ${(j.run ?? 0) + 1})` : j.status
})
const editingText = computed(() => {
  const j = job.value!
  return j.editingBy ? `${j.editingByYou ? 'By you' : `By ${j.editingBy}`} since ${formatTime(j.editingSince)}` : 'No one'
})
const expires = computed(() => (job.value?.expiresAt
  ? new Date(job.value.expiresAt * 1000).toLocaleDateString(undefined, {month: 'short', day: 'numeric'}) : '—'))

const load = async (poll = false) => {
  try {
    const r = await api.job(props.jobId, poll)
    job.value = r.job
    // Checked rows stay until the next check; a running job's rows show its progress.
    if (!rows.value.length || isRunning.value || (r.job.status !== 'Draft' && r.job.status !== 'Queued')) {
      rows.value = r.rows
    }
    error.value = ''
    return r.job
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      gone.value = 'This job was deleted.'
      job.value = null
      clearInterval(timer)
    } else {
      error.value = (e as Error).message
    }
    return null
  }
}

const check = async () => {
  if (!job.value || !['Draft', 'Queued'].includes(job.value.status)) {
    return
  }
  isChecking.value = true
  try {
    rows.value = (await api.check(props.jobId)).rows
    checkedAt.value = Date.now() / 1000
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    isChecking.value = false
  }
}

onMounted(async () => {
  if (await load()) {
    await check()
  }
  timer = setInterval(() => void load(true), isRunning.value ? 3000 : 5000)
})
onBeforeUnmount(() => clearInterval(timer))

/** After an action here: a deleted job goes back to the list; otherwise show the job as it is now. */
const done = async () => {
  if (!(await load()) && gone.value) {
    emit('back')
  }
}

// ---- the documents: paging, sorting and the Show filter (design: User interface, Large jobs) ----
const handlingLabel = (r: Row) => props.tenant.handling.find(h => h.id === r.handling)?.label ?? r.handling
const isLinked = (r: Row) => props.tenant.handling.find(h => h.id === r.handling)?.object !== 'none'
const runState = (r: Row) => r.result?.state ?? 'Not started'
const shownChecks = (r: Row) => r.checks.filter(c => c.level !== 'info')

const matches = (r: Row, filter: string): boolean => {
  const level = worstLevel(r)
  switch (filter) {
  case 'problems': return r.include && level !== 'ok'
  case 'block': return r.include && level === 'block'
  case 'warn': return r.include && level === 'warn'
  case 'protected': return !!r.protected
  case 'excluded': return !r.include
  default: return true
  }
}

const view = computed(() => tableView(rows.value, table, {
  file: r => r.file,
  handling: handlingLabel,
  id: r => r.idnum,
  obj: r => (isLinked(r) ? r.obj : ''),
  date: r => r.date || '~',
  run: r => RUN_RANK[runState(r)] ?? 4,
  checks: r => (!r.include ? 3 : LEVEL_RANK[worstLevel(r)])
}, matches))

const filters = computed<[string, string][]>(() => {
  const count = (filter: string) => rows.value.filter(r => matches(r, filter)).length
  return [
    ['all', `All documents (${rows.value.length})`],
    ['problems', `With problems (${count('problems')})`],
    ['block', `Need fixing (${count('block')})`],
    ['warn', `With warnings (${count('warn')})`],
    ['protected', `Protected (${count('protected')})`],
    ['excluded', `Excluded (${count('excluded')})`]
  ]
})

const counts = computed(() => {
  const work = rows.value.filter(r => r.include && r.result?.state !== 'Done')
  return {block: work.filter(r => worstLevel(r) === 'block').length, warn: work.filter(r => worstLevel(r) === 'warn').length}
})
</script>

<style scoped>
.thumb-col {
  width: 64px;
}
.check-line {
  font-size: 0.8125rem;
  line-height: 1.35;
}
.current-document {
  max-width: 420px;
}
</style>
