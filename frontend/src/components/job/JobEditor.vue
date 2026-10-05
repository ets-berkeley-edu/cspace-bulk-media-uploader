<template>
  <div id="job-editor">
    <v-alert
      v-if="lockedBy"
      id="editor-locked"
      class="mb-3"
      density="compact"
      type="info"
      variant="tonal"
    >
      <strong>Read-only preview.</strong> {{ lockedBy.who }} is editing this draft (since {{ formatTime(lockedBy.since) }}).
      <v-btn
        v-if="!isConfirmingTakeOver"
        id="take-over-btn"
        class="ml-2"
        size="small"
        variant="outlined"
        @click="isConfirmingTakeOver = true"
      >
        Take over…
      </v-btn>
      <div v-else id="take-over-confirm" class="mt-2">
        If you take over, {{ lockedBy.who }}'s editing ends and their page becomes read-only; everything they changed so far is already saved.
        <div class="mt-2">
          <v-btn
            id="take-over-confirm-btn"
            class="mr-2"
            color="primary"
            size="small"
            @click="() => openForEditing(lockedBy?.since)"
          >
            Take over and edit
          </v-btn>
          <v-btn
            id="take-over-cancel-btn"
            size="small"
            variant="outlined"
            @click="isConfirmingTakeOver = false"
          >
            Cancel
          </v-btn>
        </div>
      </div>
    </v-alert>
    <v-alert
      v-else-if="job && job.status === 'Draft' && job.editingByYou"
      id="editor-editing"
      class="mb-3"
      density="compact"
      type="info"
      variant="tonal"
    >
      Editing draft <strong>{{ job.name || 'Untitled job' }}</strong>. Others in {{ me.tenant.name }} see it under Drafts as being edited by you.
      Changes are saved as you make them. {{ isStaffUser ? 'Submit job moves it to the job queue.' : 'Submit for review sends it to staff, who review and submit it.' }}
      <button
        id="close-draft-btn"
        class="link-btn"
        type="button"
        @click="() => emit('close')"
      >
        Close this draft and start a new job
      </button>
    </v-alert>
    <v-alert
      v-if="job?.fixFrom && job.status === 'Draft'"
      id="editor-fixing"
      class="mb-3"
      density="compact"
      type="warning"
      variant="tonal"
    >
      <strong>Fixing after run {{ job.fixFrom.run }}</strong> (it {{ job.fixFrom.status === 'Failed' ? 'failed' : 'needed attention' }}<template v-if="job.fixFrom.code">: {{ failureOf(job.fixFrom.code).title }}</template>).
      Documents already created in CollectionSpace are read-only; one whose Media record exists takes only what the rerun still needs.
      Submitting it queues run {{ job.fixFrom.run + 1 }}, which skips everything already done. If the job isn't submitted within
      {{ job.protectedCount ? 7 : 30 }} days of the last change{{ job.protectedCount ? ' (it has protected files)' : '' }}, these edits are
      discarded and it returns to Finished jobs as it was.
    </v-alert>
    <v-alert
      v-if="job && job.status !== 'Draft'"
      id="editor-not-draft"
      class="mb-3"
      density="compact"
      type="info"
      variant="tonal"
    >
      This job is {{ OUTCOME[job.status]?.text ?? job.status }}; it can't be changed here.
      <template v-if="job.status === 'Running' && job.progress">
        {{ job.progress.done }} done · {{ job.progress.failed }} failed · {{ job.progress.total - job.progress.done - job.progress.failed }} to go.
        The Status column shows each document's run state.
      </template>
      <template v-else-if="job.status === 'Queued'">The checks below were run again just now.</template>
      <template v-if="job.status === 'NeedsAttention' || job.status === 'Failed'">Use Fix and reschedule under Finished jobs.</template>
    </v-alert>
    <CurrentDocument v-if="job && job.status === 'Running'" class="current-document mb-3" :job="job" />
    <v-alert
      v-if="job?.status === 'Queued' && counts.block"
      id="editor-changed-since"
      class="mb-3"
      density="compact"
      role="alert"
      type="error"
      variant="tonal"
    >
      Something changed in CollectionSpace since this job was submitted: {{ counts.block }} document{{ counts.block === 1 ? ' now needs' : 's now need' }}
      fixing. Edit the job to fix {{ counts.block === 1 ? 'it' : 'them' }} before it runs; otherwise {{ counts.block === 1 ? 'it' : 'they' }} will most likely fail.
    </v-alert>
    <!-- Design (Roles, Three kinds of result): one line for the job; the documents carry the status -->
    <v-alert
      v-if="job?.status === 'Draft' && counts.creator"
      id="creator-note"
      class="mb-3"
      color="creator"
      density="compact"
      variant="tonal"
    >
      <template v-if="isStaff(me)">
        {{ counts.creator === 1 ? '1 document needs' : `${counts.creator} documents need` }} a new Object, which your account can't create,
        so you can't submit this job. Leave the draft for a colleague who can create Objects, change
        {{ counts.creator === 1 ? 'its' : 'their' }} handling, have the Object{{ counts.creator === 1 ? '' : 's' }} created in
        CollectionSpace, or delete {{ counts.creator === 1 ? 'it' : 'them' }} from this job and add {{ counts.creator === 1 ? 'it' : 'them' }}
        to a new draft. (Exclude makes the BMU ignore a document for good once the job completes.)
      </template>
      <template v-else>
        {{ counts.creator === 1 ? '1 document needs' : `${counts.creator} documents need` }} a new Object. The staff member who submits
        this job must be able to create Objects.
      </template>
      <v-btn
        id="show-creator-btn"
        class="ml-2"
        size="small"
        variant="text"
        @click="showFilter('creator')"
      >
        Show {{ counts.creator === 1 ? 'it' : 'them' }}
      </v-btn>
    </v-alert>
    <v-alert
      v-if="job?.note"
      id="editor-note"
      class="mb-3"
      density="compact"
      type="warning"
      variant="tonal"
    >
      {{ job.note }}
    </v-alert>

    <label class="field-label" for="job-name">Job name</label>
    <v-text-field
      id="job-name"
      v-model="name"
      :disabled="!editable"
      hide-details
      placeholder="e.g. 2026 spring accession batch"
      @change="rename"
    />
    <!-- Design (Roles, Submit for review): an intern sent this draft to staff -->
    <v-alert
      v-if="job?.status === 'Draft' && job.review"
      id="review-note"
      class="mt-2"
      density="compact"
      type="info"
      variant="tonal"
    >
      {{ job.review.by }} sent this draft for review on {{ formatTime(job.review.at) }}.
      <template v-if="isStaffUser">Submit it when it is ready. To send it back, tick “Open to interns”.</template>
      <template v-else>A staff member reviews and submits it.</template>
    </v-alert>
    <!-- Whether interns may edit this draft (design: Roles): staff set it. An intern has nothing here: Submit for
         review is the button at the bottom of the job -->
    <div v-if="job?.status === 'Draft' && mode !== 'preview' && isStaffUser" id="intern-access" class="mt-2 text-body-2">
      <label class="align-center d-inline-flex" for="intern-open">
        <input
          id="intern-open"
          :checked="!!job.internOpen"
          class="checkbox mr-2"
          :disabled="!editable || isBusy"
          type="checkbox"
          @change="event => setInternOpen((event.target as HTMLInputElement).checked)"
        >
        Open to interns
        <span id="intern-open-hint" class="ml-2 text-medium-emphasis">{{ internOpenHint }}</span>
      </label>
    </div>

    <v-sheet
      id="group-box"
      border
      class="my-3 pa-3"
      color="surface-light"
      rounded
    >
      <label class="align-center d-flex font-weight-bold text-body-2" for="group-on">
        <input
          id="group-on"
          aria-label="Create a group of this job's objects"
          :checked="!!job?.groupOn"
          class="checkbox mr-2"
          :disabled="!editable || groupMade"
          :title="groupMade ? 'The group already exists in CollectionSpace' : undefined"
          type="checkbox"
          @change="event => setGroup({groupOn: (event.target as HTMLInputElement).checked})"
        >
        Create a group of this job's objects
      </label>
      <div class="align-center d-flex flex-wrap group-title mt-2">
        <label class="mr-2 text-body-2" for="group-title">Group title</label>
        <v-text-field
          id="group-title"
          v-model="groupTitle"
          aria-label="Group title"
          class="flex-grow-1 mr-2"
          :disabled="!editable || !job?.groupOn || groupMade"
          hide-details
          min-width="200"
          :placeholder="job?.groupOn ? 'Required' : 'Turn on “Create a group” first'"
          @change="() => setGroup({groupTitle})"
        />
        <template v-if="editable && job?.groupOn && !groupMade">
          <v-btn
            id="group-use-name-btn"
            class="mr-2"
            :disabled="!name.trim()"
            size="small"
            :title="name.trim() ? 'Fill the title with the job name, as typed' : 'Enter a job name first'"
            variant="outlined"
            @click="() => fillGroupTitle(name)"
          >
            Use the job name
          </v-btn>
          <v-btn
            id="group-use-timestamp-btn"
            size="small"
            title="Fill the title with bmu- and the date and time now (Pacific time)"
            variant="outlined"
            @click="() => fillGroupTitle(groupTimestampTitle())"
          >
            Use a timestamp
          </v-btn>
        </template>
      </div>
      <div class="field-note">
        When on, the job creates one new group in CollectionSpace, and every document linked to an object joins it once its Media record is
        linked; untick a document's Group box to leave it out. Documents that aren't linked to an object can't join. The group needs a title:
        type one, or use the job name or a timestamp. Renaming the job doesn't change it.
        <template v-if="groupMade">
          The group was created in run {{ job?.groupStep?.run }} (<code>{{ job?.groupStep?.csid }}</code>), so it can't be turned off or renamed here.
        </template>
      </div>
      <!-- Design (Roles, Three kinds of result): a problem with the user's account, not with the job: one message
           here, nothing on the documents, and only Submit is stopped -->
      <v-alert
        v-if="groupProblem"
        id="group-account-problem"
        class="mt-2"
        density="compact"
        type="warning"
        variant="tonal"
      >
        {{ groupProblem }}
      </v-alert>
    </v-sheet>

    <div
      v-if="editable"
      id="dropzone"
      class="dropzone my-3"
      :class="{drag: isDragging}"
      role="button"
      tabindex="0"
      @click="() => fileInput?.click()"
      @dragenter.prevent="isDragging = true"
      @dragleave.prevent="isDragging = false"
      @dragover.prevent="isDragging = true"
      @drop.prevent="onDrop"
      @keydown.enter.prevent="() => fileInput?.click()"
    >
      <v-icon :icon="mdiUpload" size="small" /> Drop documents here or <span class="text-decoration-underline">browse</span>
      <div class="text-caption">{{ me.tenant.filenameHint }}</div>
      <div v-if="me.tenant.fileTypesHint" class="text-caption">Accepts {{ me.tenant.fileTypesHint }}</div>
      <input
        id="file-input"
        ref="fileInput"
        :accept="accept"
        hidden
        multiple
        type="file"
        @change="onFilesPicked"
      >
    </div>

    <v-expansion-panels v-if="me.tenant.sensitivity?.summary" id="sensitivity-explain" class="my-3">
      <v-expansion-panel bg-color="surface-light" elevation="0">
        <v-expansion-panel-title id="sensitivity-explain-title" class="py-2 text-body-2">
          <span><strong>Sensitivity and publishing at {{ me.tenant.name }}:</strong> {{ me.tenant.sensitivity.summary }}</span>
        </v-expansion-panel-title>
        <v-expansion-panel-text class="text-body-2">
          <ul class="ml-5">
            <li v-for="(line, index) in me.tenant.sensitivity.explain" :key="index">{{ line }}</li>
          </ul>
          <div class="field-note">
            Three different things: the museum's sensitivity of an <em>object</em>, the publish setting of each <em>image</em>, and the BMU's
            <em>protected file</em> handling while the file is in the BMU. The Public portal column combines the first two. None of them stops
            CollectionSpace users who can read the record from seeing the image. Protected files are set automatically from CollectionSpace;
            there is no manual setting.
          </div>
        </v-expansion-panel-text>
      </v-expansion-panel>
    </v-expansion-panels>
    <input
      id="retry-file-input"
      ref="retryInput"
      aria-hidden="true"
      hidden
      type="file"
      @change="retryPicked"
    >
    <v-alert
      v-if="message"
      id="editor-message"
      class="my-2"
      density="compact"
      role="status"
      :type="message.type"
      variant="tonal"
    >
      {{ message.text }}
    </v-alert>
    <div v-if="counts.uploading || counts.uploadFailed" id="upload-counts" class="my-2 text-caption text-medium-emphasis">
      {{ counts.uploaded }} of {{ counts.work }} uploaded<template v-if="counts.uploading"> · {{ counts.uploading }} uploading</template><template v-if="counts.uploadFailed"> · {{ counts.uploadFailed }} failed</template>
    </div>

    <div class="editor-split">
      <BulkPanel
        ref="bulkPanel"
        :busy="isBusy"
        :deleting="isBusy && deleting.size > 0"
        :group-on="!!job?.groupOn"
        :languages="languages"
        :perms="perms"
        :readonly="!editable"
        :rows="rows"
        :selected="selected"
        :tenant="me.tenant"
        @apply="applyBulk"
        @delete="removeMany"
        @include="includeBulk"
      />
      <div class="grid-main">
        <Pagination
          v-if="rows.length"
          class="mb-2"
          :filters="docFilters"
          noun="documents"
          :of="view.of"
          :pages="view.pages"
          :start="view.start"
          :state="table"
          :total="view.total"
        />
        <v-alert
          v-if="selected.size"
          id="selection-banner"
          class="mb-2 sel-banner"
          density="compact"
          :icon="false"
          type="info"
          variant="tonal"
        >
          <strong>{{ selected.size.toLocaleString() }}</strong> selected<template v-if="selected.size > view.shown.length"> across pages</template>
          <template v-if="moreMatching">
            ·
            <button
              id="select-matching-btn"
              class="link-btn"
              type="button"
              @click="selectMatching"
            >
              Select all {{ view.total.toLocaleString() }}{{ view.total !== view.of ? ' matching' : '' }} documents
            </button>
          </template>
          ·
          <button
            id="clear-selection-btn"
            class="link-btn"
            type="button"
            @click="() => selected.clear()"
          >
            Clear selection
          </button>
        </v-alert>
        <v-table id="documents-table" class="border documents-table rounded" density="compact">
          <thead>
            <tr>
              <th class="thumb-col" scope="col"><span class="sr-only">Preview</span></th>
              <th class="px-1" scope="col">
                <input
                  id="select-page-checkbox"
                  aria-label="Select all documents on this page"
                  :checked="pageSelected"
                  class="checkbox"
                  :disabled="!view.shown.length"
                  type="checkbox"
                  @change="event => selectPage((event.target as HTMLInputElement).checked)"
                >
              </th>
              <th class="px-0" scope="col">
                <v-btn
                  id="expand-page-btn"
                  aria-label="Expand or collapse all rows on this page"
                  class="chevron"
                  :class="{open: pageExpanded}"
                  density="comfortable"
                  :disabled="!view.shown.length"
                  :icon="mdiChevronRight"
                  size="small"
                  title="Expand or collapse all rows on this page"
                  variant="text"
                  @click="expandPage"
                />
              </th>
              <SortableColumnHeader label="Document" sort-key="file" :state="table" />
              <SortableColumnHeader
                label="Handling"
                sort-key="handling"
                :state="table"
                style="width: 220px"
              />
              <SortableColumnHeader
                :label="me.tenant.publish.header"
                sort-key="publish"
                :state="table"
                style="width: 110px"
              />
              <SortableColumnHeader
                label="Public portal"
                sort-key="portal"
                :state="table"
                style="width: 180px"
                title="Whether this image will appear on the museum's public portal, combining the object's sensitivity and the image's own setting"
              />
              <SortableColumnHeader
                v-if="job?.groupOn"
                label="Group"
                sort-key="group"
                :state="table"
                style="width: 80px"
              />
              <SortableColumnHeader
                label="Status"
                sort-key="status"
                :state="table"
                style="width: 170px"
              />
              <SortableColumnHeader
                label="Exclude"
                sort-key="include"
                :state="table"
                style="width: 90px"
                title="To exclude a document from a job, check the box."
              />
              <th v-if="!rowsReadonly" class="del-col" scope="col"><span class="sr-only">Delete</span></th>
            </tr>
          </thead>
          <tbody v-if="!rows.length">
            <tr>
              <td id="no-documents" class="py-5 text-center text-medium-emphasis" :colspan="columns">
                No documents yet. Drop files in the box above, or browse, to add them to this job.
              </td>
            </tr>
          </tbody>
          <tbody v-else-if="!view.shown.length">
            <tr>
              <td id="no-matching-documents" class="py-5 text-center text-medium-emphasis" :colspan="columns">No documents match this filter.</td>
            </tr>
          </tbody>
          <DocumentRow
            v-for="row in view.shown"
            :key="row.n"
            :checking="checking.has(row.n)"
            :deleting="deleting.has(row.n)"
            :expanded="expanded.has(row.n)"
            :group-on="!!job?.groupOn"
            :job-id="job?.id"
            :languages="languages"
            :last="rows.length === 1"
            :other-names="otherNames"
            :perms="perms"
            :preview="previews.get(row.n)"
            :readonly="rowsReadonly"
            :row="row"
            :run-view="job?.status === 'Running'"
            :selected="selected.has(row.n)"
            :tenant="me.tenant"
            :uploading-here="uploadingHere.has(row.n)"
            @edit="edit"
            @remove="remove"
            @replace="replaceFile"
            @retry="retry"
            @select="select"
            @toggle="toggle"
          />
        </v-table>
        <Pagination
          bottom
          class="mt-2"
          noun="documents"
          :of="view.of"
          :pages="view.pages"
          :start="view.start"
          :state="table"
          :total="view.total"
        />
      </div>
    </div>

    <v-sheet
      id="schedule-bar"
      class="align-center d-flex flex-wrap mt-4 pa-3 schedule-bar"
      color="surface-light"
      rounded
    >
      <span id="document-counts" class="text-body-2">
        <strong>{{ counts.total }} document{{ counts.total === 1 ? '' : 's' }}<template v-if="counts.disabled"> ({{ counts.disabled }} excluded)</template></strong>
        · {{ counts.block ? `${counts.block} ${counts.block === 1 ? 'needs' : 'need'} fixing` : 'nothing to fix' }}<template v-if="counts.creator"> · {{ creatorText(counts.creator) }}</template><template v-if="counts.warn"> · {{ counts.warn }} {{ counts.warn === 1 ? 'has' : 'have' }} warnings</template>
      </span>
      <v-spacer />
      <v-btn
        v-if="counts.block || counts.warn"
        id="show-problems-btn"
        variant="outlined"
        @click="showProblems"
      >
        Show documents with problems
      </v-btn>
      <!-- Nothing to save or submit in a preview (design: Drafts): that's for the person editing the draft -->
      <span v-if="job?.status === 'Draft' && mode !== 'preview'" :title="saveTitle">
        <v-btn
          id="save-draft-btn"
          :disabled="!editable || isBusy"
          :title="saveTitle"
          variant="outlined"
          @click="saveDraft"
        >
          Save draft
        </v-btn>
      </span>
      <!-- Design (Roles, Submit for review): an intern can't submit a job, so the button in its place sends the
           draft to staff for review. (Its ids date from "Hand over to staff", which this replaced.) -->
      <span v-if="!isStaffUser && !readonly && mode !== 'preview'" :title="reviewTitle">
        <v-btn
          id="hand-over-btn"
          color="primary"
          :disabled="!job || !editable || isBusy || isHandingOver || !!noReview"
          :title="reviewTitle"
          @click="isHandingOver = true"
        >
          Submit for review…
        </v-btn>
      </span>
      <!-- A preview of a queued, running or finished job has nothing to submit: that's done from its own tab -->
      <span v-if="isStaffUser && !readonly && mode !== 'preview'" :title="submitTitle">
        <v-btn
          id="submit-job-btn"
          color="primary"
          :disabled="!job || isBusy || !!scheduleBlocked || (job.status === 'Draft' && !editable)"
          :title="submitTitle"
          @click="schedule"
        >
          Submit job
        </v-btn>
      </span>
      <v-alert
        v-if="isHandingOver && !isStaffUser"
        id="hand-over-confirm"
        class="mt-3 w-100"
        density="compact"
        role="alert"
        type="warning"
        variant="tonal"
      >
        <div>{{ REVIEW_CONFIRM }}</div>
        <div class="mt-2">
          <v-btn
            id="hand-over-confirm-btn"
            class="mr-2"
            color="warning"
            :disabled="isBusy"
            size="small"
            @click="handOver"
          >
            Submit for review
          </v-btn>
          <v-btn
            id="hand-over-cancel-btn"
            :disabled="isBusy"
            size="small"
            variant="outlined"
            @click="isHandingOver = false"
          >
            Cancel
          </v-btn>
        </div>
      </v-alert>
      <div v-if="savedNote" id="saved-note" class="saved-note text-caption text-medium-emphasis">{{ savedNote }}</div>
    </v-sheet>
  </div>
