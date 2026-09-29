<script setup lang="ts">
/**
 * View results (design: Results view): every document with its result, each step's outcome and the CSIDs
 * created, the run that did each step, and for each failure what happened and what to do. The run history
 * lists every run, newest first, with the documents disabled or deleted before it.
 */
import { computed } from "vue";
import { formatTime } from "../lib/files";
import { countsText, failureOf, OUTCOME, RESULT_BADGE, resultCounts, resultState, stepList, STEP_MARK, stepNote } from "../lib/results";
import type { Job, Row, Run, TenantInfo } from "../types";
import ErrorBox from "./ErrorBox.vue";
import PagerBar from "./PagerBar.vue";
import SortTh from "./SortTh.vue";
import { tableState, tableView } from "../lib/table";

const props = defineProps<{ job: Job; rows: Row[]; runs: Run[]; tenant: TenantInfo }>();

type Filter = "all" | "problems" | "failed" | "partial" | "notStarted" | "disabled" | "done";
const table = tableState();
const c = computed(() => resultCounts(props.rows));
const FILTERS = computed<[Filter, string][]>(() => [
  ["all", `All documents (${props.rows.length})`],
  ["problems", `Not finished (${c.value.failed + c.value.partial + c.value.notStarted})`],
  ["failed", `Failed (${c.value.failed})`], ["partial", `Partial (${c.value.partial})`],
  ["notStarted", `Not started (${c.value.notStarted})`], ["disabled", `Disabled (${c.value.disabled})`], ["done", `Done (${c.value.done})`],
]);
const RANK: Record<string, number> = { Failed: 0, Partial: 1, "In progress": 2, "Not started": 2, Disabled: 3, Done: 4 };
const keys = {
  n: (r: Row) => r.n,
  file: (r: Row) => r.file,
  result: (r: Row) => RANK[resultState(r)] ?? 5,
  steps: (r: Row) => { const st = Object.values(r.result?.steps ?? {}); return st.filter((x) => x.s === "done").length - st.length; },
  what: (r: Row) => (r.result?.error ? failureOf(r.result.error.code).title : "~"),
};
const view = computed(() => tableView(props.rows, table, keys, (r, f) => {
  const s = resultState(r);
  switch (f) {
    case "problems": return s === "Failed" || s === "Partial" || s === "Not started" || s === "In progress";
    case "failed": return s === "Failed";
    case "partial": return s === "Partial";
    case "notStarted": return s === "Not started" || s === "In progress";
    case "disabled": return s === "Disabled";
    case "done": return s === "Done";
    default: return true;
  }
}));
const handlingLabel = (r: Row) => props.tenant.handling.find((h) => h.id === r.handling)?.label ?? r.handling;
const newestFirst = computed(() => [...props.runs].sort((a, b) => b.run - a.run));
const outcome = (o: string) => OUTCOME[o] ?? { text: o, cls: "b-muted" };
const earlierProblem = (r: Row) => r.result?.error?.code;
</script>

