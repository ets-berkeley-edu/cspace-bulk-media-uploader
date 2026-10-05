<template>
  <div>
    <p id="drafts-description" class="mb-3 text-body-2 text-medium-emphasis">
      Jobs saved but not submitted, including incomplete jobs and jobs with problems. Everyone signed in can see
      them. Staff can edit every draft, and interns the drafts that are open to interns, one person at a time; you can take over
      a draft someone else is editing. A draft that has never run is deleted
      30 days after it was last changed or saved (7 days if it has protected files); a fix of a job that has run is reverted instead,
      and the job returns to Finished jobs. Checks are re-run against CollectionSpace each time this list is shown.
    </p>
    <v-alert
      v-if="error"
      id="drafts-error"
      class="mb-3"
      density="compact"
      type="error"
      variant="tonal"
    >
      {{ error }}
    </v-alert>
    <v-alert
      v-if="message"
      id="drafts-message"
      class="mb-3"
      density="compact"
      role="status"
      type="info"
      variant="tonal"
    >
      {{ message }}
    </v-alert>
    <div v-if="drafts.length" class="mb-1 text-body-2 text-right">
      <button
        id="drafts-expand-all-btn"
        class="link-btn"
        type="button"
        @click="() => expandAll(true)"
      >
        Expand all
      </button> ·
      <button
        id="drafts-collapse-all-btn"
        class="link-btn"
        type="button"
        @click="() => expandAll(false)"
      >
        Collapse all
      </button>
    </div>
    <v-table id="drafts-table" class="border job-list rounded" density="compact">
      <thead>
        <tr>
          <th class="toggle-col" scope="col"><span class="sr-only">Details</span></th>
          <SortableColumnHeader
            id-prefix="drafts-"
            label="Draft"
            sort-key="name"
            :state="table"
          />
          <SortableColumnHeader
            id-prefix="drafts-"
            label="Docs"
            sort-key="docs"
            :state="table"
          />
          <SortableColumnHeader
            id-prefix="drafts-"
            label="Checks now"
            sort-key="checks"
            :state="table"
          />
          <SortableColumnHeader
            id-prefix="drafts-"
            label="Last saved"
            sort-key="saved"
            :state="table"
          />
          <SortableColumnHeader
            id-prefix="drafts-"
            label="Editing"
            sort-key="editing"
            :state="table"
          />
          <SortableColumnHeader
            id-prefix="drafts-"
            label="Expires"
            sort-key="expires"
            :state="table"
          />
          <th class="actions-col" scope="col"><span class="sr-only">Actions</span></th>
        </tr>
      </thead>
      <tbody v-if="!isLoaded">
        <tr v-if="!error">
          <td
            id="drafts-loading"
            aria-busy="true"
            class="py-5 text-center text-medium-emphasis"
            colspan="8"
          >
            Loading drafts…
          </td>
        </tr>
      </tbody>
      <tbody v-else-if="!drafts.length">
        <tr>
          <td id="drafts-empty" class="py-5 text-center text-medium-emphasis" colspan="8">
            No drafts. A job you start in Create / edit job is a draft until you submit it.
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
            <div :id="`job-${job.id}-name`" class="font-weight-medium">{{ nameOf(job) }}</div>
            <div :id="`job-${job.id}-access`" class="text-caption text-medium-emphasis">{{ accessLabel(job) }}</div>
            <div class="text-caption text-medium-emphasis">created by {{ job.createdBy }}</div>
            <div v-if="job.fixFrom" :id="`job-${job.id}-fixing`" class="text-caption text-medium-emphasis">
              <v-icon :icon="mdiWrench" size="x-small" /> fixing after run {{ job.fixFrom.run }} ({{ job.fixFrom.status === 'Failed' ? 'failed' : 'needed attention' }})
            </div>
            <div v-if="job.note" :id="`job-${job.id}-note`" class="text-caption text-warning">
              <v-icon :icon="mdiAlert" size="x-small" /> {{ job.note }}
            </div>
          </td>
          <td>{{ job.rowCount }}</td>
          <td>
            <v-chip v-if="checks.get(job.id) === 'checking'" :id="`job-${job.id}-checks`" size="small">Checking…</v-chip>
            <v-chip
              v-else-if="countsOf(job.id)"
              :id="`job-${job.id}-checks`"
              :color="checksColor(countsOf(job.id)!)"
              size="small"
            >
              {{ checksText(countsOf(job.id)!) }}
            </v-chip>
          </td>
          <td>
            {{ formatTime(job.lastSavedAt) }}
            <div class="text-caption text-medium-emphasis">by {{ job.lastSavedBy || '—' }}</div>
          </td>
          <td>
            <span
              v-if="job.editingBy"
              :id="`job-${job.id}-editing`"
              class="font-weight-medium text-no-wrap text-warning"
              :title="`since ${formatTime(job.editingSince)}`"
            >
              <v-icon :icon="mdiLock" size="x-small" /> {{ job.editingByYou ? 'You' : job.editingBy }}
            </span>
            <span v-else class="text-medium-emphasis">—</span>
          </td>
          <td>
            <span :id="`job-${job.id}-expires`" :class="{'expires-soon font-weight-medium text-warning': expiry(job).soon}">{{ expiry(job).text }}</span>
            <div
              class="text-caption text-medium-emphasis"
              :title="job.fixFrom ? 'The edits are discarded and the job returns to Finished jobs as it was' : 'The draft is deleted with its files'"
            >
              {{ job.fixFrom ? 'then reverted' : 'then deleted' }}
            </div>
            <div
              v-if="job.protectedCount"
              class="text-caption text-medium-emphasis"
              title="A draft with protected files expires 7 days after it was last saved"
            >
              7 days: protected files
            </div>
          </td>
          <td class="text-right">
            <JobActions
              :confirm-to="confirmCells.get(job.id)"
              :counts="countsOf(job.id)"
              :edit-why="editWhy"
              :job="job"
              kind="drafts"
              :staff="staff"
              @confirming="on => setConfirming(job.id, on)"
              @done="done"
              @error="text => error = text"
              @open="reopen"
              @submitted="submitted => emit('submitted', submitted)"
            />
          </td>
        </tr>
        <tr v-show="confirming.has(job.id)" class="job-confirm-row">
          <td :ref="cell => setConfirmCell(job.id, cell as HTMLElement | null)" class="pb-3" colspan="8" />
        </tr>
        <tr v-if="expanded.has(job.id)" class="job-details-row">
          <td colspan="8">
            <JobDetails
              :job="job"
              kind="drafts"
              :rows="docs.get(job.id)"
              :tenant="tenant"
              @preview="() => emit('open', job.id, 'preview')"
            />
          </td>
        </tr>
      </tbody>
    </v-table>
  </div>