</template>

<script setup lang="ts">
import type {PropType} from 'vue'
import {computed, onBeforeUnmount, reactive, ref, watch} from 'vue'
import {mdiChevronRight, mdiUpload} from '@mdi/js'
import type {BulkChanges} from '@/lib/bulk'
import type {Job, Me, Option, Row, RowChange} from '@/types'
import BulkPanel from '@/components/job/BulkPanel.vue'
import CurrentDocument from '@/components/job/CurrentDocument.vue'
import DocumentRow from '@/components/job/DocumentRow.vue'
import Pagination from '@/components/util/Pagination.vue'
import SortableColumnHeader from '@/components/util/SortableColumnHeader.vue'
import {canPreview, fileTooLargeText, formIsOld, formatTime, makeThumbnail, mapLimit, skippedText, splitSize, splitSupported, tooLargeText, uploadToS3} from '@/lib/files'
import {readImageInfo} from '@/lib/imageinfo'
import {portalOf} from '@/lib/portal'
import {OUTCOME, failureOf, loadFailures} from '@/lib/results'
import {GROUP_PROBLEM, INTERN_SUBMIT_WHY, REVIEW_CONFIRM, STAFF_DRAFT_WHY, isStaff, permsFor} from '@/lib/roles'
import {groupTimestampTitle} from '@/lib/schedule'
import {creatorText, hasWork, jobCounts, worstLevel} from '@/lib/status'
import {editorColumns, tableState, tableView} from '@/lib/table'
import {alertScreenReader} from '@/lib/utils'
import {ApiError, api} from '@/api'