<template>
  <div>
    <div class="sub" style="margin:4px 0 8px">Run {{ job.run }}, finished {{ formatTime(job.finishedAt) }} (run by {{ job.runBy || job.scheduledBy }}). {{ countsText(job.counts ?? c) }}.</div>

    <div v-if="runs.length" class="runs">
      <div class="section-title">Run history (newest first)</div>
      <div v-for="rn in newestFirst" :key="rn.run" class="msg" :class="rn.outcome === 'Completed' ? 'msg-info' : 'msg-warn'">
        <strong>Run {{ rn.run }}: {{ outcome(rn.outcome).text }}<template v-if="rn.code"> — {{ failureOf(rn.code).title }}</template></strong>
        <template v-if="rn.counts"> · {{ countsText(rn.counts) }}</template>
        <div class="sub">Scheduled by {{ rn.scheduledBy || "—" }}<template v-if="rn.scheduledAt"> ({{ formatTime(rn.scheduledAt) }})</template>
          · started {{ formatTime(rn.startedAt) }} · ended {{ rn.endedAt ? formatTime(rn.endedAt) : "—" }}</div>
        <div v-if="rn.cancelledBy" class="sub">Cancelled by {{ rn.cancelledBy }}<template v-if="rn.cancelledAt"> ({{ formatTime(rn.cancelledAt) }})</template></div>
        <div v-if="rn.disabledBefore?.length || rn.deletedBefore?.length" class="sub">Before this run:
          <template v-for="(d, i) in rn.disabledBefore ?? []" :key="'d' + i">{{ i ? "; " : "" }}{{ d.file }} disabled by {{ d.by || "a user" }}</template>
          <template v-for="(d, i) in rn.deletedBefore ?? []" :key="'x' + i">{{ i || rn.disabledBefore?.length ? "; " : "" }}{{ d.file }} deleted by {{ d.by }}</template>
        </div>
      </div>
    </div>

    <div v-if="job.groupOn" class="sub" style="margin:4px 0">Group “{{ job.groupTitle }}”:
      <template v-if="job.groupStep?.s === 'done'">created in run {{ job.groupStep.run }} (<code>{{ job.groupStep.csid }}</code>)</template>
      <template v-else-if="job.groupStep?.s === 'failed'">couldn't be created in run {{ job.groupStep.run }}</template>
      <template v-else>not created (no document reached the point of joining it)</template></div>
    <div v-if="job.code" style="margin:8px 0"><ErrorBox :code="job.code" :detail="job.cancelledBy ? `Cancel requested by ${job.cancelledBy}` : job.code === 'group_failed' ? job.groupStep?.detail : undefined" /></div>

    <PagerBar :state="table" :total="view.total" :of="view.of" :pages="view.pages" :start="view.start" noun="documents" :filters="FILTERS" />
    <div class="table-wrap">
      <table>
        <thead><tr><SortTh :state="table" sort-key="n" label="#" style="width:44px" /><SortTh :state="table" sort-key="file" label="Document" style="min-width:150px" />
          <SortTh :state="table" sort-key="result" label="Result" style="width:110px" />
          <SortTh :state="table" sort-key="steps" label="Steps" style="width:300px" title="Sort by how many steps are done" />
          <SortTh :state="table" sort-key="what" label="What happened" /></tr></thead>
        <tbody>
          <tr v-if="!view.shown.length"><td colspan="5" class="muted" style="text-align:center;padding:18px">No documents match this filter.</td></tr>
          <tr v-for="r in view.shown" :key="r.n" :class="{ disabled: resultState(r) === 'Disabled' }">
            <td class="keep">{{ r.n }}</td>
            <td>{{ r.file }}<div class="sub">{{ handlingLabel(r) }}<template v-if="r.skipLink"> · not linked (stopped)</template></div></td>
            <td class="keep"><span class="badge" :class="RESULT_BADGE[resultState(r)]">{{ resultState(r) }}</span></td>
            <td class="steps">
              <div v-for="s in stepList(r)" :key="s.key" :class="{ 'step-failed': s.step.s === 'failed' }">
                {{ STEP_MARK[s.step.s] }} {{ s.label }}
                <code v-if="s.step.csid">{{ s.step.csid }}</code>
                <span v-if="stepNote(s.key, s.step)" class="sub"> ({{ stepNote(s.key, s.step) }})</span>
                <span v-if="s.step.s === 'done' && s.step.run" class="sub"> · run {{ s.step.run }}</span>
              </div>
              <span v-if="!stepList(r).length" class="sub">—</span>
            </td>
            <td class="keep">
              <span v-if="resultState(r) === 'Disabled'" class="sub">Disabled by {{ r.disabledBy || "a user" }}<template v-if="r.disabledAt"> ({{ formatTime(r.disabledAt) }})</template>; the BMU ignored it.
                <template v-if="earlierProblem(r)"> Earlier problem: {{ failureOf(earlierProblem(r)).title }}.</template>
                <template v-if="r.result?.steps?.media?.s === 'done'"> Its Media record from an earlier run ({{ r.result.steps.media.csid }}) stays in CollectionSpace, unfinished.</template></span>
              <ErrorBox v-else-if="r.result?.error" :code="r.result.error.code" :detail="r.result.error.detail" />
              <span v-else-if="resultState(r) === 'Not started'" class="sub">Not reached before the job stopped.</span>
              <span v-else-if="resultState(r) === 'Done'" class="sub">Created in CollectionSpace.</span>
              <ErrorBox v-for="(nt, i) in r.result?.notices ?? []" :key="i" :code="nt.code" :detail="nt.detail" notice />
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <PagerBar :state="table" :total="view.total" :of="view.of" :pages="view.pages" :start="view.start" noun="documents" bottom />
  </div>
</template>
