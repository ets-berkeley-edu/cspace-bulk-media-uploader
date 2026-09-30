<script setup lang="ts">
/**
 * A job's actions in Drafts and Job queue, in the list and in the job's preview (design: Drafts, scheduling and
 * the job queue; UI mockup actionsFor). Drafts: Preview, Edit (Continue editing), or Take over… after a warning
 * when someone else is editing, and Delete. Job queue: Preview, Edit (after a warning: it leaves the queue) and
 * Delete for a queued job; Cancel run (after a warning) for a running one. The preview shows the same actions
 * without Preview; Save draft and Submit job belong to Create / edit job only.
 * editWhy: why this user can't create or edit jobs (design: Permissions in the UI); those buttons are then off.
 * user, scheduler: Cancel run is only for BMU schedulers and whoever submitted the job (design: Job scheduling).
 */
import { computed, ref } from "vue";
import { api } from "../api";
import { formatTime } from "../lib/files";
import { canCancelRun, NO_CANCEL_WHY } from "../lib/schedule";
import type { Created, Job } from "../types";
import DeleteJobConfirm from "./DeleteJobConfirm.vue";

const props = defineProps<{ job: Job; kind: "drafts" | "queue"; inPreview?: boolean; editWhy?: string; user?: string; scheduler?: boolean }>();
const emit = defineEmits<{
  open: [id: string, mode: "edit" | "preview", takeOverSince?: number];
  done: [flash: string]; // the job changed (deleted, cancelled): the list refreshes
  error: [message: string];
}>();

const confirm = ref<"delete" | "takeover" | "edit" | "cancel" | null>(null);
// What the job's runs created, for the delete confirmation: undefined while it loads, null if it never ran.
const created = ref<Created | null | undefined>(undefined);
const running = computed(() => props.job.status === "Running");
const lockedByOther = computed(() => props.job.status === "Draft" && !!props.job.editingBy && !props.job.editingByYou);
const noEdit = computed(() => props.editWhy ?? "");
/** design: Job scheduling — why this user can't cancel the run, or "" when they can. */
const noCancel = computed(() => (canCancelRun(props.job, { user: props.user, scheduler: props.scheduler }) ? "" : NO_CANCEL_WHY));

function askDelete() {
  confirm.value = "delete";
  created.value = undefined;
  if (!props.job.run) created.value = null;
  else api.job(props.job.id).then((r) => { created.value = r.created; }).catch((e) => emit("error", (e as Error).message));
}
async function act(fn: () => Promise<unknown>, flash = "") {
  try {
    await fn();
    confirm.value = null;
    emit("done", flash);
    return true;
  } catch (e) {
    emit("error", (e as Error).message);
    return false;
  }
}
async function editQueued() {
  if (await act(() => api.editQueued(props.job.id))) emit("open", props.job.id, "edit");
}
const del = () => act(() => api.deleteJob(props.job.id), props.kind === "queue" ? "Deleted the job." : "");
</script>

<template>
  <DeleteJobConfirm v-if="confirm === 'delete'" :job="job" :created="created" @confirm="del" @cancel="confirm = null" />
  <div v-else-if="confirm === 'takeover'" class="msg msg-warn">
    {{ job.editingBy }} has been editing this draft since {{ formatTime(job.editingSince) }}. If you take over, their editing ends
    and their page becomes read-only; everything they changed so far is already saved.
    <button @click="emit('open', job.id, 'edit', job.editingSince)">Take over and edit</button> <button @click="confirm = null">Cancel</button>
  </div>
  <div v-else-if="confirm === 'edit'" class="msg msg-warn">
    Editing takes this job out of the queue and deletes its saved sign-in. It goes to the end of the queue when it’s
    submitted again, even if nothing changes. <button @click="editQueued">Edit anyway</button> <button @click="confirm = null">Cancel</button>
  </div>
  <div v-else-if="confirm === 'cancel'" class="msg msg-warn">
    Stop this run? The worker finishes the document it’s on, then stops; documents it hasn’t reached stay not started,
    and nothing already created is undone.
    <button @click="act(() => api.cancelRun(job.id))">Cancel run</button> <button @click="confirm = null">Keep running</button>
  </div>
  <div v-else class="actions">
    <button v-if="!inPreview" @click="emit('open', job.id, 'preview')">Preview</button>
    <template v-if="kind === 'drafts'">
      <button v-if="lockedByOther" :disabled="!!noEdit" :title="noEdit || `${job.editingBy} is editing this draft`"
              @click="confirm = 'takeover'">Take over…</button>
      <button v-else :disabled="!!noEdit" :title="noEdit" @click="emit('open', job.id, 'edit')">{{ job.editingByYou ? "Continue editing" : "Edit" }}</button>
      <button :disabled="lockedByOther || !!noEdit" :title="noEdit || (lockedByOther ? `${job.editingBy} is editing this draft` : '')"
              @click="askDelete">Delete</button>
    </template>
    <template v-else-if="running">
      <button :disabled="!!job.cancelRequested || !!noCancel" :title="noCancel || 'Stop after the document in progress'" @click="confirm = 'cancel'">Cancel run</button>
      <button disabled title="A running job can't be deleted">Delete</button>
    </template>
    <template v-else>
      <button :disabled="!!noEdit" :title="noEdit" @click="confirm = 'edit'">Edit</button>
      <button :disabled="!!noEdit" :title="noEdit" @click="askDelete">Delete</button>
    </template>
  </div>
</template>
