<template>
  <tbody :id="`document-${row.n}`" class="document">
    <tr :aria-busy="deleting" class="document-row" :class="{'row-deleting': deleting, 'row-excluded': !row.include}">
      <td class="thumb-col">
        <DocumentThumbnail :job-id="jobId" :preview="preview" :row="row" />
      </td>
      <td class="keep px-1">
        <input
          :id="`document-${row.n}-select`"
          :aria-label="`Select ${row.file}`"
          :checked="selected"
          class="checkbox"
          type="checkbox"
          @change="event => emit('select', row.n, (event.target as HTMLInputElement).checked)"
        >
      </td>
      <td class="keep px-0">
        <v-btn
          :id="`document-${row.n}-toggle-btn`"
          :aria-expanded="expanded"
          aria-label="Show details"
          class="chevron"
          :class="{open: expanded}"
          density="comfortable"
          :icon="mdiChevronRight"
          size="small"
          variant="text"
          @click="() => emit('toggle', row.n)"
        />
      </td>
      <td class="py-1">
        <div>
          <span :id="`document-${row.n}-file`">{{ row.file }}</span>
          <v-chip
            v-if="renamed"
            class="ml-2"
            color="info"
            size="x-small"
            :title="`Original: ${original}`"
          >
            Renamed
          </v-chip>
          <v-chip
            v-if="row.protected"
            class="ml-2"
            color="error"
            :prepend-icon="mdiLock"
            size="x-small"
            :title="`Protected file: ${row.protected.reason}`"
          >
            Protected
          </v-chip>
        </div>
        <div class="text-caption text-medium-emphasis">
          {{ formatBytes(row.size) }}<template v-if="handling?.object !== 'none'"> · object {{ row.obj || '—' }}</template>
        </div>
      </td>
      <td>
        <select
          :id="`document-${row.n}-handling`"
          aria-label="Handling"
          class="native-select w-100"
          :disabled="handlingLocked"
          :title="objFixed ? 'The last run already found or created this document\'s object' : relink ? 'The object already exists: choose a handling that links to it' : undefined"
          :value="row.handling"
          @change="event => emit('edit', row, {handling: (event.target as HTMLSelectElement).value})"
        >
          <option
            v-for="h in tenant.handling"
            :key="h.id"
            :disabled="!!handlingOptionOff(h)"
            :title="handlingOptionOff(h)"
            :value="h.id"
          >
            {{ h.label }}{{ h.id !== row.handling && !relink && handlingBlocked(h, perms) ? ' (no permission)' : '' }}
          </option>
        </select>
      </td>
      <td class="text-center">
        <input
          :id="`document-${row.n}-restricted`"
          :aria-label="tenant.publish.header"
          :checked="row.restricted"
          class="checkbox"
          :disabled="ro || !row.include"
          type="checkbox"
          @change="event => emit('edit', row, {restricted: (event.target as HTMLInputElement).checked})"
        >
      </td>
      <td>
        <span
          :id="`document-${row.n}-portal`"
          class="text-body-2 text-no-wrap"
          :class="portal.k === 'pub' ? 'text-success' : 'text-medium-emphasis'"
          :title="portal.why"
        >
          <v-icon :icon="portal.k === 'pub' ? mdiEarth : mdiEyeOffOutline" size="x-small" /> {{ portal.text }}
        </span>
      </td>
      <td v-if="groupOn" class="text-center">
        <input
          :id="`document-${row.n}-group`"
          :aria-label="`${row.file} in the job's group`"
          :checked="inGroup && handling?.object !== 'none'"
          class="checkbox"
          :disabled="readonly || !row.include || handling?.object === 'none' || groupDone || done || (!perms.groups && !inGroup)"
          :title="groupWhy"
          type="checkbox"
          @change="event => emit('edit', row, {group: (event.target as HTMLInputElement).checked})"
        >
      </td>
      <td class="py-1">
        <v-chip :id="`document-${row.n}-status`" :color="chipColor(status.tone)" size="small">
          <v-progress-circular
            v-if="'spin' in status && status.spin"
            aria-hidden="true"
            class="mr-1"
            indeterminate
            size="12"
            width="2"
          />
          {{ status.text }}
        </v-chip>
        <v-chip
          v-if="hasWarnings && !runView && status.tone !== 'error'"
          class="font-weight-bold ml-1"
          color="warning"
          size="small"
          title="This document has warnings"
        >
          !
        </v-chip>
        <v-progress-linear
          v-if="row.upload.s === 'uploading' && !stalled"
          :aria-label="`Uploading ${row.file}`"
          class="mt-1"
          color="primary"
          height="4"
          :model-value="row.upload.pct ?? 0"
          rounded
        />
        <div v-if="canRetry" class="align-center d-flex flex-wrap mt-1 retry-line">
          <template v-if="!isConfirmingRemove">
            <v-btn
              :id="`document-${row.n}-retry-btn`"
              class="mr-1"
              size="small"
              variant="outlined"
              @click="() => emit('retry', row)"
            >
              Retry
            </v-btn>
            <v-btn
              :id="`document-${row.n}-remove-btn`"
              size="small"
              variant="outlined"
              @click="isConfirmingRemove = true"
            >
              Remove
            </v-btn>
          </template>
          <template v-else>
            <span class="mr-1 text-caption">Remove this document?<template v-if="last"> This is the job's last document, so the job is deleted too.</template></span>
            <v-btn
              :id="`document-${row.n}-remove-confirm-btn`"
              class="mr-1"
              color="error"
              size="small"
              variant="outlined"
              @click="confirmRemove"
            >
              Remove
            </v-btn>
            <v-btn
              :id="`document-${row.n}-remove-cancel-btn`"
              size="small"
              variant="outlined"
              @click="isConfirmingRemove = false"
            >
              Cancel
            </v-btn>
          </template>
        </div>
      </td>
      <td class="keep text-center">
        <input
          v-if="row.result?.state !== 'Done'"
          :id="`document-${row.n}-exclude`"
          :aria-label="`Exclude ${row.file} from the job`"
          :checked="!row.include"
          class="checkbox"
          :disabled="readonly"
          title="Checked: the BMU ignores this document"
          type="checkbox"
          @change="event => emit('edit', row, {include: !(event.target as HTMLInputElement).checked})"
        >
      </td>
      <td v-if="!readonly" class="del-col keep px-0 text-center">
        <span :title="deleteTitle">
          <v-btn
            :id="`document-${row.n}-delete-btn`"
            :aria-label="DELETE_TITLE"
            class="row-del"
            :color="isConfirmingDelete ? 'error' : undefined"
            density="comfortable"
            :disabled="!deletable || deleting"
            :icon="mdiTrashCanOutline"
            size="small"
            :title="deleteTitle"
            variant="text"
            @click="askDelete"
          />
        </span>
      </td>
    </tr>
    <tr v-if="isConfirmingDelete && !readonly" class="del-confirm">
      <td class="py-1" :colspan="cols">
        <v-alert
          :aria-label="`Delete ${row.file}`"
          density="compact"
          role="group"
          type="warning"
          variant="tonal"
        >
          <div class="align-center d-flex flex-wrap justify-end">
            <span class="confirm-text flex-grow-1 mr-2">
              Delete “{{ row.file }}”? <template v-if="stillUploading">Its upload is stopped and anything already sent is removed</template><template v-else>Its uploaded file is removed</template>; nothing in CollectionSpace is touched.<template v-if="last"> This is the job's last document, so the job is deleted too.</template>
            </span>
            <v-btn
              :id="`document-${row.n}-delete-confirm-btn`"
              class="mr-2"
              color="error"
              size="small"
              @click="doDelete"
            >
              Delete
            </v-btn>
            <v-btn
              :id="`document-${row.n}-delete-cancel-btn`"
              size="small"
              variant="outlined"
              @click="cancelDelete"
            >
              Cancel
            </v-btn>
          </div>
        </v-alert>
      </td>
    </tr>
    <tr v-if="expanded" :id="`document-${row.n}-detail`" class="detail">
      <td class="pb-3 pt-2" :colspan="cols">
        <!-- The fields are drawn when the row comes into view: a page of a hundred open rows would otherwise take seconds. -->
        <v-lazy :min-height="created ? 140 : 330" :options="{rootMargin: '400px'}">
          <div class="dense-fields">
            <template v-if="created">
              <v-alert
                class="mb-2"
                density="compact"
                type="info"
                variant="tonal"
              >
                <template v-if="done">
                  This document was fully created in CollectionSpace (Media record {{ row.result?.steps?.media?.csid }}). Nothing here can change; to
                  change the Media record, edit it in CollectionSpace.
                </template>
                <template v-else>
                  This document's Media record was already created in CollectionSpace ({{ row.result?.steps?.media?.csid }}), so its fields, handling
                  and publishing can't be changed here; to change them, edit the Media record in CollectionSpace. Below you can change only what the
                  rerun still needs.
                </template>
              </v-alert>
              <div class="field-label">Last run</div>
              <div class="mb-2 steps text-caption">
                <div v-for="s in stepList(row)" :key="s.key" :class="{'text-error': s.step.s === 'failed'}">
                  {{ STEP_MARK[s.step.s] }} {{ s.label }}
                  <code v-if="s.step.csid">{{ s.step.csid }}</code><span v-if="stepNote(s.key, s.step)" class="text-medium-emphasis"> ({{ stepNote(s.key, s.step) }})</span>
                </div>
              </div>
              <FailureAlert v-if="row.result?.error && !done" :code="row.result.error.code" :detail="row.result.error.detail" />
              <div class="detail-grid">
                <div v-if="allowed.obj" :class="{'field-edited': objLabel.edited}">
                  <label class="field-label" :for="`document-${row.n}-obj`">Object number <em class="field-state">{{ objLabel.text }}</em></label>
                  <v-text-field
                    :id="`document-${row.n}-obj`"
                    aria-label="Object number"
                    :disabled="!canEditObj"
                    hide-details
                    :model-value="row.obj"
                    @change="(event: Event) => text('obj', event)"
                  />
                </div>
                <label v-if="allowed.skipLink && !readonly" class="align-start d-flex text-body-2 wide">
                  <input
                    :id="`document-${row.n}-skip-link`"
                    :checked="!!row.skipLink"
                    class="checkbox mr-2 mt-1"
                    :disabled="!row.include"
                    type="checkbox"
                    @change="event => emit('edit', row, {skipLink: (event.target as HTMLInputElement).checked})"
                  >
                  <span>Stop linking this Media record to an object (the rerun skips the remaining object steps; the Media record keeps its identification number)</span>
                </label>
              </div>
            </template>
            <template v-else>
              <FailureAlert v-if="row.result?.error" :code="row.result.error.code" :detail="row.result.error.detail" />
              <v-alert
                v-if="row.result?.state === 'Not started' && row.result?.run"
                class="mb-2"
                density="compact"
                type="info"
                variant="tonal"
              >
                Not reached in the last run; it runs on the rerun.
              </v-alert>
            </template>
            <div v-if="replaceable" class="mb-2 replace-line">
              <span class="mr-2 text-body-2">{{ row.replacedFor === row.result?.run ? `Replacement file: ${row.file}` : `File: ${row.file}` }}</span>
              <v-btn
                :id="`document-${row.n}-replace-btn`"
                size="small"
                variant="outlined"
                @click="() => replaceInput?.click()"
              >
                {{ row.replacedFor === row.result?.run ? 'Choose another file…' : 'Replace file…' }}
              </v-btn>
              <span class="field-note">{{ created ? 'The rerun uploads it to the existing Media record.' : 'Nothing was created for this document; the rerun checks it again with this file.' }}</span>
              <input
                ref="replaceInput"
                hidden
                type="file"
                @change="pickReplacement"
              >
            </div>
            <div v-if="!created" class="detail-grid">
              <div class="wide" :class="{'field-edited': renamed}">
                <label class="field-label" :for="`document-${row.n}-filename`">Filename <em class="field-state">{{ renamed ? `(renamed — original ${original})` : '(original)' }}</em></label>
                <v-text-field
                  :id="`document-${row.n}-filename`"
                  v-model="nameDraft"
                  aria-label="Filename"
                  :disabled="ro"
                  hide-details
                  spellcheck="false"
                  @blur="applyName"
                  @keydown.enter.prevent="applyName"
                />
                <v-alert
                  v-for="(error, index) in nameErrors"
                  :key="index"
                  class="mt-1"
                  density="compact"
                  type="error"
                  variant="tonal"
                >
                  {{ error }}
                </v-alert>
                <span class="field-note">
                  {{ tenant.filenameHint }}
                  <template v-if="renamed && !ro">
                    · <button
                      :id="`document-${row.n}-original-name-btn`"
                      class="link-btn"
                      type="button"
                      @click="() => emit('edit', row, {file: original})"
                    >Use original filename</button>
                  </template>
                </span>
              </div>
              <div :class="{'field-edited': idnLabel.edited}">
                <label class="field-label" :for="`document-${row.n}-idnum`">Identification number <em class="field-state">{{ idnLabel.text }}</em></label>
                <v-text-field
                  :id="`document-${row.n}-idnum`"
                  aria-label="Identification number"
                  :disabled="ro"
                  hide-details
                  :model-value="row.idnum"
                  @change="(event: Event) => text('idnum', event)"
                />
                <button
                  v-if="idnLabel.reset !== undefined && !ro"
                  :id="`document-${row.n}-idnum-parsed-btn`"
                  class="field-note link-btn"
                  type="button"
                  @click="() => emit('edit', row, {idnum: idnLabel.reset})"
                >
                  Use parsed value
                </button>
              </div>
              <div v-if="handling?.object !== 'none'" :class="{'field-edited': objLabel.edited}">
                <label class="field-label" :for="`document-${row.n}-obj`">Object number <em class="field-state">{{ objFixed ? 'its object already exists' : objLabel.text }}</em></label>
                <v-text-field
                  :id="`document-${row.n}-obj`"
                  aria-label="Object number"
                  :disabled="ro || objFixed"
                  hide-details
                  :model-value="row.obj"
                  @change="(event: Event) => text('obj', event)"
                />
                <button
                  v-if="objLabel.reset !== undefined && !ro && !objFixed"
                  :id="`document-${row.n}-obj-parsed-btn`"
                  class="field-note link-btn"
                  type="button"
                  @click="() => emit('edit', row, {obj: objLabel.reset})"
                >
                  Use parsed value
                </button>
              </div>
              <DateInput
                :id="`document-${row.n}-date`"
                :disabled="ro"
                :exif="row.dateExif"
                :model-value="row.date"
                :parsed="row.lookups?.date"
                @update:model-value="value => emit('edit', row, {date: value})"
              />
              <RepeatingSelect
                :id="`document-${row.n}-type`"
                :disabled="ro"
                label="Media type"
                :model-value="row.type"
                :options="tenant.mediaTypes"
                :preset="preset.type"
                word="type"
                @update:model-value="value => emit('edit', row, {type: value})"
              />
              <AuthorityInput
                :id="`document-${row.n}-creator`"
                :disabled="ro"
                field="creator"
                label="Creator"
                :model-value="row.creator"
                :timing="tenant.autocomplete"
                @update:model-value="value => emit('edit', row, {creator: value})"
              />
              <AuthorityInput
                :id="`document-${row.n}-contributor`"
                :disabled="ro"
                field="contributor"
                label="Contributor"
                :model-value="row.contributor"
                :preset="preset.contributor"
                :timing="tenant.autocomplete"
                @update:model-value="value => emit('edit', row, {contributor: value})"
              />
              <AuthorityInput
                :id="`document-${row.n}-rights-holder`"
                :disabled="ro"
                field="rightsHolder"
                label="Rights holder"
                :model-value="row.rightsHolder"
                :timing="tenant.autocomplete"
                @update:model-value="value => emit('edit', row, {rightsHolder: value})"
              />
              <div class="wide">
                <label class="field-label" :for="`document-${row.n}-description`">Description</label>
                <v-textarea
                  :id="`document-${row.n}-description`"
                  auto-grow
                  density="compact"
                  :disabled="ro"
                  hide-details
                  :model-value="row.description"
                  rows="2"
                  variant="outlined"
                  @change="(event: Event) => text('description', event)"
                />
              </div>
              <div :class="{'field-preset': preset.copyright}">
                <label class="field-label" :for="`document-${row.n}-copyright`">Copyright statement<PresetChip v-if="preset.copyright" /></label>
                <v-text-field
                  :id="`document-${row.n}-copyright`"
                  :disabled="ro"
                  hide-details
                  :model-value="row.copyright"
                  @change="(event: Event) => text('copyright', event)"
                />
              </div>
              <RepeatingSelect
                :id="`document-${row.n}-language`"
                :disabled="ro"
                label="Language"
                :model-value="row.language ?? []"
                :options="languages"
                :preset="preset.language"
                word="language"
                @update:model-value="value => emit('edit', row, {language: value})"
              />
            </div>
            <FailureAlert
              v-for="(notice, index) in row.result?.notices ?? []"
              :key="`notice-${index}`"
              :code="notice.code"
              :detail="notice.detail"
              notice
            />
            <v-alert
              v-for="(check, index) in row.checks"
              :key="index"
              class="check mt-1"
              density="compact"
              :type="alertType(check.level)"
              variant="tonal"
            >
              <strong>{{ PREFIX[check.level] }}</strong>{{ check.text }}
            </v-alert>
            <div v-if="!readonly && createdSomething(row) && !done" class="field-note mt-2">
              {{ row.result?.interrupted
                ? 'The last run stopped while working on this document, so it may have created a record in CollectionSpace that the BMU couldn\'t record. It can\'t be deleted from the job; check Exclude to have the BMU ignore it, or submit the job to finish it.'
                : 'This document already created records in CollectionSpace, so it can\'t be deleted from the job; check Exclude to have the BMU ignore it.' }}
            </div>
          </div>
        </v-lazy>
      </td>
    </tr>
  </tbody>
