<script setup lang="ts">
// The expand/collapse triangle for job and document rows. An SVG rather than the "▸" character, so it is the same size
// on every platform; the button around it (.chevron) rotates it when open.
</script>

<template>
  <svg class="chev-icon" viewBox="0 0 16 16" width="20" height="20" aria-hidden="true" focusable="false">
    <path d="M4.5 2 L13 8 L4.5 14 Z" fill="currentColor" />
  </svg>
</template>
