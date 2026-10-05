import {describe, expect, it} from 'vitest'
import {displayName, isRefName} from '../lib/refname'
import {formatBytes, mapLimit} from '../lib/files'
import {checksColor, checksText, jobCounts, rowStatus, runName, runNumber} from '../lib/status'
import {isPreset} from '../lib/presets'
import type {Row, TenantInfo} from '../types'

describe('refName', () => {
  it('shows only the display name', () => {
    const ref = 'urn:cspace:pahma.cspace.berkeley.edu:personauthorities:name(person):item:name(7475)\'Leslie Freund\''
    expect(displayName(ref)).toBe('Leslie Freund')
    expect(isRefName(ref)).toBe(true)
    expect(displayName('')).toBe('')
    expect(displayName('plain')).toBe('plain')
  })
})

describe('files', () => {
  it('maps a few at a time, keeping the order', async () => {
    let running = 0, most = 0
    const out = await mapLimit([5, 1, 3, 2], 2, async (x) => {
      running++; most = Math.max(most, running)
      await new Promise((r) => setTimeout(r, x))
      running--
      return x * 10
    })
    expect(out).toEqual([50, 10, 30, 20])
    expect(most).toBe(2)
  })
  it('formats sizes', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(3 * 1024 * 1024)).toBe('3.0 MB')
  })
})

describe('which run a job is on', () => {
  it('names it in words: a queued job\'s next run, a running job\'s current one', () => {
    expect(runName({status: 'Queued', run: 0})).toBe('first run')
    expect(runName({status: 'Running', run: 1})).toBe('first run') // not "rerun (run 1)"
    expect(runName({status: 'Queued', run: 1})).toBe('second run')
    expect(runName({status: 'Running', run: 3})).toBe('third run')
    expect(runName({status: 'Queued', run: 10})).toBe('run 11')
    expect(runNumber({})).toBe(1)
  })
})

describe('job counts', () => {
  const base = {n: 1, file: 'a.jpg', size: 1, contentType: '', handling: 'link', obj: '1', objParsed: '1', img: '', parseOk: true,
    idnum: '1', date: '', restricted: false, type: [], creator: '', contributor: '', rightsHolder: '', description: '', copyright: '',
    include: true, upload: {s: 'done' as const}, checks: [], result: null}
  it('counts only rows with work left, and uploads still on their way', () => {
    const c = jobCounts([
      {...base, checks: [{level: 'block', text: 'x'}]},
      {...base, n: 2, checks: [{level: 'warn', text: 'y'}]},
      {...base, n: 3, include: false, checks: [{level: 'block', text: 'ignored'}]},
      {...base, n: 4, upload: {s: 'verifying'}},
      {...base, n: 5, result: {state: 'Done'}},
    ])
    expect(c).toMatchObject({total: 5, disabled: 1, work: 3, block: 1, warn: 1, uploading: 1, uploaded: 2})
  })
})

describe('status by object behavior', () => {
  const tenant = {handling: [
    {id: 'link', label: 'Link to existing object', object: 'existing', id_rule: 'object'},
    {id: 'linkorcreate', label: 'Link to object (create if missing)', object: 'either', id_rule: 'object'},
    {id: 'create', label: 'Create new object + link', object: 'create', id_rule: 'object'},
  ]} as unknown as TenantInfo
  const row = (handling: string, csids: string[] | null) => ({n: 1, file: '1-2_a.jpg', size: 1, contentType: '', handling, obj: '1-2',
    objParsed: '1-2', img: '', parseOk: true, idnum: '1-2', date: '', restricted: false, type: [], creator: '', contributor: '',
    rightsHolder: '', description: '', copyright: '', include: true, upload: {s: 'done' as const}, checks: [], result: null,
    lookups: csids ? {object: {value: '1-2', csids, at: 0}} : undefined})
  it('says whether the object will be found or created', () => {
    expect(rowStatus(row('linkorcreate', ['o1']), tenant).text).toBe('Found — will link')
    expect(rowStatus(row('linkorcreate', []), tenant).text).toBe('Will create object')
    expect(rowStatus(row('create', []), tenant).text).toBe('Will create object')
    expect(rowStatus(row('link', ['o1']), tenant).text).toBe('Found — will link')
    expect(rowStatus(row('create', null), tenant).text).toBe('Not checked yet')
  })

  it('has three kinds of result (design: Roles): needs fixing, needs an Object creator, and neither', () => {
    const creator = {...row('linkorcreate', []), checks: [{level: 'creator' as const, text: 'needs a new Object'}]}
    expect(rowStatus(creator, tenant)).toEqual({text: 'Needs an Object creator', tone: 'creator'})
    const both = {...creator, checks: [...creator.checks, {level: 'block' as const, text: 'bad date'}]}
    expect(rowStatus(both, tenant).text).toBe('Needs fixing')
    expect(jobCounts([creator, both, row('link', ['o1'])])).toMatchObject({work: 3, block: 1, creator: 1})
  })

  it('counts them separately in the checks chip', () => {
    expect(checksText({block: 0, warn: 0, creator: 3})).toBe('nothing to fix · 3 need an Object creator')
    expect(checksText({block: 2, warn: 1, creator: 1})).toBe('2 need fixing · 1 needs an Object creator · 1 warning')
    expect(checksColor({block: 0, warn: 1, creator: 1})).toBe('creator')
    // someone who can create Objects sees which drafts wait for them
    expect(checksText({block: 0, warn: 0, creator: 0, newObjects: 2})).toBe('nothing to fix · 2 new Objects')
    expect(checksColor({block: 0, warn: 0, creator: 0, newObjects: 2})).toBe('success')
  })
})

