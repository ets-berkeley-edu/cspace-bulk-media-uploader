<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { api, ApiError } from "../api";
import { canPreview, readExifDate, uploadToS3 } from "../lib/files";
import type { Job, Me, Row } from "../types";
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
const drag = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);

const readonly = computed(() => !!job.value && !["Draft", "NeedsAttention", "Failed"].includes(job.value.status));
const editable = computed(() => !job.value || job.value.status === "Draft");
const counts = computed(() => {
  const inc = rows.value.filter((r) => r.include && r.result?.state !== "Done");
  return {
    total: rows.value.length,
    work: inc.length,
    block: inc.filter((r) => r.checks.some((c) => c.level === "block")).length,
    warn: inc.filter((r) => r.checks.some((c) => c.level === "warn") && !r.checks.some((c) => c.level === "block")).length,
    uploading: rows.value.filter((r) => r.upload.s === "uploading" || r.upload.s === "pending").length,
  };
});

async function load(id: string | null) {
  previews.forEach((u) => URL.revokeObjectURL(u));
  previews.clear();
  expanded.clear();
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
}
watch(() => props.jobId, (id) => (id && id === job.value?.id ? undefined : load(id).catch((e) => (message.value = { cls: "msg-block", text: e.message }))), { immediate: true });
onBeforeUnmount(() => previews.forEach((u) => URL.revokeObjectURL(u)));

async function ensureJob(): Promise<Job> {
  if (job.value) return job.value;
  job.value = await api.createJob(name.value.trim());
  emit("opened", job.value.id);
  return job.value;
}

async function rename() {
  if (!job.value) {
    if (name.value.trim()) await ensureJob();
    return;
  }
  if (name.value.trim() !== job.value.name && editable.value) job.value = await api.renameJob(job.value.id, name.value.trim());
}

function replace(row: Row) {
  const i = rows.value.findIndex((r) => r.n === row.n);
  if (i >= 0) rows.value[i] = { ...row, upload: rows.value[i].upload.s === "uploading" ? rows.value[i].upload : row.upload };
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
    const worker = async () => {
      for (let next = queue.shift(); next; next = queue.shift()) await uploadOne(j.id, next.row, next.file);
    };
    await Promise.all([worker(), worker(), worker()]);
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
    set({ s: "done" });
    let confirmed = await api.uploaded(jobId, row.n);
    const date = await readExifDate(file);
    if (date && !confirmed.date) confirmed = await api.editRow(jobId, row.n, { date });
    replace(confirmed);
  } catch {
    set({ s: "failed" });
    replace(await api.uploadFailed(jobId, row.n).catch(() => ({ ...row, upload: { s: "failed" } }) as Row));
  }
}

async function edit(row: Row, changes: Partial<Row>) {
  if (!job.value) return;
  try {
    replace(await api.editRow(job.value.id, row.n, changes));
  } catch (e) {
    message.value = { cls: "msg-block", text: (e as Error).message };
  }
}

async function remove(row: Row) {
  if (!job.value) return;
  await api.deleteRow(job.value.id, row.n);
  rows.value = rows.value.filter((r) => r.n !== row.n);
  const u = previews.get(row.n);
  if (u) URL.revokeObjectURL(u);
}

async function check() {
  if (!job.value) return;
  busy.value = true;
  try {
    const r = await api.check(job.value.id);
    rows.value = r.rows;
    message.value = r.counts.block
      ? { cls: "msg-block", text: `${r.counts.block} documents need fixing. Open them to see why.` }
      : { cls: "msg-info", text: r.counts.warn ? `No problems that block scheduling; ${r.counts.warn} documents have warnings.` : "Everything checks out." };
    r.rows.forEach((x) => x.checks.some((c) => c.level === "block") && expanded.add(x.n));
  } catch (e) {
    message.value = { cls: "msg-block", text: (e as Error).message };
  } finally {
    busy.value = false;
  }
}

async function schedule() {
  if (!job.value) return;
  busy.value = true;
  try {
    await rename();
    const j = await api.schedule(job.value.id);
    emit("scheduled", j);
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) await check();
    message.value = { cls: "msg-block", text: (e as Error).message };
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

    <div class="table-wrap">
      <table>
        <thead><tr>
          <th style="width:64px"><span class="sr-only"></span></th><th style="width:28px"></th><th>Document</th>
          <th style="width:220px">Handling</th><th style="width:90px">{{ me.tenant.publish.header }}</th>
          <th style="width:140px">Status</th><th style="width:90px"></th>
        </tr></thead>
        <tbody>
          <tr v-if="!rows.length"><td colspan="7" class="muted" style="text-align:center;padding:18px">No documents yet. Drop files in the box above, or browse, to add them to this job.</td></tr>
          <DocumentRow v-for="r in rows" :key="r.n" :row="r" :tenant="me.tenant" :preview="previews.get(r.n)"
                       :expanded="expanded.has(r.n)" :readonly="readonly || !editable"
                       @toggle="toggle(r.n)" @edit="edit(r, $event)" @remove="remove(r)" />
        </tbody>
      </table>
    </div>

    <div class="schedule-bar">
      <span><strong>{{ counts.total }} documents</strong>
        · {{ counts.block ? `${counts.block} need fixing` : "nothing to fix" }}
        <template v-if="counts.warn"> · {{ counts.warn }} with warnings</template>
        <template v-if="counts.uploading"> · {{ counts.uploading }} uploading</template></span>
      <span class="spacer"></span>
      <button :disabled="!job || busy || !rows.length" @click="check">Check against CollectionSpace</button>
      <button class="primary" :disabled="!job || busy || !counts.work || counts.uploading > 0 || readonly"
              :title="counts.uploading ? 'Wait until every file is uploaded' : ''" @click="schedule">
        {{ job && job.status !== "Draft" ? "Reschedule" : "Schedule job" }}</button>
    </div>
  </div>
</template>
