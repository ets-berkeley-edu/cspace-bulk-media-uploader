<template>
  <div>
    <Teleport :disabled="!confirmTo" :to="confirmTo">
      <DeleteJobConfirm
        v-if="confirming === 'delete'"
        :busy="isBusy"
        :created="created"
        :job="job"
        @cancel="confirming = null"
        @confirm="deleteJob"
      />
      <v-alert
        v-else-if="confirming"
        :id="`job-${job.id}-${confirming}-confirm`"
        class="text-left"
        density="compact"
        role="alert"
        :type="confirming === 'submit' ? 'info' : 'warning'"
        variant="tonal"
      >
        <div v-if="confirming === 'takeover'">
          {{ job.editingBy }} has been editing this draft since {{ formatTime(job.editingSince) }}. If you take over, their editing ends
          and their page becomes read-only; everything they changed so far is already saved.
        </div>
        <div v-else-if="confirming === 'edit'">
          Editing takes this job out of the queue and deletes its saved sign-in. It goes to the end of the queue when it’s
          submitted again, even if nothing changes.
        </div>
        <div v-else-if="confirming === 'submit'">{{ submitText }}</div>
        <div v-else-if="confirming === 'handover'">{{ REVIEW_CONFIRM }}</div>
        <div v-else-if="confirming === 'todrafts'">
          Moving takes this job out of the queue and deletes its saved sign-in. It stays in Drafts until someone submits it
          again, and then goes to the end of the queue.
        </div>
        <div v-else>
          Stop this run? The worker finishes the document it’s on, then stops; documents it hasn’t reached stay not started,
          and nothing already created is undone.
        </div>
        <div class="mt-2">
          <v-btn
            :id="`job-${job.id}-${confirming}-confirm-btn`"
            class="mr-2"
            :color="confirming === 'submit' ? 'primary' : 'warning'"
            :disabled="isBusy"
            size="small"
            @click="confirmed"
          >
            {{ CONFIRM_LABEL[confirming] }}
          </v-btn>
          <v-btn
            :id="`job-${job.id}-${confirming}-cancel-btn`"
            :disabled="isBusy"
            size="small"
            variant="outlined"
            @click="confirming = null"
          >
            {{ confirming === 'cancel' ? 'Keep running' : 'Cancel' }}
          </v-btn>
        </div>
      </v-alert>
    </Teleport>
    <div v-if="!confirming || confirmTo" :id="`job-${job.id}-actions`" class="actions align-center d-flex flex-wrap justify-end">
      <v-btn
        v-if="!inPreview"
        :id="`job-${job.id}-preview-btn`"
        :disabled="!!confirming"
        size="small"
        variant="outlined"
        @click="() => emit('open', job.id, 'preview')"
      >
        Preview
      </v-btn>
      <template v-if="kind === 'drafts'">
        <span v-if="lockedByOther" :title="noTakeOver || `${job.editingBy} is editing this draft`">
          <v-btn
            :id="`job-${job.id}-take-over-btn`"
            :disabled="!!noTakeOver || !!confirming"
            size="small"
            :title="noTakeOver || `${job.editingBy} is editing this draft`"
            variant="outlined"
            @click="confirming = 'takeover'"
          >
            Take over…
          </v-btn>
        </span>
        <span v-else :title="noEdit">
          <v-btn
            :id="`job-${job.id}-edit-btn`"
            :disabled="!!noEdit || !!confirming"
            size="small"
            :title="noEdit"
            variant="outlined"
            @click="() => emit('open', job.id, 'edit')"
          >
            {{ job.editingByYou ? 'Continue editing' : 'Edit' }}
          </v-btn>
        </span>
        <!-- Staff: submit a draft without opening it, and say whether interns may edit it (design: Roles) -->
        <template v-if="staff">
          <span :title="submitTitle">
            <v-btn
              :id="`job-${job.id}-submit-btn`"
              :disabled="!!noSubmit || !!confirming"
              size="small"
              :title="submitTitle"
              variant="outlined"
              @click="confirming = 'submit'"
            >
              Submit…
            </v-btn>
          </span>
          <v-btn
            :id="`job-${job.id}-access-btn`"
            :disabled="isBusy || !!confirming"
            size="small"
            :title="accessTitle"
            variant="outlined"
            @click="toggleAccess"
          >
            {{ accessAction }}
          </v-btn>
        </template>
        <!-- An intern: send a finished draft to staff for review (the ids date from "Hand over to staff") -->
        <span v-else-if="job.internOpen" :title="handOverTitle">
          <v-btn
            :id="`job-${job.id}-hand-over-btn`"
            :disabled="!!noReview || !!confirming"
            size="small"
            :title="handOverTitle"
            variant="outlined"
            @click="confirming = 'handover'"
          >
            Submit for review…
          </v-btn>
        </span>
      </template>
      <span v-else-if="isRunning" :title="noCancel || 'Stop after the document in progress'">
        <v-btn
          :id="`job-${job.id}-cancel-run-btn`"
          :disabled="!!job.cancelRequested || !!noCancel || !!confirming"
          size="small"
          :title="noCancel || 'Stop after the document in progress'"
          variant="outlined"
          @click="confirming = 'cancel'"
        >
          Cancel run
        </v-btn>
      </span>
      <span v-else :title="noEdit">
        <v-btn
          :id="`job-${job.id}-edit-btn`"
          :disabled="!!noEdit || !!confirming"
          size="small"
          :title="noEdit"
          variant="outlined"
          @click="confirming = 'edit'"
        >
          Edit
        </v-btn>
      </span>
      <span v-if="kind === 'queue' && !isRunning" :title="noEdit || 'Take it out of the queue, without opening it'">
        <v-btn
          :id="`job-${job.id}-to-drafts-btn`"
          :disabled="!!noEdit || !!confirming"
          size="small"
          :title="noEdit || 'Take it out of the queue, without opening it'"
          variant="outlined"
          @click="confirming = 'todrafts'"
        >
          Move to Drafts…
        </v-btn>
      </span>
      <span :title="deleteTitle">
        <v-btn
          :id="`job-${job.id}-delete-btn`"
          aria-label="Delete"
          class="job-del"
          density="comfortable"
          :disabled="!!deleteWhy || !!confirming"
          :icon="mdiTrashCanOutline"
          size="small"
          :title="deleteTitle"
          variant="text"
          @click="askDelete"
        />
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import type {PropType} from 'vue'
import {computed, ref, watch} from 'vue'
import {mdiTrashCanOutline} from '@mdi/js'
import type {CheckCounts, Created, Job} from '@/types'
import DeleteJobConfirm from '@/components/job/DeleteJobConfirm.vue'
import {formatTime} from '@/lib/files'
import {REVIEW_CONFIRM, draftBlocked, draftDeleteBlocked, listSubmitBlocked, reviewBlocked, submitConfirmText, takeOverBlocked} from '@/lib/roles'
import {NO_CANCEL_WHY, canCancelRun} from '@/lib/schedule'
import {api} from '@/api'

