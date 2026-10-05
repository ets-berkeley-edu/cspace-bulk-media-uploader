<template>
  <div>
    <p id="queue-description" class="mb-3 text-body-2 text-medium-emphasis">
      Jobs submitted to run, in the order workers pick them up. Queued jobs start at {{ tenant.name }}’s next run time,
      in this order, one job at a time, so each job waits for the ones above it; running jobs stay first.
      {{ staff ? 'Drag a job, or use its arrows, to change the order.' : '' }}
      Editing a queued job moves it to Drafts until it is submitted again. Checks are re-run against CollectionSpace each time this list is shown.
    </p>
    <QueueSchedule
      v-if="schedule"
      :schedule="schedule"
      :staff="staff"
      :tenant="tenant"
      @changed="scheduleChanged"
      @error="text => error = text"
    />
    <v-alert
      v-if="error"
      id="queue-error"
      class="mb-2"
      density="compact"
      type="error"
      variant="tonal"
    >
      {{ error }}
    </v-alert>
    <v-alert
      v-if="message"
      id="queue-message"
      class="mb-2"
      density="compact"
      role="status"
      type="info"
      variant="tonal"
    >
      {{ message }}
    </v-alert>
    <v-alert
      v-if="plan?.problems.length"
      id="queue-collisions"
      class="mb-2"
      density="compact"
      role="alert"
      type="warning"
      variant="tonal"
    >
      <div id="queue-collisions-summary" class="font-weight-medium">{{ collisionsSummary }}</div>
      <ul class="collision-list">
        <li v-for="problem in plan.problems.slice(0, 5)" :key="`${problem.job}-${problem.n}`">{{ problemText(problem) }}</li>
        <li v-if="plan.problems.length > 5">and {{ plan.problems.length - 5 }} more</li>
      </ul>
      <div v-if="plan.changes">
        <div v-if="!isConfirmingReorder">
          <v-btn
            v-if="staff"
            id="queue-reorder-btn"
            color="warning"
            :disabled="isReordering"
            size="small"
            @click="isConfirmingReorder = true"
          >
            Reorder to avoid failures…
          </v-btn>
          <span v-else id="queue-reorder-why">A staff member can reorder the queue to avoid this.</span>
        </div>
        <div v-else id="queue-reorder-confirm">
          <div>This moves {{ plan.moves.join('; ') }}. Every other job keeps its place among the rest.</div>
          <div class="mt-2">
            <v-btn
              id="queue-reorder-confirm-btn"
              class="mr-2"
              color="warning"
              :disabled="isReordering"
              size="small"
              @click="reorder"
            >
              {{ isReordering ? 'Reordering…' : 'Reorder' }}
            </v-btn>
            <v-btn
              id="queue-reorder-cancel-btn"
              :disabled="isReordering"
              size="small"
              variant="outlined"
              @click="isConfirmingReorder = false"
            >
              Cancel
            </v-btn>
          </div>
        </div>
      </div>
      <div v-if="!plan.changes || plan.remaining.length" id="queue-collisions-remaining" class="mt-1">
        <div>{{ plan.changes ? 'A reorder can’t fix:' : 'Reordering the queue can’t fix this:' }}</div>
        <ul class="collision-list">
          <li v-for="text in plan.remaining" :key="text">{{ text }}</li>
        </ul>
      </div>
    </v-alert>
    <v-alert
      v-if="isSortedView"
      id="queue-sorted-view"
      class="mb-2"
      density="compact"
      type="info"
      variant="tonal"
    >
      Sorted view. The queue still runs in its own order;
      <button
        id="queue-clear-sort-btn"
        class="link-btn"
        type="button"
        @click="table.sort = null"
      >
        clear the sort
      </button>
      to {{ staff ? 'drag or move jobs' : 'see it in run order' }}.
    </v-alert>
    <div v-if="jobs.length" class="mb-1 text-body-2 text-right">
      <button
        id="queue-expand-all-btn"
        class="link-btn"
        type="button"
        @click="() => expandAll(true)"
      >
        Expand all
      </button> ·
      <button
        id="queue-collapse-all-btn"
        class="link-btn"
        type="button"
        @click="() => expandAll(false)"
      >
        Collapse all
      </button>
    </div>
    <v-table id="queue-table" class="border job-list rounded" density="compact">
      <thead>
        <tr>
          <th class="toggle-col" scope="col"><span class="sr-only">Details</span></th>
          <SortableColumnHeader
            id-prefix="queue-"
            label="Order"
            sort-key="order"
            :state="table"
          />
          <SortableColumnHeader
            id-prefix="queue-"
            label="Job"
            sort-key="name"
            :state="table"
          />
          <SortableColumnHeader
            id-prefix="queue-"
            label="Docs"
            sort-key="docs"
            :state="table"
          />
          <SortableColumnHeader
            id-prefix="queue-"
            label="Checks now"
            sort-key="checks"
            :state="table"
          />
          <SortableColumnHeader
            id-prefix="queue-"
            label="Submitted"
            sort-key="scheduled"
            :state="table"
          />
          <SortableColumnHeader
            id-prefix="queue-"
            label="Runs at"
            sort-key="runs"
            :state="table"
          />
          <SortableColumnHeader
            id-prefix="queue-"
            label="Status"
            sort-key="status"
            :state="table"
          />
          <th class="actions-col" scope="col"><span class="sr-only">Actions</span></th>
        </tr>
      </thead>
      <tbody v-if="!isLoaded">
        <tr v-if="!error">
          <td
            id="queue-loading"
            aria-busy="true"
            class="py-5 text-center text-medium-emphasis"
            colspan="9"
          >
            Loading the job queue…
          </td>
        </tr>
      </tbody>
      <tbody v-else-if="!jobs.length">
        <tr>
          <td id="queue-empty" class="py-5 text-center text-medium-emphasis" colspan="9">
            No jobs in the queue. Create one in Create / edit job and submit it.
          </td>
        </tr>
      </tbody>
      <tbody v-for="job in running" :id="`job-${job.id}`" :key="job.id">
        <tr class="job-row" title="Running jobs stay first">
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
          <td class="text-no-wrap">
            <v-progress-circular
              aria-label="Running"
              class="mr-1"
              color="success"
              indeterminate
              role="img"
              size="14"
              title="Running"
              width="2"
            />
            {{ running.indexOf(job) + 1 }}
          </td>
          <td>
            <div :id="`job-${job.id}-name`" class="font-weight-medium">{{ nameOf(job) }}</div>
            <div v-if="runNumber(job) > 1" class="text-caption text-medium-emphasis">{{ runName(job) }}</div>
          </td>
          <td>{{ job.rowCount }}</td>
          <td><span class="text-medium-emphasis">—</span></td>
          <td>
            {{ formatTime(job.queuedAt) }}
            <div class="text-caption text-medium-emphasis">by {{ job.scheduledBy }}</div>
          </td>
          <td :id="`job-${job.id}-runs-at`" class="runs-at">Running</td>
          <td>
            <v-chip :id="`job-${job.id}-status`" color="success" size="small">Running</v-chip>
            <div :id="`job-${job.id}-progress`" class="text-caption text-medium-emphasis">
              {{ job.progress?.done ?? 0 }} done · {{ job.progress?.failed ?? 0 }} failed · {{ toGo(job) }} to go
            </div>
            <div class="run-progress">
              <span class="done" :style="{width: `${percent(job, 'done')}%`}" /><span class="failed" :style="{width: `${percent(job, 'failed')}%`}" />
            </div>
            <div v-if="job.cancelRequested" :id="`job-${job.id}-cancelling`" class="font-weight-medium text-caption text-warning">
              Cancelling after the document in progress…
            </div>
            <CurrentDocument v-else :job="job" />
          </td>
          <td class="text-right">
            <JobActions
              :confirm-to="confirmCells.get(job.id)"
              :edit-why="editWhy"
              :job="job"
              kind="queue"
              :staff="staff"
              :user="user"
              @confirming="on => setConfirming(job.id, on)"
              @done="done"
              @error="text => error = text"
              @open="(id, mode) => emit('open', id, mode)"
            />
          </td>
        </tr>
        <tr v-show="confirming.has(job.id) || pending?.jobId === job.id" class="job-confirm-row">
          <td :ref="cell => setConfirmCell(job.id, cell as HTMLElement | null)" class="pb-3" colspan="9">
            <v-alert
              v-if="pending?.jobId === job.id"
              :id="`job-${job.id}-order-confirm`"
              class="text-left"
              density="compact"
              role="alert"
              type="warning"
              variant="tonal"
            >
              <div>{{ pending.text }}</div>
              <div>If you go ahead, that job is marked “needs fixing” until the order is changed back or the job is edited.</div>
              <div class="mt-2">
                <v-btn
                  :id="`job-${job.id}-order-confirm-btn`"
                  class="mr-2"
                  color="warning"
                  :disabled="pending.busy"
                  size="small"
                  @click="goAhead"
                >
                  {{ pending.label }}
                </v-btn>
                <v-btn
                  :id="`job-${job.id}-order-cancel-btn`"
                  :disabled="pending.busy"
                  size="small"
                  variant="outlined"
                  @click="pending = null"
                >
                  Cancel
                </v-btn>
              </div>
            </v-alert>
          </td>
        </tr>
        <tr v-if="expanded.has(job.id)" class="job-details-row">
          <td colspan="9">
            <JobDetails
              :job="job"
              kind="queue"
              :rows="docs.get(job.id)"
              :tenant="tenant"
              @preview="() => emit('open', job.id, 'preview')"
            />
          </td>
        </tr>
      </tbody>
      <tbody v-for="job in shownQueued" :id="`job-${job.id}`" :key="job.id">
        <tr
          class="job-row"
          :class="{draggable: isMovable, dragging: dragId === job.id, 'drop-before': dropAt?.id === job.id && !dropAt.after, 'drop-after': dropAt?.id === job.id && dropAt.after}"
          :draggable="isMovable"
          :title="isMovable ? 'Drag to change the order' : ''"
          @dragend="dragEnded"
          @dragover="event => onDragOver(event, job)"
          @dragstart="dragId = isMovable ? job.id : null"
          @drop.prevent="onDrop"
        >
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
          <td class="text-no-wrap">
            <v-icon
              v-if="staff"
              aria-hidden="true"
              class="grip"
              :icon="mdiDragVertical"
              size="small"
            />
            <span :id="`job-${job.id}-order`">{{ running.length + queued.indexOf(job) + 1 }}</span>
            <span v-if="staff" class="ml-1 order-btns">
              <v-btn
                :id="`job-${job.id}-move-up-btn`"
                :aria-label="`Move ${job.name} up`"
                density="comfortable"
                :disabled="isSortedView || queued.indexOf(job) === 0"
                :icon="mdiArrowUp"
                size="small"
                variant="text"
                @click="() => move(job, queued.indexOf(job) - 1)"
              />
              <v-btn
                :id="`job-${job.id}-move-down-btn`"
                :aria-label="`Move ${job.name} down`"
                density="comfortable"
                :disabled="isSortedView || queued.indexOf(job) === queued.length - 1"
                :icon="mdiArrowDown"
                size="small"
                variant="text"
                @click="() => move(job, queued.indexOf(job) + 1)"
              />
            </span>
          </td>
          <td>
            <div :id="`job-${job.id}-name`" class="font-weight-medium">{{ nameOf(job) }}</div>
            <div v-if="runNumber(job) > 1" class="text-caption text-medium-emphasis">{{ runName(job) }}</div>
          </td>
          <td>{{ job.rowCount }}</td>
          <td>
            <v-chip
              v-if="checks.get(job.id)"
              :id="`job-${job.id}-checks`"
              :color="checksColor(checks.get(job.id)!)"
              size="small"
            >
              {{ checksText(checks.get(job.id)!) }}
            </v-chip>
            <v-chip v-else :id="`job-${job.id}-checks`" size="small">Checking…</v-chip>
            <div
              v-if="hasChanged(job)"
              :id="`job-${job.id}-changed`"
              class="font-weight-medium text-caption text-warning"
              title="The checks found something different from when the job was submitted"
            >
              Changed since submitted
            </div>
          </td>
          <td>
            {{ formatTime(job.queuedAt) }}
            <div class="text-caption text-medium-emphasis">by {{ job.scheduledBy }}</div>
            <div
              v-if="signIn(job)"
              :id="`job-${job.id}-sign-in`"
              class="text-caption"
              :class="signIn(job)!.soon ? 'font-weight-medium text-warning' : 'text-medium-emphasis'"
              title="If the job hasn't started by then, its saved sign-in is deleted and it moves to Drafts"
            >
              <v-icon v-if="signIn(job)!.soon" :icon="mdiAlert" size="x-small" />
              {{ signIn(job)!.soon ? 'sign-in expires in' : 'sign-in kept' }} ~{{ signIn(job)!.hours }} h
            </div>
          </td>
          <td :id="`job-${job.id}-runs-at`" class="runs-at">
            {{ runsOf(job).text }}
            <div v-if="runsOf(job).sub" class="text-caption text-medium-emphasis">{{ runsOf(job).sub }}</div>
            <div
              v-if="runsOf(job).warn"
              class="font-weight-medium text-caption text-warning"
              :title="`Its saved sign-in expires ${job.credentialExpires ? absLabel(job.credentialExpires) : ''}; if the job hasn’t started by then, it moves to Drafts`"
            >
              <v-icon :icon="mdiAlert" size="x-small" /> sign-in expires before its run time
            </div>
            <template v-if="staff">
              <template v-if="runAtEdit?.id === job.id">
                <div class="align-center d-flex flex-wrap mt-1 run-at-edit">
                  <input
                    :id="`job-${job.id}-run-at`"
                    v-model="runAtEdit.value"
                    :aria-label="`Run time for ${nameOf(job)} (Pacific time)`"
                    class="native-input"
                    :max="ptInputValue(untilOf(job))"
                    :min="nowInput()"
                    type="datetime-local"
                  >
                  <v-btn
                    :id="`job-${job.id}-run-at-save-btn`"
                    color="primary"
                    size="small"
                    @click="() => saveRunAt(job)"
                  >
                    Save
                  </v-btn>
                  <v-btn
                    :id="`job-${job.id}-run-at-clear-btn`"
                    size="small"
                    title="Return the job to the tenant’s schedule"
                    variant="outlined"
                    @click="() => clearRunAt(job)"
                  >
                    Clear
                  </v-btn>
                  <v-btn
                    :id="`job-${job.id}-run-at-cancel-btn`"
                    size="small"
                    variant="outlined"
                    @click="runAtEdit = null"
                  >
                    Cancel
                  </v-btn>
                </div>
                <div class="text-caption text-medium-emphasis">Pacific time; no later than {{ absLabel(untilOf(job)) }}, when its sign-in expires.</div>
                <v-alert
                  v-if="runAtEdit.error"
                  :id="`job-${job.id}-run-at-error`"
                  class="mt-1"
                  density="compact"
                  type="error"
                  variant="tonal"
                >
                  {{ runAtEdit.error }}
                </v-alert>
              </template>
              <div v-else class="run-controls text-caption">
                <button
                  v-if="job.runNow"
                  :id="`job-${job.id}-undo-run-now-btn`"
                  class="link-btn"
                  title="Let the job wait for its turn again"
                  type="button"
                  @click="() => runNow(job, false)"
                >
                  Undo Run now
                </button>
                <button
                  v-else
                  :id="`job-${job.id}-run-now-btn`"
                  class="link-btn"
                  title="Start this job as soon as no job is running, ahead of the queue order, even outside the run times (but not while the queue is paused)"
                  type="button"
                  @click="() => runNow(job, true)"
                >
                  Run now
                </button>
                <button
                  :id="`job-${job.id}-set-run-time-btn`"
                  class="link-btn"
                  title="Give this job its own run time, between now and when its sign-in expires"
                  type="button"
                  @click="() => openRunAt(job)"
                >
                  Set run time…
                </button>
                <button
                  v-if="job.held"
                  :id="`job-${job.id}-release-btn`"
                  class="link-btn"
                  title="Let the job run again at its turn"
                  type="button"
                  @click="() => hold(job, false)"
                >
                  Release
                </button>
                <button
                  v-else
                  :id="`job-${job.id}-hold-btn`"
                  class="link-btn"
                  title="Skip this job until it is released; its sign-in clock keeps running"
                  type="button"
                  @click="() => hold(job, true)"
                >
                  Hold
                </button>
              </div>
            </template>
          </td>
          <td><v-chip :id="`job-${job.id}-status`" color="info" size="small">Queued</v-chip></td>
          <td class="text-right">
            <JobActions
              :confirm-to="confirmCells.get(job.id)"
              :edit-why="editWhy"
              :job="job"
              kind="queue"
              :staff="staff"
              :user="user"
              @confirming="on => setConfirming(job.id, on)"
              @done="done"
              @error="text => error = text"
              @open="(id, mode) => emit('open', id, mode)"
            />
          </td>
        </tr>
        <tr v-show="confirming.has(job.id) || pending?.jobId === job.id" class="job-confirm-row">
          <td :ref="cell => setConfirmCell(job.id, cell as HTMLElement | null)" class="pb-3" colspan="9">
            <v-alert
              v-if="pending?.jobId === job.id"
              :id="`job-${job.id}-order-confirm`"
              class="text-left"
              density="compact"
              role="alert"
              type="warning"
              variant="tonal"
            >
              <div>{{ pending.text }}</div>
              <div>If you go ahead, that job is marked “needs fixing” until the order is changed back or the job is edited.</div>
              <div class="mt-2">
                <v-btn
                  :id="`job-${job.id}-order-confirm-btn`"
                  class="mr-2"
                  color="warning"
                  :disabled="pending.busy"
                  size="small"
                  @click="goAhead"
                >
                  {{ pending.label }}
                </v-btn>
                <v-btn
                  :id="`job-${job.id}-order-cancel-btn`"
                  :disabled="pending.busy"
                  size="small"
                  variant="outlined"
                  @click="pending = null"
                >
                  Cancel
                </v-btn>
              </div>
            </v-alert>
          </td>
        </tr>
        <tr v-if="expanded.has(job.id)" class="job-details-row">
          <td colspan="9">
            <JobDetails
              :job="job"
              kind="queue"
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
import {mdiAlert, mdiArrowDown, mdiArrowUp, mdiChevronRight, mdiDragVertical} from '@mdi/js'
import type {CheckCounts, Job, QueuePlan, QueueProblem, Row, Schedule, TenantInfo} from '@/types'
import CurrentDocument from '@/components/job/CurrentDocument.vue'
import JobActions from '@/components/job/JobActions.vue'
import JobDetails from '@/components/job/JobDetails.vue'
import QueueSchedule from '@/components/job/QueueSchedule.vue'
import SortableColumnHeader from '@/components/util/SortableColumnHeader.vue'
import {formatTime} from '@/lib/files'
import {absLabel, parsePtInput, ptInputValue, runsAt} from '@/lib/schedule'
import {checksColor, checksText, runName, runNumber} from '@/lib/status'
import {tableState, tableView} from '@/lib/table'
import {ApiError, api} from '@/api'

