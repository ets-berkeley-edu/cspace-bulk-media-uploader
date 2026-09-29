<script setup lang="ts">
/**
 * A document's thumbnail (design: User interface, Thumbnails): the local preview in the browser that added the
 * file; otherwise the stored thumbnail, or CollectionSpace's own derivative once the file is there, both served
 * by the web app after checking the session. A protected file shows a locked placeholder to everyone else;
 * audio, video and 3D files show a type icon. Clicking opens a larger view.
 */
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { thumbnailUrl } from "../api";
import { fileKind } from "../lib/files";
import type { Row } from "../types";

const props = defineProps<{ jobId?: string | null; row: Row; preview?: string }>();
const failed = ref(false);
const large = ref(false);
const kind = computed(() => fileKind(props.row.file));
const inCollectionSpace = computed(() => props.row.result?.steps?.upload?.s === "done");
const locked = computed(() => !props.preview && !!props.row.protected && !inCollectionSpace.value);
// Ask the server only when there can be something: a staged image, or a file already in CollectionSpace.
const remote = computed(() => !props.preview && !locked.value && !!props.jobId && kind.value.image
  && (inCollectionSpace.value || props.row.upload.s === "done"));
const src = computed(() => props.preview ?? (remote.value && !failed.value ? thumbnailUrl(props.jobId!, props.row.n, props.row.v ?? 0) : ""));
const largeSrc = computed(() => props.preview ?? (props.jobId ? thumbnailUrl(props.jobId, props.row.n, props.row.v ?? 0, true) : ""));
watch(() => [props.row.v, props.row.result?.steps?.upload?.s], () => { failed.value = false; });

function onKey(e: KeyboardEvent) { if (e.key === "Escape") large.value = false; }
watch(large, (open) => (open ? window.addEventListener("keydown", onKey) : window.removeEventListener("keydown", onKey)));
onBeforeUnmount(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <div class="thumb" :class="{ locked, clickable: !!src }" :title="locked ? 'Protected file: only the person who added it sees a preview' : kind.label">
    <button v-if="src" type="button" class="thumb-btn" :aria-label="`Larger view of ${row.file}`" @click="large = true">
      <img :src="src" alt="" loading="lazy" @error="failed = true" /></button>
    <span v-else-if="locked" aria-label="Protected file">🔒</span>
    <span v-else :aria-label="kind.label">{{ kind.icon }}</span>
  </div>
  <Teleport to="body">
    <div v-if="large" class="lightbox" role="dialog" :aria-label="`Larger view of ${row.file}`" @click.self="large = false">
      <figure>
        <img :src="largeSrc" :alt="row.file" />
        <figcaption>{{ row.file }} <button type="button" @click="large = false">Close</button></figcaption>
      </figure>
    </div>
  </Teleport>
</template>