/**
 * Create / edit job: the job's name and group, the box that takes files, the panel that changes many documents at
 * once, and the table of documents. Every change is saved as it is made; this page holds the job and its documents
 * and sends each change to the API.
 */
const props = defineProps({
  jobId: {
    default: null,
    required: false,
    type: String as PropType<string | null>
  },
  me: {
    required: true,
    type: Object as PropType<Me>
  },
  mode: {
    default: 'edit',
    required: false,
    type: String as PropType<'edit' | 'preview'>
  },
  takeOverSince: {
    default: null,
    required: false,
    type: Number as PropType<number | null>
  }
})
const emit = defineEmits<{scheduled: [job: Job], opened: [id: string], close: [], missing: [], handedOver: [name: string]}>()

const job = ref<Job | null>(null)
const rows = ref<Row[]>([])
const name = ref('')
const expanded = reactive(new Set<number>())
const previews = reactive(new Map<number, string>())
type Message = {type: 'error' | 'warning' | 'info', text: string}
const message = ref<Message | null>(null)
const isBusy = ref(false)
const checking = reactive(new Set<number>()) // rows waiting for a CollectionSpace check
const deleting = reactive(new Set<number>()) // rows whose deletion was sent; they stay, marked, until the answer
const selected = reactive(new Set<number>())
// The languages vocabulary, for the repeating Language pickers (loaded once, from CollectionSpace).
const languages = ref<Option[]>([])
api.vocabulary('languages')
  .then((r) => { languages.value = r.terms.map((t) => ({value: t.refName, label: t.displayName})) })
  .catch((e) => { message.value = {type: 'warning', text: `Couldn't load the languages list: ${(e as Error).message}`} })
