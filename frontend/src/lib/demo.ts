/**
 * Demo tools (demo builds only). DEMO_BUILD is false in a production build (`npm run build`), so the pane and
 * this module are left out of it entirely; `npm run dev` and `npm run build:demo` include them. The server side
 * is off too unless BMU_DEMO=true (every /api/_demo endpoint answers 404).
 */
import {request} from '../api'

export const DEMO_BUILD = import.meta.env.MODE !== 'production'

export interface SimSettings {
  delay: number;
  upload_mbps: number;
  rules: { step: string; match: string; status: number; effect: string; count: number; left: number; client: string }[];
  term_states: Record<string, string>;
  term_renames: Record<string, string>;
  deleted_languages: string[];
  language_renames: Record<string, string>;
  steps: string[];
  people: string[];
  orgs: string[];
  languages: Record<string, string>;
  term_names: Record<string, string>; // short identifier -> the sample term's original display name
}

export interface DemoStatus {
  browserUploadMbps: number;
  cspaceUrl: string;
  alwaysRunTime: boolean;
  sim: SimSettings | null;
  simError: string;
  /** Who is signed in, and their BMU role. */
  user: string;
  role: 'staff' | 'intern';
  /** The simulator's users, for "Sign in as" (empty against a real CollectionSpace). */
  users: { user: string; about: string }[];
}

export const demoApi = {
  status: () => request<DemoStatus>('GET', '/api/_demo/status', undefined, true),
  browserUpload: (mbps: number) => request<{ browserUploadMbps: number }>('POST', '/api/_demo/browser-upload', {mbps}),
  sim: (action: string, params: Record<string, unknown> = {}) => request<SimSettings>('POST', `/api/_demo/sim/${action}`, {params}),
  objects: () => request<{ objects: { objectNumber: string; note: string; deleted: boolean; sensitivity?: unknown }[] }>('GET', '/api/_demo/sim/objects'),
  deleteAllJobs: () => request<{ deleted: number; skipped: string[] }>('POST', '/api/_demo/delete-all-jobs'),
  /** Sign in as one of the simulator's users; whoever was signed in is signed out. Refused accounts say why. */
  signInAs: (user: string) => request<{ user: string; role: 'staff' | 'intern' }>('POST', '/api/_demo/sign-in-as', {user}),
  /** Every job, draft, file and audit entry deleted; the schedule, the simulator and the upload speeds back to the start. */
  resetEverything: () => request<{ items: number; objects: number }>('POST', '/api/_demo/reset-everything'),
}

/** "Full speed", or e.g. "2 MB/s". */
export const speedLabel = (mbps: number) => (mbps > 0 ? `${mbps} MB/s` : 'Full speed')
/** The same, inside a sentence: "full speed", or e.g. "2 MB/s". */
export const speedText = (mbps: number) => (mbps > 0 ? `${mbps} MB/s` : 'full speed')

/** What an added failure does, e.g. "The next “upload” request fails with 500." */
export function failureText(step: string, status: number, count: number): string {
  if (!count) return `Every “${step}” request fails with ${status} until you clear failures.`
  return count === 1 ? `The next “${step}” request fails with ${status}.` : `The next ${count} “${step}” requests fail with ${status}.`
}

/** The collapsed pane's one-line summary. */
export function demoSummary(st: DemoStatus | null): string {
  if (!st) return ''
  const parts = [`Browser uploads: ${speedText(st.browserUploadMbps)}`]
  if (st.sim) {
    parts.push(`Run uploads: ${speedText(st.sim.upload_mbps)}`)
    if (st.sim.delay) parts.push(`${st.sim.delay} s delay per create`)
    if (st.sim.rules.length) parts.push(`${st.sim.rules.length} failure${st.sim.rules.length === 1 ? '' : 's'} set`)
    const changed = Object.keys(st.sim.term_states).length + Object.keys(st.sim.term_renames).length
      + st.sim.deleted_languages.length + Object.keys(st.sim.language_renames).length
    if (changed) parts.push(`${changed} term change${changed === 1 ? '' : 's'}`)
  } else parts.push('simulator not reachable')
  return parts.join(' · ')
}

/** The commands the pane documents, grouped. Placeholders in angle brackets. */
export const COMMANDS: { title: string; note: string; lines: string }[] = [
  {
    title: 'Check the BMU\'s calls against the QA server (read-only)',
    note: 'scripts/check_cspace.py talks to a real CollectionSpace with your own account. Type the password at the prompt, '
      + 'so it isn\'t shown or kept in your shell history, and never put it in a file in the repo. Run it with the backend\'s '
      + 'Python environment. --create makes real records on the server, which stay: use it only on the QA tenant.',
    lines: [
      'cd backend',
      'export CSPACE_URL=https://pahma.qa.collectionspace.org CSPACE_USER=<your QA username>',
      'read -rs CSPACE_PASSWORD && export CSPACE_PASSWORD',
      'PYTHONPATH=. python ../scripts/check_cspace.py --roles          # your roles; your BMU role, and what a staff account lacks',
      'PYTHONPATH=. python ../scripts/check_cspace.py --vocabularies   # the Person and Organization vocabularies',
      'PYTHONPATH=. python ../scripts/check_cspace.py --terms <refName or person:shortId>   # read terms as the BMU\'s check does',
      'PYTHONPATH=. python ../scripts/check_cspace.py --object <object number> --term <text>  # object lookup and term search',
      'PYTHONPATH=. python ../scripts/check_cspace.py --object <object number> --show-object  # its fields and the sensitivity verdict',
      'unset CSPACE_PASSWORD',
    ].join('\n'),
  },
  {
    title: 'Which BMU job created a record?',
    note: 'scripts/find_csid.py looks CSIDs up in the audit log\'s CSID index (about a year), with the same BMU_* settings as the web app.',
    lines: 'cd backend\npython ../scripts/find_csid.py <csid> [<csid> ...]',
  },
  {
    title: 'The simulated CollectionSpace from the command line',
    note: 'The same controls as this pane, straight to the simulator (http://localhost:8180 in the local stack). Development only; '
      + 'a real server has none of these.',
    lines: [
      'curl -X POST \'http://localhost:8180/_fake/slow?seconds=2&upload_mbps=5\'   # 2 s per create, file uploads at 5 MB/s',
      'curl -X POST \'http://localhost:8180/_fake/fail?step=upload&status=500&count=1\'',
      'curl \'http://localhost:8180/_fake/objects\'    # the sample Object records',
      'curl \'http://localhost:8180/_fake/settings\'   # what the controls are set to',
      'curl -X POST \'http://localhost:8180/_fake/reset\'',
    ].join('\n'),
  },
  {
    title: 'Run the tests',
    note: 'Backend with pytest (moto and the simulator, no network needed); frontend with Vitest, then the type check and a production build.',
    lines: '(cd backend && python -m pytest -q)\n(cd frontend && npm test && npm run typecheck && npm run build)',
  },
  {
    title: 'Run a job at once, without waiting for a run time',
    note: 'BMU_ALWAYS_RUN_TIME=true (web app and worker) makes every moment a run time, so a submitted job starts at the next worker poll. '
      + 'Development only. Otherwise use Run now in the Job queue (staff).',
    lines: 'BMU_ALWAYS_RUN_TIME=true docker compose up',
  },
]