/**
 * The Job queue page (design: The job queue; Job scheduling): running jobs first, then queued jobs in the order
 * workers take them. Queued jobs start at the tenant's run times, one at a time. Everyone can preview a job. Only staff
 * reorder the queue (drag, or the arrows), set each job's Run now, own run time or hold, edit a job (back to Drafts),
 * delete it, and cancel a run (design: Roles).
 */
const props = defineProps({
  // Why this user can't change the jobs of this list (an intern, outside Drafts; design: Roles); '' when they can.
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
  },
  user: {
    default: undefined,
    required: false,
    type: String
  }
})
const emit = defineEmits<{open: [id: string, mode: 'edit' | 'preview', takeOverSince?: number]}>()

const jobs = ref<Job[]>([])
// The first answer from the server has arrived: until then the list is loading, not empty.
const isLoaded = ref(false)
const schedule = ref<Schedule | null>(null)
const docs = reactive(new Map<string, Row[]>())
const expanded = reactive(new Set<string>())
// The progress an expanded running job's documents were last read at
const runSeen = new Map<string, string>()
// Design (Jobs that collide in the queue): the documents that would fail in this order, and how a reorder avoids it
const plan = ref<QueuePlan | null>(null)
const isConfirmingReorder = ref(false)
const isReordering = ref(false)
// A staff member's change that would make a document fail, waiting for "go ahead" under the job it was made on
const pending = ref<{jobId: string, text: string, label: string, done: string, busy: boolean, run: (confirm: boolean) => Promise<unknown>} | null>(null)
// The order and the settings that decide it, as last seen: when someone else changes them, the checks are run again
let orderSeen = ''
const checks = reactive(new Map<string, CheckCounts>())
const error = ref('')
const message = ref('')
const dragId = ref<string | null>(null)
const dropAt = ref<{id: string, after: boolean} | null>(null)
const runAtEdit = ref<{id: string, value: string, error: string} | null>(null)
// Sorting only changes the view: jobs still run in queue order, and moving is off until the sort is cleared.
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
const quoted = (job: Job) => `“${nameOf(job)}”`

