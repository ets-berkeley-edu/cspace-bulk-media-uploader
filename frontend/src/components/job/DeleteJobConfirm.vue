<template>
  <v-alert
    :id="`job-${job.id}-delete-confirm`"
    class="delete-confirm text-left"
    density="compact"
    role="alert"
    type="warning"
    variant="tonal"
  >
    <div>
      <template v-if="created === undefined">Checking what this {{ noun }} created in CollectionSpace…</template>
      <template v-else-if="madeSomething">
        Delete this {{ noun }} from the BMU? Its runs created {{ createdText(created!) }}{{ unfinished }}.
        They stay in CollectionSpace; the BMU never deletes records. The audit log keeps every CSID.
      </template>
      <template v-else>
        Delete this {{ noun }}? Its {{ job.rowCount }} document{{ job.rowCount === 1 ? '' : 's' }} and uploaded files are removed from the
        BMU; it created nothing in CollectionSpace.
      </template>
    </div>
    <div class="mt-2">
      <v-btn
        :id="`job-${job.id}-delete-confirm-btn`"
        class="mr-2"
        color="error"
        :disabled="created === undefined || busy"
        size="small"
        @click="() => emit('confirm')"
      >
        {{ busy ? 'Deleting…' : `Delete ${noun}` }}
      </v-btn>
      <v-btn
        :id="`job-${job.id}-delete-cancel-btn`"
        :disabled="busy"
        size="small"
        variant="outlined"
        @click="() => emit('cancel')"
      >
        Cancel
      </v-btn>
    </div>
  </v-alert>
</template>

<script setup lang="ts">
import type {PropType} from 'vue'
import {computed} from 'vue'
import type {Created, Job} from '@/types'
import {createdText} from '@/lib/results'

/**
 * The confirmation for deleting a job, in Drafts, Job queue and Finished jobs (design: Deleting a job). It says
 * what the job's runs created in CollectionSpace, counted by record type, and how many documents are
 * unfinished; those records stay, because the BMU never deletes records.
 */
const props = defineProps({
  // The deletion was sent and the answer hasn't come back yet.
  busy: {
    required: false,
    type: Boolean
  },
  // What the job's runs created: undefined while it loads, null for a job that has never run.
  created: {
    default: undefined,
    required: false,
    type: Object as PropType<Created | null>
  },
  job: {
    required: true,
    type: Object as PropType<Job>
  }
})
const emit = defineEmits<{confirm: [], cancel: []}>()

const noun = computed(() => (props.job.status === 'Draft' ? 'draft' : 'job'))
const unfinished = computed(() => {
  const n = props.created?.unfinished
  return n ? `, including ${n} unfinished document${n === 1 ? '' : 's'}` : ''
})
const madeSomething = computed(() => !!props.created && !!(props.created.media || props.created.objects || props.created.groups))
</script>
