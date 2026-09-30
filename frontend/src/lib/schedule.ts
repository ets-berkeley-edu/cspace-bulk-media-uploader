/**
 * Job scheduling (design: Job scheduling; UI mockup schedFor, scheduleBannerHtml, runsAt): how the tenant's run
 * times, a queued job's planned start and the submit message read. Times are always Pacific time
 * (America/Los_Angeles), whatever the browser's time zone. Instants are epoch seconds, as the API sends them.
 */
import type { Job, JobPlan, Me, Schedule } from "../types";

export const PT_TZ = "America/Los_Angeles";
/** ISO weekday numbers (1 = Mon … 7 = Sun) in the order the mockup shows them: Sun first. */
export const DAY_ORDER = [7, 1, 2, 3, 4, 5, 6];
export const DAY_NAMES: Record<number, string> = { 1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun" };
/** design: Job scheduling — who may cancel a run. */
export const NO_CANCEL_WHY = "Only a BMU scheduler or the person who submitted the job can cancel its run.";

const pad2 = (n: number) => (n < 10 ? "0" : "") + n;
let ptFmt: Intl.DateTimeFormat | null = null;

/** Pacific wall-clock parts of an instant (epoch seconds). */
export function ptParts(sec: number) {
  ptFmt ??= new Intl.DateTimeFormat("en-US", { timeZone: PT_TZ, hour12: false, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  const o: Record<string, string> = {};
  ptFmt.formatToParts(new Date(sec * 1000)).forEach((p) => { o[p.type] = p.value; });
  return { y: +o.year, mo: +o.month - 1, d: +o.day, h: +o.hour % 24, mi: +o.minute };
}

/** The instant (epoch seconds) of a Pacific wall-clock time; a few rounds settle the UTC offset (and DST). */
export function ptInstant(y: number, mo: number, d: number, h: number, mi: number): number {
  const want = Date.UTC(y, mo, d, h, mi);
  let guess = want + 8 * 3600e3;
  for (let k = 0; k < 3; k++) {
    const p = ptParts(guess / 1000);
    guess += want - Date.UTC(p.y, p.mo, p.d, p.h, p.mi);
  }
  return guess / 1000;
}

/** "19:00" → "7:00 PM". */
export function fmtClock(hhmm: string): string {
  const [hs, m] = hhmm.split(":");
  const h = +hs;
  return `${h % 12 || 12}:${m} ${h < 12 ? "AM" : "PM"}`;
}

/** "Sat, Oct 3, 7:00 PM" (Pacific time). */
export function absLabel(sec: number): string {
  // Newer ICU puts a narrow no-break space before AM/PM; plain spaces match fmtClock.
  return new Date(sec * 1000).toLocaleString("en-US", { timeZone: PT_TZ, weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
    .replace(/[\u202f\u00a0]/g, " ");
}

/**
 * "tonight at 7:00 PM", "today at 7:00 PM" (today: never "tonight"), "tomorrow at 7:00 PM", "Sat, Oct 3 at 7:00 PM";
 * noAt drops the "at" ("tonight 7:00 PM", "Sat, Oct 3, 7:00 PM"). Pacific time.
 */
export function whenLabel(sec: number, o: { today?: boolean; noAt?: boolean } = {}, nowSec = Date.now() / 1000): string {
  const p = ptParts(sec), n = ptParts(nowSec);
  const dd = Math.round((Date.UTC(p.y, p.mo, p.d) - Date.UTC(n.y, n.mo, n.d)) / 86400e3);
  const t = fmtClock(`${pad2(p.h)}:${pad2(p.mi)}`);
  const day = dd === 0 ? (p.h >= 17 && !o.today ? "tonight" : "today") : dd === 1 ? "tomorrow"
    : new Date(sec * 1000).toLocaleDateString("en-US", { timeZone: PT_TZ, weekday: "short", month: "short", day: "numeric" });
  return day + (o.noAt ? (dd > 1 ? ", " : " ") : " at ") + t;
}

const capFirst = (x: string) => x.charAt(0).toUpperCase() + x.slice(1);

/** "every day", "weekdays", "on weekends", "on Mon, Wed, Fri". */
export function daysText(days: number[]): string {
  const on = [...new Set(days)].sort((a, b) => a - b);
  if (on.length === 7) return "every day";
  if (on.join() === "1,2,3,4,5") return "weekdays";
  if (on.join() === "6,7") return "on weekends";
  return "on " + DAY_ORDER.filter((d) => on.includes(d)).map((d) => DAY_NAMES[d]).join(", ");
}

/** "every day at 7:00 PM; no new jobs start after 6:00 AM" (for flashes and the audit-like "changed" check). */
export function scheduleShort(s: Pick<Schedule, "days" | "start" | "end">): string {
  return `${daysText(s.days)} at ${fmtClock(s.start)}` + (s.end ? `; no new jobs start after ${fmtClock(s.end)}` : "");
}

/** The banner's first sentence: "Jobs run every day at 7:00 PM (Pacific time)." */
export function scheduleSummary(s: Pick<Schedule, "days" | "start" | "end">): string {
  return `Jobs run ${daysText(s.days)} at ${fmtClock(s.start)} (Pacific time)` + (s.end ? `; no new jobs start after ${fmtClock(s.end)}` : "") + ".";
}

/** The whole schedule banner: summary plus "Next run time: today at 7:00 PM." */
export function scheduleBanner(s: Schedule, nowSec = Date.now() / 1000): string {
  return scheduleSummary(s) + (s.nextRunAt ? ` Next run time: ${whenLabel(s.nextRunAt, { today: true }, nowSec)}.` : "");
}

/** The paused warning banner. */
export function pausedBanner(p: NonNullable<Schedule["paused"]>): string {
  return `The queue is paused by ${p.by} since ${absLabel(p.at)}: ${p.reason}. No job starts until a BMU scheduler resumes it.`;
}

/** A datetime-local value ("2026-10-01T19:00") for an instant, in Pacific time. */
export function ptInputValue(sec: number): string {
  const p = ptParts(sec);
  return `${p.y}-${pad2(p.mo + 1)}-${pad2(p.d)}T${pad2(p.h)}:${pad2(p.mi)}`;
}

/**
 * The Group title "Use a timestamp" fills (user decision; the legacy `=job` convention): bmu-YYYY-MM-DD-HH-MM-SS
 * in Pacific time, at the moment of clicking.
 */
export function groupTimestampTitle(ms = Date.now()): string {
  const o: Record<string, string> = {};
  new Intl.DateTimeFormat("en-US", { timeZone: PT_TZ, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit" }).formatToParts(new Date(ms)).forEach((p) => { o[p.type] = p.value; });
  return `bmu-${o.year}-${o.month}-${o.day}-${o.hour}-${o.minute}-${o.second}`;
}

/** A datetime-local value read as Pacific time → epoch seconds, or null if it isn't a date and time. */
export function parsePtInput(v: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(v || "");
  return m ? ptInstant(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) : null;
}

const jobsText = (n: number, other = false) => `${n} ${other ? "other " : ""}job${n === 1 ? "" : "s"}`;

export interface RunsAt {
  text: string;
  sub?: string;
  warn: boolean; // the job's saved sign-in expires before its planned start
  key: number; // for sorting the Runs at column
}

/**
 * The Runs at column (UI mockup runsAt), from the job's plan. running: whether a job is running now (a job due now
 * then starts when it ends).
 */
export function runsAt(j: Pick<Job, "status" | "plan" | "held" | "runNow">, running: boolean, nowSec = Date.now() / 1000): RunsAt {
  const plan: JobPlan | undefined = j.plan ?? undefined;
  const warn = !!plan?.signInExpiresFirst;
  if (j.status === "Running" || plan?.kind === "running") return { text: "Running", warn: false, key: 0 };
  if (!plan) return { text: "—", warn: false, key: 7e15 };
  const dueNow = running ? "Next, as soon as the running job ends" : "Now";
  switch (plan.kind) {
    case "held":
      return { text: `Held by ${j.held?.by ?? "a scheduler"}`, sub: `${j.held?.at ? `since ${absLabel(j.held.at)}; ` : ""}its sign-in clock keeps running`, warn: false, key: 9e15 };
    case "paused":
      return { text: "Paused", sub: "until a BMU scheduler resumes the queue", warn, key: 8e15 };
    case "runNow":
      return { text: dueNow, sub: "Run now", warn, key: 1 + plan.ahead };
    case "at":
      if (plan.at == null || plan.at <= nowSec) return { text: dueNow, warn, key: 1 + plan.ahead };
      return { text: absLabel(plan.at), sub: "its own run time", warn, key: plan.at };
    default: {
      const aj = plan.ahead ? ` · after ${jobsText(plan.ahead)}` : "";
      if (plan.at == null) return { text: "No run time", warn, key: 7e15 };
      // Due now (the run window is open, or the development setting): it starts when the jobs ahead of it are done
      if (plan.at <= nowSec) return { text: plan.ahead ? `In the current run${aj}` : dueNow, warn, key: 2 + plan.ahead };
      return { text: capFirst(whenLabel(plan.at, { noAt: true }, nowSec)) + aj, warn, key: plan.at + plan.ahead };
    }
  }
}

/** Whether this user may cancel the job's run: a BMU scheduler, or whoever submitted it (design: Job scheduling). */
export function canCancelRun(j: Pick<Job, "scheduledBy">, me: { user?: string; scheduler?: boolean }): boolean {
  return !!me.scheduler || (!!me.user && j.scheduledBy === me.user);
}

/**
 * The message after Submit job (UI mockup submitJob), from the submit response's plan: when it runs, or that the
 * queue is paused, or (development setting / an open run window) that it starts now.
 */
export function submitMessage(j: Pick<Job, "name" | "plan" | "checksAtSchedule" | "status">, opts: { alwaysRunTime?: boolean } = {}, nowSec = Date.now() / 1000): string {
  const name = `“${j.name || "Untitled job"}”`;
  const warn = j.checksAtSchedule?.warn ?? 0;
  const signIn = " It runs with your sign-in, which is deleted when the run ends.";
  const plan = j.plan;
  if (j.status === "Running" || plan?.kind === "running") return `${name} was submitted and started right away.${signIn}`;
  const head = `${name} was submitted${warn ? ` with ${warn} document(s) carrying warnings` : ""} and added to the end of the queue. `;
  let when = "";
  const ahead = plan?.ahead ?? 0;
  const afterJobs = ahead ? `after ${jobsText(ahead, true)}` : "";
  if (!plan) when = "It runs at the next run time.";
  else if (plan.kind === "paused") when = "The queue is paused, so it waits until a BMU scheduler resumes it.";
  else if (plan.kind === "held") when = "It is held, so it waits until a BMU scheduler releases it.";
  else if (plan.at == null) when = "It runs at the next run time.";
  else if (plan.at <= nowSec || opts.alwaysRunTime) {
    when = (opts.alwaysRunTime ? "Development setting: every moment counts as run time, so it starts " : "A run is in progress, so it starts ")
      + (ahead ? afterJobs : "now") + ".";
  } else if (plan.kind === "at") when = `It runs at its own run time, ${absLabel(plan.at)}${ahead ? `, ${afterJobs}` : ""}.`;
  else when = `It runs at the next run time, ${whenLabel(plan.at, {}, nowSec)}${ahead ? `, ${afterJobs}` : ""}.`;
  const expires = plan?.signInExpiresFirst ? " ⚠ Its saved sign-in expires before then; if it hasn’t started by then, it moves to Drafts." : "";
  return head + when + expires + signIn;
}

/** The part of Me scheduling needs. */
export type SchedulerOf = Pick<Me, "user" | "scheduler">;
