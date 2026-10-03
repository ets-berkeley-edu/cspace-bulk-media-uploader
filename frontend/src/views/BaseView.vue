<template>
  <v-app>
    <a
      id="skip-to-content-link"
      class="sr-only sr-only-focusable"
      href="#content"
    >
      Skip to main content
    </a>
    <v-app-bar id="app-bar" color="topbar" density="comfortable">
      <div class="align-center d-flex flex-grow-1 page-width px-4">
        <div id="app-title" class="mr-4 text-h6 text-no-wrap">Bulk Media Uploader</div>
        <div id="tenant-name" class="font-weight-bold mr-3">{{ currentUser.tenant.name }}</div>
        <EnvironmentChip class="mr-3" />
        <v-chip
          v-if="editWhy"
          id="view-only"
          color="warning"
          size="small"
          :title="editWhy"
          variant="flat"
        >
          View only: your account can't create and update Media records
        </v-chip>
        <v-spacer />
        <v-menu>
          <template #activator="{props: menuProps}">
            <v-btn
              id="btn-main-menu"
              :aria-label="`Signed in as ${currentUser.user}. Menu`"
              :append-icon="mdiMenuDown"
              variant="outlined"
              v-bind="menuProps"
            >
              {{ currentUser.user }}
            </v-btn>
          </template>
          <v-list density="comfortable" role="menu">
            <v-list-item
              id="menu-item-dark-mode"
              link
              role="menuitem"
              @click="toggleColorScheme"
            >
              <v-list-item-title>{{ theme.global.current.value.dark ? 'Light' : 'Dark' }} mode</v-list-item-title>
            </v-list-item>
            <v-list-item
              id="menu-item-sign-out"
              :append-icon="mdiLogout"
              link
              role="menuitem"
              @click="signOut"
            >
              <v-list-item-title>Sign out</v-list-item-title>
            </v-list-item>
          </v-list>
        </v-menu>
      </div>
    </v-app-bar>
    <v-main id="content">
      <Snackbar />
      <div class="page-width pb-16 pt-4 px-4">
        <p id="app-description" class="mb-3 text-body-2 text-medium-emphasis">
          Prototype · creates Media records, files, Objects and Relations in CollectionSpace using your own account.
        </p>
        <!-- Demo tools: only in demo builds (lib/demo.ts). In a production build its code isn't in the bundle. -->
        <div v-if="DemoPane" class="legacy">
          <component :is="DemoPane" @jobs-deleted="session.jobsDeleted" />
        </div>
        <v-alert
          v-if="session.notice"
          id="notice"
          class="mb-3"
          closable
          close-label="Close this message"
          density="compact"
          role="status"
          type="info"
          variant="tonal"
          @click:close="session.notice = ''"
        >
          {{ session.notice }}
        </v-alert>
        <div class="align-center d-flex flex-wrap">
          <v-tabs
            id="tabs"
            aria-label="Bulk Media Uploader pages"
            class="flex-grow-1"
            color="primary"
          >
            <v-tab
              v-for="tab in tabs"
              :id="`tab-${tab.id}`"
              :key="tab.id"
              :to="tab.path"
            >
              {{ tab.title }}
            </v-tab>
          </v-tabs>
          <span id="new-job" :title="editWhy">
            <v-btn
              id="btn-new-job"
              color="primary"
              :disabled="!!editWhy"
              :prepend-icon="mdiPlus"
              @click="session.newJob"
            >
              New job
            </v-btn>
          </span>
        </div>
        <v-divider class="mb-4" />
        <!-- Create / edit job stays alive behind the other tabs, so its uploads and unsaved state go on. -->
        <router-view v-slot="{Component}">
          <keep-alive include="EditJob">
            <component :is="Component" />
          </keep-alive>
        </router-view>
      </div>
    </v-main>
  </v-app>
</template>

<script setup lang="ts">
import {computed, defineAsyncComponent} from 'vue'
import {mdiLogout, mdiMenuDown, mdiPlus} from '@mdi/js'
import {useRouter} from 'vue-router'
import {useTheme} from 'vuetify'
import type {Me} from '@/types'
import EnvironmentChip from '@/components/util/EnvironmentChip.vue'
import Snackbar from '@/components/util/Snackbar.vue'
import {alertScreenReader, putFocusNextTick, rememberDarkMode} from '@/lib/utils'
import {editBlocked} from '@/lib/status'
import {logOut} from '@/api/auth'
import {useContextStore} from '@/stores/context'
import {useJobEditSessionStore} from '@/stores/job-edit-session'

const DemoPane = import.meta.env.MODE !== 'production' ? defineAsyncComponent(() => import('@/components/DemoPane.vue')) : null

const contextStore = useContextStore()
// This page is only reached signed in (src/auth.ts), and is left before signing out clears the user.
const currentUser = contextStore.currentUser as Me
const router = useRouter()
const session = useJobEditSessionStore()
const theme = useTheme()

const tabs = [
  {id: 'job', title: 'Create / edit job', path: '/job'},
  {id: 'drafts', title: 'Drafts', path: '/drafts'},
  {id: 'queue', title: 'Job queue', path: '/queue'},
  {id: 'finished', title: 'Finished jobs', path: '/finished'}
]

// Without create and update on Media the user can view jobs but not create or edit them (design: Permissions in the UI).
const editWhy = computed(() => editBlocked(currentUser.perms))

const signOut = () => {
  logOut().catch(() => undefined).then(() => {
    // The user first: the sign-in page sends a signed-in user back to the app.
    contextStore.setCurrentUser(null)
    session.$reset()
    router.push('/login').then(() => alertScreenReader('Signed out'))
  })
}

const toggleColorScheme = () => {
  const dark = !theme.global.current.value.dark
  theme.change(dark ? 'dark' : 'light')
  rememberDarkMode(dark)
  alertScreenReader(`${dark ? 'Dark' : 'Light'} mode`)
  putFocusNextTick('btn-main-menu', {scroll: false})
}
</script>
