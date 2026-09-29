<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { api, ApiError } from "../api";
import { canPreview, formatTime, readExifDate, uploadToS3 } from "../lib/files";
import { jobCounts, worstLevel } from "../lib/status";
import { failureOf, loadFailures, OUTCOME } from "../lib/results";
import type { Job, Me, Option, Row, RowChange } from "../types";
import type { BulkChanges } from "../lib/bulk";
import BulkPanel from "./BulkPanel.vue";
import DocumentRow from "./DocumentRow.vue";
import PagerBar from "./PagerBar.vue";
import SortTh from "./SortTh.vue";
import { tableState, tableView } from "../lib/table";

const props = defineProps<{ me: Me; jobId: string | null; mode?: "edit" | "preview"; takeOverSince?: number | null }>();
const emit = defineEmits<{ scheduled: [job: Job]; opened: [id: string]; close: [] }>();

const job = ref<Job | null>(null);
const rows = ref<Row[]>([]);
const name = ref("");
const expanded = reactive(new Set<number>());
const previews = reactive(new Map<number, string>());
const message = ref<{ cls: string; text: string } | null>(null);
const busy = ref(false);
const checking = reactive(new Set<number>()); // rows waiting for a CollectionSpace check
const selected = reactive(new Set<number>());
// The languages vocabulary, for the repeating Language pickers (loaded once, from CollectionSpace).
const languages = ref<Option[]>([]);
api.vocabulary("languages")
  .then((r) => { languages.value = r.terms.map((t) => ({ value: t.refName, label: t.displayName })); })
  .catch((e) => { message.value = { cls: "msg-warn", text: `Couldn't load the languages list: ${(e as Error).message}` }; });
const bulkPanel = ref<InstanceType<typeof BulkPanel> | null>(null);
loadFailures();
// Paging, sorting and the Show filter (design: User interface, Large jobs).
const table = tableState();
const handlingLabel = (r: Row) => props.me.tenant.handling.find((h) => h.id === r.handling)?.label ?? r.handling;
const LEVEL_RANK = { block: 0, warn: 1, ok: 2 } as const;
const statusRank = (r: Row) => (!r.include ? 3 : r.result?.state === "Done" ? 4 : LEVEL_RANK[worstLevel(r)]);
const docKeys = {
  file: (r: Row) => r.file,
  handling: handlingLabel,
  publish: (r: Row) => (r.restricted ? 1 : 0),
  status: statusRank,
  include: (r: Row) => (r.include ? 0 : 1),
};
function docFilter(r: Row, f: string): boolean {
  const lv = worstLevel(r);
  switch (f) {
    case "problems": return r.include && lv !== "ok";
    case "block": return r.include && lv === "block";
    case "warn": return r.include && lv === "warn";
    case "disabled": return !r.include;
    case "selected": return selected.has(r.n);
    default: return true;
  }
}
const view = computed(() => tableView(rows.value, table, docKeys, docFilter));
const docFilters = computed<[string, string][]>(() => {
  const n = (f: string) => rows.value.filter((r) => docFilter(r, f)).length;
  return [["all", `All documents (${rows.value.length})`], ["problems", `With problems (${n("problems")})`], ["block", `Need fixing (${n("block")})`],
    ["warn", `With warnings (${n("warn")})`], ["disabled", `Disabled (${n("disabled")})`], ["selected", `Selected (${selected.size})`]];
});
const pageSelected = computed(() => view.value.shown.length > 0 && view.value.shown.every((r) => selected.has(r.n)));
const pageExpanded = computed(() => view.value.shown.length > 0 && view.value.shown.every((r) => expanded.has(r.n)));
const moreMatching = computed(() => pageSelected.value && view.value.all.some((r) => !selected.has(r.n)));
const drag = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);

const readonly = computed(() => !!job.value && job.value.status !== "Draft");
// Drafts have one editor at a time: this page can change the job only while it is the draft's editor.
const editable = computed(() => !job.value || (job.value.status === "Draft" && !!job.value.editingByYou));
const lockedBy = computed(() => job.value?.status === "Draft" && job.value.editingBy && !job.value.editingByYou
  ? { who: job.value.editingBy, since: job.value.editingSince } : null);
const confirmTakeOver = ref(false);
const savedNote = ref("");
const counts = computed(() => jobCounts(rows.value));
const scheduleBlocked = computed(() => {
  const c = counts.value;
  if (c.block) return "Fix or disable the documents marked Needs fixing first";
  if (c.uploading) return "Wait until every file is uploaded and verified";
  if (!c.work) return "Nothing left to run: every document is done or disabled";
  if (checking.size) return "Checking against CollectionSpace…";
  return "";
});

