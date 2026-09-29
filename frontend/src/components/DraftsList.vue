<script setup lang="ts">
/**
 * The Drafts tab (design: Drafts, scheduling and the job queue): every draft in the tenant, which anyone can
 * preview and edit, one person at a time. Checks are re-run against CollectionSpace each time it is shown.
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { api } from "../api";
import { formatTime } from "../lib/files";
import { tableState, tableView } from "../lib/table";
import type { Created, Job, Row, TenantInfo } from "../types";
import DeleteJobConfirm from "./DeleteJobConfirm.vue";
import JobDocs from "./JobDocs.vue";
import SortTh from "./SortTh.vue";

defineProps<{ tenant: TenantInfo }>();
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
const confirm = ref<{ id: string; kind: "delete" | "takeover" } | null>(null);
const error = ref("");
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
const lockedByOther = (j: Job) => !!j.editingBy && !j.editingByYou;
function countsOf(id: string): { block: number; warn: number } | null {
  const c = checks.get(id);
  return c && c !== "checking" ? c : null;
}

// What each draft's runs created, for the delete confirmation (null: it has never run)
const created = reactive(new Map<string, Created | null>());
function askDelete(j: Job) {
  confirm.value = { id: j.id, kind: "delete" };
  if (!j.run) created.set(j.id, null);
  else api.job(j.id).then((r) => created.set(j.id, r.created)).catch((e) => { error.value = (e as Error).message; });
}
async function del(j: Job) {
  try {
    await api.deleteJob(j.id);
    confirm.value = null;
    await refresh();
  } catch (e) {
    error.value = (e as Error).message;
  }
}
</script>

<template>
  <div>
    <p class="subtitle">Jobs saved but not scheduled, including incomplete jobs and jobs with problems. Everyone signed in can see and
      edit them, one person at a time; you can take over a draft someone else is editing. A draft that has never run is deleted
      30 days after it was last changed or saved; a fix of a job that has run is reverted instead, and the job returns to Finished jobs. Checks are re-run against CollectionSpace each time this list is shown.</p>
    <div v-if="error" class="msg msg-block">{{ error }}</div>
    <div v-if="drafts.length" class="list-tools"><button class="link" @click="expandAll(true)">Expand all</button> ·
      <button class="link" @click="expandAll(false)">Collapse all</button></div>
    <div class="table-wrap">
      <table>
        <thead><tr><th style="width:28px"></th><SortTh :state="table" sort-key="name" label="Draft" /><SortTh :state="table" sort-key="docs" label="Docs" style="width:70px" />
          <SortTh :state="table" sort-key="checks" label="Checks now" style="width:170px" /><SortTh :state="table" sort-key="saved" label="Last saved" style="width:150px" />
          <SortTh :state="table" sort-key="editing" label="Editing" style="width:110px" /><SortTh :state="table" sort-key="expires" label="Expires" style="width:140px" />
          <th style="width:250px"></th></tr></thead>
        <tbody>
          <tr v-if="!drafts.length"><td colspan="8" class="muted" style="text-align:center;padding:18px">No drafts. A job you start in Create / edit job is a draft until you schedule it.</td></tr>
          <template v-for="j in sorted" :key="j.id">
          <tr>
            <td><button class="chevron" :class="{ open: expanded.has(j.id) }" :aria-expanded="expanded.has(j.id)"
                        :aria-label="`Show details of ${j.name || 'Untitled job'}`" @click="toggle(j)">▸</button></td>
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
              <DeleteJobConfirm v-if="confirm?.id === j.id && confirm.kind === 'delete'" :job="j" :created="created.get(j.id)"
                                @confirm="del(j)" @cancel="confirm = null" />
              <div v-else-if="confirm?.id === j.id && confirm.kind === 'takeover'" class="msg msg-warn">
                {{ j.editingBy }} has been editing this draft since {{ formatTime(j.editingSince) }}. If you take over, their editing ends
                and their page becomes read-only; everything they changed so far is already saved.
                <button @click="emit('open', j.id, 'edit', j.editingSince)">Take over and edit</button> <button @click="confirm = null">Cancel</button>
              </div>
              <div v-else class="actions">
                <button @click="emit('open', j.id, 'preview')">Preview</button>
                <button v-if="lockedByOther(j)" @click="confirm = { id: j.id, kind: 'takeover' }">Take over…</button>
                <button v-else @click="emit('open', j.id, 'edit')">{{ j.editingByYou ? "Continue editing" : "Edit" }}</button>
                <button :disabled="lockedByOther(j)" :title="lockedByOther(j) ? `${j.editingBy} is editing this draft` : ''"
                        @click="askDelete(j)">Delete</button>
              </div>
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
