<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { Option, Perms, Row, TenantInfo } from "../types";
import { formatBytes } from "../lib/files";
import { filenameProblems, idLabel, objectLabel } from "../lib/filenames";
import { handlingBlocked, rowStatus, worstLevel } from "../lib/status";
import { canReplaceFile, createdSomething, fixFields, mediaCreated, objectStepRan, stepList, STEP_MARK, stepNote } from "../lib/results";
import AuthorityInput from "./AuthorityInput.vue";
import DateInput from "./DateInput.vue";
import ErrorBox from "./ErrorBox.vue";
import RepeatingSelect from "./RepeatingSelect.vue";

const props = defineProps<{
  row: Row; tenant: TenantInfo; perms: Perms; preview?: string; expanded: boolean; readonly: boolean; checking?: boolean;
  selected?: boolean; languages?: Option[]; otherNames?: string[]; uploadingHere?: boolean; groupOn?: boolean;
}>();
const emit = defineEmits<{ edit: [changes: Partial<Row>]; remove: []; toggle: []; select: [on: boolean]; replace: [file: File]; retry: [] }>();

// Design: a failed upload shows "Upload failed" with Retry and Remove. An upload this page isn't sending
// (the page that added the file was closed, or it's another person's browser) won't finish on its own.
const stalled = computed(() => !props.uploadingHere && !props.row.result && ["pending", "uploading", "verifying"].includes(props.row.upload.s));
const canRetry = computed(() => !props.readonly && props.row.include && !props.row.result && (props.row.upload.s === "failed" || stalled.value));
const confirmRemove = ref(false);

// The job's group: only documents linked to an object can join; once its object is in the group, it stays.
const inGroup = computed(() => props.row.group ?? true);
const groupDone = computed(() => props.row.result?.steps?.addToGroup?.s === "done");
const groupWhy = computed(() => handling.value?.object === "none" ? "Not linked to an object, so it can't join the group"
  : groupDone.value ? (props.row.result?.steps?.addToGroup?.sameAs ? `Its object was added by document ${props.row.result.steps.addToGroup.sameAs}` : "Its object is in the group")
  : !props.perms.groups ? "You don't have permission to create groups" : "");

// After a run (design: Fixing a job after a run): a document whose Media record exists changes only what the
// rerun still needs; a Failed one whose object step ran keeps its handling and object number.
const created = computed(() => mediaCreated(props.row));
const done = computed(() => props.row.result?.state === "Done");
const ro = computed(() => props.readonly || created.value || !props.row.include);
const objFixed = computed(() => !created.value && objectStepRan(props.row));
const allowed = computed(() => fixFields(props.row));
const canEditObj = computed(() => !props.readonly && props.row.include && (created.value ? allowed.value.obj : !objFixed.value));
const replaceable = computed(() => !props.readonly && canReplaceFile(props.row));
const replaceInput = ref<HTMLInputElement | null>(null);
function pickReplacement(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  if (f) emit("replace", f);
  (e.target as HTMLInputElement).value = "";
}
const handling = computed(() => props.tenant.handling.find((h) => h.id === props.row.handling));