describe('supported file types (design: Supported file types)', () => {
  it('skips files of other types and says which, accepting PDF', async () => {
    const {splitSupported, skippedText, fileKind} = await import('../lib/files')
    const types = ['jpg', 'jpeg', 'tif', 'tiff', 'png', 'pdf', 'wav', 'mp3', 'aac', 'mp4', 'x3d']
    const r = splitSupported([{name: '15-1234.JPG'}, {name: 'notes.pdf'}, {name: '.DS_Store'}, {name: 'a.docx'}], types)
    expect(r.ok.map((f) => f.name)).toEqual(['15-1234.JPG', 'notes.pdf'])
    expect(r.skipped.map((f) => f.name)).toEqual(['.DS_Store', 'a.docx'])
    expect(skippedText(['.DS_Store', 'a.docx'], 'JPEG or PDF')).toBe('2 files skipped: .DS_Store, a.docx. The BMU accepts JPEG or PDF.')
    expect(splitSupported([{name: 'a.docx'}], undefined).ok).toHaveLength(1)
    expect(fileKind('notes.pdf').label).toBe('PDF document')
  })
})

describe('presets (design: Handling per document)', () => {
  const eng = 'urn:cspace:pahma.cspace.berkeley.edu:vocabularies:name(languages):item:name(eng)\'English\''
  const spa = 'urn:cspace:pahma.cspace.berkeley.edu:vocabularies:name(languages):item:name(spa)\'Spanish\''
  const t = {languageDefault: eng, handling: [{id: 'link', label: '', object: 'existing', id_rule: 'object', presets: {}},
    {id: 'slide', label: '', object: 'none', id_rule: 'image', presets: {type: ['slide'], language: [spa], copyright: '© R'}}]} as unknown as TenantInfo
  const r = (p: Record<string, unknown>) => ({handling: 'link', type: [], language: [eng], copyright: '', touched: [], ...p}) as unknown as Row
  it('a field is PRESET while it holds its handling\'s preset and the user hasn\'t edited it', () => {
    expect(isPreset(r({handling: 'slide', type: ['slide']}), t, 'type')).toBe(true)
    expect(isPreset(r({handling: 'slide', type: ['slide'], touched: ['type']}), t, 'type')).toBe(false)
    expect(isPreset(r({handling: 'slide', type: ['slide', 'image']}), t, 'type')).toBe(false)
    expect(isPreset(r({handling: 'slide', copyright: '© R'}), t, 'copyright')).toBe(true)
    expect(isPreset(r({}), t, 'type')).toBe(false) // empty is never a preset
    expect(isPreset(r({}), t, 'copyright')).toBe(false)
  })
  it('Language is PRESET with the tenant\'s default only when the handling presets no language', () => {
    expect(isPreset(r({}), t, 'language')).toBe(true)
    expect(isPreset(r({handling: 'slide'}), t, 'language')).toBe(false)
    expect(isPreset(r({handling: 'slide', language: [spa]}), t, 'language')).toBe(true)
  })
})