</template>

<script setup lang="ts">
import type {PropType} from 'vue'
import {computed, ref, watch} from 'vue'
import {mdiChevronRight, mdiEarth, mdiEyeOffOutline, mdiLock, mdiTrashCanOutline} from '@mdi/js'
import type {Presettable} from '@/lib/presets'
import type {Handling, Option, Perms, Row, TenantInfo} from '@/types'
import AuthorityInput from '@/components/util/AuthorityInput.vue'
import DateInput from '@/components/util/DateInput.vue'
import DocumentThumbnail from '@/components/util/DocumentThumbnail.vue'
import FailureAlert from '@/components/util/FailureAlert.vue'
import PresetChip from '@/components/util/PresetChip.vue'
import RepeatingSelect from '@/components/util/RepeatingSelect.vue'
import {formatBytes} from '@/lib/files'
import {filenameProblems, idLabel, objectLabel} from '@/lib/filenames'
import {portalOf} from '@/lib/portal'
import {PRESETTABLE, isPreset} from '@/lib/presets'
import {RELINK_OBJECT, STEP_MARK, canReplaceFile, createdSomething, fixFields, mediaCreated, objectStepRan, stepList, stepNote} from '@/lib/results'
import type {Tone} from '@/lib/status'
import {alertType, chipColor, handlingBlocked, rowStatus, worstLevel} from '@/lib/status'
import {editorColumns} from '@/lib/table'
import {putFocusNextTick} from '@/lib/utils'

