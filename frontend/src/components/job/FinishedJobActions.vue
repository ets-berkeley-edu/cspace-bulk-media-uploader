<template>
  <div>
    <Teleport :disabled="!confirmTo" :to="confirmTo">
      <DeleteJobConfirm
        v-if="isConfirming"
        :busy="deleting"
        :created="created"
        :job="job"
        @cancel="isConfirming = false"
        @confirm="() => emit('delete')"
      />
    </Teleport>
    <div v-if="!isConfirming || confirmTo" :id="`job-${job.id}-actions`" class="actions align-center d-flex flex-wrap justify-end">
      <v-btn
        v-if="!inResults"
        :id="`job-${job.id}-view-results-btn`"
        :disabled="isConfirming"
        size="small"
        variant="outlined"
        @click="() => emit('view')"
      >
        View results
      </v-btn>
      <template v-if="job.status !== 'Completed'">
        <span :title="fixTitle">
          <v-btn
            :id="`job-${job.id}-fix-btn`"
            :color="inResults ? 'primary' : undefined"
            :disabled="busy || !!editWhy || isConfirming"
            size="small"
            :title="fixTitle"
            :variant="inResults ? 'elevated' : 'outlined'"
            @click="() => emit('fix')"
          >
            {{ fixLabel }}
          </v-btn>
        </span>
        <span :title="editWhy || 'Delete job'">
          <v-btn
            :id="`job-${job.id}-delete-btn`"
            aria-label="Delete"
            class="job-del"
            density="comfortable"
            :disabled="!!editWhy || isConfirming"
            :icon="mdiTrashCanOutline"
            size="small"
            :title="editWhy || 'Delete job'"
            variant="text"
            @click="askDelete"
          />
        </span>
      </template>
      <span v-else :id="`job-${job.id}-removed-on`" class="text-caption text-medium-emphasis">Removed {{ removedOn }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import type {PropType} from 'vue'
import {computed, ref, watch} from 'vue'
import {mdiTrashCanOutline} from '@mdi/js'
import type {Created, Job} from '@/types'
import DeleteJobConfirm from '@/components/job/DeleteJobConfirm.vue'

/**
 * A finished job's actions, in the list and in its results (design: Finished jobs and error messages): View
 * results; Fix and reschedule, or Reschedule when every failure only needs another run; and Delete, after saying
 * what stays in CollectionSpace. A completed job has nothing to fix: it says when it is removed.
 */
const props = defineProps({
  // The job is being moved to Drafts.
  busy: {
    required: false,
    type: Boolean
  },
  // Where the delete confirmation is shown: the list gives the full-width cell under the job's row.
  confirmTo: {
    default: undefined,
    required: false,
    type: Object as PropType<HTMLElement>
  },
  // What the job's runs created: undefined while it loads.
  created: {
    default: undefined,
    required: false,
    type: Object as PropType<Created | null>
  },
  // The deletion was sent and the answer hasn't come back yet.
  deleting: {
    required: false,
    type: Boolean
  },
  // Why this user can't create or edit jobs (design: Permissions in the UI); '' when they can.
  editWhy: {
    default: '',
    required: false,
    type: String
  },
  fixLabel: {
    required: true,
    type: String
  },
  // In the job's results: no View results, and Fix is the main button.
  inResults: {
    required: false,
    type: Boolean
  },
  job: {
    required: true,
    type: Object as PropType<Job>
  }
})
const emit = defineEmits<{
  // The delete confirmation opened: the list loads what the job created.
  'ask-delete': [],
  confirming: [on: boolean],
  delete: [],
  fix: [],
  view: []
}>()

const isConfirming = ref(false)
watch(isConfirming, on => emit('confirming', on))

const fixTitle = computed(() => {
  if (props.editWhy) {
    return props.editWhy
  }
  return props.fixLabel === 'Reschedule'
    ? 'Nothing needs changing: every failure only needs another run. Opens the job in Drafts so you can submit it again.'
    : 'Opens the job in Drafts to fix the documents that need it, then submit it again.'
})
const removedOn = computed(() => (props.job.expiresAt
  ? new Date(props.job.expiresAt * 1000).toLocaleDateString(undefined, {month: 'short', day: 'numeric'}) : 'in 30 days'))

const askDelete = () => {
  isConfirming.value = true
  emit('ask-delete')
}
</script>

<style scoped>
.actions {
  gap: 6px;
}
</style>
