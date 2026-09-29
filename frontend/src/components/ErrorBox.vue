<script setup lang="ts">
/** A failure as museum staff read it: title, plain explanation, what to do, and the technical detail on request. */
import { computed, ref } from "vue";
import { failureOf, failures } from "../lib/results";

const props = defineProps<{ code: string; detail?: string; notice?: boolean }>();
const open = ref(false);
const f = computed(() => failureOf(props.code, failures.value));
</script>

<template>
  <div class="msg errbox" :class="notice ? 'msg-info' : 'msg-block'">
    <strong>{{ f.title }}.</strong> {{ f.explain }}
    <div class="errbox-fix"><strong>What to do:</strong> {{ f.fix }}</div>
    <template v-if="detail">
      <button class="link" type="button" :aria-expanded="open" @click="open = !open">{{ open ? "Hide technical details" : "Show technical details" }}</button>
      <div v-if="open" class="errbox-detail">{{ code }} · {{ detail }}</div>
    </template>
  </div>
</template>