/**
 * A job's actions in Drafts and Job queue, in the list and in the job's preview (design: Drafts, scheduling and
 * the job queue). Drafts: Preview, Edit (Continue editing), or Take over… after a warning when someone else is
 * editing, and Delete. Job queue: Preview, Edit (after a warning: it leaves the queue) and Delete for a queued
 * job; Cancel run (after a warning) for a running one. The preview shows the same actions without Preview.
 */
const props = defineProps({
  // Where a confirmation is shown: a list gives the full-width cell under the job's row. Without it, in place of the buttons.
  confirmTo: {
    default: undefined,
    required: false,
    type: Object as PropType<HTMLElement>
  },
  // A draft's latest checks, for Submit: undefined while they are running.
  counts: {
    default: undefined,
    required: false,
    type: Object as PropType<CheckCounts | null>
  },
  // Why this user can't change the jobs of this list at all (an intern, in the Job queue); '' when they can.
  editWhy: {
    default: '',
    required: false,
    type: String
  },
  inPreview: {
    required: false,
    type: Boolean
  },
  job: {
    required: true,
    type: Object as PropType<Job>
  },
  kind: {
    required: true,
    type: String as PropType<'drafts' | 'queue'>
  },
  // The signed-in user is BMU staff, not an intern: what an intern may do depends on the draft (design: Roles).
  staff: {
    required: false,
    type: Boolean
  },
  user: {
    default: undefined,
    required: false,
    type: String
  }
})
const emit = defineEmits<{
  open: [id: string, mode: 'edit' | 'preview', takeOverSince?: number],
  // A confirmation opened or closed.
  confirming: [on: boolean],
  // The job changed (deleted, cancelled): the list refreshes.
  done: [flash: string],
  error: [message: string],
  // A draft was submitted from here: it is in the job queue now.
  submitted: [job: Job]
}>()

