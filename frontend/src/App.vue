<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { api, ApiError } from "./api";
import DraftsList from "./components/DraftsList.vue";
import JobEditor from "./components/JobEditor.vue";
import JobPreview from "./components/JobPreview.vue";
import FinishedJobs from "./components/FinishedJobs.vue";
import QueueList from "./components/QueueList.vue";
import LoginForm from "./components/LoginForm.vue";
import { EDIT_BLOCKED_EXPLAIN, editBlocked } from "./lib/status";
import { submitMessage } from "./lib/schedule";
import type { Job, Me } from "./types";

const me = ref<Me | null>(null);
const loading = ref(true);
const tab = ref<"editor" | "drafts" | "queue" | "jobs">("editor");
const jobId = ref<string | null>(null);
const mode = ref<"edit" | "preview">("edit");
const takeOverSince = ref<number | null>(null);
const editorKey = ref(0);
const notice = ref("");
// The job each list tab is previewing, shown inside that tab (design: Drafts, scheduling and the job queue; UI
// mockup renderPreview). Previewing never touches the draft open in Create / edit job.
const previewing = reactive<{ drafts: string | null; queue: string | null }>({ drafts: null, queue: null });
// Without create and update on Media the user can view jobs but not create or edit them (design: Permissions in the UI).
const editWhy = computed(() => (me.value ? editBlocked(me.value.perms) : ""));

// Signed out while working (idle or absolute timeout): back to the sign-in page, saying why.
if (typeof window !== "undefined") {
  window.addEventListener("bmu-signed-out", (e) => {
    if (!me.value) return;
    me.value = null;
    jobId.value = null;
    notice.value = (e as CustomEvent<string>).detail;
  });
}

onMounted(async () => {
  try {
    me.value = await api.me();
  } catch (e) {
    if (!(e instanceof ApiError && e.status === 401)) notice.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
});

/** Leaving the job in the editor: stop editing it, so others can edit it without taking over. */
async function leaveCurrent(nextId: string | null) {
  if (jobId.value && jobId.value !== nextId) await api.closeJob(jobId.value).catch(() => undefined);
}

async function signOut() {
  await api.logout().catch(() => undefined);
  me.value = null;
  jobId.value = null;
}

async function newJob() {
  await leaveCurrent(null);
  jobId.value = null;
  mode.value = "edit";
  takeOverSince.value = null;
  editorKey.value++;
  tab.value = "editor";
  notice.value = "";
}

async function openJob(id: string, m: "edit" | "preview" = "edit", since?: number) {
  if (m === "preview") {
    if (tab.value === "drafts" || tab.value === "queue") previewing[tab.value] = id;
    return;
  }
  // Opening a job for editing ends any preview of it: it's about to change.
  if (previewing.drafts === id) previewing.drafts = null;
  if (previewing.queue === id) previewing.queue = null;
  await leaveCurrent(id);
  notice.value = "";
  jobId.value = id;
  mode.value = m;
  takeOverSince.value = since ?? null;
  editorKey.value++;
  tab.value = "editor";
}

/** Submit job succeeded: say when it runs, from the response's plan (design: Job scheduling; UI mockup submitJob). */
async function scheduled(j: Job) {
  jobId.value = null; // submitting already took it out of Drafts
  const sched = await api.getSchedule().catch(() => null); // only to tell the development setting apart
  await newJob();
  notice.value = submitMessage(j, { alwaysRunTime: !!sched?.alwaysRunTime });
  tab.value = "queue";
}
</script>

<template>
  <div class="page">
    <p v-if="loading" class="muted">Loading…</p>
    <template v-else-if="!me">
      <div v-if="notice" class="msg msg-warn login-notice" role="status">{{ notice }}</div>
      <LoginForm @signed-in="me = $event; notice = ''" />
    </template>
    <template v-else>
      <h1>Bulk Media Uploader</h1>
      <p class="subtitle">Prototype · creates Media records, files, Objects and Relations in CollectionSpace using your own account.</p>
      <div class="bar">
        <strong>{{ me.tenant.name }}</strong>
        <span class="muted">Signed in as {{ me.user }}</span>
        <span v-if="editWhy" class="badge b-warn" :title="editWhy">View only: your account can't create and update Media records</span>
        <span class="spacer"></span>
        <button @click="signOut">Sign out</button>
      </div>
      <div v-if="notice" class="msg msg-info" role="status">{{ notice }}</div>
      <div class="tabs" role="tablist">
        <button class="tab" :class="{ active: tab === 'editor' }" role="tab" :aria-selected="tab === 'editor'" @click="tab = 'editor'">Create / edit job</button>
        <button class="tab" :class="{ active: tab === 'drafts' }" role="tab" :aria-selected="tab === 'drafts'" @click="tab = 'drafts'">Drafts</button>
        <button class="tab" :class="{ active: tab === 'queue' }" role="tab" :aria-selected="tab === 'queue'" @click="tab = 'queue'">Job queue</button>
        <button class="tab" :class="{ active: tab === 'jobs' }" role="tab" :aria-selected="tab === 'jobs'" @click="tab = 'jobs'">Finished jobs</button>
        <span class="spacer"></span>
        <button class="primary new-job" :disabled="!!editWhy" :title="editWhy" @click="newJob">+ New job</button>
      </div>
      <div class="card view">
        <div v-if="editWhy && !jobId" v-show="tab === 'editor'" class="msg msg-info" role="status">{{ EDIT_BLOCKED_EXPLAIN }}</div>
        <JobEditor v-else v-show="tab === 'editor'" :key="editorKey" :me="me" :job-id="jobId" :mode="mode" :take-over-since="takeOverSince"
                   @scheduled="scheduled" @opened="jobId = $event" @close="newJob" />
        <template v-if="tab === 'drafts'">
          <JobPreview v-if="previewing.drafts" :key="previewing.drafts" :job-id="previewing.drafts" from="drafts" :tenant="me.tenant" :edit-why="editWhy"
                      :user="me.user" :scheduler="!!me.scheduler"
                      @back="previewing.drafts = null" @open="openJob" />
          <DraftsList v-else :tenant="me.tenant" :edit-why="editWhy" @open="openJob" />
        </template>
        <template v-if="tab === 'queue'">
          <JobPreview v-if="previewing.queue" :key="previewing.queue" :job-id="previewing.queue" from="queue" :tenant="me.tenant" :edit-why="editWhy"
                      :user="me.user" :scheduler="!!me.scheduler"
                      @back="previewing.queue = null" @open="openJob" />
          <QueueList v-else :tenant="me.tenant" :edit-why="editWhy" :user="me.user" :scheduler="!!me.scheduler" @open="openJob" />
        </template>
        <FinishedJobs v-if="tab === 'jobs'" :tenant="me.tenant" :edit-why="editWhy" @open="(id) => openJob(id)" />
      </div>
    </template>
  </div>
</template>
