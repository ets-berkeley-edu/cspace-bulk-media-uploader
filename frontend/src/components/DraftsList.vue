<script setup lang="ts">
import ChevronIcon from "./ChevronIcon.vue";
/**
 * The Drafts tab (design: Drafts, scheduling and the job queue): every draft in the tenant, which anyone can
 * preview and edit, one person at a time. Checks are re-run against CollectionSpace each time it is shown.
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { api } from "../api";
import { formatTime } from "../lib/files";
import { tableState, tableView } from "../lib/table";
import type { Job, Row, TenantInfo } from "../types";
import JobActions from "./JobActions.vue";
import JobDocs from "./JobDocs.vue";
import SortTh from "./SortTh.vue";

/** editWhy: why this user can't create or edit jobs (design: Permissions in the UI); "" when they can. */
defineProps<{ tenant: TenantInfo; editWhy?: string }>();
const emit = defineEmits<{ open: [id: string, mode: "edit" | "preview", takeOverSince?: number] }>();
const drafts = ref<Job[]>([]);
const docs = reactive(new Map<string, Row[]>()); // each draft's documents, from its latest check
const expanded = reactive(new Set<string>());
const table = tableState();
const sorted = computed(() => tableView(drafts.value, table, {
  name: (j) => j.name || "Untitled job",
  docs: (j) => j.rowCount,
  checks: (j) => { const c = countsOf(j.id); return c ? -(c.block * 100000 + c.warn) : 1; },
  saved: (j) => -(j.lastSavedAt ?? 0),
  editing: (j) => j.editingBy || "~",
  expires: (j) => j.expiresAt ?? 0,
}, undefined, false).shown);
function toggle(j: Job) {
  if (expanded.has(j.id)) expanded.delete(j.id);
  else { expanded.add(j.id); if (!docs.has(j.id)) api.job(j.id).then((r) => docs.set(j.id, r.rows)).catch(() => undefined); }
}
function expandAll(on: boolean) {
  if (!on) { expanded.clear(); return; }
  drafts.value.forEach((j) => { if (!expanded.has(j.id)) toggle(j); });
}
const checks = reactive(new Map<string, { block: number; warn: number } | "checking">());
const error = ref("");
/** Pass on JobActions' open (a take-over carries when the other person started editing). */
function reopen(id: string, m: "edit" | "preview", since?: number) {
  if (since === undefined) emit("open", id, m);
  else emit("open", id, m, since);
}
let timer: ReturnType<typeof setInterval> | undefined;

async function refresh(runChecks = false) {
  try {
    drafts.value = (await api.jobs(!runChecks)).jobs.filter((j) => j.status === "Draft").sort((a, b) => (b.lastSavedAt ?? 0) - (a.lastSavedAt ?? 0));
    error.value = "";
  } catch (e) {
    error.value = (e as Error).message;
  }
  if (runChecks) {
    for (const d of drafts.value) {
      checks.set(d.id, "checking");
      api.check(d.id).then((r) => { checks.set(d.id, r.counts); docs.set(d.id, r.rows); }).catch(() => checks.delete(d.id));
    }
  }
}
onMounted(() => { refresh(true); timer = setInterval(() => refresh(false), 5000); });
onBeforeUnmount(() => clearInterval(timer));

