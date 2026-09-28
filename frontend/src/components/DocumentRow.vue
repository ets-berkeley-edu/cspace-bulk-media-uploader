<script setup lang="ts">
import { computed } from "vue";
import type { Row, TenantInfo } from "../types";
import { formatBytes } from "../lib/files";
import AuthorityInput from "./AuthorityInput.vue";

const props = defineProps<{ row: Row; tenant: TenantInfo; preview?: string; expanded: boolean; readonly: boolean }>();
const emit = defineEmits<{ edit: [changes: Partial<Row>]; remove: []; toggle: [] }>();

const locked = computed(() => Object.values(props.row.result?.steps ?? {}).some((s) => !!s.csid));
const ro = computed(() => props.readonly || locked.value);
const handling = computed(() => props.tenant.handling.find((h) => h.id === props.row.handling));

const status = computed(() => {
  const r = props.row;
  if (r.upload.s === "uploading") return { text: `Uploading ${r.upload.pct ?? 0}%`, cls: "b-accent" };
  if (r.upload.s === "pending") return { text: "Waiting to upload", cls: "b-muted" };
  if (r.upload.s === "failed") return { text: "Upload failed", cls: "b-danger" };
  if (!r.include) return { text: "Disabled", cls: "b-muted" };
  if (r.result?.state === "Done") return { text: "Done", cls: "b-ok" };
  if (r.result?.state === "Partial" || r.result?.state === "Failed") return { text: r.result.state, cls: "b-danger" };
  const levels = new Set(r.checks.map((c) => c.level));
  if (levels.has("block")) return { text: "Needs fixing", cls: "b-danger" };
  if (levels.has("warn")) return { text: "Check warnings", cls: "b-warn" };
  if (r.checks.length || r.result) return { text: "Ready", cls: "b-ok" };
  return { text: "Uploaded", cls: "b-ok" };
});

function text(field: keyof Row, e: Event) {
  const v = (e.target as HTMLInputElement).value;
  if (v !== props.row[field]) emit("edit", { [field]: v } as Partial<Row>);
}
</script>

<template>
  <tr :class="{ disabled: !row.include }">
    <td><div class="thumb"><img v-if="preview" :src="preview" alt="" /><span v-else>{{ row.file.split(".").pop()?.toUpperCase() }}</span></div></td>
    <td class="keep"><button class="chevron" :class="{ open: expanded }" :aria-expanded="expanded" aria-label="Show details" @click="emit('toggle')">▸</button></td>
    <td>
      <div>{{ row.file }}</div>
      <div class="sub">{{ formatBytes(row.size) }}<template v-if="handling?.object !== 'none'"> · object {{ row.obj || "—" }}</template></div>
    </td>
    <td>
      <select :value="row.handling" :disabled="ro || !row.include" aria-label="Handling" @change="emit('edit', { handling: ($event.target as HTMLSelectElement).value })">
        <option v-for="h in tenant.handling" :key="h.id" :value="h.id">{{ h.label }}</option>
      </select>
    </td>
    <td style="text-align:center">
      <input type="checkbox" :checked="row.restricted" :disabled="ro || !row.include" :aria-label="tenant.publish.header"
             @change="emit('edit', { restricted: ($event.target as HTMLInputElement).checked })" />
    </td>
    <td><span class="badge" :class="status.cls">{{ status.text }}</span>
      <div v-if="row.upload.s === 'uploading'" class="progress"><span class="up" :style="{ width: (row.upload.pct ?? 0) + '%' }"></span></div>
    </td>
    <td class="keep">
      <label v-if="row.result?.state !== 'Done'" class="sub"><input type="checkbox" :checked="row.include" :disabled="readonly"
        @change="emit('edit', { include: ($event.target as HTMLInputElement).checked })" /> Include</label>
    </td>
  </tr>
  <tr v-if="expanded" class="detail">
    <td colspan="7">
      <div v-if="locked" class="msg msg-info">This document already created records in CollectionSpace, so it can't be changed here.</div>
      <div class="grid">
        <label class="field"><span>Object number <template v-if="row.obj === row.objParsed">(parsed)</template></span>
          <input type="text" :value="row.obj" :disabled="ro || handling?.object === 'none'" @change="text('obj', $event)" /></label>
        <label class="field"><span>Identification number</span>
          <input type="text" :value="row.idnum" :disabled="ro" @change="text('idnum', $event)" /></label>
        <label class="field"><span>Date</span>
          <input type="text" :value="row.date" placeholder="YYYY-MM-DD" :disabled="ro" @change="text('date', $event)" /></label>
        <label class="field"><span>Media type</span>
          <select :value="row.type" :disabled="ro" @change="text('type', $event)">
            <option value="">—</option>
            <option v-for="t in tenant.mediaTypes" :key="t" :value="t">{{ t }}</option>
          </select></label>
        <AuthorityInput field="creator" label="Creator" :model-value="row.creator" :disabled="ro" @update:model-value="emit('edit', { creator: $event })" />
        <AuthorityInput field="contributor" label="Contributor" :model-value="row.contributor" :disabled="ro" @update:model-value="emit('edit', { contributor: $event })" />
        <AuthorityInput field="rightsHolder" label="Rights holder" :model-value="row.rightsHolder" :disabled="ro" @update:model-value="emit('edit', { rightsHolder: $event })" />
        <label class="field"><span>Copyright statement</span>
          <input type="text" :value="row.copyright" :disabled="ro" @change="text('copyright', $event)" /></label>
        <label class="field wide"><span>Description</span>
          <textarea rows="2" :value="row.description" :disabled="ro" @change="text('description', $event)"></textarea></label>
      </div>
      <div class="sub">Filename rule: {{ tenant.filenameHint }}</div>
      <div v-for="(c, i) in row.checks" :key="i" class="msg" :class="`msg-${c.level}`">{{ c.text }}</div>
      <div v-if="row.result?.error" class="msg msg-block">
        {{ row.result.error.detail }} ({{ row.result.error.code }}, step {{ row.result.error.step }})
      </div>
      <div v-if="!ro" style="margin-top:6px"><button class="link" @click="emit('remove')">Delete document</button></div>
    </td>
  </tr>
</template>
