<template>
  <div id="job-results">
    <div id="results-summary" class="mb-2 text-body-2 text-medium-emphasis">
      Run {{ job.run }}, finished {{ formatTime(job.finishedAt) }} (run by {{ job.runBy || job.scheduledBy }}). {{ countsText(job.counts ?? counts) }}.
    </div>

    <div v-if="runs.length" id="run-history" class="mb-3">
      <div class="font-weight-bold mb-1 text-body-2">Run history (newest first)</div>
      <v-alert
        v-for="run in newestFirst"
        :id="`run-${run.run}`"
        :key="run.run"
        class="mb-1 run"
        density="compact"
        :type="run.outcome === 'Completed' ? 'info' : 'warning'"
        variant="tonal"
      >
        <strong>Run {{ run.run }}: {{ outcome(run.outcome).text }}{{ run.code ? ` — ${failureOf(run.code).title}` : '' }}</strong>
        {{ run.counts ? ` · ${countsText(run.counts)}` : '' }}
        <div class="text-caption">
          Submitted by {{ run.scheduledBy || '—' }}{{ run.scheduledAt ? ` (${formatTime(run.scheduledAt)})` : '' }}
          · started {{ formatTime(run.startedAt) }} · ended {{ run.endedAt ? formatTime(run.endedAt) : '—' }}
        </div>
        <div v-if="run.cancelledBy" class="text-caption">
          Cancelled by {{ run.cancelledBy }}{{ run.cancelledAt ? ` (${formatTime(run.cancelledAt)})` : '' }}
        </div>
        <div v-if="beforeRun(run)" class="text-caption">Before this run: {{ beforeRun(run) }}</div>
      </v-alert>
    </div>

    <div v-if="job.groupOn" id="results-group" class="mb-2 text-body-2 text-medium-emphasis">
      Group “{{ job.groupTitle }}”:
      <span v-if="job.groupStep?.s === 'done'">created in run {{ job.groupStep.run }} (<code>{{ job.groupStep.csid }}</code>)</span>
      <span v-else-if="job.groupStep?.s === 'failed'">couldn't be created in run {{ job.groupStep.run }}</span>
      <span v-else>not created (no document reached the point of joining it)</span>
    </div>
    <FailureAlert
      v-if="job.code"
      id="results-job-failure"
      class="mb-3"
      :code="job.code"
      :detail="jobDetail"
    />

    <Pagination
      :filters="filters"
      id-prefix="results-"
      noun="documents"
      :of="view.of"
      :pages="view.pages"
      :start="view.start"
      :state="table"
      :total="view.total"
    />
    <v-table id="results-table" class="border my-2 results-table rounded" density="compact">
      <thead>
        <tr>
          <th class="thumb-col" scope="col"><span class="sr-only">Preview</span></th>
          <SortableColumnHeader
            id-prefix="results-"
            label="#"
            sort-key="n"
            :state="table"
          />
          <SortableColumnHeader
            id-prefix="results-"
            label="Document"
            sort-key="file"
            :state="table"
          />
          <SortableColumnHeader
            id-prefix="results-"
            label="Result"
            sort-key="result"
            :state="table"
          />
          <SortableColumnHeader
            id-prefix="results-"
            label="Steps"
            sort-key="steps"
            :state="table"
            title="Sort by how many steps are done"
          />
          <SortableColumnHeader
            id-prefix="results-"
            label="What happened"
            sort-key="what"
            :state="table"
          />
        </tr>
      </thead>
      <tbody>
        <tr v-if="!view.shown.length">
          <td id="results-no-documents" class="py-5 text-center text-medium-emphasis" colspan="6">No documents match this filter.</td>
        </tr>
        <tr
          v-for="row in view.shown"
          :id="`result-${row.n}`"
          :key="row.n"
          :class="{'row-excluded': resultState(row) === 'Excluded'}"
        >
          <td class="thumb-col"><DocumentThumbnail :job-id="job.id" :row="row" /></td>
          <td>{{ row.n }}</td>
          <td>
            {{ row.file }}
            <div class="text-caption text-medium-emphasis">{{ handlingLabel(row) }}{{ row.skipLink ? ' · not linked (stopped)' : '' }}</div>
          </td>
          <td>
            <v-chip :id="`result-${row.n}-state`" :color="chipColor(RESULT_TONE[resultState(row)])" size="small">{{ resultState(row) }}</v-chip>
          </td>
          <td :id="`result-${row.n}-steps`" class="steps">
            <div
              v-for="item in stepList(row)"
              :key="item.key"
              class="step"
              :class="{'font-weight-medium text-error': item.step.s === 'failed'}"
            >
              {{ STEP_MARK[item.step.s] }} {{ item.label }}
              <code v-if="item.step.csid">{{ item.step.csid }}</code>
              <span v-if="stepNote(item.key, item.step)" class="text-medium-emphasis"> ({{ stepNote(item.key, item.step) }})</span>
              <span v-if="item.step.s === 'done' && item.step.run" class="text-medium-emphasis"> · run {{ item.step.run }}</span>
            </div>
            <span v-if="!stepList(row).length" class="text-medium-emphasis">—</span>
          </td>
          <td :id="`result-${row.n}-what`" class="what">
            <span v-if="resultState(row) === 'Excluded'" class="text-medium-emphasis">{{ excludedText(row) }}</span>
            <FailureAlert v-else-if="row.result?.error" :code="row.result.error.code" :detail="row.result.error.detail" />
            <span v-else-if="resultState(row) === 'Not started'" class="text-medium-emphasis">Not reached before the job stopped.</span>
            <span v-else-if="resultState(row) === 'Done'" class="text-medium-emphasis">Created in CollectionSpace.</span>
            <FailureAlert
              v-for="(notice, index) in row.result?.notices ?? []"
              :key="index"
              :code="notice.code"
              :detail="notice.detail"
              notice
            />
          </td>
        </tr>
      </tbody>
    </v-table>
    <Pagination
      bottom
      id-prefix="results-"
      noun="documents"
      :of="view.of"
      :pages="view.pages"
      :start="view.start"
      :state="table"
      :total="view.total"
    />
  </div>
