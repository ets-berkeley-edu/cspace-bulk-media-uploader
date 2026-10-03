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
    <div v-else class="legacy">
      <div class="card">
        <JobEditor
          :key="session.editorKey"
          :job-id="session.jobId"
          :me="currentUser"
          :mode="session.mode"
          :take-over-since="session.takeOverSince"
          @close="session.newJob"
          @opened="id => session.jobId = id"
          @scheduled="session.scheduled"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import {onActivated} from 'vue'
import type {Me} from '@/types'
import JobEditor from '@/components/JobEditor.vue'
import {EDIT_BLOCKED_EXPLAIN, editBlocked} from '@/lib/status'
import {useContextStore} from '@/stores/context'
import {useJobEditSessionStore} from '@/stores/job-edit-session'

const contextStore = useContextStore()
const currentUser = contextStore.currentUser as Me
const editWhy = editBlocked(currentUser.perms)
const session = useJobEditSessionStore()

// This page is kept alive behind the other tabs (BaseView), so it is activated, not mounted, each time it is shown.
onActivated(() => contextStore.loadingComplete('Create / edit job'))
</script>