async function load(id: string | null) {
  previews.forEach((u) => URL.revokeObjectURL(u));
  previews.clear();
  expanded.clear();
  selected.clear();
  Object.assign(table, { page: 1, sort: null, dir: 1, filter: "all" });
  message.value = null;
  if (!id) {
    job.value = null;
    rows.value = [];
    name.value = "";
    return;
  }
  const r = await api.job(id);
  job.value = r.job;
  rows.value = r.rows;
  name.value = r.job.name;
  if (r.job.status === "Draft" && !r.job.editingByYou && props.mode !== "preview") await openForEditing(props.takeOverSince ?? undefined);
  // Design: checks reflect CollectionSpace as it is now. Rows whose lookups are stale are checked again.
  if (!readonly.value) void runChecks(r.rows.map((x) => x.n), false);
}

/** Become this draft's editor (or take over); if someone else is editing it, the page stays a preview. */
async function openForEditing(takeOverSince?: number) {
  if (!job.value) return;
  try {
    job.value = await api.openJob(job.value.id, takeOverSince);
    confirmTakeOver.value = false;
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) await refreshJob();
    else message.value = { cls: "msg-block", text: (e as Error).message };
  }
}

async function refreshJob() {
  if (job.value) job.value = (await api.job(job.value.id)).job;
}

/** Show an error; if someone took the draft over, the page becomes a read-only preview (nothing is lost). */
async function failed(e: unknown) {
  message.value = { cls: "msg-block", text: (e as Error).message };
  if (e instanceof ApiError && e.status === 409 && (e.detail as { code?: string } | null)?.code === "not_editing") await refreshJob();
}

/** A job that has run becomes Completed as soon as every document is done or disabled (design: Job states). */
function completedNote() {
  if (job.value?.status === "Completed") {
    message.value = { cls: "msg-info", text: "Every document is now done or disabled, so the job is Completed. It's under Finished jobs and is removed 30 days from now." };
    return true;
  }
  return false;
}

async function saveDraft() {
  if (!job.value) return;
  try {
    job.value = await api.saveDraft(job.value.id);
    if (completedNote()) return;
    const exp = job.value.expiresAt ? new Date(job.value.expiresAt * 1000).toLocaleDateString(undefined, { dateStyle: "medium" }) : "";
    savedNote.value = `Draft saved at ${formatTime(job.value.lastSavedAt)}` + (counts.value.block ? `; ${counts.value.block} document(s) still need fixing before it can be scheduled` : "")
      + (exp ? `. Unless it's changed or saved again, it expires on ${exp}.` : ".");
  } catch (e) {
    await failed(e);
  }
}

/** Check rows against CollectionSpace in the background; the whole job's checks come back. */
async function runChecks(ns: number[], targeted = true) {
  if (!job.value || !ns.length) return;
  ns.forEach((n) => checking.add(n));
  try {
    const r = await api.check(job.value.id, targeted ? ns : undefined);
    r.rows.forEach((row) => replace(row));
  } catch (e) {
    message.value = { cls: "msg-block", text: (e as Error).message };
  } finally {
    ns.forEach((n) => checking.delete(n));
  }
}

function apply(change: RowChange) {
  replace(change.row);
  change.others.forEach((o) => replace(o));
}
watch(() => props.jobId, (id) => (id && id === job.value?.id ? undefined : load(id).catch((e) => (message.value = { cls: "msg-block", text: e.message }))), { immediate: true });
onBeforeUnmount(() => previews.forEach((u) => URL.revokeObjectURL(u)));

// One job per editor, even if naming it and dropping files race each other.
let creating: Promise<Job> | null = null;
async function ensureJob(): Promise<Job> {
  if (job.value) return job.value;
  creating ??= api.createJob(name.value.trim()).then((j) => {
    job.value = j;
    emit("opened", j.id);
    return j;
  });
  return creating;
}

async function rename() {
  if (!job.value) {
    if (name.value.trim()) await ensureJob();
    return;
  }
  if (name.value.trim() !== job.value.name && editable.value) {
    try {
      job.value = await api.renameJob(job.value.id, name.value.trim());
    } catch (e) {
      await failed(e);
    }
  }
}

/** Take the server's copy of a row, keeping the browser's upload progress while a file is still on its way. */
function replace(row: Row) {
  const i = rows.value.findIndex((r) => r.n === row.n);
  if (i < 0) return;
  if ((row.v ?? 0) < (rows.value[i].v ?? 0)) return; // a stale copy, e.g. a slow check that started earlier
  const local = rows.value[i].upload;
  rows.value[i] = { ...row, upload: ["uploading", "verifying"].includes(local.s) && row.upload.s === "pending" ? local : row.upload };
}

