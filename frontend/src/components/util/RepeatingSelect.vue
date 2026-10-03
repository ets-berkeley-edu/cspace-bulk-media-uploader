<template>
  <div :id="`${id}-container`" :class="{'field-preset': preset}">
    <span :id="`${id}-label`" class="field-label">{{ label }}<PresetChip v-if="preset" /></span>
    <div v-for="(value, index) in draft" :key="index" class="align-center d-flex mb-1">
      <select
        :id="`${id}-${index}`"
        :aria-label="`${label} ${index + 1}`"
        class="flex-grow-1 native-select"
        :disabled="disabled"
        :value="value"
        @change="event => set(index, (event.target as HTMLSelectElement).value)"
      >
        <option value="">—</option>
        <option
          v-for="option in all"
          :key="option.value"
          :disabled="option.value !== value && draft.includes(option.value)"
          :value="option.value"
        >
          {{ option.label }}
        </option>
      </select>
      <v-btn
        v-if="draft.length > 1 && !disabled"
        :id="`${id}-${index}-remove-btn`"
        :aria-label="`Remove this ${word}`"
        class="ml-1 x-btn"
        density="comfortable"
        :icon="mdiClose"
        size="small"
        variant="text"
        @click="() => remove(index)"
      />
    </div>
    <button
      v-if="canAdd && !disabled"
      :id="`${id}-add-btn`"
      class="link link-btn text-caption"
      type="button"
      @click="draft.push('')"
    >
      + Add an additional {{ word }}
    </button>
  </div>
</template>

<script setup lang="ts">
import type {PropType} from 'vue'
import {computed, ref, watch} from 'vue'
import {mdiClose} from '@mdi/js'
import type {Option} from '@/types'
import PresetChip from '@/components/util/PresetChip.vue'
import {displayName} from '@/lib/refname'

/**
 * A repeating option picker, like CollectionSpace's for repeating fields (media type, language): one dropdown per
 * value, "+ Add an additional …" and a button to remove one. Only existing values can be chosen.
 */
const props = defineProps({
  disabled: {
    required: false,
    type: Boolean
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
    type: Array as PropType<string[]>
  },
  options: {
    required: true,
    type: Array as PropType<Option[]>
  },
  preset: {
    required: false,
    type: Boolean
  },
  // What one value is called: "type", "language".
  word: {
    required: true,
    type: String
  }
})
const emit = defineEmits<{'update:modelValue': [value: string[]]}>()

const draft = ref<string[]>([])
watch(() => props.modelValue, value => {
  draft.value = value.length ? [...value] : ['']
}, {immediate: true})

/** The options, plus any current value missing from them (e.g. before the vocabulary has loaded). */
const all = computed(() => {
  const known = new Set(props.options.map(o => o.value))
  const extra = props.modelValue.filter(v => v && !known.has(v)).map(v => ({value: v, label: displayName(v)}))
  return [...props.options, ...extra]
})
const canAdd = computed(() => draft.value.some(v => v) && !draft.value.some(v => !v))

const commit = () => {
  const out = [...new Set(draft.value.filter(v => v))]
  if (JSON.stringify(out) !== JSON.stringify(props.modelValue)) {
    emit('update:modelValue', out)
  }
}

const set = (index: number, value: string) => {
  draft.value[index] = value
  commit()
}

const remove = (index: number) => {
  draft.value.splice(index, 1)
  if (!draft.value.length) {
    draft.value.push('')
  }
  commit()
}
</script>
