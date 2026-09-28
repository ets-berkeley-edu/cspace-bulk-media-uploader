<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { Option, Perms, Row, TenantInfo } from "../types";
import { formatBytes } from "../lib/files";
import { filenameProblems, idLabel, objectLabel } from "../lib/filenames";
import { handlingBlocked, rowStatus, worstLevel } from "../lib/status";
import AuthorityInput from "./AuthorityInput.vue";
import DateInput from "./DateInput.vue";
import RepeatingSelect from "./RepeatingSelect.vue";

const props = defineProps<{
  row: Row; tenant: TenantInfo; perms: Perms; preview?: string; expanded: boolean; readonly: boolean; checking?: boolean;
  selected?: boolean; languages?: Option[]; otherNames?: string[];
}>();
const emit = defineEmits<{ edit: [changes: Partial<Row>]; remove: []; toggle: []; select: [on: boolean] }>();

const locked = computed(() => Object.values(props.row.result?.steps ?? {}).some((s) => !!s.csid));
const ro = computed(() => props.readonly || locked.value || !props.row.include);
const handling = computed(() => props.tenant.handling.find((h) => h.id === props.row.handling));

const status = computed(() => rowStatus(props.row, props.tenant, props.checking));
const hasWarnings = computed(() => props.row.include && worstLevel(props.row) === "warn");
const PREFIX: Record<string, string> = { block: "Must fix: ", warn: "Warning: ", info: "" };

// Filename: checked as you type; applied (re-parsed and re-checked on the server) only once it passes.
const original = computed(() => props.row.fileOriginal || props.row.file);
const renamed = computed(() => props.row.file !== original.value);
const nameDraft = ref(props.row.file);
watch(() => props.row.file, (f) => { nameDraft.value = f; });
const nameErrors = computed(() => nameDraft.value === props.row.file ? []
  : filenameProblems(props.tenant, nameDraft.value.trim(), original.value, props.otherNames ?? []));
function applyName() {
  const v = nameDraft.value.trim();
  if (v !== props.row.file && !nameErrors.value.length) emit("edit", { file: v });
}
const objLabel = computed(() => objectLabel(props.row));
const idnLabel = computed(() => idLabel(props.row, props.tenant));

function text(field: keyof Row, e: Event) {
  const v = (e.target as HTMLInputElement).value;
  if (v !== props.row[field]) emit("edit", { [field]: v } as Partial<Row>);
}
</script>

