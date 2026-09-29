<script setup lang="ts">
/**
 * An expanded job in the Drafts or Job queue list (design: Job lists): the job's details and its 10 most
 * important documents, problems first, with a link to the full preview.
 */
import { computed } from "vue";
import { formatTime } from "../lib/files";
import { rowStatus, worstLevel } from "../lib/status";
import type { Job, Row, TenantInfo } from "../types";

const props = defineProps<{ job: Job; rows: Row[] | undefined; tenant: TenantInfo; kind: "drafts" | "queue" }>();
const emit = defineEmits<{ preview: [] }>();

const handlingMix = computed(() => {
  const counts = new Map<string, number>();
  for (const r of props.rows ?? []) {
    const label = props.tenant.handling.find((h) => h.id === r.handling)?.label ?? r.handling;
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return [...counts].map(([k, n]) => `${n} ${k.toLowerCase()}`).join(", ") || "—";
});
const RANK = { block: 0, warn: 1, ok: 2 } as const;
const top = computed(() => (props.rows ?? []).map((r, i) => ({ r, i }))
  .sort((a, b) => (a.r.include ? RANK[worstLevel(a.r)] : 3) - (b.r.include ? RANK[worstLevel(b.r)] : 3) || a.i - b.i)
  .slice(0, 10).map((x) => x.r));
const message = (r: Row) => r.checks.find((c) => c.level === "block")?.text ?? r.checks.find((c) => c.level === "warn")?.text ?? "";
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
      </template>
      <template v-else>
        <span><strong>Scheduled</strong> {{ formatTime(job.queuedAt) }} by {{ job.scheduledBy || "—" }}</span>
        <span v-if="job.checksAtSchedule"><strong>At scheduling</strong> {{ job.checksAtSchedule.block ? `${job.checksAtSchedule.block} need fixing` : "nothing to fix" }}<template
          v-if="job.checksAtSchedule.warn"> · {{ job.checksAtSchedule.warn }} warning(s)</template></span>
        <span v-if="(job.run ?? 0) > 0"><strong>Run</strong> rerun (run {{ (job.run ?? 0) + (job.status === "Running" ? 0 : 1) }})</span>
      </template>
    </div>
    <p v-if="!rows" class="muted">Loading…</p>
    <table v-else class="inner">
      <tbody>
        <tr v-for="r in top" :key="r.n" :class="{ disabled: !r.include }">
          <td style="width:36px">{{ r.n }}</td><td>{{ r.file }}</td>
          <td style="width:170px"><span class="badge" :class="rowStatus(r, tenant).cls">{{ rowStatus(r, tenant).text }}</span></td>
          <td class="sub">{{ message(r) }}</td>
        </tr>
        <tr v-if="!top.length"><td class="muted">No documents.</td></tr>
      </tbody>
    </table>
    <button class="link" @click="emit('preview')">Open full preview</button> <span class="sub">— every document and every check, with paging, sorting and filters.</span>
  </div>
</template>
