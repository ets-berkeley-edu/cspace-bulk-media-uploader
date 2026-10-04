<template>
  <div>
    <h1 id="page-title" class="sr-only" tabindex="-1">Job queue</h1>
    <JobPreview
      v-if="session.previewing.queue"
      :key="session.previewing.queue"
      :edit-why="editWhy"
      from="queue"
      :job-id="session.previewing.queue"
      :scheduler="!!currentUser.scheduler"
      :tenant="currentUser.tenant"
      :user="currentUser.user"
      @back="session.previewing.queue = null"
      @open="openJob"
    />
    <QueueList
      v-else
      :edit-why="editWhy"
      :scheduler="!!currentUser.scheduler"
      :user="currentUser.user"
      :tenant="currentUser.tenant"
      @open="openJob"
    />
  </div>
</template>

<script setup lang="ts">
import {onMounted} from 'vue'
import type {Me} from '@/types'
import QueueList from '@/components/job/QueueList.vue'
import JobPreview from '@/components/job/JobPreview.vue'
import {editBlocked} from '@/lib/status'
import {useContextStore} from '@/stores/context'
import {useJobEditSessionStore} from '@/stores/job-edit-session'

const contextStore = useContextStore()
const currentUser = contextStore.currentUser as Me
const editWhy = editBlocked(currentUser.perms)
const session = useJobEditSessionStore()

onMounted(() => contextStore.loadingComplete('Job queue'))

// Preview opens inside this tab; Edit goes to Create / edit job.
const openJob = (id: string, mode: 'edit' | 'preview', takeOverSince?: number) => session.openJob(id, mode, takeOverSince, 'queue')
</script>