/**
 * One document of the job in Create / edit job: its row in the table, the confirmation for deleting it, and, when
 * expanded, its fields. It is a tbody of its own, so the rows stay together. It changes nothing itself: every edit
 * goes to the editor, with the row, as an event.
 */
const props = defineProps({
  checking: {
    required: false,
    type: Boolean
  },
  // Its deletion was sent and the answer hasn't come back yet.
  deleting: {
    required: false,
    type: Boolean
  },
  expanded: {
    required: true,
    type: Boolean
  },
  groupOn: {
    required: false,
    type: Boolean
  },
  jobId: {
    default: undefined,
    required: false,
    type: String as PropType<string | null>
  },
  languages: {
    default: () => [],
    required: false,
    type: Array as PropType<Option[]>
  },
  // The job's only document: deleting it deletes the job.
  last: {
    required: false,
    type: Boolean
  },
  // The filenames of the job's other documents, to catch a duplicate when this one is renamed. A function, so that
  // the row asks only then and isn't redrawn whenever another document changes.
  otherNames: {
    default: () => [],
    required: false,
    type: Function as PropType<(n: number) => string[]>
  },
  perms: {
    required: true,
    type: Object as PropType<Perms>
  },
  preview: {
    default: undefined,
    required: false,
    type: String
  },
  readonly: {
    required: true,
    type: Boolean
  },
  row: {
    required: true,
    type: Object as PropType<Row>
  },
  // The job is running: Status shows each document's run state.
  runView: {
    required: false,
    type: Boolean
  },
  selected: {
    required: false,
    type: Boolean
  },
  tenant: {
    required: true,
    type: Object as PropType<TenantInfo>
  },
  // This page is sending the document's file right now.
  uploadingHere: {
    required: false,
    type: Boolean
  }
})
const emit = defineEmits<{
  edit: [row: Row, changes: Partial<Row>],
  remove: [row: Row],
  replace: [row: Row, file: File],
  retry: [row: Row],
  select: [n: number, on: boolean],
  toggle: [n: number]
}>()

