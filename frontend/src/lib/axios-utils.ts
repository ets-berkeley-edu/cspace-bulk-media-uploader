import type {AxiosError, AxiosResponse, AxiosStatic} from 'axios'

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail: unknown = null) {
    super(message)
  }
}

// The sign-in check and the sign-in itself answer 401 as a matter of course; nobody was signed out.
const SKIP_SIGNED_OUT = ['/api/me', '/api/login']

const messageOf = (detail: unknown, status: number): string => {
  if (typeof detail === 'string') {
    return detail
  }
  if (detail && typeof detail === 'object' && 'message' in detail) {
    return String((detail as {message: unknown}).message)
  }
  if (Array.isArray(detail)) {
    return 'Some values aren\'t valid.'
  }
  return `Request failed (${status})`
}

/**
 * Set up axios for the BMU API, once, before the first request (main.ts; the unit tests' setup file).
 *
 * Every request carries X-BMU, which the API requires as its guard against cross-site requests: it is a default
 * here so that no call can leave it out. Use axios only for the BMU's own API (paths starting /api/). Files go to
 * S3 with their own request (lib/files.ts), which must not carry it. The session is an httpOnly cookie, sent by
 * the browser because the API is on the same origin.
 *
 * A failed request rejects with an ApiError holding the status and the API's message. A 401 while signed in means
 * the session ended (idle or absolute timeout): the app hears 'bmu-signed-out' and returns to the sign-in page
 * with the reason.
 */
export function initializeAxios(axios: AxiosStatic) {
  axios.defaults.headers.common['X-BMU'] = '1'
  axios.interceptors.response.use(
    (response: AxiosResponse) => response,
    (error: AxiosError) => {
      const response = error.response
      if (!response) {
        // No answer at all (network, or the request was cancelled)
        return Promise.reject(error)
      }
      const data = response.data
      const detail = data && typeof data === 'object' && 'detail' in data ? (data as {detail: unknown}).detail : null
      const apiError = new ApiError(response.status, messageOf(detail ?? null, response.status), detail ?? null)
      const path = (error.config?.url || '').split('?')[0]
      if (response.status === 401 && !SKIP_SIGNED_OUT.includes(path) && typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('bmu-signed-out', {detail: apiError.message}))
      }
      return Promise.reject(apiError)
    }
  )
}
