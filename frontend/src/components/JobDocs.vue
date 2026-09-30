<script setup lang="ts">
/**
 * An expanded job in the Drafts or Job queue list (design: Job lists; UI mockup jobDetailRow): the job's details
 * and its 10 most important documents, problems first (JobDocsTable), with a link to the full preview.
 */
import { computed } from "vue";
import { formatTime } from "../lib/files";
import type { Job, Row, TenantInfo } from "../types";
import JobDocsTable from "./JobDocsTable.vue";

const props = defineProps<{ job: Job; rows: Row[] | undefined; tenant: TenantInfo; kind: "drafts" | "queue" }>();
const emit = defineEmits<{ preview: [] }>();
const formatDate = (t: number) => new Date(t * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });

const handlingMix = computed(() => {
  const counts = new Map<string, number>();
  for (const r of props.rows ?? []) {
    const label = props.tenant.handling.find((h) => h.id === r.handling)?.label ?? r.handling;
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return [...counts].map(([k, n]) => `${n} ${k.toLowerCase()}`).join(", ") || "—";
});
</script>

<template>
  <div>
    <div class="jd-meta">
      <span><strong>Handling</strong> {{ handlingMix }}</span>
      <span><strong>Group title</strong> {{ job.groupOn ? job.groupTitle || "—" : "None" }}</span>
      <span><strong>Created by</strong> {{ job.createdBy }}</span>
      <template v-if="kind === 'drafts'">
        <span><strong>Last saved</strong> {{ formatTime(job.lastSavedAt) }} by {{ job.lastSavedBy || "—" }}</span>
        <span><strong>Being edited</strong> {{ job.editingBy ? `${job.editingByYou ? "by you" : `by ${job.editingBy}`} since ${formatTime(job.editingSince)}` : "no one" }}</span>
        <span v-if="job.expiresAt"><strong>Expires</strong> {{ formatDate(job.expiresAt) }}</span>
      </template>
      <template v-else>
        <span><strong>Submitted</strong> {{ formatTime(job.queuedAt) }} by {{ job.scheduledBy || "—" }}</span>
        <span v-if="job.checksAtSchedule"><strong>At submission</strong> {{ job.checksAtSchedule.block ? `${job.checksAtSchedule.block} need fixing` : "nothing to fix" }}<template
          v-if="job.checksAtSchedule.warn"> · {{ job.checksAtSchedule.warn }} warning(s)</template></span>
        <span v-if="(job.run ?? 0) > 0"><strong>Run</strong> rerun (run {{ (job.run ?? 0) + (job.status === "Running" ? 0 : 1) }})</span>
      </template>
    </div>
    <p v-if="!rows" class="muted">Loading…</p>
    <JobDocsTable v-else :job="job" :rows="rows" :tenant="tenant" :kind="kind" />
    <button class="link" @click="emit('preview')">Open full preview</button> <span class="sub">— every document and every check, with paging, sorting and filters.</span>
  </div>
</template>