const UPLOADING = ['pending', 'uploading', 'verifying']
// Design: a failed upload shows "Upload failed" with Retry and Remove. An upload this page isn't sending (the page
// that added the file was closed, or it's another person's browser) won't finish on its own.
/** Design (Deleting a row): a document whose file is still on its way; deleting it stops the upload. */
const stillUploading = computed(() => UPLOADING.includes(props.row.upload.s) && !mediaCreated(props.row))
const stalled = computed(() => !props.uploadingHere && !mediaCreated(props.row) && UPLOADING.includes(props.row.upload.s))
const canRetry = computed(() => !props.readonly && props.row.include && !mediaCreated(props.row) && (props.row.upload.s === 'failed' || stalled.value))
const portal = computed(() => portalOf(props.row, props.tenant))
const isConfirmingRemove = ref(false)
const confirmRemove = () => {
  isConfirmingRemove.value = false
  emit('remove', props.row)
}

// Delete (design: Deleting a row): the trash button at the end of the row, for any document that hasn't created
// anything in CollectionSpace, excluded or not. Only while the job can be edited; the column isn't there otherwise.
const cols = computed(() => editorColumns(props.groupOn, !props.readonly))
const deletable = computed(() => !createdSomething(props.row))
const DELETE_TITLE = 'Delete document'
const deleteTitle = computed(() => deletable.value ? DELETE_TITLE : props.row.result?.interrupted
  ? 'The last run stopped while working on this document, so it may have created a record in CollectionSpace. It can\'t be deleted; use Exclude instead.'
  : 'This document already created records in CollectionSpace, so it can\'t be deleted; use Exclude instead.')
