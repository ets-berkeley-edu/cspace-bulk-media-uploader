<script setup lang="ts">
/**
 * A job's read-only preview, inside the Drafts or Job queue tab it was opened from (design: Drafts, scheduling
 * and the job queue; UI mockup renderPreview). It never touches the draft open in Create / edit job. Checks are
 * re-run against CollectionSpace when it opens (Check again repeats them); a running job's documents show their
 * run state, refreshed while it runs. The action bar has only what applies: Edit or Take over, Delete; Edit and
 * Delete for a queued job; Cancel run for a running one. Nothing to save or schedule here.
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { api, ApiError } from "../api";
import { formatTime } from "../lib/files";
import { worstLevel } from "../lib/status";
import { tableState, tableView } from "../lib/table";
import type { Job, Row, TenantInfo } from "../types";
import JobActions from "./JobActions.vue";
import RunNow from "./RunNow.vue";
import PagerBar from "./PagerBar.vue";
import SortTh from "./SortTh.vue";
import ThumbCell from "./ThumbCell.vue";

/** user, scheduler: for Cancel run (design: Job scheduling). */
const props = defineProps<{ jobId: string; from: "drafts" | "queue"; tenant: TenantInfo; editWhy?: string; user?: string; scheduler?: boolean }>();
const emit = defineEmits<{ back: []; open: [id: string, mode: "edit" | "preview", takeOverSince?: number] }>();

const job = ref<Job | null>(null);
const rows = ref<Row[]>([]);
const error = ref("");
const gone = ref("");
const checking = ref(false);
const checkedAt = ref<number | null>(null);
let timer: ReturnType<typeof setInterval> | undefined;

const backLabel = computed(() => (props.from === "drafts" ? "← Back to Drafts" : "← Back to Job queue"));
const running = computed(() => job.value?.status === "Running");
const draft = computed(() => job.value?.status === "Draft");
/** Still in the tab it was opened from: a draft in Drafts, a queued or running job in Job queue. */
const inTab = computed(() => !!job.value && (props.from === "drafts" ? draft.value : ["Queued", "Running"].includes(job.value.status)));

async function load(poll = false) {
  try {
    const r = await api.job(props.jobId, poll);
    job.value = r.job;
    // Checked rows stay until the next check; a running job's rows show its progress.
    if (!rows.value.length || running.value || r.job.status !== "Draft" && r.job.status !== "Queued") rows.value = r.rows;
    error.value = "";
    return r.job;
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) { gone.value = "This job was deleted."; job.value = null; clearInterval(timer); }
    else error.value = (e as Error).message;
    return null;
  }
}
async function check() {
  if (!job.value || !["Draft", "Queued"].includes(job.value.status)) return;
  checking.value = true;
  try {
    rows.value = (await api.check(props.jobId)).rows;
    checkedAt.value = Date.now() / 1000;
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    checking.value = false;
  }
}
onMounted(async () => {
  if (await load()) await check();
  timer = setInterval(() => void load(true), running.value ? 3000 : 5000);
});
onBeforeUnmount(() => clearInterval(timer));

/** After an action here: a deleted job goes back to the list; otherwise show the job as it is now. */
async function done() {
  if (!(await load()) && gone.value) emit("back");
}

