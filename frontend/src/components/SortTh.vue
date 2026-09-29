<script setup lang="ts">
/** A sortable column heading: ascending, descending, then the original order. */
import { computed } from "vue";
import { cycleSort, type TableState } from "../lib/table";

const props = defineProps<{ state: TableState; sortKey: string; label: string; title?: string }>();
const on = computed(() => props.state.sort === props.sortKey);
</script>

<template>
  <th :aria-sort="on ? (state.dir > 0 ? 'ascending' : 'descending') : 'none'" :title="title">
    <button class="sort-btn" type="button" :aria-label="`Sort by ${label}`" @click="cycleSort(state, sortKey)">
      {{ label }} <span class="sort-ind" aria-hidden="true">{{ on ? (state.dir > 0 ? "▲" : "▼") : "↕" }}</span></button>
  </th>
</template>