/** Add files: create rows, upload each straight to S3 (3 at a time), then confirm with the API. */
async function addFiles(list: FileList | File[] | null) {
  const files = Array.from(list ?? []);
  if (!files.length || !editable.value) return;
  message.value = null;
  try {
    const j = await ensureJob();
    const { rows: created } = await api.addFiles(j.id, files.map((f) => ({ name: f.name, size: f.size, type: f.type })));
    const queue = created.map((row, i) => ({ row, file: files[i] }));
    for (const { row, file } of queue) {
      row.upload = { s: "pending" };
      rows.value.push(row);
      if (canPreview(file)) previews.set(row.n, URL.createObjectURL(file));
    }
    // Design: each row is checked as soon as its file is chosen, in one batch for the new rows.
    const checks = runChecks(created.map((r) => r.n));
    const worker = async () => {
      for (let next = queue.shift(); next; next = queue.shift()) await uploadOne(j.id, next.row, next.file);
    };
    await Promise.all([worker(), worker(), worker(), checks]);
  } catch (e) {
    await failed(e);
  }
}

/** Replace the file of a document whose Media record exists; the rerun uploads it to that record. */
async function replaceFile(row: Row, file: File) {
  if (!job.value) return;
  try {
    const r = await api.replaceFile(job.value.id, row.n, { name: file.name, size: file.size, type: file.type });
    replace(r.row);
    const old = previews.get(row.n);
    if (old) URL.revokeObjectURL(old);
    if (canPreview(file)) previews.set(row.n, URL.createObjectURL(file));
    await uploadOne(job.value.id, { ...r.row, uploadForm: r.uploadForm }, file, false);
  } catch (e) {
    await failed(e);
  }
}

async function uploadOne(jobId: string, row: Row, file: File, exif = true) {
  const live = () => rows.value.find((r) => r.n === row.n);
  const set = (u: Row["upload"]) => { const r = live(); if (r) r.upload = u; };
  set({ s: "uploading", pct: 0 });
  try {
    await uploadToS3(row.uploadForm!, file, (pct) => set({ s: "uploading", pct }));
    set({ s: "verifying" });
    let confirmed = await api.uploaded(jobId, row.n);
    const date = exif ? await readExifDate(file) : "";
    if (date && !confirmed.row.date) confirmed = await api.editRow(jobId, row.n, { date });
    set(confirmed.row.upload);
    apply(confirmed);
  } catch {
    set({ s: "failed" });
    try {
      apply(await api.uploadFailed(jobId, row.n));
    } catch { /* the row already shows the failure */ }
  }
}

async function edit(row: Row, changes: Partial<Row>) {
  if (!job.value) return;
  try {
    apply(await api.editRow(job.value.id, row.n, changes));
  } catch (e) {
    await failed(e);
  }
}

async function remove(row: Row) {
  if (!job.value) return;
  const r = await api.deleteRow(job.value.id, row.n).catch(failed);
  if (!r) return;
  if (r.jobStatus && r.jobStatus !== "Draft") {
    if (r.jobStatus === "Deleted") {
      message.value = { cls: "msg-info", text: "That was the job's last document, so the job was deleted." };
      job.value = null;
      rows.value = [];
      return;
    }
    await refreshJob();
    completedNote();
  }
  rows.value = rows.value.filter((x) => x.n !== row.n);
  selected.delete(row.n);
  r.others.forEach((o) => replace(o));
  const u = previews.get(row.n);
  if (u) URL.revokeObjectURL(u);
}

function select(n: number, on: boolean) {
  if (on) selected.add(n);
  else selected.delete(n);
}
/** The header checkbox: the documents on this page (design: with a link to select every matching document). */
function selectPage(on: boolean) {
  view.value.shown.forEach((r) => (on ? selected.add(r.n) : selected.delete(r.n)));
}
function selectMatching() {
  view.value.all.forEach((r) => selected.add(r.n));
}
function expandPage() {
  const open = !pageExpanded.value;
  view.value.shown.forEach((r) => (open ? expanded.add(r.n) : expanded.delete(r.n)));
}