const isConfirmingDelete = ref(false)
const askDelete = () => {
  isConfirmingDelete.value = true
  putFocusNextTick(`document-${props.row.n}-delete-cancel-btn`, {scroll: false})
}
const cancelDelete = () => {
  isConfirmingDelete.value = false
  putFocusNextTick(`document-${props.row.n}-delete-btn`, {scroll: false})
}
const doDelete = () => {
  isConfirmingDelete.value = false
  emit('remove', props.row)
}

// The job's group: only documents linked to an object can join; once its object is in the group, it stays.
const handling = computed(() => props.tenant.handling.find(h => h.id === props.row.handling))
const inGroup = computed(() => props.row.group ?? true)
const groupDone = computed(() => props.row.result?.steps?.addToGroup?.s === 'done')
const groupWhy = computed(() => handling.value?.object === 'none' ? 'Not linked to an object, so it can\'t join the group'
  : groupDone.value ? (props.row.result?.steps?.addToGroup?.sameAs ? `Its object was added by document ${props.row.result.steps.addToGroup.sameAs}` : 'Its object is in the group')
    : !props.perms.groups ? 'You don\'t have permission to create groups' : undefined)

// After a run (design: Fixing a job after a run): a document whose Media record exists changes only what the
// rerun still needs; a Failed one whose object step ran keeps its handling and object number.
const created = computed(() => mediaCreated(props.row))
const done = computed(() => props.row.result?.state === 'Done')
const ro = computed(() => props.readonly || created.value || !props.row.include)
const objFixed = computed(() => !created.value && objectStepRan(props.row))
const allowed = computed(() => fixFields(props.row))
const canEditObj = computed(() => !props.readonly && props.row.include && (created.value ? allowed.value.obj : !objFixed.value))
// Design (Fixing a job after a run): after object_exists, the handling may change to one that links to the existing
// object; nothing else about the Media record can change.
const relink = computed(() => !props.readonly && props.row.include && created.value && allowed.value.handling)
const handlingLocked = computed(() => relink.value ? false : ro.value || objFixed.value)
const handlingOptionOff = (h: Handling): string => {
  if (h.id === props.row.handling) {
    return ''
  }
  if (relink.value && !RELINK_OBJECT.includes(h.object)) {
    return 'Its Media record already exists: choose a handling that links to the existing object'
  }
  return handlingBlocked(h, props.perms)
}
const replaceable = computed(() => !props.readonly && canReplaceFile(props.row))
const replaceInput = ref<HTMLInputElement | null>(null)
const pickReplacement = (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) {
    emit('replace', props.row, file)
  }
  input.value = ''
}

