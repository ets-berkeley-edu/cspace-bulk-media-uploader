<script setup lang="ts">
/**
 * The Date field (design: Structured dates): the text is parsed by CollectionSpace's own parser as the user
 * types, and the earliest and latest dates show under the field. The row's check decides whether it blocks.
 */
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { api } from "../api";
import { describeDate, type DateGroup } from "../lib/dates";

const props = defineProps<{ modelValue: string; parsed?: { value: string; ok: boolean; group: DateGroup }; disabled?: boolean }>();
const emit = defineEmits<{ "update:modelValue": [value: string] }>();

const text = ref(props.modelValue);
const preview = ref<{ value: string; ok: boolean; group: DateGroup } | null>(null);
const pending = ref(false);
let timer: ReturnType<typeof setTimeout> | undefined;
let seq = 0;
watch(() => props.modelValue, (v) => { text.value = v; });
onBeforeUnmount(() => clearTimeout(timer));

function onInput() {
  clearTimeout(timer);
  const t = text.value.trim();
  if (!t || t === props.parsed?.value) { pending.value = false; preview.value = null; return; }
  pending.value = true;
  timer = setTimeout(async () => {
    const mine = ++seq;
    try {
      const r = await api.parseDate(t);
      if (mine === seq) preview.value = { value: t, ...r };
    } catch {
      if (mine === seq) preview.value = null;
    } finally {
      if (mine === seq) pending.value = false;
    }
  }, 300);
}

function commit() {
  if (text.value.trim() !== props.modelValue) emit("update:modelValue", text.value.trim());
}

const note = computed(() => {
  const t = text.value.trim();
  if (!t) return "";
  if (pending.value) return "Checking the date with CollectionSpace…";
  const p = preview.value?.value === t ? preview.value : props.parsed?.value === t ? props.parsed : null;
  if (!p) return "";
  return p.ok ? describeDate(p.group) : "Can't interpret this date";
});
</script>

<template>
  <label class="field"><span>Date</span>
    <input v-model="text" type="text" placeholder="e.g. 2026-08-30, 1920s, circa 1850" :disabled="disabled"
           @input="onInput" @change="commit" @keydown.enter.prevent="commit" />
    <span class="field-note" :class="{ bad: note === 'Can\'t interpret this date' }" aria-live="polite">{{ note }}</span>
  </label>
</template>
