<script setup lang="ts">
/**
 * "Change selected documents": the bulk-change panel to the left of the document table (design: User
 * interface; UI mockup). The apply buttons stay greyed out, with a one-line reason, until every target
 * document can take every chosen change.
 */
import { computed, reactive, ref } from "vue";
import { applyAllTargets, bulkCheck, includeTargets, type BulkChanges } from "../lib/bulk";
import { handlingBlocked } from "../lib/status";
import type { Option, Perms, Row, TenantInfo } from "../types";
import AuthorityInput from "./AuthorityInput.vue";

const props = defineProps<{
  rows: Row[]; selected: Set<number>; tenant: TenantInfo; perms: Perms; readonly: boolean; busy: boolean; languages?: Option[];
  groupOn?: boolean;
}>();
const emit = defineEmits<{ apply: [targets: number[], changes: BulkChanges]; include: [targets: number[], include: boolean] }>();

const KEY = "bmuPanelCollapsed";
function remembered(): boolean {
  try { return localStorage.getItem(KEY) === "1"; } catch { return false; }
}
const collapsed = ref(remembered());
function toggle(open?: boolean) {
  collapsed.value = open === undefined ? !collapsed.value : !open;
  try { localStorage.setItem(KEY, collapsed.value ? "1" : "0"); } catch { /* per-browser convenience only */ }
}

// The panel's choices: "" means no change.
const choice = reactive({ handling: "", publish: "", group: "", type: "", language: "", creator: "", contributor: "", rightsHolder: "" });
function reset() {
  Object.assign(choice, { handling: "", publish: "", group: "", type: "", language: "", creator: "", contributor: "", rightsHolder: "" });
}
defineExpose({ reset });

const changes = computed<BulkChanges>(() => {
  const c: BulkChanges = {};
  if (choice.handling) c.handling = choice.handling;
  if (choice.publish) c.restricted = choice.publish === "yes";
  if (choice.group && props.groupOn) c.group = choice.group === "yes";
  // Repeating fields: the chosen value replaces a document's values (as in the UI mockup).
  if (choice.type) c.type = [choice.type];
  if (choice.language) c.language = [choice.language];
  if (choice.creator) c.creator = choice.creator;
  if (choice.contributor) c.contributor = choice.contributor;
  if (choice.rightsHolder) c.rightsHolder = choice.rightsHolder;
  return c;
});

const selectedRows = computed(() => props.rows.filter((r) => props.selected.has(r.n)));
const anySelected = computed(() => selectedRows.value.length > 0);
const linking = computed(() => new Set(props.tenant.handling.filter((h) => h.object !== "none").map((h) => h.id)));
const verdict = computed(() => anySelected.value
  ? bulkCheck(selectedRows.value, changes.value, false, linking.value)
  : bulkCheck(applyAllTargets(props.rows), changes.value, true, linking.value));
const toExclude = computed(() => includeTargets(selectedRows.value, false));
const toInclude = computed(() => includeTargets(selectedRows.value, true));
const hasField = (f: string) => (props.tenant.authorityFields[f] ?? []).length > 0;

function applySelected() {
  emit("apply", selectedRows.value.map((r) => r.n), changes.value);
}
function applyAll() {
  emit("apply", applyAllTargets(props.rows).map((r) => r.n), changes.value);
}
</script>

