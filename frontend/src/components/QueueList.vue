<script setup lang="ts">
import ChevronIcon from "./ChevronIcon.vue";
/**
 * The Job queue tab (design: The job queue; Job scheduling): running jobs first, then queued jobs in the order
 * workers take them. Queued jobs start at the tenant's run times (the schedule banner), one at a time. BMU
 * schedulers change the schedule, pause the queue, reorder it (drag, or ▲▼) and set each job's Run now, own run
 * time or hold; everyone can preview, edit (back to Drafts) and delete; schedulers and the submitter cancel a run.
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { api } from "../api";
import { formatTime } from "../lib/files";
import { absLabel, DAY_NAMES, DAY_ORDER, parsePtInput, pausedBanner, ptInputValue, runsAt, scheduleBanner, scheduleShort,
  scheduleSummary, whenLabel } from "../lib/schedule";
import { tableState, tableView } from "../lib/table";
import type { Job, Row, Schedule, TenantInfo } from "../types";
import JobActions from "./JobActions.vue";
import RunNow from "./RunNow.vue";
import JobDocs from "./JobDocs.vue";
import SortTh from "./SortTh.vue";

/**
 * editWhy: why this user can't create or edit jobs (design: Permissions in the UI); "" when they can.
 * user, scheduler: the signed-in user and whether they have the BMU_Scheduler role (design: Job scheduling).
 */
const props = defineProps<{ tenant: TenantInfo; editWhy?: string; user?: string; scheduler?: boolean }>();
const emit = defineEmits<{ open: [id: string, mode: "edit" | "preview", takeOverSince?: number] }>();
const docs = reactive(new Map<string, Row[]>());
const expanded = reactive(new Set<string>());
// Sorting only changes the view: jobs still run in queue order, and moving is off until the sort is cleared.
const table = tableState();
const jobs = ref<Job[]>([]);
const checks = reactive(new Map<string, { block: number; warn: number }>());
const error = ref("");
const flash = ref("");
const dragId = ref<string | null>(null);
const dropAt = ref<{ id: string; after: boolean } | null>(null);
let timer: ReturnType<typeof setInterval> | undefined;

// ---- the schedule (design: Job scheduling; UI mockup scheduleBannerHtml) ----
const schedule = ref<Schedule | null>(null);
const schedEdit = ref<{ days: number[]; start: string; endOn: boolean; end: string; err: string; busy: boolean } | null>(null);
const pauseEdit = ref<{ reason: string; err: string; busy: boolean } | null>(null);
const runAtEdit = ref<{ id: string; val: string; err: string } | null>(null);
const canReorder = computed(() => !!props.scheduler);

const running = computed(() => jobs.value.filter((j) => j.status === "Running"));
const queued = computed(() => jobs.value.filter((j) => j.status === "Queued")
  .sort((a, b) => (a.queuePos ?? 0) - (b.queuePos ?? 0) || (a.queuedAt ?? 0) - (b.queuedAt ?? 0)));
// Sorted by Order ascending is the queue order itself, so it counts as not sorted: jobs can still be moved (design:
// User interface, Large jobs; UI mockup renderQueue).
const sortedView = computed(() => !!table.sort && !(table.sort === "order" && table.dir === 1));
const movable = computed(() => canReorder.value && !sortedView.value);
const runsOf = (j: Job) => runsAt(j, running.value.length > 0);
/** The Status column's order (design: User interface, every table is sortable; UI mockup renderQueue): Running before
 *  Queued, as in the mockup; among queued jobs, those waiting their turn, then those waiting for the paused queue to be
 *  resumed, then held ones, the same order as Runs at. Ties keep queue order. Running jobs are always listed first. */