/** The bulk-change panel: the server applies every change to every target, or refuses and changes nothing. */
async function bulk(targets: number[], changes: BulkChanges | Partial<Row>, resetPanel: boolean) {
  if (!job.value || !targets.length) return;
  busy.value = true;
  message.value = null;
  try {
    const r = await api.bulk(job.value.id, targets, changes);
    r.rows.forEach((row) => replace(row));
    if (resetPanel) bulkPanel.value?.reset();
  } catch (e) {
    await failed(e);
  } finally {
    busy.value = false;
  }
}

/** "Show documents with problems": filter to them and expand those on the page. */
function showProblems() {
  table.filter = "problems";
  table.page = 1;
  expanded.clear();
  view.value.shown.forEach((r) => expanded.add(r.n));
}

async function schedule() {
  if (!job.value) return;
  busy.value = true;
  try {
    await rename();
    const j = await api.schedule(job.value.id);
    emit("scheduled", j);
  } catch (e) {
    await failed(e);
    if (e instanceof ApiError && e.status === 409 && editable.value) {
      // Scheduling checked the whole job again (with fresh permissions): show what it found.
      rows.value = (await api.job(job.value.id)).rows;
      showProblems();
    }
  } finally {
    busy.value = false;
  }
}

function toggle(n: number) {
  if (expanded.has(n)) expanded.delete(n);
  else expanded.add(n);
}
</script>