const running = computed(() => jobs.value.filter(j => j.status === 'Running'))
const queued = computed(() => jobs.value.filter(j => j.status === 'Queued')
  .sort((a, b) => (a.queuePos ?? 0) - (b.queuePos ?? 0) || (a.queuedAt ?? 0) - (b.queuedAt ?? 0)))
// Sorted by Order ascending is the queue order itself, so it counts as not sorted: jobs can still be moved.
const isSortedView = computed(() => !!table.sort && !(table.sort === 'order' && table.dir === 1))
const isMovable = computed(() => props.staff && !isSortedView.value)
const runsOf = (job: Job) => runsAt(job, running.value.length > 0)
/** The Status column's order: among queued jobs, those waiting their turn, then those waiting for the paused queue
 *  to be resumed, then held ones, the same order as Runs at. Ties keep queue order. Running jobs are always first. */
const statusRank = (job: Job) => (job.status === 'Running' ? 0 : job.held || job.plan?.kind === 'held' ? 3 : job.plan?.kind === 'paused' ? 2 : 1)
const shownQueued = computed(() => tableView(queued.value, table, {
  order: j => queued.value.indexOf(j),
  name: nameOf,
  docs: j => j.rowCount,
  checks: j => {
    const c = checks.get(j.id)
    return c ? -(c.block * 100000 + c.warn) : 1
  },
  scheduled: j => j.queuedAt ?? 0,
  runs: j => runsOf(j).key,
  status: statusRank
}, undefined, false).shown)

