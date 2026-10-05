<template>
  <aside
    id="bulk-panel"
    aria-label="Change selected documents"
    class="bulk-side"
    :class="{collapsed: isCollapsed}"
  >
    <v-card class="bulk-panel" color="surface-light" variant="flat">
      <div class="align-center bulk-head d-flex">
        <span id="bulk-panel-title" class="bulk-title flex-grow-1 font-weight-bold text-body-2 text-truncate">Change selected documents</span>
        <v-btn
          id="bulk-panel-toggle-btn"
          :aria-expanded="!isCollapsed"
          :aria-label="`${isCollapsed ? 'Show' : 'Hide'} the panel for changing selected documents`"
          density="comfortable"
          :icon="isCollapsed ? mdiChevronRight : mdiChevronLeft"
          size="small"
          :title="isCollapsed ? 'Show panel' : 'Hide panel'"
          variant="text"
          @click="() => toggle()"
        />
      </div>
      <div v-show="!isCollapsed" class="bulk-open dense-fields">
        <div id="bulk-panel-selection" class="mb-3 text-caption">
          <template v-if="anySelected"><strong>{{ selectedRows.length }}</strong> of {{ rows.length }} documents selected. Changes apply to them.</template>
          <template v-else>No documents selected. Select rows in the table, or use Apply to all.</template>
        </div>

        <div class="field-label">Handling</div>
        <div class="mb-1 text-caption text-medium-emphasis">Changing handling also applies its preset fields, except fields you have edited yourself.</div>
        <div class="bulk-group">
          <select
            v-if="tenant.handling.length > 1"
            id="bulk-handling-select"
            v-model="choice.handling"
            aria-label="Handling for selected"
            class="native-select"
            :disabled="readonly"
          >
            <option value="">Handling — no change</option>
            <option
              v-for="h in tenant.handling"
              :key="h.id"
              :disabled="!!handlingBlocked(h, perms)"
              :title="handlingBlocked(h, perms)"
              :value="h.id"
            >
              {{ h.label }}{{ handlingNote(h, perms) }}
            </option>
          </select>
          <span v-else class="text-caption text-medium-emphasis">Handling: {{ tenant.handling[0]?.label }} (only option)</span>
          <select
            id="bulk-publish-select"
            v-model="choice.publish"
            :aria-label="`${tenant.publish.header} for selected`"
            class="native-select"
            :disabled="readonly"
          >
            <option value="">{{ tenant.publish.header }} — no change</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
          <select
            v-if="groupOn"
            id="bulk-group-select"
            v-model="choice.group"
            aria-label="Group for selected"
            class="native-select"
            :disabled="readonly || !perms.groups"
            :title="perms.groups ? undefined : 'You don\'t have permission to create groups'"
          >
            <option value="">In the job's group — no change</option>
            <option value="yes">Yes</option>
            <option value="no">No (leave out)</option>
          </select>
        </div>

        <div class="field-label">CollectionSpace Media fields</div>
        <div class="mb-1 text-caption text-medium-emphasis">
          Leave a field blank to keep each document’s current value. A media type or language replaces the document’s current ones.
        </div>
        <div class="bulk-group">
          <select
            id="bulk-type-select"
            v-model="choice.type"
            aria-label="Media type for selected"
            class="native-select"
            :disabled="readonly"
          >
            <option value="">Media type — no change</option>
            <option v-for="t in tenant.mediaTypes" :key="t.value" :value="t.value">{{ t.label }}</option>
          </select>
          <select
            id="bulk-language-select"
            v-model="choice.language"
            aria-label="Language for selected"
            class="native-select"
            :disabled="readonly"
          >
            <option value="">Language — no change</option>
            <option v-for="l in languages" :key="l.value" :value="l.value">{{ l.label }}</option>
          </select>
          <AuthorityInput
            v-for="f in authorityFields"
            :id="`bulk-${f.field}`"
            :key="f.field"
            v-model="choice[f.field]"
            :disabled="readonly"
            :field="f.field"
            :label="f.label"
            :timing="tenant.autocomplete"
          />
        </div>

        <div class="bulk-group">
          <v-btn
            id="bulk-apply-selected-btn"
            block
            color="primary"
            :disabled="readonly || busy || !anySelected || !verdict.ok"
            :title="anySelected && !verdict.ok ? verdict.why : undefined"
            @click="applySelected"
          >
            Apply to selected
          </v-btn>
          <v-btn
            id="bulk-apply-all-btn"
            block
            color="primary"
            :disabled="readonly || busy || anySelected || !verdict.ok"
            :title="!anySelected && !verdict.ok ? verdict.why : undefined"
            @click="applyAll"
          >
            Apply to all
          </v-btn>
          <div
            v-if="verdict.picked && !verdict.ok"
            id="bulk-note"
            class="text-caption"
            :class="verdict.neutral ? 'text-medium-emphasis' : 'text-warning'"
            role="status"
          >
            {{ verdict.why }}
          </div>
        </div>
        <v-divider class="mb-3" />
        <div class="bulk-group mb-0">
          <v-btn
            id="bulk-exclude-btn"
            block
            :disabled="readonly || busy || !toExclude.length"
            title="Have the BMU ignore the selected documents"
            variant="outlined"
            @click="() => emit('include', toExclude.map(r => r.n), false)"
          >
            Exclude selected
          </v-btn>
          <v-btn
            id="bulk-include-btn"
            block
            :disabled="readonly || busy || !toInclude.length"
            variant="outlined"
            @click="() => emit('include', toInclude.map(r => r.n), true)"
          >
            Include selected
          </v-btn>
          <v-btn
            v-if="!isConfirmingDelete"
            id="bulk-delete-btn"
            block
            :disabled="readonly || busy || !toDelete.length"
            :title="anySelected && !toDelete.length ? 'The selected documents already created records in CollectionSpace, so they can\'t be deleted; use Exclude instead.' : 'Delete the selected documents from this job permanently'"
            variant="outlined"
            @click="askDelete"
          >
            <v-progress-circular
              v-if="deleting"
              aria-hidden="true"
              class="mr-2"
              indeterminate
              size="14"
              width="2"
            />
            {{ deleting ? 'Deleting…' : 'Delete selected' }}
          </v-btn>
          <v-alert
            v-else
            id="bulk-delete-confirm"
            aria-label="Confirm deleting the selected documents"
            class="bulk-confirm text-caption"
            density="compact"
            role="group"
            type="warning"
            variant="tonal"
          >
            <div class="mb-2">{{ deleteQuestion }}</div>
            <v-btn
              id="bulk-delete-confirm-btn"
              block
              class="mb-2"
              color="error"
              :disabled="readonly || busy"
              @click="doDelete"
            >
              Delete {{ plural(toDelete.length, 'document') }}
            </v-btn>
            <v-btn
              id="bulk-delete-cancel-btn"
              block
              variant="outlined"
              @click="isConfirmingDelete = false"
            >
              Cancel
            </v-btn>
          </v-alert>
        </div>
      </div>
      <button
        v-if="isCollapsed"
        aria-hidden="true"
        class="bulk-rail"
        tabindex="-1"
        title="Show panel"
        type="button"
        @click="() => toggle(true)"
      >
        <span class="rail-label">Change selected documents</span>
        <v-chip
          v-if="anySelected"
          class="font-weight-bold"
          color="primary"
          size="x-small"
          variant="flat"
        >
          {{ selectedRows.length }}
        </v-chip>
      </button>
    </v-card>
  </aside>
