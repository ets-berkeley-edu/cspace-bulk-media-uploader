import {describe, expect, it} from 'vitest'
import {absLabel, canCancelRun, daysText, fmtClock, groupTimestampTitle, parsePtInput, pausedBanner, ptInputValue, runsAt, scheduleBanner,
  scheduleSummary, submitMessage, whenLabel} from '../lib/schedule'
import type {Job, JobPlan, Schedule} from '../types'

// Wed Sep 30 2026, 1:00 PM Pacific (PDT, UTC-7)
const NOW = Date.UTC(2026, 8, 30, 20, 0) / 1000
const pt = (y: number, mo: number, d: number, h: number, mi = 0, off = 7) => Date.UTC(y, mo, d, h + off, mi) / 1000
const TONIGHT = pt(2026, 8, 30, 19)
const sched = (p: Partial<Schedule> = {}): Schedule => ({days: [1, 2, 3, 4, 5, 6, 7], start: '19:00', end: '', timezone: 'America/Los_Angeles',
  paused: null, nextRunAt: TONIGHT, windowOpen: false, alwaysRunTime: false, ...p})
const plan = (p: Partial<JobPlan>): JobPlan => ({kind: 'schedule', at: TONIGHT, ahead: 0, signInExpiresFirst: false, ...p})
const q = (p: Partial<Job> = {}) => ({status: 'Queued', ...p}) as Job

describe('schedule text (design: Job scheduling; UI mockup schedSummary)', () => {
  it('formats days and times, in Pacific time', () => {
    expect(fmtClock('19:00')).toBe('7:00 PM')
    expect(fmtClock('06:30')).toBe('6:30 AM')
    expect(fmtClock('00:05')).toBe('12:05 AM')
    expect(fmtClock('12:00')).toBe('12:00 PM')
    expect(daysText([1, 2, 3, 4, 5, 6, 7])).toBe('every day')
    expect(daysText([5, 1, 2, 3, 4])).toBe('weekdays')
    expect(daysText([6, 7])).toBe('on weekends')
    expect(daysText([1, 3, 5])).toBe('on Mon, Wed, Fri')
    expect(daysText([7, 3])).toBe('on Sun, Wed')
  })

  it('builds the banner: days, start, optional end, next run time', () => {
    expect(scheduleSummary(sched())).toBe('Jobs run every day at 7:00 PM (Pacific time).')
    expect(scheduleSummary(sched({days: [1, 2, 3, 4, 5], end: '06:00'})))
      .toBe('Jobs run weekdays at 7:00 PM (Pacific time); no new jobs start after 6:00 AM.')
    expect(scheduleSummary(sched({days: [1, 3, 5], start: '20:30'}))).toBe('Jobs run on Mon, Wed, Fri at 8:30 PM (Pacific time).')
    expect(scheduleBanner(sched(), NOW)).toBe('Jobs run every day at 7:00 PM (Pacific time). Next run time: today at 7:00 PM.')
    expect(pausedBanner({by: 'jlee', at: pt(2026, 8, 30, 9, 15), reason: 'CollectionSpace upgrade'}))
      .toBe('The queue is paused by jlee since Wed, Sep 30, 9:15 AM: CollectionSpace upgrade. No job starts until a BMU scheduler resumes it.')
  })

  it('names run times relative to today, in Pacific time', () => {
    expect(whenLabel(TONIGHT, {}, NOW)).toBe('tonight at 7:00 PM')
    expect(whenLabel(TONIGHT, {today: true}, NOW)).toBe('today at 7:00 PM')
    expect(whenLabel(pt(2026, 8, 30, 15), {}, NOW)).toBe('today at 3:00 PM')
    expect(whenLabel(pt(2026, 9, 1, 19), {}, NOW)).toBe('tomorrow at 7:00 PM')
    expect(whenLabel(pt(2026, 9, 3, 19), {}, NOW)).toBe('Sat, Oct 3 at 7:00 PM')
    expect(whenLabel(pt(2026, 9, 3, 19), {noAt: true}, NOW)).toBe('Sat, Oct 3, 7:00 PM')
    expect(absLabel(pt(2026, 9, 3, 19))).toBe('Sat, Oct 3, 7:00 PM')
  })

  it('reads and writes datetime-local values as Pacific time, across daylight saving', () => {
    expect(ptInputValue(TONIGHT)).toBe('2026-09-30T19:00')
    expect(parsePtInput('2026-09-30T19:00')).toBe(TONIGHT)
    expect(parsePtInput('2026-12-01T19:00')).toBe(pt(2026, 11, 1, 19, 0, 8)) // PST, UTC-8
    expect(ptInputValue(pt(2026, 11, 1, 19, 0, 8))).toBe('2026-12-01T19:00')
    expect(parsePtInput('')).toBeNull()
  })
})

