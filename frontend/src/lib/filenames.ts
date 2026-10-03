/**
 * The filename rules for renaming a document (design: Editable numbers and names; the same rules as the
 * server, which has the final say), and the "(parsed)" / "edited — differs from …" labels.
 */
import type {Row, TenantInfo} from '../types'

const MAX = 100

function split(name: string): { stem: string; ext: string } {
  const k = name.lastIndexOf('.')
  return k > 0 ? {stem: name.slice(0, k), ext: name.slice(k + 1)} : {stem: name, ext: ''}
}

/** The tenant's filename pattern (a Python regular expression with named parts) as a JavaScript one. */
function pattern(t: TenantInfo): RegExp {
  return new RegExp(t.filenamePattern.replace(/\(\?P</g, '(?<'))
}

export function filenameProblems(t: TenantInfo, name: string, original: string, otherNames: string[]): string[] {
  if (!name) return ['Enter a filename.']
  const errs: string[] = []
  const origExt = split(original).ext.toLowerCase()
  if (name.length > MAX) errs.push(`Use ${MAX} characters or fewer.`)
  if (/[/\\]/.test(name)) errs.push('Remove slashes; a filename can\'t include a folder.')
  if (name.includes('..')) errs.push('Remove the double dot (..).')
  if (name.startsWith('.')) errs.push('A filename can\'t start with a dot.')
  if (/\s/.test(name)) errs.push('Remove spaces; use _ or - instead.')
  if (!/^[A-Za-z0-9._-]+$/.test(name.replace(/[\s/\\]/g, '') || 'x')) errs.push('Use only letters, numbers, dots, hyphens and underscores.')
  const {stem, ext} = split(name)
  if (!ext) errs.push(`Keep the file extension (.${origExt}).`)
  else if (ext.toLowerCase() !== origExt) errs.push(`Keep the extension .${origExt}; renaming can't change the file type.`)
  if (otherNames.some((o) => o.toLowerCase() === name.toLowerCase())) errs.push('Another document in this job already has this name.')
  if (!errs.length && !pattern(t).test(stem)) errs.push(`Doesn't match ${t.name}'s filename pattern: ${t.filenameHint}.`)
  return errs
}

export interface NumberLabel {
  text: string;
  edited: boolean;
  reset?: string; // the value "Use parsed value" restores
}

export function objectLabel(r: Row): NumberLabel {
  return r.obj === r.objParsed ? {text: '(parsed)', edited: false}
    : {text: `(edited — differs from parsed value ${r.objParsed || '(none)'})`, edited: true, reset: r.objParsed}
}

export function idLabel(r: Row, t: TenantInfo): NumberLabel {
  const rule = t.handling.find((h) => h.id === r.handling)?.id_rule
  const parsed = rule === 'image' ? r.img : r.objParsed
  const derived = rule === 'image' ? r.img : r.obj
  if (r.idnum === parsed) return {text: '(parsed)', edited: false}
  if (r.idnum === derived) return {text: '(from the edited object number)', edited: true}
  return {text: `(edited — differs from parsed value ${parsed || '(none)'})`, edited: true, reset: parsed}
}
