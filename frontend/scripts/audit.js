// npm audit, with a short list of known advisories allowed for a while (audit-allowlist.json).
//
// CI runs this in place of `npm audit`. Run on its own (on pushes to main, in audit.yml every Monday, and by hand), it
// fails on any advisory not on the list, on an entry past its review date, and on an entry no advisory needs any more,
// so the list only ever holds advisories someone has looked at, and empties itself out as the fixes arrive.
//
// npm audit asks GitHub's advisory database, which changes without any change here: a new advisory, a review date
// passing or an advisory withdrawn would otherwise fail every open pull request at once. So on a pull request
// (security.yml) it runs with --changed-since <the base commit>, and fails only for what the pull request changes:
//   - an advisory not on the list, in a package whose versions in package-lock.json the pull request changes (added,
//     removed or moved to another version);
//   - an allowlist entry the pull request adds or changes, held to all the rules above;
//   - a malformed entry, or npm audit itself failing.
// Everything else (an advisory in a package it doesn't change, an entry it doesn't touch that is past its date or no
// longer reported) is a warning: a ::warning:: line, and in the job's summary. The push to main that follows the merge
// runs the full check, so main still turns red and the list is still kept up. If the base's package-lock.json can't
// be read, the whole check is strict.
//   node scripts/audit.js                          (or npm run audit-check), in frontend/
//   node scripts/audit.js --changed-since HEAD^1   (a pull request's checkout is its merge commit; its first parent is
//                                                    the base)

import {appendFileSync, readFileSync} from 'node:fs'
import {spawnSync} from 'node:child_process'
import {pathToFileURL} from 'node:url'

// The advisories in `npm audit --json`'s report, one per advisory ID (GHSA-…), with the packages it was found in.
export function advisories(report) {
  const found = new Map()
  for (const [name, vulnerability] of Object.entries(report.vulnerabilities ?? {})) {
    for (const via of vulnerability.via ?? []) {
      if (typeof via !== 'object') continue // a package that is vulnerable only through another one
      const id = String(via.url ?? via.source).split('/').pop()
      const advisory = found.get(id) ?? {id, severity: via.severity, title: via.title, packages: new Set()}
      advisory.packages.add(via.name ?? name)
      found.set(id, advisory)
    }
  }
  return [...found.values()].map(a => ({...a, packages: [...a.packages].sort()}))
}

// Each package's versions in a package-lock.json (lockfileVersion 2 or 3), by name. An aliased package
// ("x": "npm:y@1.0.0") counts under its real name, as npm audit reports it.
export function lockedVersions(lock) {
  const versions = new Map()
  for (const [path, entry] of Object.entries(lock.packages ?? {})) {
    const at = path.lastIndexOf('node_modules/')
    if (at < 0 || entry.link) continue // the project itself, a workspace, or a link to one
    const name = entry.name ?? path.slice(at + 'node_modules/'.length)
    versions.set(name, (versions.get(name) ?? new Set()).add(entry.version))
  }
  return versions
}

// The names of the packages added, removed or moved to another version between two package-lock.json files. The same
// version installed in another place doesn't count.
export function changedPackages(baseLock, headLock) {
  const base = lockedVersions(baseLock)
  const head = lockedVersions(headLock)
  const key = versions => [...(versions ?? [])].sort().join(' ')
  return new Set([...new Set([...base.keys(), ...head.keys()])].filter(name => key(base.get(name)) !== key(head.get(name))))
}

