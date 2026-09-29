<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api, ApiError } from "./api";
import DraftsList from "./components/DraftsList.vue";
import JobEditor from "./components/JobEditor.vue";
import JobsList from "./components/JobsList.vue";
import LoginForm from "./components/LoginForm.vue";
import type { Job, Me } from "./types";

const me = ref<Me | null>(null);
const loading = ref(true);
const tab = ref<"editor" | "drafts" | "jobs">("editor");
const jobId = ref<string | null>(null);
const mode = ref<"edit" | "preview">("edit");
const takeOverSince = ref<number | null>(null);
const editorKey = ref(0);
const notice = ref("");

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
  await leaveCurrent(id);
  jobId.value = id;
  mode.value = m;
  takeOverSince.value = since ?? null;
  editorKey.value++;
  tab.value = "editor";
}

async function scheduled(j: Job) {
  jobId.value = null; // scheduling already took it out of Drafts
  await newJob();
  notice.value = `“${j.name || "Untitled job"}” was scheduled. It runs with your sign-in, which is deleted when the run ends.`;
  tab.value = "jobs";
}
</script>

<template>
  <div class="page">
    <p v-if="loading" class="muted">Loading…</p>
    <LoginForm v-else-if="!me" @signed-in="me = $event" />
    <template v-else>
      <h1>Bulk Media Uploader</h1>
      <p class="subtitle">Prototype · creates Media records, files, Objects and Relations in CollectionSpace using your own account.</p>
      <div class="bar">
        <strong>{{ me.tenant.name }}</strong>
        <span class="muted">Signed in as {{ me.user }}</span>
        <span v-if="!me.perms.media" class="badge b-warn">Your account can't create Media records</span>
        <span class="spacer"></span>
        <button @click="signOut">Sign out</button>
      </div>
      <div v-if="notice" class="msg msg-info" role="status">{{ notice }}</div>
      <div class="tabs" role="tablist">
        <button class="tab" :class="{ active: tab === 'editor' }" role="tab" :aria-selected="tab === 'editor'" @click="tab = 'editor'">Create / edit job</button>
        <button class="tab" :class="{ active: tab === 'drafts' }" role="tab" :aria-selected="tab === 'drafts'" @click="tab = 'drafts'">Drafts</button>
        <button class="tab" :class="{ active: tab === 'jobs' }" role="tab" :aria-selected="tab === 'jobs'" @click="tab = 'jobs'">Jobs</button>
        <span class="spacer"></span>
        <button class="primary new-job" @click="newJob">+ New job</button>
      </div>
      <div class="card view">
        <JobEditor v-show="tab === 'editor'" :key="editorKey" :me="me" :job-id="jobId" :mode="mode" :take-over-since="takeOverSince"
                   @scheduled="scheduled" @opened="jobId = $event" @close="newJob" />
        <DraftsList v-if="tab === 'drafts'" @open="openJob" />
        <JobsList v-if="tab === 'jobs'" @open="(id) => openJob(id)" />
      </div>
    </template>
  </div>
</template>
