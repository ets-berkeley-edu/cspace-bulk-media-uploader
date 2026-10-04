<template>
  <div v-if="!bottom || pages > 1" :id="`${idPrefix}pagination${bottom ? '-bottom' : ''}`" class="align-center d-flex flex-wrap pagination text-body-2">
    <div v-if="!bottom && filters" class="align-center d-flex mr-4">
      <label class="mr-2" :for="`${idPrefix}filter-select`">Show</label>
      <select
        :id="`${idPrefix}filter-select`"
        aria-label="Show"
        class="native-select"
        :value="state.filter"
        @change="event => setFilter(state, (event.target as HTMLSelectElement).value)"
      >
        <option v-for="[key, label] in filters" :key="key" :value="key">{{ label }}</option>
      </select>
    </div>
    <div :id="`${idPrefix}pagination-count${bottom ? '-bottom' : ''}`" class="flex-grow-1 mr-4 text-medium-emphasis">
      {{ range }} {{ noun }}<template v-if="total !== of"> (filtered from {{ of.toLocaleString() }})</template><template v-if="state.sort"> · sorted</template>
    </div>
    <div class="align-center d-flex mr-4">
      <v-btn
        v-for="button in buttons.slice(0, 2)"
        :id="`${idPrefix}${button.id}${bottom ? '-bottom' : ''}`"
        :key="button.id"
        :aria-label="button.label"
        density="comfortable"
        :disabled="button.disabled"
        :icon="button.icon"
        size="small"
        variant="text"
        @click="() => goToPage(state, button.page, pages)"
      />
      <span class="mx-2 text-no-wrap">Page {{ state.page }} of {{ pages }}</span>
      <v-btn
        v-for="button in buttons.slice(2)"
        :id="`${idPrefix}${button.id}${bottom ? '-bottom' : ''}`"
        :key="button.id"
        :aria-label="button.label"
        density="comfortable"
        :disabled="button.disabled"
        :icon="button.icon"
        size="small"
        variant="text"
        @click="() => goToPage(state, button.page, pages)"
      />
    </div>
    <div v-if="!bottom" class="align-center d-flex">
      <label class="mr-2" :for="`${idPrefix}page-size-select`">Per page</label>
      <select
        :id="`${idPrefix}page-size-select`"
        aria-label="Documents per page"
        class="native-select"
        :value="state.size"
        @change="event => setPageSize(state, Number((event.target as HTMLSelectElement).value))"
      >
        <option v-for="n in PAGE_SIZES" :key="n" :value="n">{{ n }}</option>
      </select>
    </div>
  </div>
</template>

<script setup lang="ts">
import type {PropType} from 'vue'
import {computed} from 'vue'
import {mdiChevronLeft, mdiChevronRight, mdiPageFirst, mdiPageLast} from '@mdi/js'
import {PAGE_SIZES, goToPage, setFilter, setPageSize} from '@/lib/table'
import type {TableState} from '@/lib/table'

/**
 * Above and below a table: the Show filter (top only), "1–25 of 340 documents", first / previous / next / last,
 * and how many per page (top only).
 */
const props = defineProps({
  bottom: {
    required: false,
    type: Boolean
  },
  filters: {
    default: undefined,
    required: false,
    type: Array as PropType<[string, string][]>
  },
  idPrefix: {
    default: '',
    required: false,
    type: String
  },
  noun: {
    required: true,
    type: String
  },
  of: {
    required: true,
    type: Number
  },
  pages: {
    required: true,
    type: Number
  },
  start: {
    required: true,
    type: Number
  },
  state: {
    required: true,
    type: Object as PropType<TableState>
  },
  total: {
    required: true,
    type: Number
  }
})

const range = computed(() => props.total
  ? `${(props.start + 1).toLocaleString()}–${Math.min(props.start + props.state.size, props.total).toLocaleString()} of ${props.total.toLocaleString()}`
  : 'No')
const buttons = computed(() => {
  const page = props.state.page
  return [
    {id: 'page-first-btn', label: 'First page', icon: mdiPageFirst, page: 1, disabled: page <= 1},
    {id: 'page-previous-btn', label: 'Previous page', icon: mdiChevronLeft, page: page - 1, disabled: page <= 1},
    {id: 'page-next-btn', label: 'Next page', icon: mdiChevronRight, page: page + 1, disabled: page >= props.pages},
    {id: 'page-last-btn', label: 'Last page', icon: mdiPageLast, page: props.pages, disabled: page >= props.pages}
  ]
})
</script>

<style scoped>
.pagination {
  row-gap: 6px;
}
</style>
