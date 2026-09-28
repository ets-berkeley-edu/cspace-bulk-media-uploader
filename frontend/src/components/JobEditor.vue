<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { api, ApiError } from "../api";
import { canPreview, readExifDate, uploadToS3 } from "../lib/files";
import { jobCounts, worstLevel } from "../lib/status";
import type { Job, Me, Option, Row, RowChange } from "../types";
import type { BulkChanges } from "../lib/bulk";
import BulkPanel from "./BulkPanel.vue";
import DocumentRow from "./DocumentRow.vue";

const props = defineProps<{ me: Me; jobId: string | null }>();
const emit = defineEmits<{ scheduled: [job: Job]; opened: [id: string] }>();

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
const allSelected = computed(() => rows.value.length > 0 && rows.value.every((r) => selected.has(r.n)));
const drag = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);

const readonly = computed(() => !!job.value && !["Draft", "NeedsAttention", "Failed"].includes(job.value.status));
const editable = computed(() => !job.value || job.value.status === "Draft");
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
  // Design: checks reflect CollectionSpace as it is now. Rows whose lookups are stale are checked again.
  if (!readonly.value) void runChecks(r.rows.map((x) => x.n), false);
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
  if (name.value.trim() !== job.value.name && editable.value) job.value = await api.renameJob(job.value.id, name.value.trim());
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
    message.value = { cls: "msg-block", text: (e as Error).message };
  }
}

async function uploadOne(jobId: string, row: Row, file: File) {
  const live = () => rows.value.find((r) => r.n === row.n);
  const set = (u: Row["upload"]) => { const r = live(); if (r) r.upload = u; };
  set({ s: "uploading", pct: 0 });
  try {
    await uploadToS3(row.uploadForm!, file, (pct) => set({ s: "uploading", pct }));
    set({ s: "verifying" });
    let confirmed = await api.uploaded(jobId, row.n);
    const date = await readExifDate(file);
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
    message.value = { cls: "msg-block", text: (e as Error).message };
  }
}

async function remove(row: Row) {
  if (!job.value) return;
  const r = await api.deleteRow(job.value.id, row.n);
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
function selectAll(on: boolean) {
  selected.clear();
  if (on) rows.value.forEach((r) => selected.add(r.n));
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
    message.value = { cls: "msg-block", text: (e as Error).message };
  } finally {
    busy.value = false;
  }
}

/** "Show documents with problems": expand just the rows that need fixing or have warnings. */
function showProblems() {
  expanded.clear();
  rows.value.forEach((r) => r.include && worstLevel(r) !== "ok" && expanded.add(r.n));
}

async function schedule() {
  if (!job.value) return;
  busy.value = true;
  try {
    await rename();
    const j = await api.schedule(job.value.id);
    emit("scheduled", j);
  } catch (e) {
    message.value = { cls: "msg-block", text: (e as Error).message };
    if (e instanceof ApiError && e.status === 409) {
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
    <div v-if="job && job.status !== 'Draft'" class="msg msg-info">
      This job is {{ job.status }}.
      <template v-if="job.status === 'NeedsAttention' || job.status === 'Failed'">Reschedule reruns only what's unfinished; finished steps are skipped.</template>
      <template v-else>It can't be changed.</template>
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
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th style="width:64px"><span class="sr-only">Preview</span></th>
          <th style="width:28px"><input type="checkbox" :checked="allSelected" :disabled="!rows.length" aria-label="Select all documents"
            @change="selectAll(($event.target as HTMLInputElement).checked)" /></th>
          <th style="width:28px"></th><th>Document</th>
          <th style="width:220px">Handling</th><th style="width:90px">{{ me.tenant.publish.header }}</th>
          <th style="width:140px">Status</th><th style="width:90px"></th>
        </tr></thead>
        <tbody>
          <tr v-if="!rows.length"><td colspan="8" class="muted" style="text-align:center;padding:18px">No documents yet. Drop files in the box above, or browse, to add them to this job.</td></tr>
          <DocumentRow v-for="r in rows" :key="r.n" :row="r" :tenant="me.tenant" :perms="me.perms" :checking="checking.has(r.n)" :preview="previews.get(r.n)"
                       :expanded="expanded.has(r.n)" :readonly="readonly || !editable" :selected="selected.has(r.n)" :languages="languages"
                       @toggle="toggle(r.n)" @edit="edit(r, $event)" @remove="remove(r)" @select="select(r.n, $event)" />
        </tbody>
      </table>
    </div>
    </div>
    </div>

    <div class="schedule-bar">
      <span><strong>{{ counts.total }} documents<template v-if="counts.disabled"> ({{ counts.disabled }} disabled)</template></strong>
        · {{ counts.block ? `${counts.block} ${counts.block === 1 ? "needs" : "need"} fixing` : "nothing to fix" }}
        <template v-if="counts.warn"> · {{ counts.warn }} {{ counts.warn === 1 ? "has" : "have" }} warnings</template></span>
      <span class="spacer"></span>
      <button v-if="counts.block || counts.warn" @click="showProblems">Show documents with problems</button>
      <button class="primary" :disabled="!job || busy || !!scheduleBlocked || readonly"
              :title="scheduleBlocked || 'Check the whole job again, then add it to the job queue'" @click="schedule">
        {{ job && job.status !== "Draft" ? "Reschedule" : "Schedule job" }}</button>
    </div>
  </div>
</template>
