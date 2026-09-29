<script setup lang="ts">
/**
 * The Job queue tab (design: The job queue): running jobs first, then queued jobs in the order workers take
 * them. Anyone in the tenant can reorder (drag, or ▲▼), preview, edit (back to Drafts), delete or cancel a run.
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
const emit = defineEmits<{ open: [id: string, mode: "edit" | "preview"] }>();
const docs = reactive(new Map<string, Row[]>());
const expanded = reactive(new Set<string>());
// Sorting only changes the view: jobs still run in queue order, and moving is off until the sort is cleared.
const table = tableState();
const jobs = ref<Job[]>([]);
const checks = reactive(new Map<string, { block: number; warn: number }>());
const confirm = ref<{ id: string; kind: "edit" | "cancel" | "delete" } | null>(null);
const error = ref("");
const flash = ref("");
const dragId = ref<string | null>(null);
const dropAt = ref<{ id: string; after: boolean } | null>(null);
let timer: ReturnType<typeof setInterval> | undefined;

const running = computed(() => jobs.value.filter((j) => j.status === "Running"));
const queued = computed(() => jobs.value.filter((j) => j.status === "Queued")
  .sort((a, b) => (a.queuePos ?? 0) - (b.queuePos ?? 0) || (a.queuedAt ?? 0) - (b.queuedAt ?? 0)));
const sortedView = computed(() => !!table.sort);
const shownQueued = computed(() => tableView(queued.value, table, {
  order: (j) => queued.value.indexOf(j),
  name: (j) => j.name || "Untitled job",
  docs: (j) => j.rowCount,
  checks: (j) => { const c = checks.get(j.id); return c ? -(c.block * 100000 + c.warn) : 1; },
  scheduled: (j) => j.queuedAt ?? 0,
}, undefined, false).shown);
function toggle(j: Job) {
  if (expanded.has(j.id)) expanded.delete(j.id);
  else { expanded.add(j.id); if (!docs.has(j.id)) api.job(j.id).then((r) => docs.set(j.id, r.rows)).catch(() => undefined); }
}
function expandAll(on: boolean) {
  if (!on) { expanded.clear(); return; }
  jobs.value.forEach((j) => { if (!expanded.has(j.id)) toggle(j); });
}

async function refresh(runChecks = false) {
  try {
    jobs.value = (await api.jobs(!runChecks)).jobs.filter((j) => j.status === "Running" || j.status === "Queued");
    error.value = "";
  } catch (e) {
    error.value = (e as Error).message;
  }
  if (runChecks) {  // design: checks are re-run against CollectionSpace each time the queue is shown
    for (const j of queued.value) api.check(j.id).then((r) => { checks.set(j.id, r.counts); docs.set(j.id, r.rows); }).catch(() => undefined);
  }
}
onMounted(() => { refresh(true); timer = setInterval(() => refresh(false), 2000); });
onBeforeUnmount(() => clearInterval(timer));

// What each job's earlier runs created, for the delete confirmation (null: it has never run)
const created = reactive(new Map<string, Created | null>());
function askDelete(j: Job) {
  confirm.value = { id: j.id, kind: "delete" };
  if (!j.run) created.set(j.id, null);
  else api.job(j.id).then((r) => created.set(j.id, r.created)).catch(() => created.set(j.id, null));
}
async function act(fn: () => Promise<unknown>, done = "") {
  try {
    await fn();
    confirm.value = null;
    flash.value = done;
    await refresh();
  } catch (e) {
    error.value = (e as Error).message;
  }
}
const move = (j: Job, to: number) => act(() => api.moveJob(j.id, Math.max(0, to)), `Moved “${j.name || "Untitled job"}” to position ${running.value.length + Math.max(0, to) + 1}.`);
async function edit(j: Job) {
  await act(() => api.editQueued(j.id));
  if (!error.value) emit("open", j.id, "edit");
}

// drag and drop among the queued jobs
function onDragOver(e: DragEvent, j: Job) {
  if (!dragId.value || j.status !== "Queued" || sortedView.value) return;
  e.preventDefault();
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
  dropAt.value = { id: j.id, after: e.clientY > r.top + r.height / 2 };
}
function onDrop() {
  const from = queued.value.findIndex((x) => x.id === dragId.value);
  const target = queued.value.findIndex((x) => x.id === dropAt.value?.id);
  if (from >= 0 && target >= 0) {
    let to = target + (dropAt.value!.after ? 1 : 0);
    if (from < to) to--;
    if (to !== from) move(queued.value[from], to);
  }
  dragId.value = null;
  dropAt.value = null;
}

function signIn(j: Job) {
  if (!j.credentialExpires) return null;
  const h = Math.max(0, Math.round((j.credentialExpires * 1000 - Date.now()) / 3600000));
  return { hours: h, soon: h <= 3 };
}
function checksText(c: { block: number; warn: number }) {
  const parts = [c.block ? `${c.block} need${c.block === 1 ? "s" : ""} fixing` : "nothing to fix"];
  if (c.warn) parts.push(`${c.warn} warning${c.warn === 1 ? "" : "s"}`);
  return parts.join(" · ");
}
const changed = (j: Job) => {
  const c = checks.get(j.id), a = j.checksAtSchedule;
  return !!c && !!a && (c.block !== a.block || c.warn !== a.warn);
};
const pct = (j: Job, k: "done" | "failed") => (j.progress?.total ? (100 * (j.progress[k] || 0)) / j.progress.total : 0);
</script>

<template>
  <div>
    <p class="subtitle">Jobs scheduled to run, in the order workers pick them up. Drag a job, or use its arrows, to change the order;
      running jobs stay first. Jobs run one at a time, so each waits for the ones above it. Editing a queued job moves it to Drafts
      until it is scheduled again. Checks are re-run against CollectionSpace each time this list is shown.</p>
    <div v-if="error" class="msg msg-block">{{ error }}</div>
    <div v-if="flash" class="msg msg-info">{{ flash }}</div>
    <div v-if="jobs.length" class="list-tools"><button class="link" @click="expandAll(true)">Expand all</button> ·
      <button class="link" @click="expandAll(false)">Collapse all</button></div>
    <div v-if="sortedView" class="msg msg-info">Sorted view. The queue still runs in its own order;
      <button class="link" @click="table.sort = null">clear the sort</button> to drag or move jobs.</div>
    <div class="table-wrap">
      <table class="queue">
        <thead><tr><th style="width:28px"></th><SortTh :state="table" sort-key="order" label="Order" style="width:96px" /><SortTh :state="table" sort-key="name" label="Job" />
          <SortTh :state="table" sort-key="docs" label="Docs" style="width:64px" /><SortTh :state="table" sort-key="checks" label="Checks now" style="width:170px" />
          <SortTh :state="table" sort-key="scheduled" label="Scheduled" style="width:150px" /><th style="width:170px">Status</th><th style="width:250px"></th></tr></thead>
        <tbody>
          <tr v-if="!jobs.length"><td colspan="8" class="muted" style="text-align:center;padding:18px">No jobs in the queue. Create one in Create / edit job and schedule it.</td></tr>
          <template v-for="j in running" :key="j.id">
          <tr>
            <td><button class="chevron" :class="{ open: expanded.has(j.id) }" :aria-expanded="expanded.has(j.id)"
                        :aria-label="`Show details of ${j.name || 'Untitled job'}`" @click="toggle(j)">▸</button></td>
            <td><span class="grip" aria-hidden="true">▶</span> {{ running.indexOf(j) + 1 }}</td>
            <td>{{ j.name || "Untitled job" }}<div v-if="(j.run ?? 0) > 1" class="sub">rerun (run {{ j.run }})</div></td>
            <td>{{ j.rowCount }}</td>
            <td><span class="sub">—</span></td>
            <td>{{ formatTime(j.queuedAt) }}<div class="sub">by {{ j.scheduledBy }}</div></td>
            <td>
              <span class="badge b-ok">Running</span>
              <div class="sub">{{ j.progress?.done ?? 0 }} done · {{ j.progress?.failed ?? 0 }} failed ·
                {{ (j.progress?.total ?? 0) - (j.progress?.done ?? 0) - (j.progress?.failed ?? 0) }} to go</div>
              <div class="progress"><span class="ok" :style="{ width: pct(j, 'done') + '%' }"></span><span class="bad" :style="{ width: pct(j, 'failed') + '%' }"></span></div>
              <div v-if="j.cancelRequested" class="sub lock">Cancelling after the document in progress…</div>
              <div v-else-if="j.currentFile" class="sub" title="Document in progress">▶ {{ j.currentFile }}</div>
            </td>
            <td>
              <div v-if="confirm?.id === j.id && confirm.kind === 'cancel'" class="msg msg-warn">
                Stop this run? The worker finishes the document it’s on, then stops; documents it hasn’t reached stay not started,
                and nothing already created is undone.
                <button @click="act(() => api.cancelRun(j.id))">Cancel run</button> <button @click="confirm = null">Keep running</button>
              </div>
              <div v-else class="actions">
                <button @click="emit('open', j.id, 'preview')">Preview</button>
                <button :disabled="!!j.cancelRequested" title="Stop after the document in progress" @click="confirm = { id: j.id, kind: 'cancel' }">Cancel run</button>
                <button disabled title="A running job can't be deleted">Delete</button>
              </div>
            </td>
          </tr>
          <tr v-if="expanded.has(j.id)" class="detail"><td colspan="8">
            <JobDocs :job="j" :rows="docs.get(j.id)" :tenant="tenant" kind="queue" @preview="emit('open', j.id, 'preview')" /></td></tr>
          </template>
          <template v-for="j in shownQueued" :key="j.id">
          <tr :draggable="!sortedView" :class="{ draggable: !sortedView, dragging: dragId === j.id, 'drop-before': dropAt?.id === j.id && !dropAt.after, 'drop-after': dropAt?.id === j.id && dropAt.after }"
              :title="sortedView ? '' : 'Drag to change the order'"
              @dragstart="dragId = j.id" @dragend="dragId = null; dropAt = null" @dragover="onDragOver($event, j)" @drop.prevent="onDrop">
            <td><button class="chevron" :class="{ open: expanded.has(j.id) }" :aria-expanded="expanded.has(j.id)"
                        :aria-label="`Show details of ${j.name || 'Untitled job'}`" @click="toggle(j)">▸</button></td>
            <td><span class="grip" aria-hidden="true">⋮⋮</span> {{ running.length + queued.indexOf(j) + 1 }}
              <span class="order-btns">
                <button :disabled="sortedView || queued.indexOf(j) === 0" :aria-label="`Move ${j.name} up`" @click="move(j, queued.indexOf(j) - 1)">▲</button>
                <button :disabled="sortedView || queued.indexOf(j) === queued.length - 1" :aria-label="`Move ${j.name} down`" @click="move(j, queued.indexOf(j) + 1)">▼</button>
              </span></td>
            <td>{{ j.name || "Untitled job" }}<div v-if="(j.run ?? 0) > 0" class="sub">rerun (run {{ (j.run ?? 0) + 1 }})</div></td>
            <td>{{ j.rowCount }}</td>
            <td>
              <span v-if="checks.get(j.id)" class="badge" :class="checks.get(j.id)!.block ? 'b-danger' : checks.get(j.id)!.warn ? 'b-warn' : 'b-ok'">
                {{ checksText(checks.get(j.id)!) }}</span>
              <span v-else class="badge b-muted">Checking…</span>
              <div v-if="changed(j)" class="sub lock" title="The checks found something different from when the job was scheduled">Changed since scheduled</div>
            </td>
            <td>{{ formatTime(j.queuedAt) }}<div class="sub">by {{ j.scheduledBy }}</div>
              <div v-if="signIn(j)" class="sub" :class="{ lock: signIn(j)!.soon }"
                   :title="`If the job hasn't started by then, its saved sign-in is deleted and it moves to Drafts`">
                {{ signIn(j)!.soon ? "⚠ sign-in expires in" : "sign-in kept" }} ~{{ signIn(j)!.hours }} h</div></td>
            <td><span class="badge b-accent">Queued</span></td>
            <td>
              <div v-if="confirm?.id === j.id && confirm.kind === 'edit'" class="msg msg-warn">
                Editing takes this job out of the queue and deletes its saved sign-in. It goes to the end of the queue when it’s
                scheduled again, even if nothing changes. <button @click="edit(j)">Edit anyway</button> <button @click="confirm = null">Cancel</button>
              </div>
              <DeleteJobConfirm v-else-if="confirm?.id === j.id && confirm.kind === 'delete'" :job="j" :created="created.get(j.id)"
                                @confirm="act(() => api.deleteJob(j.id), 'Deleted the job.')" @cancel="confirm = null" />
              <div v-else class="actions">
                <button @click="emit('open', j.id, 'preview')">Preview</button>
                <button @click="confirm = { id: j.id, kind: 'edit' }">Edit</button>
                <button @click="askDelete(j)">Delete</button>
              </div>
            </td>
          </tr>
          <tr v-if="expanded.has(j.id)" class="detail"><td colspan="8">
            <JobDocs :job="j" :rows="docs.get(j.id)" :tenant="tenant" kind="queue" @preview="emit('open', j.id, 'preview')" /></td></tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>