const bulkPanel = ref<InstanceType<typeof BulkPanel> | null>(null)
loadFailures()
// Paging, sorting and the Show filter (design: User interface, Large jobs).
const table = tableState()
/** The file picker offers only the file types the BMU accepts. */
const accept = computed(() => (props.me.tenant.fileTypes ?? []).map((t) => '.' + t).join(','))
const handlingLabel = (r: Row) => props.me.tenant.handling.find((h) => h.id === r.handling)?.label ?? r.handling
const LEVEL_RANK = {block: 0, creator: 0.5, warn: 1, ok: 2} as const
const statusRank = (r: Row) => (!r.include ? 3 : r.result?.state === 'Done' ? 4 : LEVEL_RANK[worstLevel(r)])
const docKeys = {
  file: (r: Row) => r.file,
  handling: handlingLabel,
  publish: (r: Row) => (r.restricted ? 1 : 0),
  portal: (r: Row) => portalOf(r, props.me.tenant).text,
  group: (r: Row) => (r.group ?? true ? 0 : 1),
  status: statusRank,
  include: (r: Row) => (r.include ? 0 : 1),
}
function docFilter(r: Row, f: string): boolean {
  const lv = worstLevel(r)
  switch (f) {
  // A document that needs an Object creator has no problem with it (design: Roles): it has its own filter
  case 'problems': return r.include && (lv === 'block' || lv === 'warn')
  case 'block': return r.include && lv === 'block'
  case 'creator': return r.include && lv === 'creator'
  case 'warn': return r.include && lv === 'warn'
  case 'protected': return !!r.protected
  case 'excluded': return !r.include
  case 'selected': return selected.has(r.n)
  default: return true
  }
}
const view = computed(() => tableView(rows.value, table, docKeys, docFilter))
const docFilters = computed<[string, string][]>(() => {
  const n = (f: string) => rows.value.filter((r) => docFilter(r, f)).length
  return [['all', `All documents (${rows.value.length})`], ['problems', `With problems (${n('problems')})`], ['block', `Need fixing (${n('block')})`],
          ['creator', `Need an Object creator (${n('creator')})`], ['warn', `With warnings (${n('warn')})`], ['protected', `Protected (${n('protected')})`], ['excluded', `Excluded (${n('excluded')})`],
          ['selected', `Selected (${selected.size})`]]
})
const pageSelected = computed(() => view.value.shown.length > 0 && view.value.shown.every((r) => selected.has(r.n)))
const pageExpanded = computed(() => view.value.shown.length > 0 && view.value.shown.every((r) => expanded.has(r.n)))
const moreMatching = computed(() => pageSelected.value && view.value.all.some((r) => !selected.has(r.n)))
const isDragging = ref(false)
// The files this page added, kept for Retry, and the uploads this page is sending right now.
const localFiles = new Map<number, File>()
const uploadingHere = reactive(new Set<number>())
/** The uploads this page is sending, so deleting a document can stop its upload at once (design: Deleting a row). */
const inFlight = new Map<number, AbortController>()
/** Stop the uploads of deleted documents; ones still waiting their turn are skipped because their rows are gone. */
function stopUploads(ns: number[] | 'all') {
  for (const [n, c] of inFlight) if (ns === 'all' || ns.includes(n)) c.abort()
}
const retryInput = ref<HTMLInputElement | null>(null)
let retryRow: Row | null = null
const fileInput = ref<HTMLInputElement | null>(null)

