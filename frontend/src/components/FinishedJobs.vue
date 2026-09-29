<script setup lang="ts">
/**
 * The Finished jobs tab (design: Finished jobs and error messages): jobs that have run, newest first, with
 * their outcome, documents by result, when they finished and who ran them. View results shows every
 * document; Fix and reschedule (or Reschedule, when every failure only needs another run) moves a job that
 * needs attention or failed to Drafts; Delete removes it from the BMU (never from CollectionSpace).
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { api } from "../api";
import { formatTime } from "../lib/files";
import { countsText, createdText, failureOf, importantRows, loadFailures, needsFix, OUTCOME, RESULT_BADGE, resultState, rowCodes } from "../lib/results";
import type { Created, Job, Row, Run, TenantInfo } from "../types";
import JobResults from "./JobResults.vue";
import ThumbCell from "./ThumbCell.vue";
import SortTh from "./SortTh.vue";
import { tableState, tableView } from "../lib/table";

const props = defineProps<{ tenant: TenantInfo }>();
const emit = defineEmits<{ open: [id: string] }>();

const FINISHED = ["Completed", "NeedsAttention", "Failed"];
const jobs = ref<Job[]>([]);
const error = ref("");
const flash = ref("");
const details = reactive(new Map<string, { rows: Row[]; runs: Run[]; created: Created }>());
const expanded = reactive(new Set<string>());
const blocking = reactive(new Map<string, number>()); // documents that fail a blocking check now
const resultsId = ref<string | null>(null);
const confirmDelete = ref<string | null>(null);
const busy = ref(false);
let timer: ReturnType<typeof setInterval> | undefined;

const table = tableState();
const OUT_RANK: Record<string, number> = { Failed: 0, NeedsAttention: 1, Completed: 2 };
const newestFirst = computed(() => [...jobs.value].sort((a, b) => (b.finishedAt ?? b.updated) - (a.finishedAt ?? a.updated)));
const sorted = computed(() => tableView(newestFirst.value, table, {
  name: (j) => j.name || "Untitled job",
  outcome: (j) => OUT_RANK[j.status] ?? 3,
  docs: (j) => j.rowCount,
  finished: (j) => -(j.finishedAt ?? 0),
}, undefined, false).shown);
const open = computed(() => jobs.value.find((j) => j.id === resultsId.value) ?? null);

async function load(id: string) {
  const r = await api.job(id);
  details.set(id, { rows: r.rows, runs: r.runs, created: r.created });
  return r;
}

async function refresh(runChecks = false) {
  try {
    jobs.value = (await api.jobs()).jobs.filter((j) => FINISHED.includes(j.status));
    error.value = "";
    for (const id of [...expanded, ...(resultsId.value ? [resultsId.value] : [])]) {
      if (jobs.value.some((j) => j.id === id)) await load(id);
    }
  } catch (e) {
    error.value = (e as Error).message;
  }
  if (runChecks) {
    // Design: the button reads Fix and reschedule when a document fails a blocking check now, so the jobs that
    // can be rerun are checked against CollectionSpace as it is now; their results decide the label.
    for (const j of jobs.value.filter((x) => x.status !== "Completed")) {
      if (!details.has(j.id)) load(j.id).catch(() => undefined);
      api.check(j.id).then((r) => blocking.set(j.id, r.counts.block)).catch(() => undefined);
    }
  }
}
onMounted(() => { loadFailures(); refresh(true); timer = setInterval(() => refresh(false), 4000); });
onBeforeUnmount(() => clearInterval(timer));

function fixLabel(j: Job): "Fix and reschedule" | "Reschedule" {
  return needsFix(j, details.get(j.id)?.rows ?? [], blocking.get(j.id) ?? 0) ? "Fix and reschedule" : "Reschedule";
}
function fixTitle(j: Job) {
  return fixLabel(j) === "Reschedule"
    ? "Nothing needs changing: every failure only needs another run. Opens the job in Drafts so you can schedule it again."
    : "Opens the job in Drafts to fix the documents that need it, then schedule it again.";
}

async function toggle(j: Job) {
  if (expanded.has(j.id)) { expanded.delete(j.id); return; }
  expanded.add(j.id);
  if (!details.has(j.id)) await load(j.id).catch((e) => (error.value = (e as Error).message));
}
function expandAll(on: boolean) {
  if (!on) { expanded.clear(); return; }
  for (const j of jobs.value) { expanded.add(j.id); if (!details.has(j.id)) load(j.id).catch(() => undefined); }
}

async function viewResults(j: Job) {
  resultsId.value = j.id;
  if (!details.has(j.id)) await load(j.id).catch((e) => (error.value = (e as Error).message));
}

async function fix(j: Job) {
  busy.value = true;
  try {
    await api.fix(j.id);
    emit("open", j.id);
  } catch (e) {
    error.value = (e as Error).message;
    await refresh();
  } finally {
    busy.value = false;
  }
}

async function askDelete(j: Job) {
  confirmDelete.value = j.id;
  if (!details.has(j.id)) await load(j.id).catch(() => undefined);
}
async function del(j: Job) {
  try {
    await api.deleteJob(j.id);
    confirmDelete.value = null;
    if (resultsId.value === j.id) resultsId.value = null;
    flash.value = `Deleted “${j.name || "Untitled job"}” from the BMU. Records its runs created stay in CollectionSpace; the audit log lists them.`;
    await refresh();
  } catch (e) {
    error.value = (e as Error).message;
  }
}
function removedOn(j: Job) {
  return j.expiresAt ? new Date(j.expiresAt * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "in 30 days";
}
function mainMessage(r: Row): string {
  const s = resultState(r);
  if (s === "Disabled") return `Disabled by ${r.disabledBy || "a user"}`;
  if (s === "Done") return "Created in CollectionSpace";
  if (s === "Not started") return "Not reached before the job stopped";
  const code = rowCodes(r)[0];
  return code ? failureOf(code).title : "";
}
</script>

<template>
  <div>
    <template v-if="open">
      <button class="link" @click="resultsId = null">← Back to finished jobs</button>
      <h2 class="results-title">{{ open.name || "Untitled job" }}
        <span class="badge" :class="OUTCOME[open.status]?.cls">{{ OUTCOME[open.status]?.text ?? open.status }}</span></h2>
      <div v-if="error" class="msg msg-block">{{ error }}</div>
      <p v-if="!details.get(open.id)" class="muted">Loading…</p>
      <JobResults v-else :job="open" :rows="details.get(open.id)!.rows" :runs="details.get(open.id)!.runs" :tenant="props.tenant" />
      <div class="schedule-bar">
        <span class="spacer"></span>
        <template v-if="open.status !== 'Completed'">
          <div v-if="confirmDelete === open.id" class="msg msg-warn delete-confirm">
            <template v-if="details.get(open.id)?.created && (details.get(open.id)!.created.media || details.get(open.id)!.created.objects)">
              Delete this job from the BMU? Its runs created {{ createdText(details.get(open.id)!.created) }}<template v-if="details.get(open.id)!.created.unfinished">, including {{ details.get(open.id)!.created.unfinished }} unfinished document(s)</template>.
              They stay in CollectionSpace; the BMU never deletes records. The audit log keeps every CSID.
            </template>
            <template v-else>Delete this job? It created nothing in CollectionSpace.</template>
            <button @click="del(open)">Delete job</button> <button @click="confirmDelete = null">Cancel</button>
          </div>
          <template v-else>
            <button class="primary" :disabled="busy" :title="fixTitle(open)" @click="fix(open)">{{ fixLabel(open) }}</button>
            <button @click="askDelete(open)">Delete</button>
          </template>
        </template>
        <span v-else class="sub">Removed {{ removedOn(open) }}</span>
      </div>
    </template>

    <template v-else>
      <p class="subtitle">Jobs that have run, newest first. Completed jobs are removed 30 days after they finish. Jobs that need
        attention or failed stay until someone fixes and reruns them or deletes them; a rerun skips everything already created in
        CollectionSpace.</p>
      <div v-if="flash" class="msg msg-info" role="status">{{ flash }}</div>
      <div v-if="error" class="msg msg-block">{{ error }}</div>
      <div v-if="sorted.length" class="list-tools"><button class="link" @click="expandAll(true)">Expand all</button> ·
        <button class="link" @click="expandAll(false)">Collapse all</button></div>
      <div class="table-wrap">
        <table>
          <thead><tr><th style="width:28px"></th><SortTh :state="table" sort-key="name" label="Job" />
            <SortTh :state="table" sort-key="outcome" label="Outcome" style="width:150px" /><SortTh :state="table" sort-key="docs" label="Documents" />
            <SortTh :state="table" sort-key="finished" label="Finished" style="width:140px" class="hide-narrow" /><th style="width:270px"></th></tr></thead>
          <tbody>
            <tr v-if="!sorted.length"><td colspan="6" class="muted" style="text-align:center;padding:18px">No finished jobs yet.</td></tr>
            <template v-for="j in sorted" :key="j.id">
              <tr>
                <td><button class="chevron" :class="{ open: expanded.has(j.id) }" :aria-expanded="expanded.has(j.id)"
                            :aria-label="`Show details of ${j.name || 'Untitled job'}`" @click="toggle(j)">▸</button></td>
                <td>{{ j.name || "Untitled job" }}<span v-if="j.run > 1" class="sub"> (run {{ j.run }})</span></td>
                <td :title="j.code ? failureOf(j.code).title : ''"><span class="badge" :class="OUTCOME[j.status]?.cls">{{ OUTCOME[j.status]?.text }}</span>
                  <div v-if="j.code" class="sub">{{ failureOf(j.code).title }}</div></td>
                <td>{{ countsText(j.counts) }}</td>
                <td class="hide-narrow" :title="`run by ${j.runBy || j.scheduledBy || '—'}`">{{ formatTime(j.finishedAt) }}<div class="sub">by {{ j.runBy || j.scheduledBy || "—" }}</div></td>
                <td>
                  <div v-if="confirmDelete === j.id" class="msg msg-warn delete-confirm">
                    <template v-if="details.get(j.id)?.created && (details.get(j.id)!.created.media || details.get(j.id)!.created.objects)">
                      Delete this job from the BMU? Its runs created {{ createdText(details.get(j.id)!.created) }}<template v-if="details.get(j.id)!.created.unfinished">, including {{ details.get(j.id)!.created.unfinished }} unfinished document(s)</template>.
                      They stay in CollectionSpace; the BMU never deletes records. The audit log keeps every CSID.
                    </template>
                    <template v-else>Delete this job? It created nothing in CollectionSpace.</template>
                    <button @click="del(j)">Delete job</button> <button @click="confirmDelete = null">Cancel</button>
                  </div>
                  <div v-else class="actions">
                    <button @click="viewResults(j)">View results</button>
                    <template v-if="j.status !== 'Completed'">
                      <button :disabled="busy" :title="fixTitle(j)" @click="fix(j)">{{ fixLabel(j) }}</button>
                      <button @click="askDelete(j)">Delete</button>
                    </template>
                    <span v-else class="sub">Removed {{ removedOn(j) }}</span>
                  </div>
                </td>
              </tr>
              <tr v-if="expanded.has(j.id)" class="detail">
                <td colspan="6">
                  <div class="sub">Run {{ j.run }} scheduled by {{ j.runBy || j.scheduledBy || "—" }} · started {{ formatTime(j.startedAt) }} · finished {{ formatTime(j.finishedAt) }}
                    <template v-if="j.cancelledBy"> · cancelled by {{ j.cancelledBy }}</template></div>
                  <p v-if="!details.get(j.id)" class="muted">Loading…</p>
                  <table v-else class="inner">
                    <tbody>
                      <tr v-for="r in importantRows(details.get(j.id)!.rows)" :key="r.n">
                        <td style="width:64px"><ThumbCell :job-id="j.id" :row="r" /></td><td style="width:36px">{{ r.n }}</td><td>{{ r.file }}</td>
                        <td style="width:110px"><span class="badge" :class="RESULT_BADGE[resultState(r)]">{{ resultState(r) }}</span></td>
                        <td class="sub">{{ mainMessage(r) }}</td>
                      </tr>
                    </tbody>
                  </table>
                  <button class="link" @click="viewResults(j)">View all {{ j.rowCount }} documents' results</button>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>