const toggle = (job: Job) => {
  if (expanded.has(job.id)) {
    expanded.delete(job.id)
    runSeen.delete(job.id)
  } else {
    expanded.add(job.id)
    if (!docs.has(job.id)) {
      api.job(job.id).then(r => docs.set(job.id, r.rows)).catch(() => undefined)
    }
  }
}

const expandAll = (on: boolean) => {
  if (on) {
    jobs.value.filter(j => !expanded.has(j.id)).forEach(toggle)
  } else {
    expanded.clear()
  }
}

const refresh = async (runChecks = false) => {
  try {
    const [r, s] = await Promise.all([api.jobs(!runChecks), api.getSchedule(!runChecks)])
    jobs.value = r.jobs.filter(j => j.status === 'Running' || j.status === 'Queued')
    schedule.value = s
    error.value = ''
    const order = jobs.value.map(j => `${j.id}:${j.status}:${j.queuePos}:${!!j.runNow}:${j.runAt ?? ''}:${!!j.held}`).join('|')
    // Someone changed the order (or a job joined, left or started): what would fail may have changed with it
    runChecks = runChecks || (isLoaded.value && order !== orderSeen)
    orderSeen = order
    isLoaded.value = true
  } catch (e) {
    error.value = (e as Error).message
  }
  // An expanded running job shows each document's run state: read its documents again whenever its progress moved.
  for (const job of running.value) {
    const at = `${job.progress?.done}/${job.progress?.failed}/${job.currentFile}/${job.currentStep}`
    if (expanded.has(job.id) && runSeen.get(job.id) !== at) {
      runSeen.set(job.id, at)
      api.job(job.id, true).then(r => docs.set(job.id, r.rows)).catch(() => runSeen.delete(job.id))
    }
  }
  if (runChecks) {
    // Design: checks are re-run against CollectionSpace each time the queue is shown, and when its order changes.
    for (const job of queued.value) {
      api.check(job.id).then(r => {
        checks.set(job.id, r.counts)
        docs.set(job.id, r.rows)
      }).catch(() => undefined)
    }
    api.queueCollisions(true).then(p => {
      plan.value = Array.isArray(p?.problems) ? p : null
      if (!plan.value?.changes) {
        isConfirmingReorder.value = false
      }
    }).catch(() => undefined)
  }
}