function expiry(j: Job) {
  if (!j.expiresAt) return { text: "—", soon: false };
  const days = Math.ceil((j.expiresAt * 1000 - Date.now()) / 86400000);
  const date = new Date(j.expiresAt * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return { text: `${date} (${days <= 0 ? "today" : `in ${days} day${days === 1 ? "" : "s"}`})`, soon: days <= 3 };
}
function checksText(c: { block: number; warn: number }) {
  const parts = [c.block ? `${c.block} need${c.block === 1 ? "s" : ""} fixing` : "nothing to fix"];
  if (c.warn) parts.push(`${c.warn} warning${c.warn === 1 ? "" : "s"}`);
  return parts.join(" · ");
}
function countsOf(id: string): { block: number; warn: number } | null {
  const c = checks.get(id);
  return c && c !== "checking" ? c : null;
}
</script>

<template>
  <div>
    <p class="subtitle">Jobs saved but not submitted, including incomplete jobs and jobs with problems. Everyone signed in can see and
      edit them, one person at a time; you can take over a draft someone else is editing. A draft that has never run is deleted
      30 days after it was last changed or saved (7 days if it has protected files); a fix of a job that has run is reverted instead, and the job returns to Finished jobs. Checks are re-run against CollectionSpace each time this list is shown.</p>
    <div v-if="error" class="msg msg-block">{{ error }}</div>
    <div v-if="drafts.length" class="list-tools"><button class="link" @click="expandAll(true)">Expand all</button> ·
      <button class="link" @click="expandAll(false)">Collapse all</button></div>
    <div class="table-wrap">
      <table>
        <thead><tr><th style="width:40px"></th><SortTh :state="table" sort-key="name" label="Draft" /><SortTh :state="table" sort-key="docs" label="Docs" style="width:70px" />
          <SortTh :state="table" sort-key="checks" label="Checks now" style="width:170px" /><SortTh :state="table" sort-key="saved" label="Last saved" style="width:150px" />
          <SortTh :state="table" sort-key="editing" label="Editing" style="width:110px" /><SortTh :state="table" sort-key="expires" label="Expires" style="width:140px" />
          <th style="width:250px"></th></tr></thead>
        <tbody>
          <tr v-if="!drafts.length"><td colspan="8" class="muted" style="text-align:center;padding:18px">No drafts. A job you start in Create / edit job is a draft until you submit it.</td></tr>
          <template v-for="j in sorted" :key="j.id">
          <tr>
            <td><button class="chevron" :class="{ open: expanded.has(j.id) }" :aria-expanded="expanded.has(j.id)"
                        :aria-label="`Show details of ${j.name || 'Untitled job'}`" @click="toggle(j)"><ChevronIcon /></button></td>
            <td>{{ j.name || "Untitled job" }}<div class="sub">created by {{ j.createdBy }}</div>
              <div v-if="j.fixFrom" class="sub">🔧 fixing after run {{ j.fixFrom.run }} ({{ j.fixFrom.status === "Failed" ? "failed" : "needed attention" }})</div>
              <div v-if="j.note" class="sub note">⚠ {{ j.note }}</div></td>
            <td>{{ j.rowCount }}</td>
            <td>
              <span v-if="checks.get(j.id) === 'checking'" class="badge b-muted">Checking…</span>
              <span v-else-if="countsOf(j.id)" class="badge"
                    :class="countsOf(j.id)!.block ? 'b-danger' : countsOf(j.id)!.warn ? 'b-warn' : 'b-ok'">
                {{ checksText(countsOf(j.id)!) }}</span>
            </td>
            <td>{{ formatTime(j.lastSavedAt) }}<div class="sub">by {{ j.lastSavedBy || "—" }}</div></td>
            <td><span v-if="j.editingBy" class="lock" :title="`since ${formatTime(j.editingSince)}`">🔒 {{ j.editingByYou ? "You" : j.editingBy }}</span>
              <span v-else class="sub">—</span></td>
            <td><span :class="{ soon: expiry(j).soon }">{{ expiry(j).text }}</span><div class="sub" :title="j.fixFrom ? 'The edits are discarded and the job returns to Finished jobs as it was' : 'The draft is deleted with its files'">{{ j.fixFrom ? "then reverted" : "then deleted" }}</div>
              <div v-if="j.protectedCount" class="sub" title="A draft with protected files expires 7 days after it was last saved">7 days: protected files</div></td>
            <td>
              <JobActions :job="j" kind="drafts" :edit-why="editWhy" @open="reopen"
                          @done="refresh()" @error="error = $event" />
            </td>
          </tr>
          <tr v-if="expanded.has(j.id)" class="detail"><td colspan="8">
            <JobDocs :job="j" :rows="docs.get(j.id)" :tenant="tenant" kind="drafts" @preview="emit('open', j.id, 'preview')" /></td></tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>