describe('Runs at (design: Job scheduling; UI mockup runsAt)', () => {
  it('reads the job\'s plan', () => {
    expect(runsAt(q({status: 'Running'}), true, NOW).text).toBe('Running')
    expect(runsAt(q({plan: plan({ahead: 2})}), false, NOW).text).toBe('Tonight 7:00 PM · after 2 jobs')
    expect(runsAt(q({plan: plan({ahead: 1, at: pt(2026, 9, 3, 19)})}), false, NOW).text).toBe('Sat, Oct 3, 7:00 PM · after 1 job')
    expect(runsAt(q({plan: plan({kind: 'runNow', at: null})}), true, NOW)).toMatchObject({text: 'Next, as soon as the running job ends', sub: 'Run now'})
    expect(runsAt(q({plan: plan({kind: 'runNow', at: null})}), false, NOW).text).toBe('Now')
    expect(runsAt(q({plan: plan({kind: 'at', at: pt(2026, 9, 1, 8, 30)})}), false, NOW)).toMatchObject({text: 'Thu, Oct 1, 8:30 AM', sub: 'its own run time'})
    expect(runsAt(q({plan: plan({kind: 'paused'})}), false, NOW)).toMatchObject({text: 'Paused', sub: 'until a BMU scheduler resumes the queue'})
    expect(runsAt(q({held: {by: 'jlee', at: NOW}, plan: plan({kind: 'held', at: null})}), false, NOW).text).toBe('Held by jlee')
    // the run window is open (or the development setting): it starts when the jobs ahead are done
    expect(runsAt(q({plan: plan({at: NOW - 60, ahead: 1})}), true, NOW).text).toBe('In the current run · after 1 job')
    expect(runsAt(q({plan: plan({at: NOW - 60})}), true, NOW).text).toBe('Next, as soon as the running job ends')
  })

  it('flags a saved sign-in that expires before the run time', () => {
    expect(runsAt(q({plan: plan({signInExpiresFirst: true})}), false, NOW).warn).toBe(true)
    expect(runsAt(q({plan: plan({})}), false, NOW).warn).toBe(false)
  })

  it('orders held and paused jobs last when sorting', () => {
    const keys = [plan({kind: 'runNow', at: null}), plan({}), plan({kind: 'paused'}), plan({kind: 'held', at: null})]
      .map((p) => runsAt(q({plan: p}), false, NOW).key)
    expect([...keys].sort((a, b) => a - b)).toEqual(keys)
  })
})

describe('who may cancel a run (design: Job scheduling)', () => {
  it('schedulers and the submitter', () => {
    expect(canCancelRun({scheduledBy: 'jlee'}, {user: 'admin', scheduler: true})).toBe(true)
    expect(canCancelRun({scheduledBy: 'jlee'}, {user: 'jlee', scheduler: false})).toBe(true)
    expect(canCancelRun({scheduledBy: 'jlee'}, {user: 'admin', scheduler: false})).toBe(false)
    expect(canCancelRun({scheduledBy: undefined}, {user: undefined})).toBe(false)
  })
})

describe('Submit job message (design: Job scheduling; UI mockup submitJob)', () => {
  const sub = (p: Partial<Job>) => ({name: 'Spring batch', status: 'Queued', ...p}) as Job
  const tail = ' It runs with your sign-in, which is deleted when the run ends.'
  it('names the next run time and the jobs ahead', () => {
    expect(submitMessage(sub({plan: plan({ahead: 2})}), {}, NOW)).toBe('“Spring batch” was submitted and added to the end of the queue. '
      + 'It runs at the next run time, tonight at 7:00 PM, after 2 other jobs.' + tail)
    expect(submitMessage(sub({plan: plan({}), checksAtSchedule: {block: 0, warn: 3}}), {}, NOW))
      .toBe('“Spring batch” was submitted with 3 document(s) carrying warnings and added to the end of the queue. It runs at the next run time, tonight at 7:00 PM.' + tail)
  })
  it('says when the queue is paused, or that it starts now in development mode', () => {
    expect(submitMessage(sub({plan: plan({kind: 'paused'})}), {}, NOW)).toContain('The queue is paused, so it waits until a BMU scheduler resumes it.')
    expect(submitMessage(sub({plan: plan({at: NOW})}), {alwaysRunTime: true}, NOW))
      .toContain('Development setting: every moment counts as run time, so it starts now.')
    expect(submitMessage(sub({plan: plan({at: NOW, ahead: 1})}), {alwaysRunTime: true}, NOW)).toContain('so it starts after 1 other job.')
    expect(submitMessage(sub({status: 'Running', plan: plan({kind: 'running'})}), {}, NOW)).toBe('“Spring batch” was submitted and started right away.' + tail)
    expect(submitMessage(sub({plan: plan({signInExpiresFirst: true})}), {}, NOW)).toContain('expires before then')
  })
})

describe('Group title timestamp (user decision; legacy =job convention)', () => {
  it('is bmu-YYYY-MM-DD-HH-MM-SS in Pacific time', () => {
    expect(groupTimestampTitle(NOW * 1000 + 5_000)).toBe('bmu-2026-09-30-13-00-05')
    expect(groupTimestampTitle(Date.UTC(2026, 0, 2, 7, 4, 9))).toBe('bmu-2026-01-01-23-04-09') // PST, the day before in UTC
  })
})