const readonly = computed(() => !!job.value && job.value.status !== 'Draft')
// Drafts have one editor at a time: this page can change the job only while it is the draft's editor.
const editable = computed(() => !job.value || (job.value.status === 'Draft' && !!job.value.editingByYou))
const lockedBy = computed(() => job.value?.status === 'Draft' && job.value.editingBy && !job.value.editingByYou
  ? {who: job.value.editingBy, since: job.value.editingSince} : null)
const isConfirmingTakeOver = ref(false)
// Documents can be deleted (the Delete column) only while this page can change the job.
const rowsReadonly = computed(() => readonly.value || !editable.value)
const columns = computed(() => editorColumns(!!job.value?.groupOn, !rowsReadonly.value))
const savedNote = ref('')
const counts = computed(() => jobCounts(rows.value))
// The job's group (design: Groups): on/off and its title; fixed once the Group exists in CollectionSpace.
const groupMade = computed(() => job.value?.groupStep?.s === 'done')
const groupTitle = ref('')
watch(() => job.value?.groupTitle, (t) => { groupTitle.value = t ?? '' }, {immediate: true})
/** "Use the job name" / "Use a timestamp" (user decision): fill the title once; it never follows the job name after. */
function fillGroupTitle(title: string) {
  groupTitle.value = title
  return setGroup({groupTitle: title})
}
async function setGroup(fields: { groupOn?: boolean; groupTitle?: string }) {
  try {
    const j = await ensureJob()
    const {rows: changed, ...rest} = await api.patchJob(j.id, fields)
    ;(changed ?? []).forEach(row => replace(row))
    job.value = rest
  } catch (e) {
    await failed(e)
  }
}

// ---- whether interns may edit this draft (design: Roles) ----
const isStaffUser = computed(() => isStaff(props.me))
const isHandingOver = ref(false)
const internOpenHint = computed(() => (job.value?.internOpen ? 'Interns can edit this draft.' : 'Only staff can edit this draft.'))
async function setInternOpen(open: boolean) {
  if (!job.value) return
  try {
    job.value = {...job.value, ...(await api.internAccess(job.value.id, open))}
  } catch (e) {
    await failed(e)
  }
}
async function handOver() {
  if (!job.value) return
  isBusy.value = true
  try {
    const name = job.value.name
    await rename()
    await api.sendForReview(job.value.id)
    isHandingOver.value = false
    emit('handedOver', name)
  } catch (e) {
    isHandingOver.value = false
    await failed(e)
    if (e instanceof ApiError && e.status === 409 && editable.value) {
      rows.value = (await api.job(job.value.id)).rows // the server checked the job again: show what it found
      showProblems()
    }
  } finally {
    isBusy.value = false
  }
}

// What the controls go by: the user's own permissions, or every permission for an intern (see permsFor)
const perms = computed(() => permsFor(props.me))

const scheduleBlocked = computed(() => {
  const c = counts.value
  if (!isStaff(props.me)) return INTERN_SUBMIT_WHY
  if (job.value?.groupOn && !job.value.groupTitle?.trim()) return 'Enter a group title, or turn off the job\'s group'
  if (c.block) return 'Fix or exclude the documents marked Needs fixing first'
  if (c.uploading) return 'Wait until every file is uploaded and verified'
  if (!c.work) return 'Nothing left to run: every document is done or excluded'
  if (checking.size) return 'Checking against CollectionSpace…'
  if (groupProblem.value) return 'Your account can\'t create groups, which this job\'s group needs'
  if (c.creator) {
    return `${c.creator === 1 ? 'A document needs' : `${c.creator} documents need`} a new Object, which your account can't create: `
      + 'leave the draft for a colleague who can create Objects'
  }
  return ''
})

/** Why an intern can't send this draft for review yet: only a document that needs fixing, or an unfinished upload. */
const noReview = computed(() => {
  const c = counts.value
  if (job.value && !job.value.internOpen) return STAFF_DRAFT_WHY
  if (job.value?.groupOn && !job.value.groupTitle?.trim()) return 'Enter a group title, or turn off the job\'s group'
  if (c.block) return 'Fix or exclude the documents marked Needs fixing first'
  if (c.uploading) return 'Wait until every file is uploaded and verified'
  if (!c.work) return 'Nothing to review: add a document first'
  if (checking.size) return 'Checking against CollectionSpace…'
  return ''
})
const reviewTitle = computed(() => noReview.value || 'Send this draft to staff for review: it becomes staff only, and a staff member submits it')

/**
 * Design (Roles, Three kinds of result): creating groups is the one permission, creating Objects aside, that staff
 * can lack after sign-in. It is the account's problem, not the job's: said once, beside the group, and it stops
 * only Submit, while the job's Group doesn't exist yet and a document to run would join it. Interns aren't told:
 * they act for whoever submits.
 */
