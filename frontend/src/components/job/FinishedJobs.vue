<template>
  <div>
    <div v-if="open" id="finished-results">
      <button
        id="results-back-btn"
        class="link-btn mb-2"
        type="button"
        @click="resultsId = null"
      >
        ← Back to finished jobs
      </button>
      <h2 id="results-title" class="align-center d-flex flex-wrap mb-1 text-h6">
        <span class="mr-2">{{ nameOf(open) }}</span>
        <v-chip id="results-outcome" :color="outcomeColor(open)" size="small">{{ outcomeText(open) }}</v-chip>
      </h2>
      <v-alert
        v-if="error"
        id="finished-error"
        class="mb-2"
        density="compact"
        type="error"
        variant="tonal"
      >
        {{ error }}
      </v-alert>
      <p v-if="!details.get(open.id)" id="results-loading" class="text-medium-emphasis">Loading…</p>
      <JobResults
        v-else
        :job="open"
        :rows="details.get(open.id)!.rows"
        :runs="details.get(open.id)!.runs"
        :tenant="tenant"
      />
      <div id="results-actions" class="mt-3">
        <FinishedJobActions
          :busy="isBusy"
          :created="details.get(open.id)?.created"
          :deleting="deletingId === open.id"
          :edit-why="editWhy"
          :fix-label="fixLabel(open)"
          in-results
          :job="open"
          @ask-delete="() => ensureLoaded(open!)"
          @delete="() => deleteJob(open!)"
          @fix="() => fix(open!)"
        />
      </div>
    </div>

    <div v-else id="finished-list">
      <p id="finished-description" class="mb-3 text-body-2 text-medium-emphasis">
        Jobs that have run, newest first. Completed jobs are removed 30 days after they finish. Jobs that need
        attention or failed stay until someone fixes and reruns them or deletes them; a rerun skips everything already created in
        CollectionSpace.
      </p>
      <v-alert
        v-if="flash"
        id="finished-message"
        class="mb-3"
        density="compact"
        role="status"
        type="info"
        variant="tonal"
      >
        {{ flash }}
      </v-alert>
      <v-alert
        v-if="error"
        id="finished-error"
        class="mb-3"
        density="compact"
        type="error"
        variant="tonal"
      >
        {{ error }}
      </v-alert>
      <div v-if="sorted.length" class="mb-1 text-body-2 text-right">
        <button
          id="finished-expand-all-btn"
          class="link-btn"
          type="button"
          @click="() => expandAll(true)"
        >
          Expand all
        </button> ·
        <button
          id="finished-collapse-all-btn"
          class="link-btn"
          type="button"
          @click="() => expandAll(false)"
        >
          Collapse all
        </button>
      </div>
      <v-table id="finished-table" class="border job-list rounded" density="compact">
        <thead>
          <tr>
            <th class="toggle-col" scope="col"><span class="sr-only">Details</span></th>
            <SortableColumnHeader
              id-prefix="finished-"
              label="Job"
              sort-key="name"
              :state="table"
            />
            <SortableColumnHeader
              class="outcome-col"
              id-prefix="finished-"
              label="Outcome"
              sort-key="outcome"
              :state="table"
            />
            <SortableColumnHeader
              id-prefix="finished-"
              label="Documents"
              sort-key="docs"
              :state="table"
            />
            <SortableColumnHeader
              class="finished-col"
              id-prefix="finished-"
              label="Finished"
              sort-key="finished"
              :state="table"
            />
            <th class="actions-col" scope="col"><span class="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody v-if="!isLoaded">
          <tr v-if="!error">
            <td
              id="finished-loading"
              aria-busy="true"
              class="py-5 text-center text-medium-emphasis"
              colspan="6"
            >
              Loading finished jobs…
            </td>
          </tr>
        </tbody>
        <tbody v-else-if="!sorted.length">
          <tr>
            <td id="finished-empty" class="py-5 text-center text-medium-emphasis" colspan="6">
              No finished jobs yet.
            </td>
          </tr>
        </tbody>
        <tbody v-for="job in sorted" :id="`job-${job.id}`" :key="job.id">
          <tr class="job-row">
            <td class="px-1">
              <v-btn
                :id="`job-${job.id}-toggle-btn`"
                :aria-expanded="expanded.has(job.id)"
                :aria-label="`Show details of ${nameOf(job)}`"
                class="chevron"
                :class="{open: expanded.has(job.id)}"
                density="comfortable"
                :icon="mdiChevronRight"
                size="small"
                variant="text"
                @click="() => toggle(job)"
              />
            </td>
            <td>
              <span :id="`job-${job.id}-name`" class="font-weight-medium">{{ nameOf(job) }}</span>
              <span v-if="job.run > 1" class="text-caption text-medium-emphasis"> (run {{ job.run }})</span>
            </td>
            <td :title="job.code ? failureOf(job.code).title : ''">
              <v-chip :id="`job-${job.id}-outcome`" :color="outcomeColor(job)" size="small">{{ outcomeText(job) }}</v-chip>
              <div v-if="job.code" :id="`job-${job.id}-failure`" class="text-caption text-medium-emphasis">{{ failureOf(job.code).title }}</div>
            </td>
            <td :id="`job-${job.id}-counts`">{{ countsText(job.counts) }}</td>
            <td class="text-no-wrap" :title="`run by ${ranBy(job)}`">
              {{ formatTime(job.finishedAt) }}
              <div class="text-caption text-medium-emphasis">by {{ ranBy(job) }}</div>
            </td>
            <td class="text-right">
              <FinishedJobActions
                :busy="isBusy"
                :confirm-to="confirmCells.get(job.id)"
                :created="details.get(job.id)?.created"
                :deleting="deletingId === job.id"
                :edit-why="editWhy"
                :fix-label="fixLabel(job)"
                :job="job"
                @ask-delete="() => ensureLoaded(job)"
                @confirming="on => setConfirming(job.id, on)"
                @delete="() => deleteJob(job)"
                @fix="() => fix(job)"
                @view="() => viewResults(job)"
              />
            </td>
          </tr>
          <tr v-show="confirming.has(job.id)" class="job-confirm-row">
            <td :ref="cell => setConfirmCell(job.id, cell as HTMLElement | null)" class="pb-3" colspan="6" />
          </tr>
          <tr v-if="expanded.has(job.id)" class="job-details-row">
            <td colspan="6">
              <div :id="`job-${job.id}-details`" class="py-3">
                <div class="mb-2 text-body-2 text-medium-emphasis">{{ runLine(job) }}</div>
                <p v-if="!details.get(job.id)" class="text-medium-emphasis">Loading…</p>
                <JobDocumentsTable
                  v-else
                  :job="job"
                  kind="history"
                  :rows="details.get(job.id)!.rows"
                  :tenant="tenant"
                />
                <div class="mt-2 text-body-2">
                  <button
                    :id="`job-${job.id}-all-results-btn`"
                    class="link-btn"
                    type="button"
                    @click="() => viewResults(job)"
                  >
                    View all {{ job.rowCount }} documents' results
                  </button>
                </div>
              </div>
            </td>
          </tr>
        </tbody>
      </v-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import type {PropType} from 'vue'
