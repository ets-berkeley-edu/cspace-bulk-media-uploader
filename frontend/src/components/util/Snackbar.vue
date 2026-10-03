<template>
  <div id="snackbar-container" aria-live="assertive" role="alert">
    <v-snackbar
      v-model="snackbarShow"
      attach="#snackbar-container"
      :color="snackbar.color"
      location="top"
      multi-line
      :timeout="snackbar.timeout"
    >
      <div id="alert-text">{{ snackbar.text }}</div>
      <template #actions>
        <v-btn
          id="btn-close-alert"
          aria-label="Close this message"
          text="Close"
          variant="text"
          @click="contextStore.snackbarClose"
        />
      </template>
    </v-snackbar>
  </div>
</template>

<script setup lang="ts">
import {storeToRefs} from 'pinia'
import {useContextStore} from '@/stores/context'

const contextStore = useContextStore()
const {snackbar, snackbarShow} = storeToRefs(contextStore)
</script>
