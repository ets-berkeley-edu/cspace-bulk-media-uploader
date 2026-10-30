import type {NavigationGuard, NavigationGuardNext, RouteLocationNormalized} from 'vue-router'
import {useContextStore} from '@/stores/context'

const NO_REDIRECT = ['/', '/job', '/404']

/** The page to return to after signing in, unless it is where signing in leads anyway. */
export const returnTo = (to: RouteLocationNormalized) => (NO_REDIRECT.includes(to.path) ? undefined : to.fullPath)

const goToLogin = (to: RouteLocationNormalized, next: NavigationGuardNext) => {
  next({
    path: '/login',
    query: {
      redirect: returnTo(to)
    }
  })
}

/** Where to go after signing in: the page that was asked for, if it is one of the app's own. */
export function redirectAfterLogin(redirect: unknown): string {
  return typeof redirect === 'string' && /^\/(?!\/)/.test(redirect) ? redirect : '/'
}

/** Every page but the sign-in page needs a signed-in user; without one, sign in first and then come back. */
export const requiresAuthenticated: NavigationGuard = (to, from, next) => {
  return useContextStore().currentUser ? next() : goToLogin(to, next)
}
