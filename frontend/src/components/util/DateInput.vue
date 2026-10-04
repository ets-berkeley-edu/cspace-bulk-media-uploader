<template>
  <div :id="`${id}-container`" :class="{'field-edited': source?.edited}">
    <label class="field-label" :for="id">Date <em v-if="source" class="field-state">{{ source.text }}</em></label>
    <v-text-field
      :id="id"
      v-model="text"
      aria-label="Date"
      :disabled="disabled"
      hide-details
      placeholder="e.g. 2026-08-30, 1920s, circa 1850"
      @change="commit"
      @input="onInput"
      @keydown.enter.prevent="commit"
    />
    <span aria-live="polite" class="field-note" :class="{bad: note === CANNOT_INTERPRET}">{{ note }}</span>
    <button
      v-if="source?.edited && !disabled"
      :id="`${id}-use-exif-btn`"
      class="field-note link-btn"
      type="button"
      @click="useExif"
    >
      Use EXIF date
    </button>
  </div>
</template>

<script setup lang="ts">
import type {PropType} from 'vue'
import {computed, onBeforeUnmount, ref, watch} from 'vue'
import type {DateGroup} from '@/lib/dates'
import {describeDate} from '@/lib/dates'
import {api} from '@/api'

type Parsed = {value: string, ok: boolean, group: DateGroup}

/**
 * The Date field (design: Structured dates): the text is parsed by CollectionSpace's own parser as the user
 * types, and the earliest and latest dates show under the field. The row's check decides whether it blocks.
 * Like the other derived values, it says where it came from: "(from EXIF)" while it holds the date read from
 * the file, and "(edited — EXIF date …)" or "(cleared — EXIF date …)" with a link back once changed.
 */
const props = defineProps({
  disabled: {
    required: false,
    type: Boolean
  },
  exif: {
    default: undefined,
    required: false,
    type: String
  },
  id: {
    required: true,
    type: String
  },
  modelValue: {
    required: true,
    type: String
  },
  parsed: {
    default: undefined,
    required: false,
    type: Object as PropType<Parsed>
  }
})
const emit = defineEmits<{'update:modelValue': [value: string]}>()

const CANNOT_INTERPRET = 'Can\'t interpret this date'
const isPending = ref(false)
const preview = ref<Parsed | null>(null)
const text = ref(props.modelValue)
let timer: ReturnType<typeof setTimeout> | undefined
let seq = 0

watch(() => props.modelValue, value => {
  text.value = value
})
onBeforeUnmount(() => clearTimeout(timer))

const onInput = () => {
  clearTimeout(timer)
  const t = text.value.trim()
  if (!t || t === props.parsed?.value) {
    isPending.value = false
    preview.value = null
    return
  }
  isPending.value = true
  timer = setTimeout(async () => {
    const mine = ++seq
    try {
      const r = await api.parseDate(t)
      if (mine === seq) {
        preview.value = {value: t, ...r}
      }
    } catch {
      if (mine === seq) {
        preview.value = null
      }
    } finally {
      if (mine === seq) {
        isPending.value = false
      }
    }
  }, 300)
}

const commit = () => {
  if (text.value.trim() !== props.modelValue) {
    emit('update:modelValue', text.value.trim())
  }
}

/** Where the value came from, for a file whose EXIF had a date. */
const source = computed(() => {
  if (!props.exif) {
    return null
  }
  if (props.modelValue === props.exif) {
    return {text: '(from EXIF)', edited: false}
  }
  return {text: props.modelValue ? `(edited — EXIF date ${props.exif})` : `(cleared — EXIF date ${props.exif})`, edited: true}
})

const useExif = () => {
  text.value = props.exif ?? ''
  preview.value = null
  emit('update:modelValue', text.value)
}

const note = computed(() => {
  const t = text.value.trim()
  if (!t) {
    return ''
  }
  if (isPending.value) {
    return 'Checking the date with CollectionSpace…'
  }
  const p = preview.value?.value === t ? preview.value : props.parsed?.value === t ? props.parsed : null
  if (!p) {
    return ''
  }
  return p.ok ? describeDate(p.group) : CANNOT_INTERPRET
})
</script>
