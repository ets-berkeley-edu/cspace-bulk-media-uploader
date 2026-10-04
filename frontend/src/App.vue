<template>
  <div>
    <div
      id="screen-reader-alert"
      :aria-live="contextStore.screenReaderAlert.politeness"
      class="sr-only"
    >
      {{ contextStore.screenReaderAlert.message }}
    </div>
    <router-view />
  </div>
</template>

<script setup lang="ts">
import {onMounted, onUnmounted} from 'vue'
import {useRouter} from 'vue-router'
import {useTheme} from 'vuetify'
import {prefersDarkMode} from '@/lib/utils'
import {useContextStore} from '@/stores/context'
import {useJobEditSessionStore} from '@/stores/job-edit-session'

const contextStore = useContextStore()
const router = useRouter()
const theme = useTheme()

// Signed out while working (the session's idle or absolute timeout): back to the sign-in page, saying why.
const onSignedOut = (event: Event) => {
  if (contextStore.currentUser) {
    contextStore.setCurrentUser(null)
    useJobEditSessionStore().$reset()
    router.push({path: '/login', query: {m: (event as CustomEvent<string>).detail}})
  }
}

onMounted(() => {
  theme.change(prefersDarkMode() ? 'dark' : 'light')
  window.addEventListener('bmu-signed-out', onSignedOut)
})

onUnmounted(() => window.removeEventListener('bmu-signed-out', onSignedOut))
</script>

<style>
@import '@/assets/styles/bmu-global.css';
</style>