onMounted(() => {
  refresh(true)
  timer = setInterval(() => refresh(false), 2000)
})
onBeforeUnmount(() => clearInterval(timer))

/**
 * A staff member's change to the queue. The server refuses one that would make a document fail (409 would_fail) until it
 * is confirmed: the question opens under the job, and goAhead sends the change again, confirmed. Afterwards the
 * checks are run again, so a job that would now fail is marked at once.
 */
const change = async (job: Job, run: (confirm: boolean) => Promise<unknown>, done: string, label: string, confirm = false) => {
  try {
    await run(confirm)
    pending.value = null
    await refresh(true)
    message.value = done
    error.value = ''
    return true
  } catch (e) {
    const detail = e instanceof ApiError ? e.detail as {code?: string} | null : null
    if (!confirm && detail?.code === 'would_fail') {
      pending.value = {jobId: job.id, text: (e as Error).message, label, done, busy: false, run}
      error.value = ''
    } else {
      pending.value = null
      error.value = (e as Error).message
    }
    return false
  }
}

const goAhead = async () => {
  const asked = pending.value
  const job = jobs.value.find(j => j.id === asked?.jobId)
  if (asked && job) {
    asked.busy = true
    await change(job, asked.run, asked.done, asked.label, true)
  }
}

/** A job's action finished (deleted, cancelled): say so and show the queue as it is now. */
const done = async (text: string) => {
  message.value = text
  error.value = ''
  await refresh()
}

