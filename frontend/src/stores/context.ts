import {defineStore} from 'pinia'
import {ApiError} from '@/lib/axios-utils'
import {alertScreenReader, putFocusNextTick} from '@/lib/utils'
import type {BmuConfig, Me, ScreenReaderAlert, SnackbarState} from '@/types'
import {getConfig} from '@/api/config'
import {getMyProfile} from '@/api/auth'

/** State the whole app shares, as in the context store of BOA, Damien and Diablo. */
export const useContextStore = defineStore('context', {
  state: () => ({
    config: {
      label: '',
      realCollectionSpace: false,
      tenants: []
    } as BmuConfig,
    // The signed-in user, with their tenant and permissions; null when nobody is signed in.
    currentUser: null as Me | null,
    screenReaderAlert: {
      message: '',
      politeness: 'polite'
    } as ScreenReaderAlert,
    snackbar: {
      color: 'primary',
      text: undefined,
      timeout: 8000
    } as SnackbarState,
    snackbarShow: false
  }),
  actions: {
    /**
     * Before the app is shown (main.ts): which environment this is, and who is signed in, if anyone. Neither
     * failing stops the app: without a label none is shown, and without a user the sign-in page is.
     */
    async init() {
      const [config, currentUser] = await Promise.all([
        getConfig().catch(() => ({label: '', realCollectionSpace: false, tenants: []})),
        getMyProfile().catch((error: Error) => {
          if (!(error instanceof ApiError && error.status === 401)) {
            this.snackbarReportError(error.message)
          }
          return null
        })
      ])
      this.config = {...config, tenants: config.tenants || []}
      this.currentUser = currentUser
    },
    /** A page is ready: name it in the browser's title, and put the keyboard at its heading (or another element). */
    loadingComplete(pageTitle?: string, alert?: string, putFocusElementId = 'page-title') {
      const environment = this.config.label ? ` · ${this.config.label}` : ''
      document.title = `${pageTitle ? `${pageTitle} | ` : ''}BMU${environment}`
      if (alert) {
        alertScreenReader(alert)
      }
      putFocusNextTick(putFocusElementId, {scroll: false})
    },
    setCurrentUser(currentUser: Me | null) {
      this.currentUser = currentUser
    },
    setScreenReaderAlert(screenReaderAlert: ScreenReaderAlert) {
      this.screenReaderAlert = {
        message: screenReaderAlert.message,
        politeness: screenReaderAlert.politeness || 'polite'
      }
    },
    snackbarClose() {
      this.snackbarShow = false
      this.snackbar.text = undefined
      alertScreenReader('Message closed')
    },
    snackbarOpen(text: string, color?: string) {
      this.snackbar.text = text
      this.snackbar.color = color || 'primary'
      this.snackbarShow = true
    },
    snackbarReportError(text: string) {
      this.snackbar.text = text
      this.snackbar.color = 'error'
      this.snackbarShow = true
    }
  }
})
