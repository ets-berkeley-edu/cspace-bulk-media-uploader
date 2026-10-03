<template>
  <div>
    <div
      id="announcer"
      :aria-live="contextStore.screenReaderAlert.politeness"
      class="sr-only"
    >
      {{ contextStore.screenReaderAlert.message }}
    </div>
    <router-view />
  </div>
</template>

<script setup lang="ts">
import {useContextStore} from '@/stores/context'

const contextStore = useContextStore()
</script>