</template>

<script setup lang="ts">
import type {PropType} from 'vue'
import {computed, reactive, ref, watch} from 'vue'
import {mdiChevronLeft, mdiChevronRight} from '@mdi/js'
import type {BulkChanges} from '@/lib/bulk'
import type {Option, Perms, Row, TenantInfo} from '@/types'
import AuthorityInput from '@/components/util/AuthorityInput.vue'
import {applyAllTargets, bulkCheck, includeTargets} from '@/lib/bulk'
import {createdSomething} from '@/lib/results'
import {handlingBlocked, handlingNote} from '@/lib/status'
import {putFocusNextTick} from '@/lib/utils'

/**
 * "Change selected documents": the bulk-change panel to the left of the document table (design: User interface).
 * The apply buttons stay greyed out, with a one-line reason, until every target document can take every chosen
 * change.
 */
const props = defineProps({
  busy: {
    required: true,
    type: Boolean
  },
  // Delete selected was sent and the answer hasn't come back yet.
  deleting: {
    required: false,
    type: Boolean
  },
  groupOn: {
    required: false,
    type: Boolean
  },
  languages: {
    default: () => [],
    required: false,
    type: Array as PropType<Option[]>
  },
  perms: {
    required: true,
    type: Object as PropType<Perms>
  },
  readonly: {
    required: true,
    type: Boolean
  },
  rows: {
    required: true,
    type: Array as PropType<Row[]>
  },
  selected: {
    required: true,
    type: Set as PropType<Set<number>>
  },
  tenant: {
    required: true,
    type: Object as PropType<TenantInfo>
  }
})
const emit = defineEmits<{apply: [targets: number[], changes: BulkChanges], include: [targets: number[], include: boolean], delete: [targets: number[]]}>()

type AuthorityField = 'creator' | 'contributor' | 'rightsHolder'
const AUTHORITY_FIELDS: {field: AuthorityField, label: string}[] = [
  {field: 'creator', label: 'Creator'},
  {field: 'contributor', label: 'Contributor'},
  {field: 'rightsHolder', label: 'Rights holder'}
]
const KEY = 'bmuPanelCollapsed'
const NO_CHOICE = {handling: '', publish: '', group: '', type: '', language: '', creator: '', contributor: '', rightsHolder: ''}

const remembered = (): boolean => {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}
const isCollapsed = ref(remembered())
const toggle = (open?: boolean) => {
  isCollapsed.value = open === undefined ? !isCollapsed.value : !open
  try {
    localStorage.setItem(KEY, isCollapsed.value ? '1' : '0')
  } catch {
    // A per-browser convenience only
  }
}