const RUN_TONE: Record<string, Tone> = {'In progress': 'info', Done: 'success', Partial: 'warning', Failed: 'error', 'Not started': 'neutral'}
const status = computed((): {text: string, tone: Tone, spin?: boolean} => {
  if (props.runView) {
    if (!props.row.include) {
      return {text: 'Excluded — ignored', tone: 'info'}
    }
    const state = props.row.result?.state ?? 'Not started'
    return {text: state, tone: RUN_TONE[state] ?? 'neutral', spin: state === 'In progress'}
  }
  if (props.deleting) {
    return {text: 'Deleting…', tone: 'neutral', spin: true}
  }
  return stalled.value && props.row.include ? {text: 'Upload not finished', tone: 'error'} : rowStatus(props.row, props.tenant, props.checking)
})
const hasWarnings = computed(() => props.row.include && worstLevel(props.row) === 'warn')
const PREFIX: Record<string, string> = {block: 'Must fix: ', warn: 'Warning: ', info: ''}

// Filename: checked as you type; applied (re-parsed and re-checked on the server) only once it passes.
const original = computed(() => props.row.fileOriginal || props.row.file)
const renamed = computed(() => props.row.file !== original.value)
const nameDraft = ref(props.row.file)
watch(() => props.row.file, file => {
  nameDraft.value = file
})
const nameErrors = computed(() => nameDraft.value === props.row.file ? []
  : filenameProblems(props.tenant, nameDraft.value.trim(), original.value, props.otherNames(props.row.n)))
