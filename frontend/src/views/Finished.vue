<template>
  <div>
    <h1 id="page-title" class="sr-only" tabindex="-1">Finished jobs</h1>
    <FinishedJobs :edit-why="editWhy" :tenant="currentUser.tenant" @open="id => session.openJob(id)" />
  </div>
</template>

<script setup lang="ts">
import {onMounted} from 'vue'
import type {Me} from '@/types'
import FinishedJobs from '@/components/job/FinishedJobs.vue'
import {staffOnly} from '@/lib/roles'
import {useContextStore} from '@/stores/context'
import {useJobEditSessionStore} from '@/stores/job-edit-session'

const contextStore = useContextStore()
const currentUser = contextStore.currentUser as Me
// Only staff change a submitted job (design: Roles).
const editWhy = staffOnly(currentUser)
const session = useJobEditSessionStore()

onMounted(() => contextStore.loadingComplete('Finished jobs'))
</script>
