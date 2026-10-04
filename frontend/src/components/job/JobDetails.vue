<template>
  <div :id="`job-${job.id}-details`" class="py-3">
    <dl class="job-facts mb-3 text-body-2">
      <div><dt>Handling</dt><dd>{{ rows ? handlingMix(rows, tenant) : '—' }}</dd></div>
      <div><dt>Group title</dt><dd>{{ job.groupOn ? job.groupTitle || '—' : 'None' }}</dd></div>
      <div><dt>Created by</dt><dd>{{ job.createdBy }}</dd></div>
      <template v-if="kind === 'drafts'">
        <div><dt>Last saved</dt><dd>{{ formatTime(job.lastSavedAt) }} by {{ job.lastSavedBy || '—' }}</dd></div>
        <div>
          <dt>Being edited</dt>
          <dd>{{ job.editingBy ? `${job.editingByYou ? 'by you' : `by ${job.editingBy}`} since ${formatTime(job.editingSince)}` : 'no one' }}</dd>
        </div>
        <div v-if="job.expiresAt"><dt>Expires</dt><dd>{{ shortDate(job.expiresAt) }}</dd></div>
      </template>
      <template v-else>
        <div><dt>Submitted</dt><dd>{{ formatTime(job.queuedAt) }} by {{ job.scheduledBy || '—' }}</dd></div>
        <div v-if="job.checksAtSchedule">
          <dt>At submission</dt>
          <dd>
            {{ checksText(job.checksAtSchedule) }}
          </dd>
        </div>
        <div><dt>Run</dt><dd :id="`job-${job.id}-run`">{{ runName(job) }}</dd></div>
      </template>
    </dl>
    <p v-if="!rows" class="text-medium-emphasis">Loading…</p>
    <JobDocumentsTable
      v-else
      :job="job"
      :kind="kind"
      :rows="rows"
      :tenant="tenant"
    />
    <div class="mt-2 text-body-2">
      <button
        :id="`job-${job.id}-full-preview-btn`"
        class="link-btn"
        type="button"
        @click="() => emit('preview')"
      >
        Open full preview
      </button>
      <span class="text-medium-emphasis"> — every document and every check, with paging, sorting and filters.</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import type {PropType} from 'vue'
import type {Job, Row, TenantInfo} from '@/types'
import JobDocumentsTable from '@/components/job/JobDocumentsTable.vue'
import {formatTime} from '@/lib/files'
import {checksText, handlingMix, runName} from '@/lib/status'

/**
 * An expanded job in the Drafts or Job queue list (design: Job lists): the job's details and its 10 most
 * important documents, problems first, with a link to the full preview.
 */
defineProps({
  job: {
    required: true,
    type: Object as PropType<Job>
  },
  kind: {
    required: true,
    type: String as PropType<'drafts' | 'queue'>
  },
  // The job's documents; undefined while they load.
  rows: {
    default: undefined,
    required: false,
    type: Array as PropType<Row[]>
  },
  tenant: {
    required: true,
    type: Object as PropType<TenantInfo>
  }
})
const emit = defineEmits<{preview: []}>()

const shortDate = (t: number) => new Date(t * 1000).toLocaleDateString(undefined, {month: 'short', day: 'numeric'})
</script>