const groupProblem = computed(() => {
  if (!isStaff(props.me) || !job.value?.groupOn || groupMade.value || props.me.perms.groups) return ''
  const joins = rows.value.some((r) => hasWork(r) && (r.group ?? true) && props.me.tenant.handling.find((h) => h.id === r.handling)?.object !== 'none')
  return joins ? GROUP_PROBLEM : ''
})

async function load(id: string | null) {
  previews.forEach((u) => URL.revokeObjectURL(u))
  previews.clear()
  expanded.clear()
  selected.clear()
  Object.assign(table, {page: 1, sort: null, dir: 1, filter: 'all'})
  message.value = null
  if (!id) {
    job.value = null
    rows.value = []
    name.value = ''
    return
  }
  const r = await api.job(id)
  job.value = r.job
  rows.value = r.rows
  name.value = r.job.name
  if (r.job.status === 'Draft' && !r.job.editingByYou && props.mode !== 'preview') await openForEditing(props.takeOverSince ?? undefined)
  // Design: checks reflect CollectionSpace as it is now (drafts, and previews of queued jobs). Rows whose lookups
  // are stale are checked again.
  if (r.job.status === 'Draft' || r.job.status === 'Queued') void runChecks(r.rows.map((x) => x.n), false)
  watchRun()
}

// A running job's preview lists each document's run state, refreshed while it runs (design: Run duration and the UI).
let runTimer: ReturnType<typeof setInterval> | undefined
function watchRun() {
  clearInterval(runTimer)
  if (job.value?.status !== 'Running') return
  runTimer = setInterval(async () => {
    if (!job.value) return
    const r = await api.job(job.value.id, true).catch(() => null)
    if (!r) return
    job.value = r.job
    rows.value = r.rows
    if (r.job.status !== 'Running') clearInterval(runTimer)
  }, 3000)
}
onBeforeUnmount(() => clearInterval(runTimer))

/** Become this draft's editor (or take over); if someone else is editing it, the page stays a preview. */
async function openForEditing(takeOverSince?: number) {
  if (!job.value) return
  try {
    job.value = await api.openJob(job.value.id, takeOverSince)
    isConfirmingTakeOver.value = false
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) await refreshJob()
    else message.value = {type: 'error', text: (e as Error).message}
  }
}

async function refreshJob() {
  if (job.value) job.value = (await api.job(job.value.id)).job
}

/** Show an error; if someone took the draft over, the page becomes a read-only preview (nothing is lost). */
async function failed(e: unknown) {
  message.value = {type: 'error', text: (e as Error).message}
  if (e instanceof ApiError && e.status === 409 && (e.detail as { code?: string } | null)?.code === 'not_editing') await refreshJob()
}

/** A job that has run becomes Completed as soon as every document is done or excluded (design: Job states). */
function completedNote() {
  if (job.value?.status === 'Completed') {
    message.value = {type: 'info', text: 'Every document is now done or excluded, so the job is Completed. It\'s under Finished jobs and is removed 30 days from now.'}
    return true
  }
  return false
}

async function saveDraft() {
  if (!job.value) return
  try {
    job.value = await api.saveDraft(job.value.id)
    if (completedNote()) return
    const exp = job.value.expiresAt ? new Date(job.value.expiresAt * 1000).toLocaleDateString(undefined, {dateStyle: 'medium'}) : ''
    savedNote.value = `Draft saved at ${formatTime(job.value.lastSavedAt)}` + (counts.value.block ? `; ${counts.value.block} document(s) still need fixing before it can be submitted` : '')
      + (exp ? `. Unless it's changed or saved again, it expires on ${exp}.` : '.')
  } catch (e) {
    await failed(e)
  }
}

/** Check rows against CollectionSpace in the background; the whole job's checks come back. */
async function runChecks(ns: number[], targeted = true) {
  if (!job.value || !ns.length) return
  ns.forEach((n) => checking.add(n))
  try {
    const r = await api.check(job.value.id, targeted ? ns : undefined)
    r.rows.forEach((row) => replace(row))
  } catch (e) {
    message.value = {type: 'error', text: (e as Error).message}
  } finally {
    ns.forEach((n) => checking.delete(n))
  }
}

function apply(change: RowChange) {
  replace(change.row)
  change.others.forEach((o) => replace(o))
}
// A job that isn't there (deleted, expired, or a mistyped address) is reported, so the page can start a new job.
function loadFailed(e: unknown) {
  if (e instanceof ApiError && e.status === 404) emit('missing')
  else message.value = {type: 'error', text: (e as Error).message}
}
watch(() => props.jobId, (id) => (id && id === job.value?.id ? undefined : load(id).catch(loadFailed)), {immediate: true})
onBeforeUnmount(() => previews.forEach((u) => URL.revokeObjectURL(u)))

// One job per editor, even if naming it and dropping files race each other.
let creating: Promise<Job> | null = null
async function ensureJob(): Promise<Job> {
  if (job.value) return job.value
  creating ??= api.createJob(name.value.trim()).then((j) => {
    job.value = j
    emit('opened', j.id)
    return j
  })
  return creating
}

async function rename() {
  if (!job.value) {
    if (name.value.trim()) await ensureJob()
    return
  }
  if (name.value.trim() !== job.value.name && editable.value) {
    try {
      job.value = await api.patchJob(job.value.id, {name: name.value.trim()})
    } catch (e) {
      await failed(e)
    }
  }
}

/** Take the server's copy of a row, keeping the browser's upload progress while a file is still on its way. */
function replace(row: Row) {
  const i = rows.value.findIndex((r) => r.n === row.n)
  if (i < 0) return
  if ((row.v ?? 0) < (rows.value[i].v ?? 0)) return // a stale copy, e.g. a slow check that started earlier
  const local = rows.value[i].upload
  rows.value[i] = {...row, upload: ['uploading', 'verifying'].includes(local.s) && row.upload.s === 'pending' ? local : row.upload}
}

