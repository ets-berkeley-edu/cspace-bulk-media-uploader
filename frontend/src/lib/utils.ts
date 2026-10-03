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
      if (typeof document === 'undefined') {
        // The page is gone (a test that ended meanwhile)
        clearInterval(putFocus)
        return
      }
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

const DARK_MODE_KEY = 'prefersDarkMode'

/**
 * Light or dark, as Damien decides it: the choice made with the user menu's Dark mode item, remembered in this
 * browser; until one is made, the system's setting.
 */
export function prefersDarkMode(): boolean {
  let stored: string | null = null
  try {
    stored = window.localStorage.getItem(DARK_MODE_KEY)
  } catch {
    // No storage (a private window, say): the system's setting decides.
  }
  if (stored) {
    return stored === 'true'
  }
  return !!window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
}

export function rememberDarkMode(dark: boolean) {
  try {
    window.localStorage.setItem(DARK_MODE_KEY, `${dark}`)
  } catch {
    // No storage: the choice lasts until the page is reloaded.
  }
}