const statusRank = (j: Job) => (j.status === "Running" ? 0 : j.held || j.plan?.kind === "held" ? 3 : j.plan?.kind === "paused" ? 2 : 1);
const shownQueued = computed(() => tableView(queued.value, table, {
  order: (j) => queued.value.indexOf(j),
  name: (j) => j.name || "Untitled job",
  docs: (j) => j.rowCount,
  checks: (j) => { const c = checks.get(j.id); return c ? -(c.block * 100000 + c.warn) : 1; },
  scheduled: (j) => j.queuedAt ?? 0,
  runs: (j) => runsOf(j).key,
  status: statusRank,
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
    const [r, s] = await Promise.all([api.jobs(!runChecks), api.getSchedule(!runChecks)]);
    jobs.value = r.jobs.filter((j) => j.status === "Running" || j.status === "Queued");
    schedule.value = s;
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

async function act(fn: () => Promise<unknown>, done: string | (() => string) = "") {
  try {
    await fn();
    await refresh();
    flash.value = typeof done === "function" ? done() : done;
    error.value = "";
    return true;
  } catch (e) {
    error.value = (e as Error).message;
    return false;
  }
}
const move = (j: Job, to: number) => act(() => api.moveJob(j.id, Math.max(0, to)), `Moved “${j.name || "Untitled job"}” to position ${running.value.length + Math.max(0, to) + 1}.`);
async function done(msg: string) {
  flash.value = msg;
  error.value = "";
  await refresh();
}

// ---- schedule settings, pause and resume (schedulers; the server's 422 messages show inline) ----
function openSchedule() {
  const s = schedule.value;
  if (!s) return;
  schedEdit.value = { days: [...s.days], start: s.start, endOn: !!s.end, end: s.end || "06:00", err: "", busy: false };
}
function toggleDay(d: number, on: boolean) {
  const e = schedEdit.value!;
  e.days = on ? [...new Set([...e.days, d])].sort((a, b) => a - b) : e.days.filter((x) => x !== d);
}
async function saveSchedule() {
  const e = schedEdit.value, before = schedule.value;
  if (!e || !before) return;
  if (e.endOn && !e.end) { e.err = "Enter the end time, or untick “Don’t start new jobs after”."; return; }
  e.busy = true;
  try {
    const s = await api.putSchedule({ days: e.days, start: e.start, end: e.endOn ? e.end : "" });
    schedule.value = s;
    schedEdit.value = null;
    flash.value = scheduleShort(before) === scheduleShort(s) ? "The schedule didn’t change."
      : `Schedule saved. ${scheduleSummary(s)}` + (s.nextRunAt ? ` Next run time: ${whenLabel(s.nextRunAt, { today: true })}.` : "");
    await refresh();
  } catch (err) {
    e.err = (err as Error).message;
  } finally {
    e.busy = false;
  }
}
async function pause() {
  const e = pauseEdit.value;
  if (!e) return;
  const reason = e.reason.trim();
  if (!reason) { e.err = "Enter a reason, so others know why the queue is paused."; return; }
  e.busy = true;
  try {
    schedule.value = await api.pauseQueue(reason);
    pauseEdit.value = null;
    flash.value = "You paused the queue. A running job finishes; no other job starts until a BMU scheduler resumes it.";
    await refresh();
  } catch (err) {
    e.err = (err as Error).message;
  } finally {
    e.busy = false;
  }
}
const resume = () => act(() => api.resumeQueue(), () => "You resumed the queue."
  + (schedule.value?.nextRunAt ? ` Queued jobs start at the next run time, ${whenLabel(schedule.value.nextRunAt)}.` : ""));

// ---- per-job run controls (schedulers; UI mockup runsAtCell) ----
const nm = (j: Job) => `“${j.name || "Untitled job"}”`;
const runNow = (j: Job, on: boolean) => act(() => api.runNow(j.id, on), on
  ? `${nm(j)} ${schedule.value?.paused ? "runs next once the queue is resumed." : "runs next, as soon as no job is running."}`
  : `${nm(j)} waits for its turn again.`);
const hold = (j: Job, on: boolean) => act(() => api.hold(j.id, on), on
  ? `${nm(j)} is held and will be skipped until it is released.` : `${nm(j)} was released.`);
const nowInput = () => ptInputValue(Date.now() / 1000);
const untilOf = (j: Job) => j.credentialExpires ?? Date.now() / 1000 + 72 * 3600;
function openRunAt(j: Job) {
  runAtEdit.value = { id: j.id, val: j.runAt ? ptInputValue(j.runAt) : "", err: "" };
}
async function saveRunAt(j: Job) {
  const e = runAtEdit.value;
  if (!e) return;
  const at = parsePtInput(e.val);
  if (at == null) { e.err = "Choose a date and time, or use Clear to return the job to the schedule."; return; }
  try {
    await api.runAt(j.id, at);
    runAtEdit.value = null;
    flash.value = `${nm(j)} runs at ${absLabel(at)} (Pacific time)${schedule.value?.paused ? ", if the queue has been resumed by then" : ""}.`;
    error.value = "";
    await refresh();
  } catch (err) {
    e.err = (err as Error).message;
  }
}
async function clearRunAt(j: Job) {
  const had = !!j.runAt;
  runAtEdit.value = null;
  if (had) await act(() => api.runAt(j.id, null), `${nm(j)} follows the schedule again.`);
}

// drag and drop among the queued jobs (schedulers only)
function onDragOver(e: DragEvent, j: Job) {
  if (!dragId.value || j.status !== "Queued" || !movable.value) return;
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
    <p class="subtitle">Jobs submitted to run, in the order workers pick them up. Queued jobs start at {{ tenant.name }}’s next run time,
      in this order, one job at a time, so each job waits for the ones above it; running jobs stay first.
      <template v-if="scheduler">Drag a job, or use its arrows, to change the order. </template>Editing a queued job moves it to Drafts
      until it is submitted again. Checks are re-run against CollectionSpace each time this list is shown.</p>
    <template v-if="schedule">
      <div v-if="schedule.paused" class="banner warn" role="status">{{ pausedBanner(schedule.paused) }}</div>
      <div class="banner sched-banner">{{ scheduleBanner(schedule) }}</div>
      <div v-if="schedule.alwaysRunTime" class="sub muted sched-hint">Development setting: every moment counts as run time.</div>
      <div v-if="!scheduler" class="sub muted sched-hint">Only BMU schedulers can change the schedule or the order of the queue.</div>
      <div v-if="scheduler" class="sched-tools">
        <button :disabled="!!schedEdit" @click="openSchedule">Schedule settings…</button>
        <button v-if="schedule.paused" @click="resume">Resume queue</button>
        <button v-else :disabled="!!pauseEdit" title="Stop new jobs from starting; a running job finishes"
                @click="pauseEdit = { reason: '', err: '', busy: false }">Pause queue…</button>
      </div>
      <div v-if="scheduler && pauseEdit && !schedule.paused" class="sched-panel">
        <div class="row"><label for="pauseReason">Reason for pausing</label>
          <input id="pauseReason" v-model="pauseEdit.reason" type="text" style="width:320px" maxlength="200" :placeholder="`Shown to everyone in ${tenant.name}`">
          <button :disabled="pauseEdit.busy" @click="pause">Pause</button><button @click="pauseEdit = null">Cancel</button></div>
        <div class="sub muted">A running job finishes; no other job starts until a BMU scheduler resumes the queue. Queued jobs’ sign-in clocks keep running.</div>
        <div v-if="pauseEdit.err" class="msg msg-block">{{ pauseEdit.err }}</div>
      </div>
      <div v-if="scheduler && schedEdit" class="sched-panel" aria-label="Schedule settings">
        <strong>Schedule for {{ tenant.name }}</strong>
        <div class="row days"><span>Run days</span>
          <label v-for="d in DAY_ORDER" :key="d"><input type="checkbox" class="sched-day" :checked="schedEdit.days.includes(d)"
                 @change="toggleDay(d, ($event.target as HTMLInputElement).checked)"> {{ DAY_NAMES[d] }}</label></div>
        <div class="row"><label for="schedStart">Start time</label><input id="schedStart" v-model="schedEdit.start" type="time">
          <label><input v-model="schedEdit.endOn" type="checkbox" class="sched-end-on"> Don’t start new jobs after</label>
          <input v-model="schedEdit.end" type="time" aria-label="End time" class="sched-end" :disabled="!schedEdit.endOn">
          <span class="sub muted">Pacific time</span></div>
        <div class="sub muted">Run days can’t be more than 3 days apart: a queued job’s saved sign-in lasts 72 hours. An end time may be after midnight.</div>
        <div v-if="schedEdit.err" class="msg msg-block">{{ schedEdit.err }}</div>
        <div class="row"><button class="primary" :disabled="schedEdit.busy" @click="saveSchedule">Save</button><button @click="schedEdit = null">Cancel</button></div>
      </div>
    </template>
    <div v-if="error" class="msg msg-block">{{ error }}</div>
    <div v-if="flash" class="msg msg-info">{{ flash }}</div>
    <div v-if="jobs.length" class="list-tools"><button class="link" @click="expandAll(true)">Expand all</button> ·
      <button class="link" @click="expandAll(false)">Collapse all</button></div>
    <div v-if="sortedView" class="msg msg-info">Sorted view. The queue still runs in its own order;
      <button class="link" @click="table.sort = null">clear the sort</button> to {{ scheduler ? "drag or move jobs" : "see it in run order" }}.</div>
    <div class="table-wrap">
      <table class="queue">
        <thead><tr><th style="width:40px"></th><SortTh :state="table" sort-key="order" label="Order" style="width:96px" /><SortTh :state="table" sort-key="name" label="Job" />
          <SortTh :state="table" sort-key="docs" label="Docs" style="width:64px" /><SortTh :state="table" sort-key="checks" label="Checks now" style="width:170px" />
          <SortTh :state="table" sort-key="scheduled" label="Submitted" style="width:150px" /><SortTh :state="table" sort-key="runs" label="Runs at" style="width:190px" />
          <SortTh :state="table" sort-key="status" label="Status" style="width:190px" /><th style="width:250px"></th></tr></thead>
        <tbody>
          <tr v-if="!jobs.length"><td colspan="9" class="muted" style="text-align:center;padding:18px">No jobs in the queue. Create one in Create / edit job and submit it.</td></tr>
          <template v-for="j in running" :key="j.id">
          <tr title="Running jobs stay first">
            <td><button class="chevron" :class="{ open: expanded.has(j.id) }" :aria-expanded="expanded.has(j.id)"
                        :aria-label="`Show details of ${j.name || 'Untitled job'}`" @click="toggle(j)"><ChevronIcon /></button></td>
            <td><span class="run-spin" role="img" aria-label="Running" title="Running"></span> {{ running.indexOf(j) + 1 }}</td>
            <td>{{ j.name || "Untitled job" }}<div v-if="(j.run ?? 0) > 1" class="sub">rerun (run {{ j.run }})</div></td>
            <td>{{ j.rowCount }}</td>
            <td><span class="sub">—</span></td>
            <td>{{ formatTime(j.queuedAt) }}<div class="sub">by {{ j.scheduledBy }}</div></td>
            <td class="runs-at">Running</td>
            <td>
              <span class="badge b-ok">Running</span>
              <div class="sub">{{ j.progress?.done ?? 0 }} done · {{ j.progress?.failed ?? 0 }} failed ·
                {{ (j.progress?.total ?? 0) - (j.progress?.done ?? 0) - (j.progress?.failed ?? 0) }} to go</div>
              <div class="progress"><span class="ok" :style="{ width: pct(j, 'done') + '%' }"></span><span class="bad" :style="{ width: pct(j, 'failed') + '%' }"></span></div>
              <div v-if="j.cancelRequested" class="sub lock">Cancelling after the document in progress…</div>
              <RunNow v-else :job="j" />
            </td>
            <td>
              <JobActions :job="j" kind="queue" :edit-why="editWhy" :user="user" :scheduler="scheduler"
                          @open="(id, m) => emit('open', id, m)" @done="done" @error="error = $event" />
            </td>
          </tr>
          <tr v-if="expanded.has(j.id)" class="detail"><td colspan="9">
            <JobDocs :job="j" :rows="docs.get(j.id)" :tenant="tenant" kind="queue" @preview="emit('open', j.id, 'preview')" /></td></tr>
          </template>
          <template v-for="j in shownQueued" :key="j.id">
          <tr :draggable="movable" :class="{ draggable: movable, dragging: dragId === j.id, 'drop-before': dropAt?.id === j.id && !dropAt.after, 'drop-after': dropAt?.id === j.id && dropAt.after }"
              :title="movable ? 'Drag to change the order' : ''"
              @dragstart="dragId = movable ? j.id : null" @dragend="dragId = null; dropAt = null" @dragover="onDragOver($event, j)" @drop.prevent="onDrop">
            <td><button class="chevron" :class="{ open: expanded.has(j.id) }" :aria-expanded="expanded.has(j.id)"
                        :aria-label="`Show details of ${j.name || 'Untitled job'}`" @click="toggle(j)"><ChevronIcon /></button></td>
            <td><span v-if="canReorder" class="grip" aria-hidden="true">⋮⋮</span> {{ running.length + queued.indexOf(j) + 1 }}
              <span v-if="canReorder" class="order-btns">
                <button :disabled="sortedView || queued.indexOf(j) === 0" :aria-label="`Move ${j.name} up`" @click="move(j, queued.indexOf(j) - 1)">▲</button>
                <button :disabled="sortedView || queued.indexOf(j) === queued.length - 1" :aria-label="`Move ${j.name} down`" @click="move(j, queued.indexOf(j) + 1)">▼</button>
              </span></td>
            <td>{{ j.name || "Untitled job" }}<div v-if="(j.run ?? 0) > 0" class="sub">rerun (run {{ (j.run ?? 0) + 1 }})</div></td>
            <td>{{ j.rowCount }}</td>
            <td>
              <span v-if="checks.get(j.id)" class="badge" :class="checks.get(j.id)!.block ? 'b-danger' : checks.get(j.id)!.warn ? 'b-warn' : 'b-ok'">
                {{ checksText(checks.get(j.id)!) }}</span>
              <span v-else class="badge b-muted">Checking…</span>
              <div v-if="changed(j)" class="sub lock" title="The checks found something different from when the job was submitted">Changed since submitted</div>
            </td>
            <td>{{ formatTime(j.queuedAt) }}<div class="sub">by {{ j.scheduledBy }}</div>
              <div v-if="signIn(j)" class="sub" :class="{ lock: signIn(j)!.soon }"
                   :title="`If the job hasn't started by then, its saved sign-in is deleted and it moves to Drafts`">
                {{ signIn(j)!.soon ? "⚠ sign-in expires in" : "sign-in kept" }} ~{{ signIn(j)!.hours }} h</div></td>
            <td class="runs-at">{{ runsOf(j).text }}
              <div v-if="runsOf(j).sub" class="sub">{{ runsOf(j).sub }}</div>
              <div v-if="runsOf(j).warn" class="sub lock" :title="`Its saved sign-in expires ${j.credentialExpires ? absLabel(j.credentialExpires) : ''}; if the job hasn’t started by then, it moves to Drafts`">
                ⚠ sign-in expires before its run time</div>
              <template v-if="scheduler">
                <template v-if="runAtEdit?.id === j.id">
                  <div class="runat-edit">
                    <input v-model="runAtEdit.val" type="datetime-local" :aria-label="`Run time for ${j.name || 'Untitled job'} (Pacific time)`"
                           :min="nowInput()" :max="ptInputValue(untilOf(j))">
                    <button @click="saveRunAt(j)">Save</button>
                    <button title="Return the job to the tenant’s schedule" @click="clearRunAt(j)">Clear</button>
                    <button @click="runAtEdit = null">Cancel</button>
                  </div>
                  <div class="sub">Pacific time; no later than {{ absLabel(untilOf(j)) }}, when its sign-in expires.</div>
                  <div v-if="runAtEdit.err" class="msg msg-block">{{ runAtEdit.err }}</div>
                </template>
                <div v-else class="run-acts">
                  <button v-if="j.runNow" class="link" title="Let the job wait for its turn again" @click="runNow(j, false)">Undo Run now</button>
                  <button v-else class="link" title="Start this job as soon as no job is running, ahead of the queue order, even outside the run times (but not while the queue is paused)"
                          @click="runNow(j, true)">Run now</button>
                  <button class="link" title="Give this job its own run time, between now and when its sign-in expires" @click="openRunAt(j)">Set run time…</button>
                  <button v-if="j.held" class="link" title="Let the job run again at its turn" @click="hold(j, false)">Release</button>
                  <button v-else class="link" title="Skip this job until it is released; its sign-in clock keeps running" @click="hold(j, true)">Hold</button>
                </div>
              </template>
            </td>
            <td><span class="badge b-accent">Queued</span></td>
            <td>
              <JobActions :job="j" kind="queue" :edit-why="editWhy" :user="user" :scheduler="scheduler"
                          @open="(id, m) => emit('open', id, m)" @done="done" @error="error = $event" />
            </td>
          </tr>
          <tr v-if="expanded.has(j.id)" class="detail"><td colspan="9">
            <JobDocs :job="j" :rows="docs.get(j.id)" :tenant="tenant" kind="queue" @preview="emit('open', j.id, 'preview')" /></td></tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>
