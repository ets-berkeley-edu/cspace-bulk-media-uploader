<template>
  <div>
    <v-table :id="`job-${job.id}-documents`" class="border job-documents rounded" density="compact">
      <thead>
        <tr>
          <th class="thumb-col" scope="col"><span class="sr-only">Preview</span></th>
          <SortableColumnHeader
            :id-prefix="idPrefix"
            label="Document"
            sort-key="file"
            :state="table"
          />
          <SortableColumnHeader
            :id-prefix="idPrefix"
            label="Handling"
            sort-key="handling"
            :state="table"
          />
          <SortableColumnHeader
            :id-prefix="idPrefix"
            label="Identification number"
            sort-key="id"
            :state="table"
          />
          <SortableColumnHeader
            :id-prefix="idPrefix"
            :label="kind === 'history' ? 'Result' : 'Status'"
            sort-key="status"
            :state="table"
          />
          <SortableColumnHeader
            :id-prefix="idPrefix"
            :label="kind === 'history' ? 'What happened' : 'Most important issue'"
            sort-key="issue"
            :state="table"
          />
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in sorted"
          :id="`job-${job.id}-document-${row.n}`"
          :key="row.n"
          :class="{'text-medium-emphasis': !row.include}"
        >
          <td class="thumb-col"><DocumentThumbnail :job-id="job.id" :row="row" /></td>
          <td>
            {{ row.file }}
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
          <td><v-chip :color="chipColor(status(row).cls)" size="small">{{ status(row).text }}</v-chip></td>
          <td :class="{'text-medium-emphasis': !issue(row)}">{{ issue(row) || '—' }}</td>
        </tr>
        <tr v-if="!top.length">
          <td class="text-medium-emphasis" colspan="6">No documents.</td>
        </tr>
      </tbody>
    </v-table>
    <div v-if="rows.length > LIMIT" class="mt-1 text-caption text-medium-emphasis">
      Showing the {{ LIMIT }} most important of {{ rows.length.toLocaleString() }} documents.
    </div>
  </div>
</template>

<script setup lang="ts">
import type {PropType} from 'vue'
import {computed} from 'vue'
import {mdiLock} from '@mdi/js'
import type {Job, Row, TenantInfo} from '@/types'
import DocumentThumbnail from '@/components/util/DocumentThumbnail.vue'
import SortableColumnHeader from '@/components/util/SortableColumnHeader.vue'
import {RESULT_BADGE, failureOf, importantRows, resultState, rowCodes} from '@/lib/results'
import {chipColor, rowStatus, worstLevel} from '@/lib/status'
import {tableState, tableView} from '@/lib/table'

/**
 * The documents of an expanded job in Drafts, Job queue and Finished jobs (design: Job lists): its 10 most
 * important documents, problems first, one line each with the thumbnail, the document (and its Protected chip),
 * handling, identification number, then Status and the most important issue (Drafts, Job queue) or Result and
 * what happened, with what to do (Finished jobs). Sortable like every table.
 */
const props = defineProps({
  job: {
    required: true,
    type: Object as PropType<Job>
  },
  kind: {
    required: true,
    type: String as PropType<'drafts' | 'queue' | 'history'>
  },
  rows: {
    required: true,
    type: Array as PropType<Row[]>
  },
  tenant: {
    required: true,
    type: Object as PropType<TenantInfo>
  }
})

const LIMIT = 10
const LEVEL_RANK = {block: 0, warn: 1, ok: 2} as const
const RUN_RANK: Record<string, number> = {'In progress': 0, Failed: 1, Partial: 1, 'Not started': 2, Done: 3}
const RUN_BADGE: Record<string, string> = {'In progress': 'b-accent', Done: 'b-ok', Partial: 'b-warn', Failed: 'b-danger', 'Not started': 'b-muted'}

const idPrefix = computed(() => `job-${props.job.id}-documents-`)
const runView = computed(() => props.kind === 'queue' && props.job.status === 'Running')
const runState = (r: Row) => (!r.include ? 'Excluded' : r.result?.state ?? 'Not started')

/** The 10 that matter most: blocking checks, then warnings (Drafts, Job queue); run state while running; results after. */
const top = computed<Row[]>(() => {
  if (props.kind === 'history') {
    return importantRows(props.rows, LIMIT)
  }
  const rank = (r: Row) => (runView.value ? RUN_RANK[runState(r)] ?? 4 : r.include ? LEVEL_RANK[worstLevel(r)] : 3)
  return props.rows.map((r, i) => ({r, i})).sort((a, b) => rank(a.r) - rank(b.r) || a.i - b.i).slice(0, LIMIT).map(x => x.r)
})

const handlingLabel = (r: Row) => props.tenant.handling.find(h => h.id === r.handling)?.label ?? r.handling

const status = (r: Row): {text: string, cls: string} => {
  if (props.kind === 'history') {
    const s = resultState(r)
    return {text: s, cls: RESULT_BADGE[s]}
  }
  if (runView.value) {
    const s = runState(r)
    return {text: s, cls: RUN_BADGE[s] ?? 'b-muted'}
  }
  return rowStatus(r, props.tenant)
}

/** Drafts, Job queue: the row's most important check. Finished jobs: what happened, and what to do about it. */
const issue = (r: Row): string => {
  if (props.kind === 'history') {
    const s = resultState(r)
    if (s === 'Excluded') {
      return `Excluded by ${r.disabledBy || 'a user'}; ignored.`
    }
    const code = rowCodes(r)[0]
    if (code) {
      const f = failureOf(code)
      return `${f.title.replace(/\.$/, '')}. ${f.fix}`
    }
    if (s === 'Not started') {
      return 'Not reached before the job stopped.'
    }
    return s === 'Done' ? 'Created in CollectionSpace.' : ''
  }
  if (runView.value) {
    return ''
  }
  const c = r.checks.find(x => x.level === 'block') ?? r.checks.find(x => x.level === 'warn')
  return c ? `${c.level === 'block' ? 'Must fix: ' : 'Warning: '}${c.text}` : ''
}

const table = tableState()
const sorted = computed(() => tableView(top.value, table, {
  file: r => r.file,
  handling: handlingLabel,
  id: r => r.idnum,
  status: r => status(r).text,
  issue: r => issue(r) || '~'
}, undefined, false).shown)
</script>

<style scoped>
.thumb-col {
  width: 64px;
}
</style>
