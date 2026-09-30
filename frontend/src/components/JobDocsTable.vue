<script setup lang="ts">
/**
 * The documents of an expanded job in Drafts, Job queue and Finished jobs (design: Job lists; UI mockup
 * jobDocsTable): its 10 most important documents, problems first, one line each with the thumbnail, the
 * document (and its Protected badge), handling, identification number, then Status and the most important issue
 * (Drafts, Job queue) or Result and what happened, with what to do (Finished jobs). Sortable like every table.
 */
import { computed } from "vue";
import { rowStatus, worstLevel } from "../lib/status";
import { failureOf, importantRows, RESULT_BADGE, resultState, rowCodes } from "../lib/results";
import { tableState, tableView } from "../lib/table";
import type { Job, Row, TenantInfo } from "../types";
import SortTh from "./SortTh.vue";
import ThumbCell from "./ThumbCell.vue";

const props = defineProps<{ job: Job; rows: Row[]; tenant: TenantInfo; kind: "drafts" | "queue" | "history" }>();

const LIMIT = 10;
const LEVEL_RANK = { block: 0, warn: 1, ok: 2 } as const;
const RUN_RANK: Record<string, number> = { "In progress": 0, Failed: 1, Partial: 1, "Not started": 2, Done: 3 };
const RUN_BADGE: Record<string, string> = { "In progress": "b-accent", Done: "b-ok", Partial: "b-warn", Failed: "b-danger", "Not started": "b-muted" };
const runView = computed(() => props.kind === "queue" && props.job.status === "Running");
const runState = (r: Row) => (!r.include ? "Excluded" : r.result?.state ?? "Not started");

/** The 10 that matter most: blocking checks, then warnings (Drafts, Job queue); run state while running; results after. */
const top = computed<Row[]>(() => {
  if (props.kind === "history") return importantRows(props.rows, LIMIT);
  const rank = (r: Row) => (runView.value ? RUN_RANK[runState(r)] ?? 4 : r.include ? LEVEL_RANK[worstLevel(r)] : 3);
  return props.rows.map((r, i) => ({ r, i })).sort((a, b) => rank(a.r) - rank(b.r) || a.i - b.i).slice(0, LIMIT).map((x) => x.r);
});

const handlingLabel = (r: Row) => props.tenant.handling.find((h) => h.id === r.handling)?.label ?? r.handling;

function status(r: Row): { text: string; cls: string } {
  if (props.kind === "history") { const s = resultState(r); return { text: s, cls: RESULT_BADGE[s] }; }
  if (runView.value) { const s = runState(r); return { text: s, cls: RUN_BADGE[s] ?? "b-muted" }; }
  return rowStatus(r, props.tenant);
}

/** Drafts, Job queue: the row's most important check. Finished jobs: what happened, and what to do about it. */
function issue(r: Row): string {
  if (props.kind === "history") {
    const s = resultState(r);
    if (s === "Excluded") return `Excluded by ${r.disabledBy || "a user"}; ignored.`;
    const code = rowCodes(r)[0];
    if (code) { const f = failureOf(code); return `${f.title.replace(/\.$/, "")}. ${f.fix}`; }
    if (s === "Not started") return "Not reached before the job stopped.";
    if (s === "Done") return "Created in CollectionSpace.";
    return "";
  }
  if (runView.value) return "";
  const c = r.checks.find((x) => x.level === "block") ?? r.checks.find((x) => x.level === "warn");
  return c ? `${c.level === "block" ? "Must fix: " : "Warning: "}${c.text}` : "";
}

const table = tableState();
const sorted = computed(() => tableView(top.value, table, {
  file: (r) => r.file, handling: handlingLabel, id: (r) => r.idnum, status: (r) => status(r).text, issue: (r) => issue(r) || "~",
}, undefined, false).shown);
</script>

<template>
  <table class="inner jd-docs">
    <thead><tr><th style="width:64px"><span class="sr-only">Preview</span></th>
      <SortTh :state="table" sort-key="file" label="Document" /><SortTh :state="table" sort-key="handling" label="Handling" style="width:170px" />
      <SortTh :state="table" sort-key="id" label="Identification number" style="width:150px" />
      <SortTh :state="table" sort-key="status" :label="kind === 'history' ? 'Result' : 'Status'" style="width:160px" />
      <SortTh :state="table" sort-key="issue" :label="kind === 'history' ? 'What happened' : 'Most important issue'" /></tr></thead>
    <tbody>
      <tr v-for="r in sorted" :key="r.n" :class="{ disabled: !r.include }">
        <td style="width:64px"><ThumbCell :job-id="job.id" :row="r" /></td>
        <td>{{ r.file }}<span v-if="r.protected" class="badge b-danger" style="margin-left:6px" :title="`Protected file: ${r.protected.reason}`">🔒 Protected</span></td>
        <td>{{ handlingLabel(r) }}</td>
        <td>{{ r.idnum || "—" }}</td>
        <td><span class="badge" :class="status(r).cls">{{ status(r).text }}</span></td>
        <td :class="{ sub: !issue(r) }">{{ issue(r) || "—" }}</td>
      </tr>
      <tr v-if="!top.length"><td colspan="6" class="muted">No documents.</td></tr>
    </tbody>
  </table>
  <div v-if="rows.length > LIMIT" class="jd-more sub">Showing the {{ LIMIT }} most important of {{ rows.length.toLocaleString() }} documents.</div>
</template>
