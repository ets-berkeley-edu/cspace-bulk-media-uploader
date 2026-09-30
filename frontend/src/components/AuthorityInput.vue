<script setup lang="ts">
/**
 * Autocomplete for an authority field. Only existing CollectionSpace terms can be chosen: the value
 * is the term's refName, the input shows only its display name.
 */
import { computed, ref, watch } from "vue";
import { api } from "../api";
import { displayName } from "../lib/refname";
import type { Term } from "../types";

const props = defineProps<{ modelValue: string; field: string; label: string; disabled?: boolean;
  timing?: { findDelayMs: number; minLength: number };
  /** The value came from the row's handling preset (design: Handling per document, marked as presets). */
  preset?: boolean }>();
const emit = defineEmits<{ "update:modelValue": [value: string] }>();

const text = ref(displayName(props.modelValue));
const terms = ref<Term[]>([]);
const open = ref(false);
const message = ref("");
const active = ref(-1);
let timer: ReturnType<typeof setTimeout> | undefined;
// The tenant's CollectionSpace UI timing (its profile's autocompleteFindDelay and autocompleteMinLength);
// cspace-ui's defaults are 500 ms and 3 characters.
const findDelay = computed(() => props.timing?.findDelayMs ?? 500);
const minLength = computed(() => props.timing?.minLength ?? 3);
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
  if (q.length < minLength.value) {
    terms.value = [];
    message.value = `Continue typing to find matching terms (${minLength.value}+ characters)`;
    return;
  }
  message.value = "Searching…";
  timer = setTimeout(async () => {
    const mine = ++seq;
    try {
      const r = await api.terms(props.field, q);
      if (mine !== seq) return;
      terms.value = r.terms;
      const total = r.total ?? r.terms.length;
      message.value = r.message ? r.message
        : r.more ? `${total} matching terms; showing the first ${r.terms.length}. Continue typing to narrow the results.`
        : r.terms.length ? `${total} matching ${total === 1 ? "term" : "terms"} found`
        : "No matching terms found. New terms are added in CollectionSpace.";
    } catch (e) {
      if (mine === seq) message.value = (e as Error).message;
    }
  }, findDelay.value);
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
  <label class="field" :class="{ 'field-preset': preset }">
    <span>{{ label }}<em v-if="preset" class="preset-tag" title="Filled in automatically; it stays until you change it">PRESET</em></span>
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