<template>
  <aside class="bulk-side" :class="{ collapsed }" aria-label="Change selected documents">
    <div class="bulk-panel">
      <div class="bulk-head">
        <span class="bulk-title">Change selected documents</span>
        <button class="icon-btn" :aria-expanded="!collapsed" :title="collapsed ? 'Show panel' : 'Hide panel'"
                :aria-label="`${collapsed ? 'Show' : 'Hide'} the panel for changing selected documents`" @click="toggle()">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 3.5 5.5 8 10 12.5"/></svg>
        </button>
      </div>
      <div v-show="!collapsed" class="bulk-open">
        <div class="bulk-sel">
          <template v-if="anySelected"><strong>{{ selectedRows.length }}</strong> of {{ rows.length }} documents selected. Changes apply to them.</template>
          <template v-else>No documents selected. Select rows in the table, or use Apply to all.</template>
        </div>

        <div class="section-title">Handling</div>
        <div class="section-hint">Changing handling also applies its preset fields, except fields you have edited yourself.</div>
        <div class="bulk-group">
          <select v-if="tenant.handling.length > 1" v-model="choice.handling" aria-label="Handling for selected" :disabled="readonly">
            <option value="">Handling — no change</option>
            <option v-for="h in tenant.handling" :key="h.id" :value="h.id" :disabled="!!handlingBlocked(h, perms)" :title="handlingBlocked(h, perms)">
              {{ h.label }}{{ handlingBlocked(h, perms) ? " (no permission)" : "" }}</option>
          </select>
          <span v-else class="sub">Handling: {{ tenant.handling[0]?.label }} (only option)</span>
          <select v-model="choice.publish" :aria-label="`${tenant.publish.header} for selected`" :disabled="readonly">
            <option value="">{{ tenant.publish.header }} — no change</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
          <select v-if="groupOn" v-model="choice.group" aria-label="Group for selected" :disabled="readonly || !perms.groups"
                  :title="perms.groups ? '' : 'You don\'t have permission to create groups'">
            <option value="">In the job's group — no change</option>
            <option value="yes">Yes</option>
            <option value="no">No (leave out)</option>
          </select>
        </div>

        <div class="section-title">CollectionSpace Media fields</div>
        <div class="section-hint">Leave a field blank to keep each document’s current value. A media type or language
          replaces the document’s current ones.</div>
        <div class="bulk-group">
          <select v-model="choice.type" aria-label="Media type for selected" :disabled="readonly">
            <option value="">Media type — no change</option>
            <option v-for="t in tenant.mediaTypes" :key="t.value" :value="t.value">{{ t.label }}</option>
          </select>
          <select v-model="choice.language" aria-label="Language for selected" :disabled="readonly">
            <option value="">Language — no change</option>
            <option v-for="l in languages ?? []" :key="l.value" :value="l.value">{{ l.label }}</option>
          </select>
          <AuthorityInput v-if="hasField('creator')" field="creator" label="Creator" :model-value="choice.creator" :disabled="readonly"
                          @update:model-value="choice.creator = $event" />
          <AuthorityInput v-if="hasField('contributor')" field="contributor" label="Contributor" :model-value="choice.contributor" :disabled="readonly"
                          @update:model-value="choice.contributor = $event" />
          <AuthorityInput v-if="hasField('rightsHolder')" field="rightsHolder" label="Rights holder" :model-value="choice.rightsHolder" :disabled="readonly"
                          @update:model-value="choice.rightsHolder = $event" />
        </div>

        <div class="bulk-group">
          <button class="primary" :disabled="readonly || busy || !anySelected || !verdict.ok" :title="anySelected && !verdict.ok ? verdict.why : ''"
                  @click="applySelected">Apply to selected</button>
          <button class="primary" :disabled="readonly || busy || anySelected || !verdict.ok" :title="!anySelected && !verdict.ok ? verdict.why : ''"
                  @click="applyAll">Apply to all</button>
          <div v-if="verdict.picked && !verdict.ok" class="bulk-note" :class="{ neutral: verdict.neutral }" role="status">{{ verdict.why }}</div>
        </div>
        <div class="bulk-group divided">
          <button :disabled="readonly || busy || !toExclude.length" title="Have the BMU ignore the selected documents"
                  @click="emit('include', toExclude.map((r) => r.n), false)">Exclude selected</button>
          <button :disabled="readonly || busy || !toInclude.length" @click="emit('include', toInclude.map((r) => r.n), true)">Include selected</button>
        </div>
      </div>
      <button v-if="collapsed" class="bulk-rail" tabindex="-1" aria-hidden="true" title="Show panel" @click="toggle(true)">
        <span class="rail-label">Change selected documents</span>
        <span v-if="anySelected" class="rail-count">{{ selectedRows.length }}</span>
      </button>
    </div>
  </aside>
</template>
