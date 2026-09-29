<script setup lang="ts">
/**
 * Above and below a document table: the Show filter (top only), "1–25 of 340 documents", first / previous /
 * next / last, and documents per page (top only).
 */
import { computed } from "vue";
import { PAGE_SIZES, type TableState } from "../lib/table";

const props = defineProps<{
  state: TableState; total: number; of: number; pages: number; start: number; noun: string;
  filters?: [string, string][]; bottom?: boolean;
}>();
const range = computed(() => props.total
  ? `${(props.start + 1).toLocaleString()}–${Math.min(props.start + props.state.size, props.total).toLocaleString()} of ${props.total.toLocaleString()}`
  : "No");
function go(page: number) {
  props.state.page = Math.min(Math.max(1, page), props.pages);
}
function setFilter(e: Event) {
  props.state.filter = (e.target as HTMLSelectElement).value;
  props.state.page = 1;
}
function setSize(e: Event) {
  props.state.size = Number((e.target as HTMLSelectElement).value);
  props.state.page = 1;
}
</script>

<template>
  <div v-if="!bottom || pages > 1" class="pager">
    <label v-if="!bottom && filters">Show <select :value="state.filter" aria-label="Show" @change="setFilter">
      <option v-for="[k, label] in filters" :key="k" :value="k">{{ label }}</option></select></label>
    <span class="pager-count">{{ range }} {{ noun }}<template v-if="total !== of"> (filtered from {{ of.toLocaleString() }})</template><template
      v-if="state.sort"> · sorted</template></span>
    <span class="pager-nav">
      <button type="button" :disabled="state.page <= 1" aria-label="First page" @click="go(1)">«</button>
      <button type="button" :disabled="state.page <= 1" aria-label="Previous page" @click="go(state.page - 1)">‹</button>
      <span>Page {{ state.page }} of {{ pages }}</span>
      <button type="button" :disabled="state.page >= pages" aria-label="Next page" @click="go(state.page + 1)">›</button>
      <button type="button" :disabled="state.page >= pages" aria-label="Last page" @click="go(pages)">»</button>
    </span>
    <label v-if="!bottom">Per page <select :value="state.size" aria-label="Documents per page" @change="setSize">
      <option v-for="n in PAGE_SIZES" :key="n" :value="n">{{ n }}</option></select></label>
  </div>
</template>
