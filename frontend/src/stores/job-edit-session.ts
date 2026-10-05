import {defineStore} from 'pinia'
import {submitMessage} from '@/lib/schedule'
import router from '@/router'
import type {Job} from '@/types'
import {api} from '@/api'

type ListTab = 'drafts' | 'queue'

// The name of Create / edit job's route (src/router.ts)
const EDIT_JOB = 'Create / edit job'

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
  getters: {
    /** The address of Create / edit job: with the open draft, so a reload or a bookmark reopens it. */
    jobPath: (state): string => (state.jobId ? `/job/${encodeURIComponent(state.jobId)}` : '/job')
  },
  actions: {
    /** The address names a draft that isn't the one open (a reload, a bookmark, Back or Forward): open it. */
    async adopt(id: string) {
      await this.leaveCurrent(id)
      this.jobId = id
      this.mode = 'edit'
      this.takeOverSince = null
      this.editorKey++
    },
    /** The editor created the job (a name was typed, or files were added): the address now names it. */
    async created(id: string) {
      this.jobId = id
      if (router.currentRoute.value.name === EDIT_JOB) {
        await router.replace(this.jobPath)
      }
    },
    /** The draft in the address isn't there (deleted, expired, or mistyped): say so and start a new job. */
    async missing() {
      this.jobId = null
      this.mode = 'edit'
      this.takeOverSince = null
      this.editorKey++
      this.notice = 'The job at that address isn\'t there: it was deleted, it expired, or the address is wrong. This is a new, empty job.'
      if (router.currentRoute.value.name === EDIT_JOB) {
        await router.replace('/job')
      }
    },
    /** Demo tools deleted every job: nothing is open any more. */
    jobsDeleted(message: string) {
      this.jobId = null
      this.previewing.drafts = null
      this.previewing.queue = null
      this.editorKey++
      this.notice = message
      if (router.currentRoute.value.name === EDIT_JOB) {
        void router.replace('/job')
      }
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
      await router.push(this.jobPath)
    },
    /** Submit job succeeded: say when it runs, from the response's plan (design: Job scheduling). */
    async scheduled(job: Job) {
      this.jobId = null // submitting already took it out of Drafts
      const schedule = await api.getSchedule().catch(() => null) // only to tell the development setting apart
      await this.newJob()
      this.notice = submitMessage(job, {alwaysRunTime: !!schedule?.alwaysRunTime})
      await router.push('/queue')
    },
    /** A staff member submitted a draft from the Drafts list or its preview, without opening it. */
    async submittedFromList(job: Job) {
      if (this.jobId === job.id) {
        return this.scheduled(job) // it was the draft open in the editor
      }
      this.previewing.drafts = null
      const schedule = await api.getSchedule().catch(() => null)
      this.notice = submitMessage(job, {alwaysRunTime: !!schedule?.alwaysRunTime})
      await router.push('/queue')
    },
    /** An intern sent the draft in the editor to staff for review: it is staff only now, so the editor starts a new job. */
    async handedOver(name: string) {
      this.jobId = null // handing over already ended this page's editing
      await this.newJob()
      this.notice = `“${name || 'Untitled job'}” was sent to staff for review. It is in Drafts, marked Needs review.`
    }
  }
})