/** Add files: create rows, upload each straight to S3 (3 at a time), then confirm with the API. */
async function addFiles(list: FileList | File[] | null) {
  const chosen = Array.from(list ?? [])
  if (!chosen.length || !editable.value) return
  message.value = null
  // Design (Supported file types): files of other types are skipped here and never uploaded.
  const {ok: supported, skipped} = splitSupported(chosen, props.me.tenant.fileTypes)
  // Design (Browser uploads): so are files over the size limit; the server refuses them too.
  const {ok: files, tooLarge} = splitSize(supported, props.me.maxFileBytes)
  const notes = [
    ...(skipped.length ? [skippedText(skipped.map((f) => f.name), props.me.tenant.fileTypesHint)] : []),
    ...(tooLarge.length ? [tooLargeText(tooLarge.map((f) => f.name), props.me.maxFileBytes!)] : []),
  ]
  if (notes.length) message.value = {type: 'warning', text: notes.join(' ')}
  if (!files.length) return
  try {
    const j = await ensureJob()
    // Design: the browser reads each image's EXIF date and orientation first and sends them with the documents,
    // so the date is pre-filled from the start (a few files at a time; only small parts of each file are read).
    const info = await mapLimit(files, 8, readImageInfo)
    const {rows: created} = await api.addFiles(j.id, files.map((f, i) => ({
      name: f.name, size: f.size, type: f.type, exifDate: info[i].date, orientation: info[i].orientation})))
    const signedAt = Date.now() // when these forms were received: a file still waiting long after gets a fresh one
    const queue = created.map((row, i) => ({row, file: files[i]}))
    for (const {row, file} of queue) {
      row.upload = {s: 'pending'}
      localFiles.set(row.n, file)
      uploadingHere.add(row.n)
      rows.value.push(row)
      if (canPreview(file)) previews.set(row.n, URL.createObjectURL(file))
    }
    // Design: each row is checked as soon as its file is chosen, in one batch for the new rows.
    const checks = runChecks(created.map((r) => r.n))
    const worker = async () => {
      for (let next = queue.shift(); next; next = queue.shift()) await uploadOne(j.id, next.row, next.file, signedAt)
    }
    await Promise.all([worker(), worker(), worker(), checks])
  } catch (e) {
    await failed(e)
  }
}

/** Replace the file of a document whose Media record exists; the rerun uploads it to that record. */
async function replaceFile(row: Row, file: File) {
  if (!job.value) return
  if (!splitSupported([file], props.me.tenant.fileTypes).ok.length) {
    message.value = {type: 'warning', text: skippedText([file.name], props.me.tenant.fileTypesHint)}
    return
  }
  if (tooLargeFor(file)) return
  try {
    const r = await api.replaceFile(job.value.id, row.n, {name: file.name, size: file.size, type: file.type})
    replace(r.row)
    const old = previews.get(row.n)
    if (old) URL.revokeObjectURL(old)
    if (canPreview(file)) previews.set(row.n, URL.createObjectURL(file))
    await uploadOne(job.value.id, {...r.row, uploadForm: r.uploadForm}, file)
  } catch (e) {
    await failed(e)
  }
}

/** A file over the size limit is not sent (design: Browser uploads): say so, and return true. */
function tooLargeFor(file: File): boolean {
  if (!splitSize([file], props.me.maxFileBytes).tooLarge.length) return false
  message.value = {type: 'warning', text: fileTooLargeText(file.name, props.me.maxFileBytes!)}
  return true
}

/** Send one document's file. signedAt: when its upload form was received (now, unless it waited its turn). */
async function uploadOne(jobId: string, row: Row, file: File, signedAt = Date.now()) {
  // A document deleted while its upload waited for its turn: nothing is sent
  if (job.value?.id !== jobId || !rows.value.some((r) => r.n === row.n)) return
  const stop = new AbortController()
  inFlight.set(row.n, stop)
  uploadingHere.add(row.n)
  try {
    await sendFile(jobId, row, file, signedAt, stop.signal)
  } finally {
    uploadingHere.delete(row.n)
    if (inFlight.get(row.n) === stop) inFlight.delete(row.n)
  }
}

/** Retry an upload that failed or never finished, with the file this page still holds, or one the user picks again. */
async function retry(row: Row, picked?: File) {
  if (!job.value) return
  const file = picked ?? localFiles.get(row.n)
  if (!file) {
    retryRow = row
    retryInput.value?.click()
    return
  }
  if (tooLargeFor(file)) return
  try {
    const r = await api.retryUpload(job.value.id, row.n, {name: file.name, size: file.size, type: file.type})
    localFiles.set(row.n, file)
    replace(r.row)
    if (!previews.has(row.n) && canPreview(file)) previews.set(row.n, URL.createObjectURL(file))
    await uploadOne(job.value.id, {...r.row, uploadForm: r.uploadForm}, file)
  } catch (e) {
    await failed(e)
  }
}
function retryPicked(e: Event) {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  input.value = ''
  if (f && retryRow) void retry(retryRow, f)
  retryRow = null
}

/** Upload a document's file to S3 and confirm it. A form that got old while the file waited its turn is replaced by a
 *  fresh one first (design: Browser uploads, "Sign": forms expire after about 15 minutes). */
async function sendFile(jobId: string, row: Row, file: File, signedAt: number, signal?: AbortSignal) {
  const live = () => rows.value.find((r) => r.n === row.n)
  const set = (u: Row['upload']) => { const r = live(); if (r) r.upload = u }
  set({s: 'uploading', pct: 0})
  try {
    let form = row.uploadForm!
    if (formIsOld(signedAt)) {
      form = (await api.uploadForm(jobId, row.n, file.size)).uploadForm
      if (signal?.aborted || !live()) return // deleted while the new form was on its way: nothing is sent
    }
    await uploadToS3(form, file, (pct) => set({s: 'uploading', pct}), signal)
    if (signal?.aborted) return // deleted just as the upload finished: the server removed the file with the row
    set({s: 'verifying'})
    const confirmed = await api.uploaded(jobId, row.n)
    set(confirmed.row.upload)
    apply(confirmed)
    // Design: the browser makes the thumbnail for JPEG and PNG and sends it with the file (none for a protected file).
    if (confirmed.row.upload.s === 'done' && !confirmed.row.protected) {
      const thumb = await makeThumbnail(file)
      if (thumb) await api.putThumbnail(jobId, row.n, thumb).catch(() => undefined)
    }
  } catch {
    if (signal?.aborted) return // stopped because the document was deleted: not a failure
    set({s: 'failed'})
    try {
      apply(await api.uploadFailed(jobId, row.n))
    } catch { /* the row already shows the failure */ }
  }
}

async function edit(row: Row, changes: Partial<Row>) {
  if (!job.value) return
  try {
    apply(await api.editRow(job.value.id, row.n, changes))
  } catch (e) {
    await failed(e)
  }
}

async function remove(row: Row) {
  if (!job.value || deleting.has(row.n)) return
  deleting.add(row.n)
  alertScreenReader(`Deleting ${row.file}`)
  try {
    const r = await api.deleteRow(job.value.id, row.n).catch(failed)
    if (!r) return
    await removed([row.n], r)
    alertScreenReader(`Deleted ${row.file}`)
  } finally {
    deleting.delete(row.n)
  }
}