const applyName = () => {
  const value = nameDraft.value.trim()
  if (value !== props.row.file && !nameErrors.value.length) {
    emit('edit', props.row, {file: value})
  }
}
const objLabel = computed(() => objectLabel(props.row))
const idnLabel = computed(() => idLabel(props.row, props.tenant))
/** Fields that still hold their handling's preset or the tenant's default language (design: PRESET marks). */
const preset = computed(() => Object.fromEntries(PRESETTABLE.map(f => [f, isPreset(props.row, props.tenant, f)])) as Record<Presettable, boolean>)

const text = (field: keyof Row, event: Event) => {
  const value = (event.target as HTMLInputElement).value
  if (value !== props.row[field]) {
    emit('edit', props.row, {[field]: value} as Partial<Row>)
  }
}
</script>

<style scoped>
.document-row.row-excluded > td:not(.keep) {
  opacity: 0.5;
}
.document-row.row-deleting > td {
  opacity: 0.5;
}
.thumb-col {
  width: 64px;
}
.detail > td {
  background: rgb(var(--v-theme-surface-light));
}
.detail-grid {
  display: grid;
  gap: 10px 14px;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  padding: 6px 0;
}
.detail-grid > .wide {
  grid-column: 1 / -1;
}
.confirm-text {
  min-width: 200px;
}
.steps > div {
  white-space: nowrap;
}
.del-col {
  width: 40px;
}
</style>
