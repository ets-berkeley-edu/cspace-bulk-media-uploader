<template>
  <div :id="`${id}-container`" class="authority-input" :class="{'field-preset': preset}">
    <label class="field-label" :for="id">{{ label }}<PresetChip v-if="preset" /></label>
    <div class="position-relative">
      <v-text-field
        :id="id"
        v-model="text"
        :aria-controls="`${id}-options`"
        :aria-expanded="isOpen"
        autocomplete="off"
        :disabled="disabled"
        hide-details
        :placeholder="`Search ${label.toLowerCase()}…`"
        role="combobox"
        :title="modelValue ? `refName: ${modelValue}` : undefined"
        @blur="onBlur"
        @input="onInput"
        @keydown="onKey"
      />
      <div
        v-if="isOpen"
        :id="`${id}-options`"
        class="ac-list elevation-4"
        role="listbox"
      >
        <div class="ac-msg">{{ message }}</div>
        <div
          v-for="entry in entries"
          :id="entry.term ? `${id}-option-${entry.index}` : undefined"
          :key="entry.key"
          :aria-selected="entry.term ? entry.index === active : undefined"
          :class="entry.term ? {'ac-item': true, active: entry.index === active} : 'ac-group'"
          :role="entry.term ? 'option' : 'presentation'"
          @mousedown.prevent="() => entry.term && choose(entry.term)"
        >
          {{ entry.text }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type {PropType} from 'vue'
import {computed, ref, watch} from 'vue'
import type {Term} from '@/types'
import PresetChip from '@/components/util/PresetChip.vue'
import {displayName} from '@/lib/refname'
import {api} from '@/api'

/**
 * Autocomplete for an authority field. Only existing CollectionSpace terms can be chosen: the value is the term's
 * refName, the input shows only its display name. It searches as CollectionSpace's own UI does, after the tenant's
 * find delay and minimum length, and lists the terms by source.
 */
const props = defineProps({
  disabled: {
    required: false,
    type: Boolean
  },
  field: {
    required: true,
    type: String
  },
  id: {
    required: true,
    type: String
  },
  label: {
    required: true,
    type: String
  },
  modelValue: {
    required: true,
    type: String
  },
  // The value came from the row's handling preset (design: Handling per document, marked as presets).
  preset: {
    required: false,
    type: Boolean
  },
  // The tenant's CollectionSpace UI timing (its profile's autocompleteFindDelay and autocompleteMinLength).
  timing: {
    default: undefined,
    required: false,
    type: Object as PropType<{findDelayMs: number, minLength: number}>
  }
})
const emit = defineEmits<{'update:modelValue': [value: string]}>()

const active = ref(-1)
const isOpen = ref(false)
const message = ref('')
const terms = ref<Term[]>([])
const text = ref(displayName(props.modelValue))
let timer: ReturnType<typeof setTimeout> | undefined
let seq = 0
// cspace-ui's defaults are 500 ms and 3 characters.
const findDelay = computed(() => props.timing?.findDelayMs ?? 500)
const minLength = computed(() => props.timing?.minLength ?? 3)

watch(() => props.modelValue, value => {
  text.value = displayName(value)
})

const sourceLabel = (source: string) => (source === 'person' ? 'Persons' : source === 'organization' ? 'Organizations' : source)

type Entry = {key: string, text: string, term?: Term, index: number}
/** The list as shown: the terms in the order they came, under a heading for each source. */
const entries = computed(() => {
  const bySource = new Map<string, Entry[]>()
  terms.value.forEach((term, index) => {
    if (!bySource.has(term.source)) {
      bySource.set(term.source, [{key: `source-${term.source}`, text: sourceLabel(term.source), index: -1}])
    }
    bySource.get(term.source)!.push({key: term.refName, text: term.displayName, term, index})
  })
  return [...bySource.values()].flat()
})

const onInput = () => {
  isOpen.value = true
  active.value = -1
  clearTimeout(timer)
  const q = text.value.trim()
  if (q.length < minLength.value) {
    terms.value = []
    message.value = `Continue typing to find matching terms (${minLength.value}+ characters)`
    return
  }
  message.value = 'Searching…'
  timer = setTimeout(async () => {
    const mine = ++seq
    try {
      const r = await api.terms(props.field, q)
      if (mine !== seq) {
        return
      }
      terms.value = r.terms
      const total = r.total ?? r.terms.length
      message.value = r.message ? r.message
        : r.more ? `${total} matching terms; showing the first ${r.terms.length}. Continue typing to narrow the results.`
          : r.terms.length ? `${total} matching ${total === 1 ? 'term' : 'terms'} found`
            : 'No matching terms found. New terms are added in CollectionSpace.'
    } catch (e) {
      if (mine === seq) {
        message.value = (e as Error).message
      }
    }
  }, findDelay.value)
}

const choose = (term: Term) => {
  text.value = term.displayName
  isOpen.value = false
  emit('update:modelValue', term.refName)
}

const onBlur = () => {
  // Wait, so that a click on a suggestion counts first.
  setTimeout(() => {
    isOpen.value = false
    if (!text.value.trim()) {
      if (props.modelValue) {
        emit('update:modelValue', '')
      }
    } else if (text.value !== displayName(props.modelValue)) {
      text.value = displayName(props.modelValue) // free text is never saved
    }
  }, 150)
}

const onKey = (event: KeyboardEvent) => {
  if (!isOpen.value || !terms.value.length) {
    return
  }
  if (event.key === 'ArrowDown') {
    active.value = Math.min(terms.value.length - 1, active.value + 1)
    event.preventDefault()
  } else if (event.key === 'ArrowUp') {
    active.value = Math.max(0, active.value - 1)
    event.preventDefault()
  } else if (event.key === 'Enter' && active.value >= 0) {
    choose(terms.value[active.value])
    event.preventDefault()
  } else if (event.key === 'Escape') {
    isOpen.value = false
  }
}
</script>

<style scoped>
.ac-list {
  background: rgb(var(--v-theme-surface));
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 4px;
  font-size: 0.8125rem;
  left: 0;
  margin-top: 2px;
  max-height: 240px;
  overflow-y: auto;
  position: absolute;
  right: 0;
  top: 100%;
  z-index: 30;
}
.ac-group {
  font-size: 0.6875rem;
  font-weight: 600;
  opacity: var(--v-medium-emphasis-opacity);
  padding: 4px 10px 2px;
}
.ac-item {
  cursor: pointer;
  padding: 4px 10px;
}
.ac-item:hover,
.ac-item.active {
  background: rgba(var(--v-theme-primary), 0.12);
  color: rgb(var(--v-theme-primary));
}
.ac-msg {
  font-size: 0.75rem;
  opacity: var(--v-medium-emphasis-opacity);
  padding: 6px 10px;
}
</style>