// ---- the documents: paging, sorting and the Show filter (design: User interface, Large jobs) ----
const handlingLabel = (r: Row) => props.tenant.handling.find((h) => h.id === r.handling)?.label ?? r.handling;
const linked = (r: Row) => props.tenant.handling.find((h) => h.id === r.handling)?.object !== "none";
const LEVEL_RANK = { block: 0, warn: 1, ok: 2 } as const;
const RUN_RANK: Record<string, number> = { "In progress": 0, Failed: 1, Partial: 1, "Not started": 2, Done: 3 };
const RUN_BADGE: Record<string, string> = { "In progress": "b-accent", Done: "b-ok", Partial: "b-warn", Failed: "b-danger", "Not started": "b-muted" };
const runState = (r: Row) => r.result?.state ?? "Not started";
const table = tableState();
function docFilter(r: Row, f: string): boolean {
  const lv = worstLevel(r);
  switch (f) {
    case "problems": return r.include && lv !== "ok";
    case "block": return r.include && lv === "block";
    case "warn": return r.include && lv === "warn";
    case "protected": return !!r.protected;
    case "excluded": return !r.include;
    default: return true;
  }
}
const view = computed(() => tableView(rows.value, table, {
  file: (r) => r.file, handling: handlingLabel, id: (r) => r.idnum, obj: (r) => (linked(r) ? r.obj : ""), date: (r) => r.date || "~",
  run: (r) => RUN_RANK[runState(r)] ?? 4, checks: (r) => (!r.include ? 3 : LEVEL_RANK[worstLevel(r)]),
}, docFilter));
const filters = computed<[string, string][]>(() => {
  const n = (f: string) => rows.value.filter((r) => docFilter(r, f)).length;
  return [["all", `All documents (${rows.value.length})`], ["problems", `With problems (${n("problems")})`], ["block", `Need fixing (${n("block")})`],
    ["warn", `With warnings (${n("warn")})`], ["protected", `Protected (${n("protected")})`], ["excluded", `Excluded (${n("excluded")})`]];
});
const counts = computed(() => {
  const work = rows.value.filter((r) => r.include && r.result?.state !== "Done");
  return { block: work.filter((r) => worstLevel(r) === "block").length, warn: work.filter((r) => worstLevel(r) === "warn").length };
});
const shownChecks = (r: Row) => r.checks.filter((c) => c.level !== "info");
const handlingMix = computed(() => {
  const m = new Map<string, number>();
  rows.value.forEach((r) => m.set(handlingLabel(r), (m.get(handlingLabel(r)) ?? 0) + 1));
  return [...m].map(([k, n]) => `${n} ${k.toLowerCase()}`).join(", ") || "—";
});
const expires = computed(() => job.value?.expiresAt
  ? new Date(job.value.expiresAt * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "—");
function checksText(c: { block: number; warn: number }) {
  const parts = [c.block ? `${c.block} need${c.block === 1 ? "s" : ""} fixing` : "nothing to fix"];
  if (c.warn) parts.push(`${c.warn} warning${c.warn === 1 ? "" : "s"}`);
  return parts.join(" · ");
}
</script>

<template>
  <div class="job-preview">
    <button class="link" @click="emit('back')">{{ backLabel }}</button>
    <div v-if="gone" class="msg msg-info">{{ gone }}</div>
    <p v-else-if="!job" class="muted">{{ error || "Loading…" }}</p>
    <template v-else>
      <h2 class="results-title">{{ job.name || "Untitled job" }}
        <span class="badge" :class="running ? 'b-ok' : draft ? 'b-warn' : 'b-accent'">{{ job.status }}<template
          v-if="job.status === 'Queued' && (job.run ?? 0) > 0"> — rerun (run {{ (job.run ?? 0) + 1 }})</template></span></h2>
      <div class="sub" style="margin-bottom:8px">Read-only preview.
        <template v-if="running && job.progress">{{ job.progress.done }} done · {{ job.progress.failed }} failed ·
          {{ job.progress.total - job.progress.done - job.progress.failed }} to go.</template>
        <template v-else-if="checking">Checking against CollectionSpace…</template>
        <template v-else-if="checkedAt">Checks were re-run against CollectionSpace at {{ formatTime(checkedAt) }}.
          <button class="link" @click="check">Check again</button></template>
      </div>
      <RunNow v-if="running" :job="job" style="margin:-4px 0 10px;max-width:420px" />
      <div v-if="!inTab" class="msg msg-info">This job is now {{ job.status === "NeedsAttention" ? "Needs attention" : job.status }}, so it's no longer in
        {{ from === "drafts" ? "Drafts" : "the job queue" }}.</div>
      <div v-if="error" class="msg msg-block">{{ error }}</div>
      <div class="jd-meta">
        <span><strong>Documents</strong> {{ rows.length }}</span>
        <span><strong>Handling</strong> {{ handlingMix }}</span>
        <span><strong>Group title</strong> {{ job.groupOn ? job.groupTitle || "—" : "None" }}</span>
        <span><strong>Created by</strong> {{ job.createdBy }}</span>
        <template v-if="draft">
          <span><strong>Last saved</strong> {{ formatTime(job.lastSavedAt) }} by {{ job.lastSavedBy || "—" }}</span>
          <span><strong>Being edited</strong> {{ job.editingBy ? `${job.editingByYou ? "By you" : `By ${job.editingBy}`} since ${formatTime(job.editingSince)}` : "No one" }}</span>
          <span><strong>Expires</strong> {{ expires }}</span>
        </template>
        <template v-else>
          <span><strong>Submitted</strong> {{ formatTime(job.queuedAt) }} by {{ job.scheduledBy || "—" }}</span>
          <span v-if="job.checksAtSchedule"><strong>At submission</strong> {{ checksText(job.checksAtSchedule) }}</span>
        </template>
        <span v-if="!running && checkedAt"><strong>Checks now</strong>
          <span class="badge" :class="counts.block ? 'b-danger' : counts.warn ? 'b-warn' : 'b-ok'">{{ checksText(counts) }}</span></span>
      </div>
      <div v-if="job.note" class="msg msg-warn">{{ job.note }}</div>
      <div v-if="counts.block && job.status === 'Queued'" class="msg msg-block" role="alert">Something changed in CollectionSpace since this job was
        submitted: {{ counts.block }} document{{ counts.block === 1 ? " now needs" : "s now need" }} fixing. Edit the job to fix
        {{ counts.block === 1 ? "it" : "them" }} before it runs.</div>
      <div v-if="counts.block && draft" class="banner">This draft has {{ counts.block }} document{{ counts.block === 1 ? "" : "s" }} that
        need{{ counts.block === 1 ? "s" : "" }} fixing before it can be submitted.</div>

      <PagerBar :state="table" :total="view.total" :of="view.of" :pages="view.pages" :start="view.start" noun="documents" :filters="filters" />
      <div class="table-wrap">
        <table>
          <thead><tr><th style="width:64px"><span class="sr-only">Preview</span></th>
            <SortTh :state="table" sort-key="file" label="Document" /><SortTh :state="table" sort-key="handling" label="Handling" style="width:170px" />
            <SortTh :state="table" sort-key="id" label="Identification number" style="width:150px" />
            <SortTh :state="table" sort-key="obj" label="Object" style="width:110px" /><SortTh :state="table" sort-key="date" label="Date" style="width:100px" />
            <SortTh v-if="running" :state="table" sort-key="run" label="Run state" style="width:110px" />
            <SortTh :state="table" sort-key="checks" label="Checks now" style="width:260px" /></tr></thead>
          <tbody>
            <tr v-if="!view.shown.length"><td :colspan="running ? 8 : 7" class="muted" style="text-align:center;padding:18px">{{ rows.length ? "No documents match this filter." : "No documents." }}</td></tr>
            <tr v-for="r in view.shown" :key="r.n" :class="{ disabled: !r.include }">
              <td><ThumbCell :job-id="job.id" :row="r" /></td>
              <td>{{ r.file }}<span v-if="!r.include" class="badge b-accent" style="margin-left:6px">Excluded</span><span
                v-if="r.protected" class="badge b-danger" style="margin-left:6px" :title="`Protected file: ${r.protected.reason}`">🔒 Protected</span></td>
              <td>{{ handlingLabel(r) }}</td>
              <td>{{ r.idnum || "—" }}</td>
              <td>{{ linked(r) ? r.obj || "—" : "—" }}</td>
              <td>{{ r.date || "—" }}</td>
              <td v-if="running"><span class="badge" :class="RUN_BADGE[runState(r)] ?? 'b-muted'">{{ runState(r) }}</span></td>
              <td>
                <span v-if="r.result?.state === 'Done'" class="badge b-ok">Done in last run</span>
                <template v-else-if="shownChecks(r).length">
                  <div v-for="(c, i) in shownChecks(r)" :key="i" class="msg" :class="`msg-${c.level}`"><strong>{{ c.level === "block" ? "Must fix:" : "Warning:" }}</strong> {{ c.text }}</div>
                </template>
                <span v-else class="badge b-ok">OK</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <PagerBar :state="table" :total="view.total" :of="view.of" :pages="view.pages" :start="view.start" noun="documents" bottom />
      <div v-if="inTab" class="schedule-bar">
        <span class="spacer"></span>
        <JobActions :job="job" :kind="from" in-preview :edit-why="editWhy" :user="user" :scheduler="scheduler" @open="(id, m, since) => emit('open', id, m, since)"
                    @done="done" @error="error = $event" />
      </div>
    </template>
  </div>
</template>
