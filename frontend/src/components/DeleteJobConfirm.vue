<script setup lang="ts">
/**
 * The confirmation for deleting a job, in Drafts, Job queue and Finished jobs (design: Deleting a job). It says
 * what the job's runs created in CollectionSpace, counted by record type, and how many documents are
 * unfinished; those records stay, because the BMU never deletes records. created: undefined while it loads,
 * null for a job that has never run.
 */
import { computed } from "vue";
import { createdText } from "../lib/results";
import type { Created, Job } from "../types";

const props = defineProps<{ job: Job; created: Created | null | undefined }>();
const emit = defineEmits<{ confirm: []; cancel: [] }>();
const noun = computed(() => (props.job.status === "Draft" ? "draft" : "job"));
const madeSomething = computed(() => !!props.created && !!(props.created.media || props.created.objects || props.created.groups));
</script>

<template>
  <div class="msg msg-warn delete-confirm" role="alert">
    <template v-if="created === undefined">Checking what this {{ noun }} created in CollectionSpace…</template>
    <template v-else-if="madeSomething">
      Delete this {{ noun }} from the BMU? Its runs created {{ createdText(created!) }}<template v-if="created!.unfinished">, including
        {{ created!.unfinished }} unfinished document{{ created!.unfinished === 1 ? "" : "s" }}</template>.
      They stay in CollectionSpace; the BMU never deletes records. The audit log keeps every CSID.
    </template>
    <template v-else>
      Delete this {{ noun }}? Its {{ job.rowCount }} document{{ job.rowCount === 1 ? "" : "s" }} and uploaded files are removed from the
      BMU; it created nothing in CollectionSpace.
    </template>
    <button :disabled="created === undefined" @click="emit('confirm')">Delete {{ noun }}</button> <button @click="emit('cancel')">Cancel</button>
  </div>
</template>
