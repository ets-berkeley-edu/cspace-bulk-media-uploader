<script setup lang="ts">
/**
 * The document a running job is on (design: The job queue): its filename and the step in progress, and while its
 * file is sent to CollectionSpace, a bar with the share sent, like the upload bars in Create / edit job.
 */
import { computed } from "vue";
import { formatBytes } from "../lib/files";
import type { Job } from "../types";

const props = defineProps<{ job: Job }>();
/** What the worker is doing now, short enough for the queue's Status column (the steps of lib/results STEP_LABEL). */
const DOING: Record<string, string> = {
  values: "checking values", media: "creating the Media record", findObject: "finding the object",
  createObject: "creating the object", findOrCreateObject: "finding or creating the object", upload: "uploading the file",
  relMediaObject: "relating Media and object", relObjectMedia: "relating Media and object", addToGroup: "adding to the group",
};
const step = computed(() => (props.job.currentStep ? DOING[props.job.currentStep] ?? props.job.currentStep : ""));
const upload = computed(() => {
  const u = props.job.currentUpload;
  if (props.job.currentStep !== "upload" || !u || !u.total) return null;
  const pct = Math.min(100, Math.floor((u.sent / u.total) * 100));
  return { pct, text: `${pct}% · ${formatBytes(u.sent)} of ${formatBytes(u.total)}` };
});
</script>

<template>
  <div v-if="job.currentFile" class="run-now" title="Document in progress">
    <div class="sub">Now: {{ job.currentFile }}<template v-if="step">, {{ step }}</template></div>
    <template v-if="upload">
      <div class="progress" role="progressbar" :aria-valuenow="upload.pct" aria-valuemin="0" aria-valuemax="100"
           :aria-label="`Sending ${job.currentFile} to CollectionSpace`"><span class="up" :style="{ width: upload.pct + '%' }"></span></div>
      <div class="sub">{{ upload.text }}</div>
    </template>
  </div>
</template>