const scheduleChanged = async (s: Schedule, text: string) => {
  schedule.value = s
  message.value = text
  error.value = ''
  await refresh()
}

const move = (job: Job, to: number) => change(
  job,
  confirm => api.moveJob(job.id, Math.max(0, to), confirm),
  `Moved ${quoted(job)} to position ${running.value.length + Math.max(0, to) + 1}.`,
  'Move anyway'
)

// ---- per-job run controls (staff) ----
const runNow = (job: Job, on: boolean) => change(
  job,
  confirm => api.runNow(job.id, on, confirm),
  on ? `${quoted(job)} ${schedule.value?.paused ? 'runs next once the queue is resumed.' : 'runs next, as soon as no job is running.'}` : `${quoted(job)} waits for its turn again.`,
  on ? 'Run now anyway' : 'Undo Run now anyway'
)
const hold = (job: Job, on: boolean) => change(
  job,
  confirm => api.hold(job.id, on, confirm),
  on ? `${quoted(job)} is held and will be skipped until it is released.` : `${quoted(job)} was released.`,
  on ? 'Hold anyway' : 'Release anyway'
)
const nowInput = () => ptInputValue(Date.now() / 1000)
const untilOf = (job: Job) => job.credentialExpires ?? Date.now() / 1000 + 72 * 3600