const status = computed(() => stalled.value && props.row.include ? { text: "Upload not finished", cls: "b-danger" }
  : rowStatus(props.row, props.tenant, props.checking));
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
      <select :value="row.handling" :disabled="ro || objFixed" aria-label="Handling" :title="objFixed ? '🔒 The last run already found or created this document\'s object' : ''" @change="emit('edit', { handling: ($event.target as HTMLSelectElement).value })">
        <option v-for="h in tenant.handling" :key="h.id" :value="h.id" :disabled="!!handlingBlocked(h, perms) && h.id !== row.handling"
                :title="handlingBlocked(h, perms)">{{ h.label }}{{ handlingBlocked(h, perms) ? " (no permission)" : "" }}</option>
      </select>
    </td>
    <td style="text-align:center">
      <input type="checkbox" :checked="row.restricted" :disabled="ro || !row.include" :aria-label="tenant.publish.header"
             @change="emit('edit', { restricted: ($event.target as HTMLInputElement).checked })" />
    </td>
    <td v-if="groupOn" style="text-align:center">
      <input type="checkbox" :checked="inGroup && handling?.object !== 'none'" :aria-label="`${row.file} in the job's group`" :title="groupWhy"
             :disabled="readonly || !row.include || handling?.object === 'none' || groupDone || done || (!perms.groups && !inGroup)"
             @change="emit('edit', { group: ($event.target as HTMLInputElement).checked })" /></td>
    <td><span class="badge" :class="status.cls">{{ status.text }}</span>
      <span v-if="hasWarnings && status.cls !== 'b-danger'" class="badge b-warn" title="This document has warnings"> !</span>
      <div v-if="row.upload.s === 'uploading' && !stalled" class="progress"><span class="up" :style="{ width: (row.upload.pct ?? 0) + '%' }"></span></div>
      <div v-if="canRetry" class="retry-line">
        <template v-if="!confirmRemove"><button type="button" @click="emit('retry')">Retry</button>
          <button type="button" @click="confirmRemove = true">Remove</button></template>
        <template v-else><span class="sub">Remove this document?</span> <button type="button" @click="confirmRemove = false; emit('remove')">Remove</button>
          <button type="button" @click="confirmRemove = false">Cancel</button></template>
      </div>
    </td>
    <td class="keep">
      <label v-if="row.result?.state !== 'Done'" class="sub"><input type="checkbox" :checked="row.include" :disabled="readonly"
        @change="emit('edit', { include: ($event.target as HTMLInputElement).checked })" /> Include</label>
    </td>
  </tr>
  <tr v-if="expanded" class="detail">
    <td :colspan="groupOn ? 9 : 8">
      <template v-if="created">
        <div class="msg msg-info">
          <template v-if="done">This document was fully created in CollectionSpace (Media record {{ row.result?.steps?.media?.csid }}). Nothing here can
            change; to change the Media record, edit it in CollectionSpace.</template>
          <template v-else>This document's Media record was already created in CollectionSpace ({{ row.result?.steps?.media?.csid }}), so its
            fields, handling and publishing can't be changed here; to change them, edit the Media record in CollectionSpace. Below you can
            change only what the rerun still needs.</template>
        </div>
        <div class="section-title">Last run</div>
        <div class="steps" style="margin-bottom:6px">
          <div v-for="s in stepList(row)" :key="s.key" :class="{ 'step-failed': s.step.s === 'failed' }">{{ STEP_MARK[s.step.s] }} {{ s.label }}
            <code v-if="s.step.csid">{{ s.step.csid }}</code><span v-if="stepNote(s.key, s.step)" class="sub"> ({{ stepNote(s.key, s.step) }})</span></div>
        </div>
        <ErrorBox v-if="row.result?.error && !done" :code="row.result.error.code" :detail="row.result.error.detail" />
        <div class="grid">
          <div v-if="allowed.obj" class="field" :class="{ edited: objLabel.edited }">
            <label><span>Object number <em class="num-state">{{ objLabel.text }}</em></span>
              <input type="text" :value="row.obj" :disabled="!canEditObj" aria-label="Object number" @change="text('obj', $event)" /></label>
          </div>
          <label v-if="allowed.skipLink && !readonly" class="field wide check-line">
            <input type="checkbox" :checked="!!row.skipLink" :disabled="!row.include"
                   @change="emit('edit', { skipLink: ($event.target as HTMLInputElement).checked })" />
            Stop linking this Media record to an object (the rerun skips the remaining object steps; the Media record keeps its
            identification number)</label>
          <div v-if="replaceable" class="field wide">
            <span class="field-note" style="font-size:12px">{{ row.replacedFor === row.result?.run ? `Replacement file: ${row.file}` : `File: ${row.file}` }}</span>
            <button type="button" @click="replaceInput?.click()">{{ row.replacedFor === row.result?.run ? "Choose another file…" : "Replace file…" }}</button>
            <span class="field-note">The rerun uploads it to the existing Media record.</span>
            <input ref="replaceInput" type="file" hidden @change="pickReplacement" />
          </div>
        </div>
      </template>
      <template v-else>
      <ErrorBox v-if="row.result?.error" :code="row.result.error.code" :detail="row.result.error.detail" />
      <div v-if="row.result?.state === 'Not started' && row.result?.run" class="msg msg-info">Not reached in the last run; it runs on the rerun.</div>
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
          <label><span>Object number <em class="num-state">{{ objFixed ? "🔒 its object already exists" : objLabel.text }}</em></span>
            <input type="text" :value="row.obj" :disabled="ro || objFixed" aria-label="Object number" @change="text('obj', $event)" /></label>
          <button v-if="objLabel.reset !== undefined && !ro && !objFixed" class="link field-note" type="button" @click="emit('edit', { obj: objLabel.reset })">Use parsed value</button>
        </div>
        <div class="field" :class="{ edited: idnLabel.edited }">
          <label><span>Identification number <em class="num-state">{{ idnLabel.text }}</em></span>
            <input type="text" :value="row.idnum" :disabled="ro" aria-label="Identification number" @change="text('idnum', $event)" /></label>
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
      </template>
      <ErrorBox v-for="(nt, i) in row.result?.notices ?? []" :key="'n' + i" :code="nt.code" :detail="nt.detail" notice />
      <div v-for="(c, i) in row.checks" :key="i" class="msg" :class="`msg-${c.level}`"><strong>{{ PREFIX[c.level] }}</strong>{{ c.text }}</div>
      <div v-if="!readonly && row.include && !createdSomething(row)" style="margin-top:6px">
        <template v-if="!confirmRemove"><button class="link" @click="confirmRemove = true">Delete document</button>
          <span class="field-note" style="display:inline">Permanent, unlike Include off. Only for documents that haven't created anything in CollectionSpace.</span></template>
        <div v-else class="msg msg-warn">Delete “{{ row.file }}” from this job permanently? Its uploaded file is removed; nothing in CollectionSpace is touched.
          <button @click="confirmRemove = false; emit('remove')">Delete document</button> <button @click="confirmRemove = false">Cancel</button></div></div>
      <div v-else-if="!readonly && createdSomething(row) && !done" class="field-note" style="margin-top:6px">This document already created records in
        CollectionSpace, so it can't be deleted from the job; switch Include off to have the BMU ignore it.</div>
    </td>
  </tr>
</template>
