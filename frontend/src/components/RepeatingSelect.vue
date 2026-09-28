<script setup lang="ts">
/**
 * A repeating option picker, like CollectionSpace's for repeating fields (media type, language): one
 * dropdown per value, "+ Add an additional …" and × to remove one. Only existing values can be chosen.
 */
import { computed, ref, watch } from "vue";
import { displayName } from "../lib/refname";
import type { Option } from "../types";

const props = defineProps<{ modelValue: string[]; options: Option[]; label: string; word: string; disabled?: boolean }>();
const emit = defineEmits<{ "update:modelValue": [value: string[]] }>();

const draft = ref<string[]>([]);
watch(() => props.modelValue, (v) => { draft.value = v.length ? [...v] : [""]; }, { immediate: true });

/** The options, plus any current value missing from them (e.g. before the vocabulary has loaded). */
const all = computed(() => {
  const known = new Set(props.options.map((o) => o.value));
  const extra = props.modelValue.filter((v) => v && !known.has(v)).map((v) => ({ value: v, label: displayName(v) }));
  return [...props.options, ...extra];
});
const canAdd = computed(() => draft.value.some((v) => v) && !draft.value.some((v) => !v));

function commit() {
  const out = [...new Set(draft.value.filter((v) => v))];
  if (JSON.stringify(out) !== JSON.stringify(props.modelValue)) emit("update:modelValue", out);
}
function set(j: number, v: string) {
  draft.value[j] = v;
  commit();
}
function remove(j: number) {
  draft.value.splice(j, 1);
  if (!draft.value.length) draft.value.push("");
  commit();
}
</script>

<template>
  <div class="field repeating">
    <span>{{ label }}</span>
    <div v-for="(v, j) in draft" :key="j" class="rep-row">
      <select :value="v" :disabled="disabled" :aria-label="`${label} ${j + 1}`" @change="set(j, ($event.target as HTMLSelectElement).value)">
        <option value="">—</option>
        <option v-for="o in all" :key="o.value" :value="o.value" :disabled="o.value !== v && draft.includes(o.value)">{{ o.label }}</option>
      </select>
      <button v-if="draft.length > 1 && !disabled" type="button" class="x-btn" :aria-label="`Remove this ${word}`" @click="remove(j)">×</button>
    </div>
    <button v-if="canAdd && !disabled" type="button" class="link" @click="draft.push('')">+ Add an additional {{ word }}</button>
  </div>
</template>