const openRunAt = (job: Job) => {
  runAtEdit.value = {id: job.id, value: job.runAt ? ptInputValue(job.runAt) : '', error: ''}
}

const saveRunAt = async (job: Job) => {
  const edit = runAtEdit.value
  if (!edit) {
    return
  }
  const at = parsePtInput(edit.value)
  if (at === null || at === undefined) {
    edit.error = 'Choose a date and time, or use Clear to return the job to the schedule.'
    return
  }
  const text = `${quoted(job)} runs at ${absLabel(at)} (Pacific time)${schedule.value?.paused ? ', if the queue has been resumed by then' : ''}.`
  const before = error.value
  if (await change(job, confirm => api.runAt(job.id, at, confirm), text, 'Set run time anyway') || pending.value) {
    runAtEdit.value = null
  } else {
    // Refused for another reason (a time in the past, after the sign-in expires): shown beside the field
    edit.error = error.value
    error.value = before
  }
}

const clearRunAt = async (job: Job) => {
  runAtEdit.value = null
  if (job.runAt) {
    await change(job, confirm => api.runAt(job.id, null, confirm), `${quoted(job)} follows the schedule again.`, 'Clear run time anyway')
  }
}

// ---- drag and drop among the queued jobs (staff) ----
const onDragOver = (event: DragEvent, job: Job) => {
  if (!dragId.value || job.status !== 'Queued' || !isMovable.value) {
    return
  }
  event.preventDefault()
  const box = (event.currentTarget as HTMLElement).getBoundingClientRect()
  dropAt.value = {id: job.id, after: event.clientY > box.top + box.height / 2}
}

