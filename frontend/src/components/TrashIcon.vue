<script setup lang="ts">
// The trash-can icon for deleting: a document in the editor, and a job in Drafts, Job queue and Finished jobs.
// Buttons that use it keep a visually hidden word, so screen readers still hear "Delete".
</script>

<template>
  <svg class="trash-icon" viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5"
       stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
    <path d="M2.5 4h11M6.5 4V2.5h3V4M4 4l.7 9.5h6.6L12 4M6.8 6.5v4.5M9.2 6.5v4.5" />
  </svg>
</template>
