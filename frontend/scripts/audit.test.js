import {describe, expect, it} from 'vitest'
import {advisories, changedPackages, check, lockedVersions} from './audit.js'

const report = (...vias) => ({
  vulnerabilities: {
    minimatch: {via: vias.filter(v => v.name === 'minimatch')},
    glob: {via: [...vias.filter(v => v.name === 'glob'), 'minimatch']},
    eslint: {via: ['minimatch']}
  }
})
const minimatch = {
  name: 'minimatch', source: 1, severity: 'moderate', title: 'ReDoS',
  url: 'https://github.com/advisories/GHSA-aaaa-bbbb-cccc'
}
const glob = {
  name: 'glob', source: 2, severity: 'high', title: 'Traversal', url: 'https://github.com/advisories/GHSA-dddd-eeee-ffff'
}
const entry = (id, review_by = '2026-11-30') => ({id, reason: 'dev tooling only', review_by})

describe('the npm audit check', () => {
  it('lists each advisory once, with the packages it was found in', () => {
    expect(advisories(report(minimatch, glob))).toEqual([
      {id: 'GHSA-aaaa-bbbb-cccc', severity: 'moderate', title: 'ReDoS', packages: ['minimatch']},
      {id: 'GHSA-dddd-eeee-ffff', severity: 'high', title: 'Traversal', packages: ['glob']}
    ])
  })

  it('passes a clean report and an empty list', () => {
    expect(check({vulnerabilities: {}}, [], '2026-11-01')).toEqual({failures: [], warnings: [], allowed: []})
  })

  it('passes advisories that are on the list', () => {
    const result = check(report(minimatch), [entry('GHSA-aaaa-bbbb-cccc')], '2026-11-01')
    expect(result.failures).toEqual([])
    expect(result.allowed.map(a => a.id)).toEqual(['GHSA-aaaa-bbbb-cccc'])
  })

  it('fails on an advisory that is not on the list', () => {
    const {failures} = check(report(minimatch, glob), [entry('GHSA-aaaa-bbbb-cccc')], '2026-11-01')
    expect(failures).toEqual(['high GHSA-dddd-eeee-ffff in glob: Traversal'])
  })

  it('fails on an entry past its review date', () => {
    const {failures} = check(report(minimatch), [entry('GHSA-aaaa-bbbb-cccc', '2026-10-31')], '2026-11-01')
    expect(failures).toEqual(['audit-allowlist.json: GHSA-aaaa-bbbb-cccc was to be reviewed by 2026-10-31: is a fix out yet?'])
  })

  it('fails on an entry the report no longer needs', () => {
    const {failures} = check({vulnerabilities: {}}, [entry('GHSA-aaaa-bbbb-cccc')], '2026-11-01')
    expect(failures).toEqual(['audit-allowlist.json: GHSA-aaaa-bbbb-cccc is no longer reported: remove it'])
  })

  it('fails on an entry without an ID, a reason or a review date', () => {
    const {failures} = check(report(minimatch), [{id: 'GHSA-aaaa-bbbb-cccc', review_by: '2026-11-30'}], '2026-11-01')
    expect(failures).toEqual([
      'audit-allowlist.json: "GHSA-aaaa-bbbb-cccc" needs a GHSA ID, a reason and review_by (YYYY-MM-DD)'
    ])
  })

  it('fails when npm audit itself fails', () => {
    const {failures} = check({error: {summary: 'registry unreachable'}}, [], '2026-11-01')
    expect(failures).toEqual(['npm audit failed: registry unreachable'])
  })
})

const lock = packages => ({lockfileVersion: 3, packages: {'': {name: 'app'}, ...packages}})
const at = version => ({version})

