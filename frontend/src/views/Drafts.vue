<template>
  <div>
    <h1 id="page-title" class="sr-only" tabindex="-1">Drafts</h1>
    <JobPreview
      v-if="session.previewing.drafts"
      :key="session.previewing.drafts"
      :edit-why="editWhy"
      from="drafts"
      :job-id="session.previewing.drafts"
      :staff="currentUser.role === 'staff'"
      :tenant="currentUser.tenant"
      :user="currentUser.user"
      @back="session.previewing.drafts = null"
      @open="openJob"
    />
    <DraftsList
      v-else
      :edit-why="editWhy"
      :staff="currentUser.role === 'staff'"
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
import {useContextStore} from '@/stores/context'
import {useJobEditSessionStore} from '@/stores/job-edit-session'

const contextStore = useContextStore()
const currentUser = contextStore.currentUser as Me
// Staff and interns both work in Drafts; which drafts an intern may change is decided per draft (design: Roles).
const editWhy = ''
const session = useJobEditSessionStore()

onMounted(() => contextStore.loadingComplete('Drafts'))

// Preview opens inside this tab; Edit goes to Create / edit job.
const openJob = (id: string, mode: 'edit' | 'preview', takeOverSince?: number) => session.openJob(id, mode, takeOverSince, 'drafts')
</script>