// The panel's choices: "" means no change.
const choice = reactive({...NO_CHOICE})
const reset = () => Object.assign(choice, NO_CHOICE)
defineExpose({reset})

const changes = computed<BulkChanges>(() => {
  const c: BulkChanges = {}
  if (choice.handling) c.handling = choice.handling
  if (choice.publish) c.restricted = choice.publish === 'yes'
  if (choice.group && props.groupOn) c.group = choice.group === 'yes'
  // Repeating fields: the chosen value replaces a document's values.
  if (choice.type) c.type = [choice.type]
  if (choice.language) c.language = [choice.language]
  if (choice.creator) c.creator = choice.creator
  if (choice.contributor) c.contributor = choice.contributor
  if (choice.rightsHolder) c.rightsHolder = choice.rightsHolder
  return c
})

const selectedRows = computed(() => props.rows.filter(r => props.selected.has(r.n)))
const anySelected = computed(() => selectedRows.value.length > 0)
const linking = computed(() => new Set(props.tenant.handling.filter(h => h.object !== 'none').map(h => h.id)))
const verdict = computed(() => anySelected.value
  ? bulkCheck(selectedRows.value, changes.value, false, linking.value)
  : bulkCheck(applyAllTargets(props.rows), changes.value, true, linking.value))
const toExclude = computed(() => includeTargets(selectedRows.value, false))
const toInclude = computed(() => includeTargets(selectedRows.value, true))
// Delete selected (design: Deleting a row): documents that created something in CollectionSpace stay.
const toDelete = computed(() => selectedRows.value.filter(r => !createdSomething(r)))
/** Selected documents whose files are still uploading: deleting them stops the upload. */
const uploadingCount = computed(() => toDelete.value.filter(r => ['pending', 'uploading', 'verifying'].includes(r.upload.s)).length)
const keptCount = computed(() => selectedRows.value.length - toDelete.value.length)
const deletesAll = computed(() => toDelete.value.length > 0 && toDelete.value.length === props.rows.length)
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`
const deleteQuestion = computed(() => {
  const k = toDelete.value.length
  return `Delete ${plural(k, 'selected document')} from this job permanently? `
    + (uploadingCount.value === k
      ? `${k === 1 ? 'Its upload is' : 'Their uploads are'} stopped and anything already sent is removed`
      : `${k === 1 ? 'Its uploaded file is removed' : 'Their uploaded files are removed'}`)
    + '; nothing in CollectionSpace is touched.'
    + (uploadingCount.value && uploadingCount.value < k
      ? ` ${plural(uploadingCount.value, 'upload')} still in progress ${uploadingCount.value === 1 ? 'is' : 'are'} stopped.` : '')
    + (keptCount.value ? ` ${plural(keptCount.value, 'selected document')} already created records in CollectionSpace and will stay (use Exclude for those).` : '')
    + (deletesAll.value ? ' That\'s every document in the job, so the job is deleted too.' : '')
})
const isConfirmingDelete = ref(false)
watch(() => toDelete.value.length, k => {
  if (!k) {
    isConfirmingDelete.value = false
  }
})

const askDelete = () => {
  isConfirmingDelete.value = true
  putFocusNextTick('bulk-delete-cancel-btn', {scroll: false})
}

/** Sends every selected document: the server deletes those it may and reports the ones it kept. */
const doDelete = () => {
  isConfirmingDelete.value = false
  emit('delete', selectedRows.value.map(r => r.n))
}

// The authority fields this tenant has set up
const authorityFields = computed(() => AUTHORITY_FIELDS.filter(f => (props.tenant.authorityFields[f.field] ?? []).length > 0))

const applySelected = () => emit('apply', selectedRows.value.map(r => r.n), changes.value)
const applyAll = () => emit('apply', applyAllTargets(props.rows).map(r => r.n), changes.value)
</script>

<style scoped>
.bulk-side {
  min-width: 0;
  position: sticky;
  top: 76px;
}
.bulk-head {
  min-height: 42px;
  padding: 8px 8px 8px 12px;
}
.bulk-side.collapsed .bulk-head {
  justify-content: center;
  padding: 8px 0;
}
.bulk-side.collapsed .bulk-title {
  display: none;
}
.bulk-open {
  padding: 0 12px 12px;
}
.bulk-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 4px 0 12px;
}
.bulk-rail {
  align-items: center;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 200px;
  padding: 6px 0 12px;
  width: 100%;
}
.rail-label {
  font-size: 0.75rem;
  font-weight: 600;
  transform: rotate(180deg);
  white-space: nowrap;
  writing-mode: vertical-rl;
}
@media (max-width: 900px) {
  .bulk-side {
    position: static;
  }
  .bulk-side.collapsed .bulk-head {
    justify-content: flex-start;
    padding: 8px 8px 8px 12px;
  }
  .bulk-side.collapsed .bulk-title {
    display: block;
  }
  .bulk-rail {
    display: none;
  }
}
</style>