describe('the packages a pull request changes', () => {
  it('lists each package\'s versions by name, wherever it is installed', () => {
    const versions = lockedVersions(lock({
      'node_modules/minimatch': at('9.0.5'),
      'node_modules/glob/node_modules/minimatch': at('3.1.2'),
      'node_modules/@scope/pkg': at('1.0.0'),
      'node_modules/alias': {name: 'glob', version: '10.0.0'},
      'packages/workspace': at('0.1.0'),
      'node_modules/workspace': {resolved: 'packages/workspace', link: true}
    }))
    expect(Object.fromEntries([...versions].map(([name, v]) => [name, [...v].sort()]))).toEqual({
      minimatch: ['3.1.2', '9.0.5'], '@scope/pkg': ['1.0.0'], glob: ['10.0.0']
    })
  })

  it('counts a package added, removed or moved to another version, not one installed elsewhere', () => {
    const base = lock({
      'node_modules/kept': at('1.0.0'),
      'node_modules/moved': at('2.0.0'),
      'node_modules/upgraded': at('1.0.0'),
      'node_modules/removed': at('1.0.0'),
      'node_modules/nested': at('1.0.0')
    })
    const head = lock({
      'node_modules/kept': at('1.0.0'),
      'node_modules/other/node_modules/moved': at('2.0.0'),
      'node_modules/upgraded': at('1.0.1'),
      'node_modules/added': at('1.0.0'),
      'node_modules/nested': at('1.0.0'),
      'node_modules/x/node_modules/nested': at('0.9.0')
    })
    expect([...changedPackages(base, head)].sort()).toEqual(['added', 'nested', 'removed', 'upgraded'])
  })

  it('counts nothing when the lockfile is unchanged', () => {
    const same = lock({'node_modules/minimatch': at('9.0.5')})
    expect(changedPackages(same, same).size).toBe(0)
  })
})

describe('the npm audit check on a pull request', () => {
  const since = (changed, allowlist = []) => ({changed: new Set(changed), allowlist})

  it('fails on an advisory not on the list in a package the pull request changes', () => {
    const result = check(report(minimatch, glob), [], '2026-11-01', since(['glob']))
    expect(result.failures).toEqual(['high GHSA-dddd-eeee-ffff in glob: Traversal'])
    expect(result.warnings).toEqual([
      'moderate GHSA-aaaa-bbbb-cccc in minimatch: ReDoS (in a package this pull request doesn\'t change)'
    ])
  })

  it('only warns of an advisory in a package it doesn\'t change', () => {
    const result = check(report(minimatch), [], '2026-11-01', since([]))
    expect(result.failures).toEqual([])
    expect(result.warnings).toHaveLength(1)
  })

  it('only warns of an entry it doesn\'t touch that is past its date or no longer reported', () => {
    const old = entry('GHSA-aaaa-bbbb-cccc', '2026-10-31')
    const gone = entry('GHSA-dddd-eeee-ffff')
    const result = check(report(minimatch), [old, gone], '2026-11-01', since([], [old, gone]))
    expect(result.failures).toEqual([])
    expect(result.warnings).toEqual([
      'audit-allowlist.json: GHSA-aaaa-bbbb-cccc was to be reviewed by 2026-10-31: is a fix out yet? ' +
        '(an entry this pull request doesn\'t change)',
      'audit-allowlist.json: GHSA-dddd-eeee-ffff is no longer reported: remove it (an entry this pull request doesn\'t change)'
    ])
  })

  it('holds an entry it adds or changes to every rule', () => {
    const added = entry('GHSA-dddd-eeee-ffff')
    const changed = entry('GHSA-aaaa-bbbb-cccc', '2026-10-31')
    const base = [{...changed, review_by: '2026-12-01'}]
    const {failures, warnings} = check(report(minimatch), [changed, added], '2026-11-01', since([], base))
    expect(failures).toEqual([
      'audit-allowlist.json: GHSA-aaaa-bbbb-cccc was to be reviewed by 2026-10-31: is a fix out yet?',
      'audit-allowlist.json: GHSA-dddd-eeee-ffff is no longer reported: remove it'
    ])
    expect(warnings).toEqual([])
  })

  it('still fails on a malformed entry and on npm audit failing', () => {
    const malformed = {id: 'GHSA-aaaa-bbbb-cccc', review_by: '2026-11-30'}
    expect(check(report(minimatch), [malformed], '2026-11-01', since([], [malformed])).failures).toHaveLength(1)
    expect(check({error: {summary: 'registry unreachable'}}, [], '2026-11-01', since([])).failures).toEqual([
      'npm audit failed: registry unreachable'
    ])
  })

  it('passes an advisory on the list, in a changed package or not', () => {
    const listed = entry('GHSA-aaaa-bbbb-cccc')
    expect(check(report(minimatch), [listed], '2026-11-01', since(['minimatch'], [listed]))).toEqual({
      failures: [], warnings: [], allowed: [expect.objectContaining({id: 'GHSA-aaaa-bbbb-cccc'})]
    })
  })
})
