<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { api } from "../api";
import { formatTime } from "../lib/files";
import { displayName } from "../lib/refname";
import type { Job, Row } from "../types";

const emit = defineEmits<{ open: [id: string] }>();
const jobs = ref<Job[]>([]);
const error = ref("");
const openId = ref<string | null>(null);
const openRows = ref<Row[]>([]);
let timer: ReturnType<typeof setInterval> | undefined;

const STATUS: Record<string, { text: string; cls: string }> = {
  Draft: { text: "Draft", cls: "b-muted" },
  Queued: { text: "Queued", cls: "b-accent" },
  Running: { text: "Running", cls: "b-accent" },
  Completed: { text: "Completed", cls: "b-ok" },
  NeedsAttention: { text: "Needs attention", cls: "b-warn" },
  Failed: { text: "Failed", cls: "b-danger" },
};
const STEP_LABEL: Record<string, string> = {
  media: "Create Media record", findObject: "Find object", createObject: "Create object",
  upload: "Upload file (creates the Blob)", relMediaObject: "Relate Media → Object", relObjectMedia: "Relate Object → Media",
};
const MARK: Record<string, string> = { done: "✓", failed: "✗", skipped: "–" };

const sorted = computed(() => [...jobs.value].sort((a, b) => b.updated - a.updated));

async function refresh() {
  try {
    jobs.value = (await api.jobs()).jobs.filter((j) => ["Completed", "NeedsAttention", "Failed"].includes(j.status)); // finished jobs
    if (openId.value) openRows.value = (await api.job(openId.value)).rows;
    error.value = "";
  } catch (e) {
    error.value = (e as Error).message;
  }
}

async function toggle(j: Job) {
  if (openId.value === j.id) { openId.value = null; return; }
  openId.value = j.id;
  openRows.value = (await api.job(j.id)).rows;
}

onMounted(() => { refresh(); timer = setInterval(refresh, 3000); });
onBeforeUnmount(() => clearInterval(timer));

const pct = (j: Job, k: "done" | "failed") => (j.progress?.total ? (100 * (j.progress[k] || 0)) / j.progress.total : 0);
</script>

<template>
  <div>
    <p class="subtitle">Jobs that have run, newest first, with every document's steps and the CSIDs created. This list refreshes every few seconds.</p>
    <div v-if="error" class="msg msg-block">{{ error }}</div>
    <div class="table-wrap">
      <table>
        <thead><tr><th style="width:28px"></th><th>Job</th><th>Status</th><th class="hide-narrow">Documents</th><th class="hide-narrow">Scheduled by</th><th class="hide-narrow">Updated</th><th></th></tr></thead>
        <tbody>
          <tr v-if="!sorted.length"><td colspan="7" class="muted" style="text-align:center;padding:18px">No jobs yet.</td></tr>
          <template v-for="j in sorted" :key="j.id">
            <tr>
              <td><button class="chevron" :class="{ open: openId === j.id }" :aria-expanded="openId === j.id" aria-label="Show documents" @click="toggle(j)">▸</button></td>
              <td>{{ j.name || "Untitled job" }}<div class="sub">run {{ j.run || 0 }}<template v-if="j.code"> · {{ j.code }}</template></div></td>
              <td>
                <span class="badge" :class="STATUS[j.status]?.cls">{{ STATUS[j.status]?.text ?? j.status }}</span>
                <div v-if="j.progress && j.status !== 'Draft'" style="min-width:120px">
                  <div class="progress"><span class="ok" :style="{ width: pct(j, 'done') + '%' }"></span><span class="bad" :style="{ width: pct(j, 'failed') + '%' }"></span></div>
                  <div class="sub">{{ j.progress.done }} done · {{ j.progress.failed }} failed · {{ j.progress.total - j.progress.done - j.progress.failed }} to go</div>
                </div>
              </td>
              <td class="hide-narrow">{{ j.rowCount }}</td>
              <td class="hide-narrow">{{ j.scheduledBy || j.createdBy }}</td>
              <td class="hide-narrow">{{ formatTime(j.updated) }}</td>
              <td><button v-if="['NeedsAttention', 'Failed'].includes(j.status)" @click="emit('open', j.id)">Open to reschedule</button></td>
            </tr>
            <tr v-if="openId === j.id" class="detail">
              <td colspan="7">
                <table>
                  <thead><tr><th>#</th><th>Document</th><th>Result</th><th>Steps and CSIDs</th></tr></thead>
                  <tbody>
                    <tr v-for="r in openRows" :key="r.n">
                      <td>{{ r.n }}</td>
                      <td>{{ r.file }}<div class="sub">{{ displayName(r.creator) }}</div></td>
                      <td><span class="badge" :class="r.result?.state === 'Done' ? 'b-ok' : r.result?.error ? 'b-danger' : 'b-muted'">
                        {{ r.include ? (r.result?.state ?? "Not started") : "Disabled" }}</span>
                        <div v-if="r.result?.error" class="sub" style="color:var(--text-danger)">{{ r.result.error.detail }}</div></td>
                      <td class="steps">
                        <div v-for="(st, k) in r.result?.steps ?? {}" :key="k">
                          {{ MARK[st.s] ?? "·" }} {{ STEP_LABEL[k] ?? k }}
                          <code v-if="st.csid">{{ st.csid }}</code>
                          <span v-else-if="st.s === 'skipped'" class="sub">(skipped: needs {{ STEP_LABEL[st.after ?? ""] ?? st.after }})</span>
                          <span v-else-if="st.s === 'failed'" class="sub">({{ st.code }})</span>
                        </div>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>
