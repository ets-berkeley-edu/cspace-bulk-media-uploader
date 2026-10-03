<template>
  <div>
    <h1 id="page-title" class="sr-only" tabindex="-1">Finished jobs</h1>
    <div class="legacy">
      <div class="card">
        <FinishedJobs :edit-why="editWhy" :tenant="currentUser.tenant" @open="id => session.openJob(id)" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import {onMounted} from 'vue'
import type {Me} from '@/types'
import FinishedJobs from '@/components/FinishedJobs.vue'
import {editBlocked} from '@/lib/status'
import {useContextStore} from '@/stores/context'
import {useJobEditSessionStore} from '@/stores/job-edit-session'

const contextStore = useContextStore()
const currentUser = contextStore.currentUser as Me
const editWhy = editBlocked(currentUser.perms)
const session = useJobEditSessionStore()

onMounted(() => contextStore.loadingComplete('Finished jobs'))
</script>