/** Delete selected (the bulk-change panel): the server deletes those it may and skips the others. */
async function removeMany(targets: number[]) {
  if (!job.value || !targets.length) return
  isBusy.value = true
  message.value = null
  targets.forEach((n) => deleting.add(n))
  alertScreenReader(`Deleting ${targets.length} document${targets.length === 1 ? '' : 's'}`)
  try {
    const r = await api.deleteRows(job.value.id, targets)
    const k = r.deleted.length
    const created = r.skipped.filter((x) => x.code === 'created').length
    const other = r.skipped.length - created
    const text = `Deleted ${k} document${k === 1 ? '' : 's'}.`
      + (created ? ` ${created} couldn't be deleted because ${created === 1 ? 'it' : 'they'} already created records in CollectionSpace.` : '')
      + (other ? ` ${other} ${other === 1 ? 'wasn\'t' : 'weren\'t'} deleted because ${other === 1 ? 'it' : 'they'} changed meanwhile; reload and try again.` : '')
    const done = await removed(r.deleted, r) // the job was deleted, or completed: removed() said so
    const shown = message.value as Message | null
    if (!done) message.value = {type: created || other ? 'warning' : 'info', text}
    else if (r.jobStatus !== 'Deleted' && shown) message.value = {...shown, text: `${text} ${shown.text}`}
  } catch (e) {
    await failed(e)
  } finally {
    targets.forEach((n) => deleting.delete(n))
    isBusy.value = false
  }
}

/** Documents were deleted: drop them from the table and the selection. True if the job was deleted or completed
 * (the page shows that instead). */
async function removed(ns: number[], r: { others: Row[]; jobStatus?: string }): Promise<boolean> {
  stopUploads(r.jobStatus === 'Deleted' ? 'all' : ns)
  if (r.jobStatus === 'Deleted') {
    message.value = {type: 'info', text: 'That was the job\'s last document, so the job was deleted.'}
    job.value = null
    rows.value = []
    selected.clear()
    creating = null // files added next start a new job, not the deleted one
    return true
  }
  const gone = new Set(ns)
  rows.value = rows.value.filter((x) => !gone.has(x.n))
  ns.forEach((n) => {
    selected.delete(n)
    expanded.delete(n)
    const u = previews.get(n)
    if (u) URL.revokeObjectURL(u)
    previews.delete(n)
  })
  r.others.forEach((o) => replace(o))
  if (r.jobStatus && r.jobStatus !== 'Draft') {
    await refreshJob()
    return completedNote()
  }
  return false
}

function select(n: number, on: boolean) {
  if (on) selected.add(n)
  else selected.delete(n)
}
/** The header checkbox: the documents on this page (design: with a link to select every matching document). */
function selectPage(on: boolean) {
  view.value.shown.forEach((r) => (on ? selected.add(r.n) : selected.delete(r.n)))
}
function selectMatching() {
  view.value.all.forEach((r) => selected.add(r.n))
}
function expandPage() {
  const open = !pageExpanded.value
  view.value.shown.forEach((r) => (open ? expanded.add(r.n) : expanded.delete(r.n)))
}

/** The bulk-change panel: the server applies every change to every target, or refuses and changes nothing. */
async function bulk(targets: number[], changes: BulkChanges | Partial<Row>, resetPanel: boolean) {
  if (!job.value || !targets.length) return
  isBusy.value = true
  message.value = null
  try {
    const r = await api.bulk(job.value.id, targets, changes)
    r.rows.forEach((row) => replace(row))
    if (resetPanel) bulkPanel.value?.reset()
  } catch (e) {
    await failed(e)
  } finally {
    isBusy.value = false
  }
}

/** "Show documents with problems": filter to them and expand those on the page. */
function showFilter(filter: string) {
  table.filter = filter
  table.page = 1
  expanded.clear()
  view.value.shown.forEach((r) => expanded.add(r.n))
}
const showProblems = () => showFilter('problems')

async function schedule() {
  if (!job.value) return
  isBusy.value = true
  try {
    await rename()
    const j = await api.schedule(job.value.id)
    emit('scheduled', j)
  } catch (e) {
    await failed(e)
    if (e instanceof ApiError && e.status === 409 && editable.value) {
      // Scheduling checked the whole job again (with fresh permissions): show what it found.
      rows.value = (await api.job(job.value.id)).rows
      const detail = e.detail as { code?: string } | null
      if (detail?.code === 'creator') {
        showFilter('creator') // nothing is wrong with those documents: show them as what they are
      } else if (detail?.code !== 'account') {
        showProblems()
      }
    }
  } finally {
    isBusy.value = false
  }
}

/** The filenames of the job's other documents: a document asks for them only while it is being renamed. */
const otherNames = (n: number) => rows.value.filter((x) => x.n !== n).map((x) => x.file)

function onDrop(event: DragEvent) {
  isDragging.value = false
  void addFiles(event.dataTransfer?.files ?? null)
}
function onFilesPicked(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  void addFiles(files)
}
const applyBulk = (targets: number[], changes: BulkChanges) => bulk(targets, changes, true)
const includeBulk = (targets: number[], include: boolean) => bulk(targets, {include}, false)
const saveTitle = computed(() => `Every change is already saved; this confirms it and restarts the draft's ${job.value?.protectedCount ? '7-day expiry (it has protected files)' : '30-day expiry'}`)
const submitTitle = computed(() => scheduleBlocked.value || 'Check the whole job again, then add it to the job queue; it runs at the next run time')

function toggle(n: number) {
  if (expanded.has(n)) expanded.delete(n)
  else expanded.add(n)
}
</script>

<style scoped>
.current-document {
  max-width: 420px;
}
.dropzone {
  border: 1.5px dashed rgba(var(--v-theme-on-surface), 0.38);
  border-radius: 8px;
  cursor: pointer;
  opacity: 1;
  padding: 18px;
  text-align: center;
}
.dropzone.drag {
  background: rgba(var(--v-theme-primary), 0.08);
  border-color: rgb(var(--v-theme-primary));
  color: rgb(var(--v-theme-primary));
}
.dropzone:focus-visible {
  outline: 2px solid rgb(var(--v-theme-primary));
  outline-offset: 1px;
}
.editor-split {
  align-items: start;
  display: grid;
  gap: 16px;
  grid-template-columns: 264px minmax(0, 1fr);
}
.editor-split:has(.bulk-side.collapsed) {
  grid-template-columns: 44px minmax(0, 1fr);
}
.grid-main {
  min-width: 0;
}
.schedule-bar {
  gap: 10px;
}
.saved-note {
  flex-basis: 100%;
}
.thumb-col {
  width: 64px;
}
.del-col {
  width: 40px;
}
@media (max-width: 900px) {
  .editor-split,
  .editor-split:has(.bulk-side.collapsed) {
    grid-template-columns: 1fr;
  }
}
</style>