type Confirming = 'delete' | 'takeover' | 'edit' | 'cancel' | 'submit' | 'handover' | 'todrafts'
const CONFIRM_LABEL: Record<Confirming, string> = {delete: 'Delete', takeover: 'Take over and edit', edit: 'Edit anyway', cancel: 'Cancel run',
                                                   submit: 'Submit job', handover: 'Submit for review', todrafts: 'Move to Drafts'}

const confirming = ref<Confirming | null>(null)
// What the job's runs created, for the delete confirmation: undefined while it loads, null if it never ran.
const created = ref<Created | null | undefined>(undefined)
const isBusy = ref(false)
watch(confirming, now => emit('confirming', !!now))
const isRunning = computed(() => props.job.status === 'Running')
const lockedByOther = computed(() => props.job.status === 'Draft' && !!props.job.editingBy && !props.job.editingByYou)
const isDraft = computed(() => props.kind === 'drafts')
const noEdit = computed(() => props.editWhy || (isDraft.value ? draftBlocked(props.job, props.staff) : ''))
const noTakeOver = computed(() => props.editWhy || takeOverBlocked(props.job, props.staff))
const noCancel = computed(() => (canCancelRun({staff: props.staff}) ? '' : NO_CANCEL_WHY))
const deleteWhy = computed(() => {
  if (props.kind === 'queue' && isRunning.value) {
    return 'A running job can\'t be deleted'
  }
  return noEdit.value || (isDraft.value ? draftDeleteBlocked(props.job, props.staff) : '')
    || (lockedByOther.value ? `${props.job.editingBy} is editing this draft` : '')
})
const deleteTitle = computed(() => deleteWhy.value || 'Delete job')
const jobName = computed(() => `“${props.job.name || 'Untitled job'}”`)
// Submit from the list (staff): only a draft whose checks found nothing to fix; the server checks it all again
const noSubmit = computed(() => listSubmitBlocked(props.job, props.counts))
const submitTitle = computed(() => noSubmit.value || 'Check the whole job again, then add it to the job queue, without opening it')
const submitText = computed(() => submitConfirmText(props.job, props.counts))
const accessAction = computed(() => (props.job.internOpen ? 'Make staff only' : 'Open to interns'))
const accessTitle = computed(() => (props.job.internOpen ? 'Interns can edit this draft now. Make it staff only.' : 'Only staff can edit this draft now. Let interns edit it too.'))
const noReview = computed(() => reviewBlocked(props.job, props.counts))
const handOverTitle = computed(() => noReview.value || 'Send this draft to staff for review: it becomes staff only, and a staff member submits it')

const askDelete = () => {
  confirming.value = 'delete'
  created.value = undefined
  if (!props.job.run) {
    created.value = null
  } else {
    api.job(props.job.id).then(r => {
      created.value = r.created
    }).catch(e => emit('error', (e as Error).message))
  }
}

const act = async (fn: () => Promise<unknown>, flash = '') => {
  isBusy.value = true
  try {
    await fn()
    confirming.value = null
    emit('done', flash)
    return true
  } catch (e) {
    emit('error', (e as Error).message)
    return false
  } finally {
    isBusy.value = false
  }
}

const toggleAccess = () => act(
  () => api.internAccess(props.job.id, !props.job.internOpen),
  props.job.internOpen ? `${jobName.value} is now staff only.` : `${jobName.value} is now open to interns.`
)

const submit = async () => {
  isBusy.value = true
  try {
    const job = await api.schedule(props.job.id)
    confirming.value = null
    emit('submitted', job)
  } catch (e) {
    confirming.value = null
    emit('error', (e as Error).message)
    emit('done', '') // the list reads the draft again: its checks may have changed
  } finally {
    isBusy.value = false
  }
}

const deleteJob = () => act(() => api.deleteJob(props.job.id), props.kind === 'queue' ? 'Deleted the job.' : '')

const confirmed = async () => {
  if (confirming.value === 'takeover') {
    emit('open', props.job.id, 'edit', props.job.editingSince)
  } else if (confirming.value === 'edit') {
    if (await act(() => api.editQueued(props.job.id))) {
      emit('open', props.job.id, 'edit')
    }
  } else if (confirming.value === 'cancel') {
    await act(() => api.cancelRun(props.job.id))
  } else if (confirming.value === 'submit') {
    await submit()
  } else if (confirming.value === 'handover') {
    await act(() => api.sendForReview(props.job.id), `${jobName.value} was sent to staff for review.`)
  } else if (confirming.value === 'todrafts') {
    await act(() => api.toDrafts(props.job.id), `Moved ${jobName.value} to Drafts.`)
  }
}
</script>

<style scoped>
.actions {
  gap: 6px;
}
</style>
