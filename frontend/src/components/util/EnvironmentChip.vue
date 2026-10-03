<template>
  <v-chip
    v-if="config.label"
    id="environment-label"
    :color="config.realCollectionSpace ? 'warning' : undefined"
    size="small"
    :title="title"
    :variant="config.realCollectionSpace ? 'flat' : 'tonal'"
  >
    {{ config.label }}
  </v-chip>
</template>

<script setup lang="ts">
import {computed} from 'vue'
import {storeToRefs} from 'pinia'
import {useContextStore} from '@/stores/context'

// Which environment this is (local with the simulator, local against PAHMA QA, AWS), so it's always clear which one
// you're using: a warning colour when its CollectionSpace is a real server.
const {config} = storeToRefs(useContextStore())
const title = computed(() => config.value.realCollectionSpace
  ? 'Records you create here are created in a real CollectionSpace, and stay there'
  : 'Uses the simulated CollectionSpace: nothing reaches a real server')
</script>
