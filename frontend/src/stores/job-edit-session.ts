import {defineStore} from 'pinia'
import {submitMessage} from '@/lib/schedule'
import router from '@/router'
import type {Job} from '@/types'
import {api} from '@/api'

type ListTab = 'drafts' | 'queue'

/**
 * What the tabs share about the job being worked on: the draft open in Create / edit job, the job each list tab is
 * previewing, and the message shown above the tabs. It lives here, not in a page, because the tabs are routes.
 */
export const useJobEditSessionStore = defineStore('jobEditSession', {
  state: () => ({
    // Changing it starts the editor afresh.
    editorKey: 0,
    // The draft open in Create / edit job; null for a new, empty job.
    jobId: null as string | null,
    mode: 'edit' as 'edit' | 'preview',
    notice: '',
    // The job each list tab is previewing, shown inside that tab (design: Drafts, scheduling and the job queue).
    // Previewing never touches the draft open in Create / edit job.
    previewing: {
      drafts: null,
      queue: null
    } as Record<ListTab, string | null>,
    takeOverSince: null as number | null
  }),
  actions: {
    /** Demo tools deleted every job: nothing is open any more. */
    jobsDeleted(message: string) {
      this.jobId = null
      this.previewing.drafts = null
      this.previewing.queue = null
      this.editorKey++
      this.notice = message
    },
    /** Leaving the job in the editor: stop editing it, so others can edit it without taking over. */
    async leaveCurrent(nextId: string | null) {
      if (this.jobId && this.jobId !== nextId) {
        await api.closeJob(this.jobId).catch(() => undefined)
      }
    },
    async newJob() {
      await this.leaveCurrent(null)
      this.jobId = null
      this.mode = 'edit'
      this.takeOverSince = null
      this.editorKey++
      this.notice = ''
      await router.push('/job')
    },
    /** Open a job for editing, or (from a list tab) preview it inside that tab. */
    async openJob(id: string, mode: 'edit' | 'preview' = 'edit', takeOverSince?: number, from?: ListTab) {
      if (mode === 'preview') {
        if (from) {
          this.previewing[from] = id
        }
        return
      }
      // Opening a job for editing ends any preview of it: it's about to change.
      if (this.previewing.drafts === id) {
        this.previewing.drafts = null
      }
      if (this.previewing.queue === id) {
        this.previewing.queue = null
      }
      await this.leaveCurrent(id)
      this.notice = ''
      this.jobId = id
      this.mode = mode
      this.takeOverSince = takeOverSince ?? null
      this.editorKey++
      await router.push('/job')
    },
    /** Submit job succeeded: say when it runs, from the response's plan (design: Job scheduling). */
    async scheduled(job: Job) {
      this.jobId = null // submitting already took it out of Drafts
      const schedule = await api.getSchedule().catch(() => null) // only to tell the development setting apart
      await this.newJob()
      this.notice = submitMessage(job, {alwaysRunTime: !!schedule?.alwaysRunTime})
      await router.push('/queue')
    }
  }
})