<template>
  <div>
    <div v-if="lockedBy" class="banner">
      <strong>Read-only preview.</strong> {{ lockedBy.who }} is editing this draft (since {{ formatTime(lockedBy.since) }}).
      <template v-if="!confirmTakeOver"> <button @click="confirmTakeOver = true">Take over…</button></template>
      <div v-else class="msg msg-warn" style="margin-top:6px">
        If you take over, {{ lockedBy.who }}'s editing ends and their page becomes read-only; everything they changed so far
        is already saved. <button @click="openForEditing(lockedBy.since)">Take over and edit</button>
        <button @click="confirmTakeOver = false">Cancel</button>
      </div>
    </div>
    <div v-else-if="job && job.status === 'Draft' && job.editingByYou" class="banner">
      Editing draft <strong>{{ job.name || "Untitled job" }}</strong>. Others in {{ me.tenant.name }} see it under Drafts as being
      edited by you. Changes are saved as you make them. Schedule job moves it to the job queue.
      <button class="link" @click="emit('close')">Close this draft and start a new job</button>
    </div>
    <div v-if="job?.fixFrom && job.status === 'Draft'" class="msg msg-warn">
      <strong>Fixing after run {{ job.fixFrom.run }}</strong> (it {{ job.fixFrom.status === "Failed" ? "failed" : "needed attention" }}<template
        v-if="job.fixFrom.code">: {{ failureOf(job.fixFrom.code).title }}</template>). Documents already created in CollectionSpace are read-only;
      one whose Media record exists takes only what the rerun still needs. Scheduling queues run {{ job.fixFrom.run + 1 }}, which skips everything
      already done. If the job isn't scheduled within 30 days of the last change, these edits are discarded and it returns to Finished jobs as it was.
    </div>
    <div v-if="job && job.status !== 'Draft'" class="msg msg-info">
      This job is {{ OUTCOME[job.status]?.text ?? job.status }}; it can't be changed here.
      <template v-if="job.status === 'NeedsAttention' || job.status === 'Failed'">Use Fix and reschedule under Finished jobs.</template>
    </div>
    <div v-if="job?.note" class="msg msg-warn">{{ job.note }}</div>
    <label class="field"><span><strong>Job name</strong></span>
      <input v-model="name" type="text" placeholder="e.g. 2026 spring accession batch" :disabled="!editable" @change="rename" /></label>

    <div v-if="editable" class="dropzone" :class="{ drag }" role="button" tabindex="0"
         @click="fileInput?.click()" @keydown.enter.prevent="fileInput?.click()"
         @dragenter.prevent="drag = true" @dragover.prevent="drag = true" @dragleave.prevent="drag = false"
         @drop.prevent="drag = false; addFiles($event.dataTransfer?.files ?? null)">
      ⬆ Drop documents here or <span style="text-decoration:underline">browse</span>
      <div class="sub">{{ me.tenant.filenameHint }}</div>
      <input ref="fileInput" type="file" multiple hidden @change="addFiles(($event.target as HTMLInputElement).files); ($event.target as HTMLInputElement).value = ''" />
    </div>

    <div v-if="message" class="msg" :class="message.cls" role="status">{{ message.text }}</div>
    <div v-if="counts.uploading || counts.uploadFailed" class="sub" style="margin:6px 0">
      {{ counts.uploaded }} of {{ counts.work }} uploaded<template v-if="counts.uploading"> · {{ counts.uploading }} uploading</template><template v-if="counts.uploadFailed"> · {{ counts.uploadFailed }} failed</template>
    </div>

    <div class="editor-split">
    <BulkPanel ref="bulkPanel" :rows="rows" :selected="selected" :tenant="me.tenant" :perms="me.perms" :readonly="!editable" :busy="busy" :languages="languages"
               @apply="(t, c) => bulk(t, c, true)" @include="(t, on) => bulk(t, { include: on }, false)" />
    <div class="grid-main">
    <PagerBar v-if="rows.length" :state="table" :total="view.total" :of="view.of" :pages="view.pages" :start="view.start" noun="documents" :filters="docFilters" />
    <div v-if="selected.size" class="sel-banner"><strong>{{ selected.size.toLocaleString() }}</strong> selected<template
      v-if="selected.size > view.shown.length"> across pages</template><template v-if="moreMatching"> · <button class="link" @click="selectMatching">Select all
      {{ view.total.toLocaleString() }}{{ view.total !== view.of ? " matching" : "" }} documents</button></template>
      · <button class="link" @click="selected.clear()">Clear selection</button></div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th style="width:64px"><span class="sr-only">Preview</span></th>
          <th style="width:28px"><input type="checkbox" :checked="pageSelected" :disabled="!view.shown.length" aria-label="Select all documents on this page"
            @change="selectPage(($event.target as HTMLInputElement).checked)" /></th>
          <th style="width:28px"><button class="chevron" :class="{ open: pageExpanded }" :disabled="!view.shown.length"
            title="Expand or collapse all rows on this page" aria-label="Expand or collapse all rows on this page" @click="expandPage">▸</button></th>
          <SortTh :state="table" sort-key="file" label="Document" />
          <SortTh :state="table" sort-key="handling" label="Handling" style="width:220px" />
          <SortTh :state="table" sort-key="publish" :label="me.tenant.publish.header" style="width:110px" />
          <SortTh :state="table" sort-key="status" label="Status" style="width:150px" />
          <SortTh :state="table" sort-key="include" label="Include" style="width:90px" title="Turn off to have the BMU ignore a document" />
        </tr></thead>
        <tbody>
          <tr v-if="!rows.length"><td colspan="8" class="muted" style="text-align:center;padding:18px">No documents yet. Drop files in the box above, or browse, to add them to this job.</td></tr>
          <tr v-else-if="!view.shown.length"><td colspan="8" class="muted" style="text-align:center;padding:18px">No documents match this filter.</td></tr>
          <DocumentRow v-for="r in view.shown" :key="r.n" :row="r" :tenant="me.tenant" :perms="me.perms" :checking="checking.has(r.n)" :preview="previews.get(r.n)"
                       :expanded="expanded.has(r.n)" :readonly="readonly || !editable" :selected="selected.has(r.n)" :languages="languages"
                       :other-names="rows.filter((x) => x.n !== r.n).map((x) => x.file)"
                       @toggle="toggle(r.n)" @edit="edit(r, $event)" @remove="remove(r)" @select="select(r.n, $event)" @replace="replaceFile(r, $event)" />
        </tbody>
      </table>
    </div>
    <PagerBar :state="table" :total="view.total" :of="view.of" :pages="view.pages" :start="view.start" noun="documents" bottom />
    </div>
    </div>

    <div class="schedule-bar">
      <span><strong>{{ counts.total }} documents<template v-if="counts.disabled"> ({{ counts.disabled }} disabled)</template></strong>
        · {{ counts.block ? `${counts.block} ${counts.block === 1 ? "needs" : "need"} fixing` : "nothing to fix" }}
        <template v-if="counts.warn"> · {{ counts.warn }} {{ counts.warn === 1 ? "has" : "have" }} warnings</template></span>
      <span class="spacer"></span>
      <button v-if="counts.block || counts.warn" @click="showProblems">Show documents with problems</button>
      <button v-if="job?.status === 'Draft'" :disabled="!editable || busy" title="Every change is already saved; this confirms it and restarts the draft's 30-day expiry"
              @click="saveDraft">Save draft</button>
      <button class="primary" :disabled="!job || busy || !!scheduleBlocked || readonly || (job.status === 'Draft' && !editable)"
              :title="scheduleBlocked || 'Check the whole job again, then add it to the job queue'" @click="schedule">
        {{ job && job.status !== "Draft" ? "Reschedule" : "Schedule job" }}</button>
      <div v-if="savedNote" class="result">{{ savedNote }}</div>
    </div>
  </div>
</template>
