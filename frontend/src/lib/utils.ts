/** Accessibility helpers, from BOA (src/lib/utils.ts), so the BMU's screens announce and move focus the same way. */
import {nextTick} from 'vue'
import type {ScreenReaderAlert} from '@/types'
import {useContextStore} from '@/stores/context'

let $_screenReaderAlertExpiry: number

/**
 * Say something to screen reader users through the page's live region (App.vue's #announcer). The message is
 * cleared after five seconds unless persistent, so the same message can be announced again later.
 */
export function alertScreenReader(message: string, persistent?: boolean, politeness?: ScreenReaderAlert['politeness']) {
  clearScreenReaderAlert()
  nextTick(() => {
    useContextStore().setScreenReaderAlert({message, politeness})
    window.clearInterval($_screenReaderAlertExpiry)
    if (!persistent) {
      $_screenReaderAlertExpiry = window.setInterval(clearScreenReaderAlert, 5000)
    }
  })
}

const clearScreenReaderAlert = () => {
  window.clearInterval($_screenReaderAlertExpiry)
  useContextStore().setScreenReaderAlert({message: ''})
}

/**
 * Move keyboard focus to the element with this id (or to cssSelector inside it) once it exists, trying for up to
 * three seconds: for content that appears after a request or a transition.
 */
export function putFocusNextTick(
  id: string,
  {scroll = true, scrollBlock = 'center', cssSelector = undefined}: {scroll?: boolean, scrollBlock?: ScrollLogicalPosition, cssSelector?: string} = {}
) {
  nextTick(() => {
    let counter = 0
    const putFocus = setInterval(() => {
      let el: HTMLElement | null = document.getElementById(id)
      el = el && cssSelector ? el.querySelector<HTMLElement>(cssSelector) : el
      if (el) {
        el.classList.add('scroll-margins')
        el.focus()
        if (scroll) {
          el.scrollIntoView({behavior: 'smooth', block: scrollBlock})
        }
      }
      if (el || ++counter > 5) {
        // Stop after success or six attempts
        clearInterval(putFocus)
      }
    }, 500)
  })
}