</template>

<script setup lang="ts">
import type {PropType} from 'vue'
import {computed, onBeforeUnmount, onMounted, reactive, ref} from 'vue'
import {mdiAlert, mdiChevronRight, mdiLock, mdiWrench} from '@mdi/js'
import type {CheckCounts, Job, Row, TenantInfo} from '@/types'
import JobActions from '@/components/job/JobActions.vue'
import JobDetails from '@/components/job/JobDetails.vue'
import SortableColumnHeader from '@/components/util/SortableColumnHeader.vue'
import {formatTime} from '@/lib/files'
import {accessLabel} from '@/lib/roles'
import {checksColor, checksText} from '@/lib/status'
import {tableState, tableView} from '@/lib/table'
import {api} from '@/api'

/**
 * The Drafts page (design: Drafts, scheduling and the job queue): every draft in the tenant, which anyone can
 * preview. Staff edit any of them, and interns the ones that are open to interns (design: Roles), one person at a time. Checks are re-run against CollectionSpace each time it is shown.
 */
defineProps({
  // Why this user can't change any draft; '' when they can (what an intern may do depends on the draft).
  editWhy: {
    default: '',
    required: false,
    type: String
  },
  // The signed-in user is BMU staff, not an intern (design: Roles).
  staff: {
    required: false,
    type: Boolean
  },
  tenant: {
    required: true,
    type: Object as PropType<TenantInfo>
  }
})
const emit = defineEmits<{
  open: [id: string, mode: 'edit' | 'preview', takeOverSince?: number],
  // A draft was submitted from the list: it is in the job queue now.
  submitted: [job: Job]
}>()