<template>
  <tr :class="{ disabled: !row.include }">
    <td><div class="thumb"><img v-if="preview" :src="preview" alt="" /><span v-else>{{ row.file.split(".").pop()?.toUpperCase() }}</span></div></td>
    <td class="keep"><input type="checkbox" :checked="selected" :aria-label="`Select ${row.file}`"
      @change="emit('select', ($event.target as HTMLInputElement).checked)" /></td>
    <td class="keep"><button class="chevron" :class="{ open: expanded }" :aria-expanded="expanded" aria-label="Show details" @click="emit('toggle')">▸</button></td>
    <td>
      <div>{{ row.file }}<span v-if="renamed" class="badge b-accent" style="margin-left:6px" :title="`Original: ${original}`">Renamed</span></div>
      <div class="sub">{{ formatBytes(row.size) }}<template v-if="handling?.object !== 'none'"> · object {{ row.obj || "—" }}</template></div>
    </td>
    <td>
      <select :value="row.handling" :disabled="ro || !row.include" aria-label="Handling" @change="emit('edit', { handling: ($event.target as HTMLSelectElement).value })">
        <option v-for="h in tenant.handling" :key="h.id" :value="h.id" :disabled="!!handlingBlocked(h, perms) && h.id !== row.handling"
                :title="handlingBlocked(h, perms)">{{ h.label }}{{ handlingBlocked(h, perms) ? " (no permission)" : "" }}</option>
      </select>
    </td>
    <td style="text-align:center">
      <input type="checkbox" :checked="row.restricted" :disabled="ro || !row.include" :aria-label="tenant.publish.header"
             @change="emit('edit', { restricted: ($event.target as HTMLInputElement).checked })" />
    </td>
    <td><span class="badge" :class="status.cls">{{ status.text }}</span>
      <span v-if="hasWarnings && status.cls !== 'b-danger'" class="badge b-warn" title="This document has warnings"> !</span>
      <div v-if="row.upload.s === 'uploading'" class="progress"><span class="up" :style="{ width: (row.upload.pct ?? 0) + '%' }"></span></div>
    </td>
    <td class="keep">
      <label v-if="row.result?.state !== 'Done'" class="sub"><input type="checkbox" :checked="row.include" :disabled="readonly"
        @change="emit('edit', { include: ($event.target as HTMLInputElement).checked })" /> Include</label>
    </td>
  </tr>
  <tr v-if="expanded" class="detail">
    <td colspan="8">
      <div v-if="locked" class="msg msg-info">This document already created records in CollectionSpace, so it can't be changed here.</div>
      <div class="grid">
        <div class="field wide" :class="{ edited: renamed }">
          <label><span>Filename <em class="num-state">{{ renamed ? `(renamed — original ${original})` : "(original)" }}</em></span>
            <input v-model="nameDraft" type="text" spellcheck="false" :disabled="ro" aria-label="Filename"
                   @blur="applyName" @keydown.enter.prevent="applyName" /></label>
          <div v-for="(e, i) in nameErrors" :key="i" class="msg msg-block">{{ e }}</div>
          <span class="field-note">{{ tenant.filenameHint }}
            <template v-if="renamed && !ro"> · <button class="link" type="button" @click="emit('edit', { file: original })">Use original filename</button></template></span>
        </div>
        <div v-if="handling?.object !== 'none'" class="field" :class="{ edited: objLabel.edited }">
          <label><span>Object number <em class="num-state">{{ objLabel.text }}</em></span>
            <input type="text" :value="row.obj" :disabled="ro" @change="text('obj', $event)" /></label>
          <button v-if="objLabel.reset !== undefined && !ro" class="link field-note" type="button" @click="emit('edit', { obj: objLabel.reset })">Use parsed value</button>
        </div>
        <div class="field" :class="{ edited: idnLabel.edited }">
          <label><span>Identification number <em class="num-state">{{ idnLabel.text }}</em></span>
            <input type="text" :value="row.idnum" :disabled="ro" @change="text('idnum', $event)" /></label>
          <button v-if="idnLabel.reset !== undefined && !ro" class="link field-note" type="button" @click="emit('edit', { idnum: idnLabel.reset })">Use parsed value</button>
        </div>
        <DateInput :model-value="row.date" :parsed="row.lookups?.date" :disabled="ro" @update:model-value="emit('edit', { date: $event })" />
        <RepeatingSelect label="Media type" word="type" :model-value="row.type" :options="tenant.mediaTypes" :disabled="ro"
                         @update:model-value="emit('edit', { type: $event })" />
        <RepeatingSelect label="Language" word="language" :model-value="row.language ?? []" :options="languages ?? []" :disabled="ro"
                         @update:model-value="emit('edit', { language: $event })" />
        <AuthorityInput field="creator" label="Creator" :model-value="row.creator" :disabled="ro" @update:model-value="emit('edit', { creator: $event })" />
        <AuthorityInput field="contributor" label="Contributor" :model-value="row.contributor" :disabled="ro" @update:model-value="emit('edit', { contributor: $event })" />
        <AuthorityInput field="rightsHolder" label="Rights holder" :model-value="row.rightsHolder" :disabled="ro" @update:model-value="emit('edit', { rightsHolder: $event })" />
        <label class="field"><span>Copyright statement</span>
          <input type="text" :value="row.copyright" :disabled="ro" @change="text('copyright', $event)" /></label>
        <label class="field wide"><span>Description</span>
          <textarea rows="2" :value="row.description" :disabled="ro" @change="text('description', $event)"></textarea></label>
      </div>
      <div v-for="(c, i) in row.checks" :key="i" class="msg" :class="`msg-${c.level}`"><strong>{{ PREFIX[c.level] }}</strong>{{ c.text }}</div>
      <div v-if="row.result?.error" class="msg msg-block">
        {{ row.result.error.detail }} ({{ row.result.error.code }}, step {{ row.result.error.step }})
      </div>
      <div v-if="!ro" style="margin-top:6px"><button class="link" @click="emit('remove')">Delete document</button></div>
    </td>
  </tr>
</template>
