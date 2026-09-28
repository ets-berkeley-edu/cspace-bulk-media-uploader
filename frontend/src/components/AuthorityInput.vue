<script setup lang="ts">
/**
 * Autocomplete for an authority field. Only existing CollectionSpace terms can be chosen: the value
 * is the term's refName, the input shows only its display name.
 */
import { computed, ref, watch } from "vue";
import { api } from "../api";
import { displayName } from "../lib/refname";
import type { Term } from "../types";

const props = defineProps<{ modelValue: string; field: string; label: string; disabled?: boolean }>();
const emit = defineEmits<{ "update:modelValue": [value: string] }>();

const text = ref(displayName(props.modelValue));
const terms = ref<Term[]>([]);
const open = ref(false);
const message = ref("");
const active = ref(-1);
let timer: ReturnType<typeof setTimeout> | undefined;
let seq = 0;

watch(() => props.modelValue, (v) => { text.value = displayName(v); });

const groups = computed(() => {
  const out: { source: string; items: { t: Term; i: number }[] }[] = [];
  terms.value.forEach((t, i) => {
    let g = out.find((x) => x.source === t.source);
    if (!g) out.push((g = { source: t.source, items: [] }));
    g.items.push({ t, i });
  });
  return out;
});

function onInput() {
  open.value = true;
  active.value = -1;
  clearTimeout(timer);
  const q = text.value.trim();
  if (q.length < 3) {
    terms.value = [];
    message.value = "Continue typing to find matching terms (3+ characters)";
    return;
  }
  message.value = "Searching…";
  timer = setTimeout(async () => {
    const mine = ++seq;
    try {
      const r = await api.terms(props.field, q);
      if (mine !== seq) return;
      terms.value = r.terms;
      message.value = r.terms.length
        ? `${r.terms.length} matching ${r.terms.length === 1 ? "term" : "terms"} found`
        : "No matching terms found. New terms are added in CollectionSpace.";
    } catch (e) {
      if (mine === seq) message.value = (e as Error).message;
    }
  }, 250);
}

function choose(t: Term) {
  text.value = t.displayName;
  open.value = false;
  emit("update:modelValue", t.refName);
}

function onBlur() {
  // wait so a click on a suggestion counts first
  setTimeout(() => {
    open.value = false;
    if (!text.value.trim()) {
      if (props.modelValue) emit("update:modelValue", "");
    } else if (text.value !== displayName(props.modelValue)) {
      text.value = displayName(props.modelValue); // free text is never saved
    }
  }, 150);
}

function onKey(e: KeyboardEvent) {
  if (!open.value || !terms.value.length) return;
  if (e.key === "ArrowDown") { active.value = Math.min(terms.value.length - 1, active.value + 1); e.preventDefault(); }
  else if (e.key === "ArrowUp") { active.value = Math.max(0, active.value - 1); e.preventDefault(); }
  else if (e.key === "Enter" && active.value >= 0) { choose(terms.value[active.value]); e.preventDefault(); }
  else if (e.key === "Escape") open.value = false;
}

const sourceLabel = (s: string) => (s === "person" ? "Persons" : s === "organization" ? "Organizations" : s);
</script>

<template>
  <label class="field">
    <span>{{ label }}</span>
    <div class="ac">
      <input
        v-model="text"
        type="text"
        autocomplete="off"
        :disabled="disabled"
        :placeholder="`Search ${label.toLowerCase()}…`"
        :title="modelValue ? `refName: ${modelValue}` : ''"
        role="combobox"
        :aria-expanded="open"
        @input="onInput"
        @blur="onBlur"
        @keydown="onKey"
      />
      <div v-if="open" class="ac-list" role="listbox">
        <div class="ac-msg">{{ message }}</div>
        <template v-for="g in groups" :key="g.source">
          <div class="ac-group">{{ sourceLabel(g.source) }}</div>
          <div
            v-for="{ t, i } in g.items"
            :key="t.refName"
            class="ac-item"
            :class="{ active: i === active }"
            role="option"
            @mousedown.prevent="choose(t)"
          >{{ t.displayName }}</div>
        </template>
      </div>
    </div>
  </label>
</template>
