<template>
  <div v-if="job.currentFile" id="current-document" title="Document in progress">
    <div class="text-caption text-medium-emphasis">Now: {{ job.currentFile }}<template v-if="step">, {{ step }}</template></div>
    <template v-if="upload">
      <v-progress-linear
        :aria-label="`Sending ${job.currentFile} to CollectionSpace`"
        color="primary"
        height="4"
        :model-value="upload.pct"
        rounded
      />
      <div class="text-caption text-medium-emphasis">{{ upload.text }}</div>
    </template>
  </div>
</template>

<script setup lang="ts">
import type {PropType} from 'vue'
import {computed} from 'vue'
import type {Job} from '@/types'
import {formatBytes} from '@/lib/files'

/**
 * The document a running job is on (design: The job queue): its filename and the step in progress, and while its
 * file is sent to CollectionSpace, a bar with the share sent, like the upload bars in Create / edit job.
 */
const props = defineProps({
  job: {
    required: true,
    type: Object as PropType<Job>
  }
})

/** What the worker is doing now (the steps of lib/results STEP_LABEL). */
const DOING: Record<string, string> = {
  values: 'checking the document', media: 'creating the Media record', findObject: 'finding the object',
  createObject: 'creating the object', findOrCreateObject: 'finding or creating the object', upload: 'uploading the file',
  relMediaObject: 'relating Media and object', relObjectMedia: 'relating Media and object', addToGroup: 'adding to the group'
}
const step = computed(() => (props.job.currentStep ? DOING[props.job.currentStep] ?? props.job.currentStep : ''))
const upload = computed(() => {
  const u = props.job.currentUpload
  if (props.job.currentStep !== 'upload' || !u || !u.total) {
    return null
  }
  const pct = Math.min(100, Math.floor((u.sent / u.total) * 100))
  return {pct, text: `${pct}% · ${formatBytes(u.sent)} of ${formatBytes(u.total)}`}
})
</script>