import {computed, onBeforeUnmount, onMounted, reactive, ref} from 'vue'
import {mdiChevronRight} from '@mdi/js'
import type {Created, Job, Row, Run, TenantInfo} from '@/types'
import FinishedJobActions from '@/components/job/FinishedJobActions.vue'
import JobDocumentsTable from '@/components/job/JobDocumentsTable.vue'
import JobResults from '@/components/job/JobResults.vue'
import SortableColumnHeader from '@/components/util/SortableColumnHeader.vue'
import {formatTime} from '@/lib/files'
import {OUTCOME, countsText, failureOf, loadFailures, needsFix} from '@/lib/results'
import {chipColor} from '@/lib/status'
import {tableState, tableView} from '@/lib/table'
import {api} from '@/api'

/**
 * The Finished jobs page (design: Finished jobs and error messages): jobs that have run, newest first, with
 * their outcome, documents by result, when they finished and who ran them. View results shows every
 * document; Fix and reschedule (or Reschedule, when every failure only needs another run) moves a job that
 * needs attention or failed to Drafts; Delete removes it from the BMU (never from CollectionSpace).
 */
defineProps({
  // Why this user can't create or edit jobs (design: Permissions in the UI); '' when they can.
  editWhy: {
    default: '',
    required: false,
    type: String
  },
  tenant: {
    required: true,
    type: Object as PropType<TenantInfo>
  }
})
const emit = defineEmits<{open: [id: string]}>()

const FINISHED = ['Completed', 'NeedsAttention', 'Failed']
const OUT_RANK: Record<string, number> = {Failed: 0, NeedsAttention: 1, Completed: 2}

const jobs = ref<Job[]>([])
// The first answer from the server has arrived: until then the list is loading, not empty.
const isLoaded = ref(false)
const error = ref('')
const flash = ref('')
const details = reactive(new Map<string, {rows: Row[], runs: Run[], created: Created}>())
const expanded = reactive(new Set<string>())
// Documents that fail a blocking check now
const blocking = reactive(new Map<string, number>())
const resultsId = ref<string | null>(null)
const deletingId = ref<string | null>(null)
const isBusy = ref(false)
const table = tableState()
let timer: ReturnType<typeof setInterval> | undefined

