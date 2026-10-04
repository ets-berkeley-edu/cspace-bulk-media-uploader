<template>
  <v-alert
    class="failure-alert my-1"
    density="compact"
    :type="notice ? 'info' : 'error'"
    variant="tonal"
  >
    <strong>{{ failure.title }}.</strong> {{ failure.explain }}
    <div class="mt-1">
      <strong>What to do:</strong> {{ failure.fix }}
    </div>
    <template v-if="detail">
      <button
        :aria-expanded="isOpen"
        class="link-btn mt-1 text-caption"
        type="button"
        @click="isOpen = !isOpen"
      >
        {{ isOpen ? 'Hide technical details' : 'Show technical details' }}
      </button>
      <div v-if="isOpen" class="failure-detail mt-1">{{ code }} · {{ detail }}</div>
    </template>
  </v-alert>
</template>

<script setup lang="ts">
import {computed, ref} from 'vue'
import {failureOf, failures} from '@/lib/results'

/** A failure as museum staff read it: title, plain explanation, what to do, and the technical detail on request. */
const props = defineProps({
  code: {
    required: true,
    type: String
  },
  detail: {
    default: undefined,
    required: false,
    type: String
  },
  notice: {
    required: false,
    type: Boolean
  }
})

const isOpen = ref(false)
const failure = computed(() => failureOf(props.code, failures.value))
</script>

<style scoped>
.failure-detail {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  word-break: break-all;
}
</style>