// What fails the check, what is only a warning, and the advisories the list allows. Today is YYYY-MM-DD.
// Without `since`, everything below fails: an error from npm audit, an advisory not on the list, an entry past its
// review date, or an entry for an advisory the report no longer has. With since = {changed, allowlist} (the packages
// the pull request changes, and the list as it was at the base), an advisory in a package it doesn't change, and an
// entry it doesn't add or change that is past its date or no longer reported, are warnings instead.
export function check(report, allowlist, today, since) {
  if (report.error) {
    return {failures: [`npm audit failed: ${report.error.summary ?? JSON.stringify(report.error)}`], warnings: [], allowed: []}
  }
  const found = advisories(report)
  const listed = new Map(allowlist.map(entry => [entry.id, entry]))
  const failures = []
  const warnings = []
  const baseEntries = new Map((since?.allowlist ?? []).map(entry => [entry.id, JSON.stringify(entry)]))
  const touched = entry => !since || baseEntries.get(entry.id) !== JSON.stringify(entry)
  for (const advisory of found) {
    if (!listed.has(advisory.id)) {
      const problem = `${advisory.severity} ${advisory.id} in ${advisory.packages.join(', ')}: ${advisory.title}`
      if (!since || advisory.packages.some(name => since.changed.has(name))) failures.push(problem)
      else warnings.push(`${problem} (in a package this pull request doesn't change)`)
    }
  }
  for (const entry of allowlist) {
    if (!/^GHSA(-[0-9a-z]{4}){3}$/.test(entry.id) || !entry.reason || !/^\d{4}-\d{2}-\d{2}$/.test(entry.review_by)) {
      failures.push(`audit-allowlist.json: ${JSON.stringify(entry.id)} needs a GHSA ID, a reason and review_by (YYYY-MM-DD)`)
      continue
    }
    const problem = entry.review_by < today
      ? `audit-allowlist.json: ${entry.id} was to be reviewed by ${entry.review_by}: is a fix out yet?`
      : !found.some(advisory => advisory.id === entry.id)
        ? `audit-allowlist.json: ${entry.id} is no longer reported: remove it`
        : undefined
    if (!problem) continue
    if (touched(entry)) failures.push(problem)
    else warnings.push(`${problem} (an entry this pull request doesn't change)`)
  }
  return {failures, warnings, allowed: found.filter(advisory => listed.has(advisory.id))}
}

// A file as it is at a git commit (path relative to frontend/), or undefined if git can't give it.
function atCommit(ref, path) {
  const run = spawnSync('git', ['show', `${ref}:./${path}`], {encoding: 'utf8', maxBuffer: 64 * 1024 * 1024})
  if (run.status !== 0) return undefined
  try {
    return JSON.parse(run.stdout)
  } catch {
    return undefined
  }
}

function main() {
  const args = process.argv.slice(2)
  const at = args.indexOf('--changed-since')
  const ref = at >= 0 ? args[at + 1] : undefined
  if (at >= 0 && !ref) {
    process.stderr.write('usage: node scripts/audit.js [--changed-since <git ref>]\n')
    process.exit(2)
  }
  const run = spawnSync('npm', ['audit', '--json'], {encoding: 'utf8', maxBuffer: 64 * 1024 * 1024})
  let report
  try {
    report = JSON.parse(run.stdout)
  } catch {
    process.stderr.write(`npm audit gave no report (exit ${run.status}):\n${run.stderr}\n`)
    process.exit(1)
  }
  const read = file => JSON.parse(readFileSync(new URL(`../${file}`, import.meta.url), 'utf8'))
  const allowlist = read('audit-allowlist.json')
  const notes = []
  let since
  if (ref) {
    const baseLock = atCommit(ref, 'package-lock.json')
    if (baseLock) {
      since = {changed: changedPackages(baseLock, read('package-lock.json')), allowlist: atCommit(ref, 'audit-allowlist.json') ?? []}
      notes.push(`Compared with ${ref}: ${since.changed.size} package(s) changed in package-lock.json` +
        (since.changed.size ? ` (${[...since.changed].sort().join(', ')})` : '') + '.')
    } else {
      notes.push(`Could not read package-lock.json at ${ref}: checking every advisory, as on main.`)
    }
  }
  const {failures, warnings, allowed} = check(report, allowlist, new Date().toISOString().slice(0, 10), since)
  for (const note of notes) process.stdout.write(`${note}\n`)
  for (const advisory of allowed) {
    const entry = allowlist.find(e => e.id === advisory.id)
    process.stdout.write(`Allowed until ${entry.review_by}: ${advisory.id} in ${advisory.packages.join(', ')}\n`)
  }
  for (const warning of warnings) process.stdout.write(`::warning::${warning}\n`)
  if (process.env.GITHUB_STEP_SUMMARY && (failures.length || warnings.length || notes.length)) {
    const list = items => items.map(item => `- ${item}\n`).join('')
    appendFileSync(process.env.GITHUB_STEP_SUMMARY, '### npm audit\n\n' + notes.map(note => `${note}\n\n`).join('') +
      (failures.length ? `Fails the check:\n\n${list(failures)}\n` : '') +
      (warnings.length ? `To fix on main, or in the pull request that touches them (they don't fail this one):\n\n${list(warnings)}\n` : ''))
  }
  if (failures.length) {
    process.stderr.write(`${failures.join('\n')}\n`)
    process.exit(1)
  }
  process.stdout.write(warnings.length
    ? `npm audit: nothing this pull request changes, but ${warnings.length} warning(s) above to fix on main.\n`
    : 'npm audit: nothing but the allowed advisories.\n')
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main()
