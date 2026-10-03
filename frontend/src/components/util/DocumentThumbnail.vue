<template>
  <div
    class="thumb"
    :class="{locked}"
    :title="locked ? 'Protected file: only the person who added it sees a preview' : kind.label"
  >
    <button
      v-if="src"
      :id="`thumbnail-${row.n}-btn`"
      :aria-label="`Larger view of ${row.file}`"
      class="thumb-btn"
      type="button"
      @click="isLargeOpen = true"
    >
      <img
        alt=""
        loading="lazy"
        :src="src"
        @error="hasFailed = true"
      >
    </button>
    <v-icon
      v-else-if="locked"
      aria-label="Protected file"
      :icon="mdiLock"
      size="small"
    />
    <span v-else :aria-label="kind.label">{{ kind.icon }}</span>
    <v-dialog
      v-if="isLargeOpen"
      v-model="isLargeOpen"
      :aria-label="`Larger view of ${row.file}`"
      content-class="lightbox"
      max-width="900"
    >
      <v-card>
        <v-card-text class="pa-3">
          <img :alt="row.file" class="lightbox-img" :src="largeSrc">
          <div class="align-center d-flex justify-space-between mt-2">
            <span>{{ row.file }}</span>
            <v-btn :id="`thumbnail-${row.n}-close-btn`" variant="outlined" @click="isLargeOpen = false">Close</v-btn>
          </div>
        </v-card-text>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup lang="ts">
import type {PropType} from 'vue'
import {computed, ref, watch} from 'vue'
import {mdiLock} from '@mdi/js'
import type {Row} from '@/types'
import {fileKind} from '@/lib/files'
import {thumbnailUrl} from '@/api'

/**
 * A document's thumbnail (design: User interface, Thumbnails): the local preview in the browser that added the
 * file; otherwise the stored thumbnail, or CollectionSpace's own derivative once the file is there, both served
 * by the web app after checking the session. A protected file shows a lock to everyone else; audio, video and 3D
 * files show a type icon. Clicking opens a larger view.
 */
const props = defineProps({
  jobId: {
    default: undefined,
    required: false,
    type: String as PropType<string | null>
  },
  preview: {
    default: undefined,
    required: false,
    type: String
  },
  row: {
    required: true,
    type: Object as PropType<Row>
  }
})

const hasFailed = ref(false)
const isLargeOpen = ref(false)
const kind = computed(() => fileKind(props.row.file))
const inCollectionSpace = computed(() => props.row.result?.steps?.upload?.s === 'done')
const locked = computed(() => !props.preview && !!props.row.protected && !inCollectionSpace.value)
// Ask the server only when there can be something: a staged image, or a file already in CollectionSpace.
const remote = computed(() => !props.preview && !locked.value && !!props.jobId && kind.value.image
  && (inCollectionSpace.value || props.row.upload.s === 'done'))
const src = computed(() => props.preview ?? (remote.value && !hasFailed.value ? thumbnailUrl(props.jobId!, props.row.n, props.row.v ?? 0) : ''))
const largeSrc = computed(() => props.preview ?? (props.jobId ? thumbnailUrl(props.jobId, props.row.n, props.row.v ?? 0, true) : ''))

watch(() => [props.row.v, props.row.result?.steps?.upload?.s], () => {
  hasFailed.value = false
})
</script>

<style scoped>
.thumb {
  align-items: center;
  background: rgb(var(--v-theme-surface-light));
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 4px;
  display: flex;
  font-size: 10px;
  height: 42px;
  justify-content: center;
  opacity: 1;
  overflow: hidden;
  width: 56px;
}
.thumb.locked {
  background: rgba(var(--v-theme-error), 0.12);
  color: rgb(var(--v-theme-error));
}
.thumb-btn {
  cursor: zoom-in;
  height: 100%;
  width: 100%;
}
.thumb-btn img {
  display: block;
  height: 100%;
  object-fit: cover;
  width: 100%;
}
.lightbox-img {
  display: block;
  margin: 0 auto;
  max-height: 75vh;
  max-width: 100%;
}
</style>