const dragEnded = () => {
  dragId.value = null
  dropAt.value = null
}

const onDrop = () => {
  const from = queued.value.findIndex(j => j.id === dragId.value)
  const target = queued.value.findIndex(j => j.id === dropAt.value?.id)
  if (from >= 0 && target >= 0) {
    let to = target + (dropAt.value!.after ? 1 : 0)
    if (from < to) {
      to--
    }
    if (to !== from) {
      move(queued.value[from], to)
    }
  }
  dragEnded()
}

// ---- Reorder to avoid failures (design: Jobs that collide in the queue) ----
const collisionsSummary = computed(() => {
  const n = plan.value?.problems.length ?? 0
  return `${n} document${n === 1 ? '' : 's'} would fail in this order, because a job that runs first creates ${n === 1 ? 'its' : 'their'} object:`
})
const problemText = (p: QueueProblem) => `“${p.file}” in “${p.name}”: “${p.otherName}” would create object ${p.object} first`

const reorder = async () => {
  isReordering.value = true
  try {
    plan.value = await api.reorderToAvoidFailures()
    isConfirmingReorder.value = false
    await refresh(true)
    message.value = 'Reordered the queue to avoid failures.'
    error.value = ''
  } catch (e) {
    error.value = (e as Error).message
    await refresh(true)
  } finally {
    isReordering.value = false
  }
}

const signIn = (job: Job) => {
  if (!job.credentialExpires) {
    return null
  }
  const hours = Math.max(0, Math.round((job.credentialExpires * 1000 - Date.now()) / 3600000))
  return {hours, soon: hours <= 3}
}

const hasChanged = (job: Job) => {
  const now = checks.get(job.id)
  const then = job.checksAtSchedule
  return !!now && !!then && (now.block !== then.block || now.warn !== then.warn)
}

const toGo = (job: Job) => (job.progress?.total ?? 0) - (job.progress?.done ?? 0) - (job.progress?.failed ?? 0)
const percent = (job: Job, key: 'done' | 'failed') => (job.progress?.total ? (100 * (job.progress[key] || 0)) / job.progress.total : 0)
</script>

<style scoped>
.collision-list {
  padding-left: 18px;
}
.toggle-col {
  width: 40px;
}
.actions-col {
  width: 230px;
}
.job-row.draggable {
  cursor: grab;
}
.job-row.dragging {
  opacity: 0.5;
}
.job-row.drop-before > td {
  box-shadow: inset 0 2px 0 rgb(var(--v-theme-primary));
}
.job-row.drop-after > td {
  box-shadow: inset 0 -2px 0 rgb(var(--v-theme-primary));
}
.grip {
  opacity: var(--v-medium-emphasis-opacity);
}
.order-btns {
  white-space: nowrap;
}
.run-progress {
  background-color: rgba(var(--v-theme-on-surface), 0.12);
  border-radius: 2px;
  display: flex;
  height: 4px;
  margin: 2px 0;
  max-width: 180px;
  overflow: hidden;
}
.run-progress .done {
  background-color: rgb(var(--v-theme-success));
}
.run-progress .failed {
  background-color: rgb(var(--v-theme-error));
}
.run-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 10px;
  margin-top: 2px;
}
.run-at-edit {
  gap: 4px;
}
</style>
