import axios from 'axios'
import type {Me} from '@/types'

/** Who is signed in. Rejects with a 401 ApiError when nobody is. */
export function getMyProfile(): Promise<Me> {
  return axios.get('/api/me').then(response => response.data)
}

/**
 * Sign in with a CollectionSpace account, at the museum chosen (left out when the BMU serves one). The session is an
 * httpOnly cookie; the password is not kept here.
 */
export function logIn(username: string, password: string, tenant?: string): Promise<Me> {
  return axios.post('/api/login', {username, password, ...(tenant ? {tenant} : {})}).then(response => response.data)
}

export function logOut(): Promise<void> {
  return axios.post('/api/logout').then(() => undefined)
}