const drafts = ref<Job[]>([])
// Each draft's documents, from its latest check
const docs = reactive(new Map<string, Row[]>())
const expanded = reactive(new Set<string>())
const checks = reactive(new Map<string, CheckCounts | 'checking'>())
// What a job's action just did ("… is now staff only."), until the next one
const message = ref('')
const error = ref('')
// The first answer from the server has arrived: until then the list is loading, not empty.
const isLoaded = ref(false)
const table = tableState()
let timer: ReturnType<typeof setInterval> | undefined

// A job's confirmation (Delete, Take over, Edit, Cancel run) is shown in a full-width row under the job.
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
// A job's action finished: say what it did and read the drafts again. A refused Submit says nothing here (the
// reason is shown as an error); the checks run again, because the server found something this list didn't show.
const done = async (flash: string) => {
  message.value = flash
  const refused = flash ? '' : error.value
  await refresh(!flash)
  error.value = refused || error.value // reading the drafts again cleared it
}
const countsOf = (id: string): CheckCounts | null => {
  const c = checks.get(id)
  return c && c !== 'checking' ? c : null
}

const sorted = computed(() => tableView(drafts.value, table, {
  name: nameOf,
  docs: j => j.rowCount,
  checks: j => {
    const c = countsOf(j.id)
    return c ? -(c.block * 100000 + c.warn) : 1
  },
  saved: j => -(j.lastSavedAt ?? 0),
  editing: j => j.editingBy || '~',
  expires: j => j.expiresAt ?? 0
}, undefined, false).shown)

const toggle = (job: Job) => {
  if (expanded.has(job.id)) {
    expanded.delete(job.id)
  } else {
    expanded.add(job.id)
    if (!docs.has(job.id)) {
      api.job(job.id).then(r => docs.set(job.id, r.rows)).catch(() => undefined)
    }
  }
}

const expandAll = (on: boolean) => {
  if (on) {
    drafts.value.filter(j => !expanded.has(j.id)).forEach(toggle)
  } else {
    expanded.clear()
  }
}

/** Pass on JobActions' open (a take-over carries when the other person started editing). */
const reopen = (id: string, mode: 'edit' | 'preview', since?: number) => {
  if (since === undefined) {
    emit('open', id, mode)
  } else {
    emit('open', id, mode, since)
  }
}

const refresh = async (runChecks = false) => {
  try {
    drafts.value = (await api.jobs(!runChecks)).jobs.filter(j => j.status === 'Draft').sort((a, b) => (b.lastSavedAt ?? 0) - (a.lastSavedAt ?? 0))
    error.value = ''
    isLoaded.value = true
  } catch (e) {
    error.value = (e as Error).message
  }
  if (runChecks) {
    for (const draft of drafts.value) {
      checks.set(draft.id, 'checking')
      api.check(draft.id).then(r => {
        checks.set(draft.id, r.counts)
        docs.set(draft.id, r.rows)
      }).catch(() => checks.delete(draft.id))
    }
  }
}

onMounted(() => {
  refresh(true)
  timer = setInterval(() => refresh(false), 5000)
})
onBeforeUnmount(() => clearInterval(timer))

const expiry = (job: Job) => {
  if (!job.expiresAt) {
    return {text: '—', soon: false}
  }
  const days = Math.ceil((job.expiresAt * 1000 - Date.now()) / 86400000)
  const date = new Date(job.expiresAt * 1000).toLocaleDateString(undefined, {month: 'short', day: 'numeric'})
  return {text: `${date} (${days <= 0 ? 'today' : `in ${days} day${days === 1 ? '' : 's'}`})`, soon: days <= 3}
}
</script>

<style scoped>
.toggle-col {
  width: 40px;
}
.actions-col {
  width: 250px;
}
</style>
