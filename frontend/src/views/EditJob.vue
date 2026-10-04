<template>
  <div>
    <h1 id="page-title" class="sr-only" tabindex="-1">Create / edit job</h1>
    <v-alert
      v-if="editWhy && !session.jobId"
      id="edit-blocked"
      density="compact"
      role="status"
      type="info"
      variant="tonal"
    >
      {{ EDIT_BLOCKED_EXPLAIN }}
    </v-alert>
    <JobEditor
      v-else
      :key="session.editorKey"
      :job-id="session.jobId"
      :me="currentUser"
      :mode="session.mode"
      :take-over-since="session.takeOverSince"
      @close="session.newJob"
      @missing="session.missing"
      @opened="session.created"
      @scheduled="session.scheduled"
    />
  </div>
</template>

<script setup lang="ts">
import {onActivated, watch} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import type {Me} from '@/types'
import JobEditor from '@/components/job/JobEditor.vue'
import {EDIT_BLOCKED_EXPLAIN, editBlocked} from '@/lib/status'
import {useContextStore} from '@/stores/context'
import {useJobEditSessionStore} from '@/stores/job-edit-session'

const contextStore = useContextStore()
const currentUser = contextStore.currentUser as Me
const editWhy = editBlocked(currentUser.perms)
const session = useJobEditSessionStore()

const route = useRoute()
const router = useRouter()

// The address and the open draft agree. An address that names another draft (a reload, a bookmark, Back or Forward)
// opens it. An address without one, while a draft is open, is corrected: the draft stays open with its uploads.
// Someone who can't edit jobs gets the explanation above, whatever the address.
watch(() => (route.name === 'Create / edit job' ? route.params.id as string | undefined || null : undefined), id => {
  if (id === undefined || id === session.jobId) {
    return
  }
  if (id && !editWhy) {
    void session.adopt(id)
  } else {
    void router.replace(session.jobPath)
  }
}, {immediate: true})

// This page is kept alive behind the other tabs (BaseView), so it is activated, not mounted, each time it is shown.
onActivated(() => contextStore.loadingComplete('Create / edit job'))
</script>
