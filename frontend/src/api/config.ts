import axios from 'axios'
import type {BmuConfig} from '@/types'

/** Which environment this is (no sign-in needed): its label, and whether its CollectionSpace is a real server. */
export function getConfig(): Promise<BmuConfig> {
  return axios.get('/api/env').then(response => response.data)
}
