<template>
  <div>
    <h1 id="page-title" class="sr-only" tabindex="-1">Drafts</h1>
    <JobPreview
      v-if="session.previewing.drafts"
      :key="session.previewing.drafts"
      :edit-why="editWhy"
      from="drafts"
      :job-id="session.previewing.drafts"
      :scheduler="!!currentUser.scheduler"
      :tenant="currentUser.tenant"
      :user="currentUser.user"
      @back="session.previewing.drafts = null"
      @open="openJob"
    />
    <DraftsList
      v-else
      :edit-why="editWhy"
      :tenant="currentUser.tenant"
      @open="openJob"
    />
  </div>
</template>

<script setup lang="ts">
import {onMounted} from 'vue'
import type {Me} from '@/types'
import DraftsList from '@/components/job/DraftsList.vue'
import JobPreview from '@/components/job/JobPreview.vue'
import {editBlocked} from '@/lib/status'
import {useContextStore} from '@/stores/context'
import {useJobEditSessionStore} from '@/stores/job-edit-session'

const contextStore = useContextStore()
const currentUser = contextStore.currentUser as Me
const editWhy = editBlocked(currentUser.perms)
const session = useJobEditSessionStore()

onMounted(() => contextStore.loadingComplete('Drafts'))

// Preview opens inside this tab; Edit goes to Create / edit job.
const openJob = (id: string, mode: 'edit' | 'preview', takeOverSince?: number) => session.openJob(id, mode, takeOverSince, 'drafts')
</script>
