<template>
  <th
    :aria-sort="isSorted ? (state.dir > 0 ? 'ascending' : 'descending') : 'none'"
    class="px-1"
    scope="col"
    :title="title"
  >
    <v-btn
      :id="`${idPrefix}sort-col-${sortKey}-btn`"
      :append-icon="icon"
      :aria-label="`Sort by ${label}`"
      class="font-weight-bold sort-col-btn text-no-wrap"
      :class="{'icon-visible': isSorted}"
      density="compact"
      size="small"
      variant="plain"
      @click="() => cycleSort(state, sortKey)"
    >
      {{ label }}
    </v-btn>
  </th>
</template>

<script setup lang="ts">
import type {PropType} from 'vue'
import {computed} from 'vue'
import {mdiArrowDown, mdiArrowUp, mdiUnfoldMoreHorizontal} from '@mdi/js'
import {cycleSort} from '@/lib/table'
import type {TableState} from '@/lib/table'

/** A sortable column heading: ascending, descending, then the original order. */
const props = defineProps({
  idPrefix: {
    default: '',
    required: false,
    type: String
  },
  label: {
    required: true,
    type: String
  },
  sortKey: {
    required: true,
    type: String
  },
  state: {
    required: true,
    type: Object as PropType<TableState>
  },
  title: {
    default: undefined,
    required: false,
    type: String
  }
})

const isSorted = computed(() => props.state.sort === props.sortKey)
const icon = computed(() => (isSorted.value ? (props.state.dir > 0 ? mdiArrowUp : mdiArrowDown) : mdiUnfoldMoreHorizontal))
</script>

<style scoped>
.sort-col-btn {
  height: 28px !important;
  letter-spacing: normal !important;
  min-width: 0 !important;
  opacity: 1;
  padding: 0 2px 0 4px;
}
.sort-col-btn :deep(.v-btn__append) {
  margin-inline: 2px 0;
}
.sort-col-btn :deep(.v-btn__append .v-icon) {
  opacity: var(--v-disabled-opacity);
}
.sort-col-btn.icon-visible :deep(.v-btn__append .v-icon) {
  color: rgb(var(--v-theme-primary));
  opacity: 1;
}
</style>