</template>

<script setup lang="ts">
import type {PropType} from 'vue'
import {computed} from 'vue'
import type {Job, Row, Run, TenantInfo} from '@/types'
import DocumentThumbnail from '@/components/util/DocumentThumbnail.vue'
import FailureAlert from '@/components/util/FailureAlert.vue'
import Pagination from '@/components/util/Pagination.vue'
import SortableColumnHeader from '@/components/util/SortableColumnHeader.vue'
import {formatTime} from '@/lib/files'
import {OUTCOME, RESULT_TONE, STEP_MARK, countsText, failureOf, resultCounts, resultState, stepList, stepNote} from '@/lib/results'
import {chipColor} from '@/lib/status'
import {tableState, tableView} from '@/lib/table'

/**
 * A finished job's results (design: Results view): every document with its result, each step's outcome and the
 * CSIDs created, the run that did each step, and for each failure what happened and what to do. The run history
 * lists every run, newest first, with the documents excluded or deleted before it.
 */
const props = defineProps({
  job: {
    required: true,
    type: Object as PropType<Job>
  },
  rows: {
    required: true,
    type: Array as PropType<Row[]>
  },
  runs: {
    required: true,
    type: Array as PropType<Run[]>
  },
  tenant: {
    required: true,
    type: Object as PropType<TenantInfo>
  }
})

const RANK: Record<string, number> = {Failed: 0, Partial: 1, 'In progress': 2, 'Not started': 2, Excluded: 3, Done: 4}

const table = tableState()
const counts = computed(() => resultCounts(props.rows))
const filters = computed<[string, string][]>(() => [
  ['all', `All documents (${props.rows.length})`],
  ['problems', `Not finished (${counts.value.failed + counts.value.partial + counts.value.notStarted})`],
  ['failed', `Failed (${counts.value.failed})`],
  ['partial', `Partial (${counts.value.partial})`],
  ['notStarted', `Not started (${counts.value.notStarted})`],
  ['excluded', `Excluded (${counts.value.disabled})`],
  ['done', `Done (${counts.value.done})`]
])

const matches = (row: Row, filter: string): boolean => {
  const state = resultState(row)
  switch (filter) {
  case 'problems': return state === 'Failed' || state === 'Partial' || state === 'Not started' || state === 'In progress'
  case 'failed': return state === 'Failed'
  case 'partial': return state === 'Partial'
  case 'notStarted': return state === 'Not started' || state === 'In progress'
  case 'excluded': return state === 'Excluded'
  case 'done': return state === 'Done'
  default: return true
  }
}

const view = computed(() => tableView(props.rows, table, {
  n: row => row.n,
  file: row => row.file,
  result: row => RANK[resultState(row)] ?? 5,
  steps: row => {
    const steps = Object.values(row.result?.steps ?? {})
    return steps.filter(step => step.s === 'done').length - steps.length
  },
  what: row => (row.result?.error ? failureOf(row.result.error.code).title : '~')
}, matches))

const handlingLabel = (row: Row) => props.tenant.handling.find(h => h.id === row.handling)?.label ?? row.handling
const newestFirst = computed(() => [...props.runs].sort((a, b) => b.run - a.run))
const outcome = (o: string) => OUTCOME[o] ?? {text: o, tone: 'neutral'}

/** The documents excluded or deleted before a run. */
const beforeRun = (run: Run) => [
  ...(run.disabledBefore ?? []).map(d => `${d.file} excluded by ${d.by || 'a user'}`),
  ...(run.deletedBefore ?? []).map(d => `${d.file} deleted by ${d.by}`)
].join('; ')

const excludedText = (row: Row) => {
  const earlier = row.result?.error?.code
  const media = row.result?.steps?.media
  return `Excluded by ${row.disabledBy || 'a user'}${row.disabledAt ? ` (${formatTime(row.disabledAt)})` : ''}; the BMU ignored it.`
    + (earlier ? ` Earlier problem: ${failureOf(earlier).title}.` : '')
    + (media?.s === 'done' ? ` Its Media record from an earlier run (${media.csid}) stays in CollectionSpace, unfinished.` : '')
}

/** The technical detail of the job-level failure (design: technical detail shown on request); jobs that ended
 *  before the worker stored codeDetail fall back to what the job itself says. */
const jobDetail = computed(() => props.job.codeDetail
  || (props.job.cancelledBy ? `Cancel requested by ${props.job.cancelledBy}` : props.job.code === 'group_failed' ? props.job.groupStep?.detail : undefined)
  || undefined)
</script>

<style scoped>
.thumb-col {
  width: 64px;
}
.results-table td {
  padding-bottom: 6px !important;
  padding-top: 6px !important;
  vertical-align: top;
}
.row-excluded > td {
  opacity: 0.6;
}
.step {
  font-size: 0.8125rem;
  line-height: 1.4;
}
.step code {
  font-size: 0.75rem;
}
.what {
  font-size: 0.8125rem;
  min-width: 260px;
}
</style>
