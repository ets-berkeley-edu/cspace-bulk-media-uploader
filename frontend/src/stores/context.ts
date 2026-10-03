import {defineStore} from 'pinia'
import type {ScreenReaderAlert} from '@/types'

/** State the whole app shares, as in BOA's context store. It starts with the screen reader announcement. */
export const useContextStore = defineStore('context', {
  state: () => ({
    screenReaderAlert: {
      message: '',
      politeness: 'polite'
    } as ScreenReaderAlert
  }),
  actions: {
    setScreenReaderAlert(screenReaderAlert: ScreenReaderAlert) {
      this.screenReaderAlert = {
        message: screenReaderAlert.message,
        politeness: screenReaderAlert.politeness || 'polite'
      }
    }
  }
})
