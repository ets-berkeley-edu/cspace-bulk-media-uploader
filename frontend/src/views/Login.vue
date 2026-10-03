<template>
  <v-app>
    <Snackbar />
    <v-main class="align-center d-flex flex-column">
      <div class="my-auto pa-4 w-100">
        <div class="login-column mx-auto">
          <div v-if="contextStore.config.label" class="d-flex justify-center mb-4">
            <EnvironmentChip />
          </div>
          <v-alert
            v-if="message"
            id="sign-in-notice"
            class="mb-4"
            density="compact"
            role="status"
            type="warning"
            variant="tonal"
          >
            {{ message }}
          </v-alert>
          <v-card class="pa-2" variant="outlined">
            <v-card-text>
              <h1 id="page-title" class="text-h5 mb-2" tabindex="-1">Bulk Media Uploader</h1>
              <p class="mb-5 text-body-2 text-medium-emphasis">
                Sign in with your CollectionSpace account. Your password is used only for your uploads and is deleted when they finish.
              </p>
              <v-form @submit.prevent="signIn">
                <label class="font-weight-medium text-body-2" for="username">CollectionSpace username</label>
                <v-text-field
                  id="username"
                  v-model="username"
                  autocomplete="username"
                  class="mb-4 mt-1"
                  :disabled="isSigningIn"
                  hide-details
                />
                <label class="font-weight-medium text-body-2" for="password">Password</label>
                <v-text-field
                  id="password"
                  v-model="password"
                  autocomplete="current-password"
                  class="mb-4 mt-1"
                  :disabled="isSigningIn"
                  hide-details
                  type="password"
                />
                <v-alert
                  v-if="error"
                  id="sign-in-error"
                  class="mb-4"
                  density="compact"
                  role="alert"
                  type="error"
                  variant="tonal"
                >
                  {{ error }}
                </v-alert>
                <v-btn
                  id="btn-sign-in"
                  block
                  color="primary"
                  :disabled="isSigningIn"
                  size="large"
                  type="submit"
                >
                  {{ isSigningIn ? 'Signing in…' : 'Sign in' }}
                </v-btn>
              </v-form>
            </v-card-text>
          </v-card>
        </div>
      </div>
    </v-main>
  </v-app>
</template>

<script setup lang="ts">
import {computed, onMounted, ref} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import EnvironmentChip from '@/components/util/EnvironmentChip.vue'
import Snackbar from '@/components/util/Snackbar.vue'
import {redirectAfterLogin} from '@/auth'
import {alertScreenReader, putFocusNextTick} from '@/lib/utils'
import {logIn} from '@/api/auth'
import {useContextStore} from '@/stores/context'

const contextStore = useContextStore()
const error = ref('')
const isSigningIn = ref(false)
const password = ref('')
const route = useRoute()
const router = useRouter()
const username = ref('')

// Why the sign-in page is showing, when the app sent the user here (their session ended).
const message = computed(() => (typeof route.query.m === 'string' ? route.query.m : ''))

onMounted(() => {
  contextStore.loadingComplete('Sign in', message.value || 'Bulk Media Uploader. Please sign in.', 'username')
})

const signIn = () => {
  const name = username.value.trim()
  if (!name || !password.value) {
    error.value = 'Enter your CollectionSpace username and password.'
    putFocusNextTick(name ? 'password' : 'username')
    return
  }
  isSigningIn.value = true
  error.value = ''
  logIn(name, password.value).then(
    currentUser => {
      contextStore.setCurrentUser(currentUser)
      alertScreenReader('Signed in')
      router.push(redirectAfterLogin(route.query.redirect))
    },
    (e: Error) => {
      error.value = e.message
      putFocusNextTick('password')
    }
  ).finally(() => {
    // The password is never kept longer than the attempt.
    password.value = ''
    isSigningIn.value = false
  })
}
</script>

<style scoped>
.login-column {
  max-width: 420px;
}
</style>
