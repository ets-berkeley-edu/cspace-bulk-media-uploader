<template>
  <div class="py-8 text-center">
    <h1 id="page-title" class="mb-2 text-h5" tabindex="-1">Page not found</h1>
    <p class="mb-4">There is no page at this address.</p>
    <v-btn id="btn-go-to-jobs" color="primary" to="/job">Go to Create / edit job</v-btn>
  </div>
</template>

<script setup lang="ts">
import {onMounted} from 'vue'
import {useContextStore} from '@/stores/context'

onMounted(() => useContextStore().loadingComplete('Page not found', 'Page not found'))
</script>