// A job's delete confirmation is shown in a full-width row under the job.
const confirming = reactive(new Set<string>())
const confirmCells = reactive(new Map<string, HTMLElement>())
const setConfirmCell = (id: string, cell: HTMLElement | null) => {
  if (cell && confirmCells.get(id) !== cell) {
    confirmCells.set(id, cell)
  } else if (!cell) {
    confirmCells.delete(id)
  }
}
const setConfirming = (id: string, on: boolean) => {
  if (on) {
    confirming.add(id)
  } else {
    confirming.delete(id)
  }
}

const nameOf = (job: Job) => job.name || 'Untitled job'
const ranBy = (job: Job) => job.runBy || job.scheduledBy || '—'
const outcomeText = (job: Job) => OUTCOME[job.status]?.text ?? job.status
const outcomeColor = (job: Job) => chipColor(OUTCOME[job.status]?.tone ?? '')
const runLine = (job: Job) => `Run ${job.run} submitted by ${ranBy(job)} · started ${formatTime(job.startedAt)} · finished ${formatTime(job.finishedAt)}`
  + (job.cancelledBy ? ` · cancelled by ${job.cancelledBy}` : '')

const newestFirst = computed(() => [...jobs.value].sort((a, b) => (b.finishedAt ?? b.updated) - (a.finishedAt ?? a.updated)))
const sorted = computed(() => tableView(newestFirst.value, table, {
  name: nameOf,
  outcome: j => OUT_RANK[j.status] ?? 3,
  docs: j => j.rowCount,
  finished: j => -(j.finishedAt ?? 0)
}, undefined, false).shown)
const open = computed(() => jobs.value.find(j => j.id === resultsId.value) ?? null)

const load = async (id: string, poll = false) => {
  const r = await api.job(id, poll)
  details.set(id, {rows: r.rows, runs: r.runs, created: r.created})
  return r
}
const showError = (e: unknown) => {
  error.value = (e as Error).message
}
const ensureLoaded = async (job: Job, quiet = true) => {
  if (!details.has(job.id)) {
    await load(job.id).catch(e => quiet ? undefined : showError(e))
  }
}

const refresh = async (runChecks = false) => {
  try {
    jobs.value = (await api.jobs(!runChecks)).jobs.filter(j => FINISHED.includes(j.status))
    error.value = ''
    isLoaded.value = true
    for (const id of [...expanded, ...(resultsId.value ? [resultsId.value] : [])]) {
      if (jobs.value.some(j => j.id === id)) {
        await load(id, !runChecks)
      }
    }
  } catch (e) {
    showError(e)
  }
  if (runChecks) {
    // Design: the button reads Fix and reschedule when a document fails a blocking check now, so the jobs that
    // can be rerun are checked against CollectionSpace as it is now; their results decide the label.
    for (const job of jobs.value.filter(j => j.status !== 'Completed')) {
      ensureLoaded(job)
      api.check(job.id).then(r => blocking.set(job.id, r.counts.block)).catch(() => undefined)
    }
  }
}

onMounted(() => {
  loadFailures()
  refresh(true)
  timer = setInterval(() => refresh(false), 4000)
})
onBeforeUnmount(() => clearInterval(timer))

const fixLabel = (job: Job): 'Fix and reschedule' | 'Reschedule' => (
  needsFix(job, details.get(job.id)?.rows ?? [], blocking.get(job.id) ?? 0) ? 'Fix and reschedule' : 'Reschedule'
)

const toggle = (job: Job) => {
  if (expanded.has(job.id)) {
    expanded.delete(job.id)
  } else {
    expanded.add(job.id)
    ensureLoaded(job, false)
  }
}
const expandAll = (on: boolean) => {
  if (on) {
    jobs.value.filter(j => !expanded.has(j.id)).forEach(toggle)
  } else {
    expanded.clear()
  }
}

const viewResults = (job: Job) => {
  resultsId.value = job.id
  ensureLoaded(job, false)
}

const fix = async (job: Job) => {
  isBusy.value = true
  try {
    await api.fix(job.id)
    emit('open', job.id)
  } catch (e) {
    showError(e)
    await refresh()
  } finally {
    isBusy.value = false
  }
}

const deleteJob = async (job: Job) => {
  deletingId.value = job.id
  try {
    await api.deleteJob(job.id)
    if (resultsId.value === job.id) {
      resultsId.value = null
    }
    confirming.delete(job.id)
    flash.value = `Deleted “${nameOf(job)}” from the BMU. Records its runs created stay in CollectionSpace; the audit log lists them.`
    await refresh()
  } catch (e) {
    showError(e)
  } finally {
    deletingId.value = null
  }
}
</script>

<style scoped>
.toggle-col {
  width: 40px;
}
.outcome-col {
  width: 150px;
}
.finished-col {
  width: 190px;
}
.actions-col {
  width: 340px;
}
</style>
