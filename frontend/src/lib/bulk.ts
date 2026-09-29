/**
 * Rules of the bulk-change panel (design: User interface, Bulk-change panel). The server applies the same
 * rules and refuses a change that any target can't take, so a bulk change is never applied partially.
 */
import type { Row } from "../types";

/** The panel's choices; a missing key means "no change". */
export type BulkChanges = Partial<Pick<Row, "handling" | "restricted" | "type" | "language" | "creator" | "contributor" | "rightsHolder" | "group">>;

type Problem = "done" | "excluded" | "created" | "handling" | "nogroup" | "grouped";

const PROBLEM_TEXT: Record<Problem, [string, string]> = { // [plural, singular]
  done: ["are already done", "is already done"],
  excluded: ["are excluded from the job (include them first)", "is excluded from the job (include it first)"],
  created: ["already created their records in CollectionSpace", "already created its records in CollectionSpace"],
  handling: ["keep their handling because the last run already found or created their objects (🔒)",
             "keeps its handling because the last run already found or created its object (🔒)"],
  nogroup: ["aren't linked to an object, so they can't join the group", "isn't linked to an object, so it can't join the group"],
  grouped: ["already have their objects in the group", "already has its object in the group"],
};

export function isDone(r: Row): boolean {
  return r.result?.state === "Done";
}

/** True once the row created anything in CollectionSpace (finding an existing object doesn't count). */
export function isLocked(r: Row): boolean {
  return Object.entries(r.result?.steps ?? {}).some(([name, st]) => name !== "findObject" && !!st.csid && !st.found && !st.sameAs);
}

/** A Failed row whose object step already ran keeps its object, so its handling can't change. */
export function objectStepRan(r: Row): boolean {
  const s = r.result?.steps ?? {};
  return s.findObject?.s === "done" || s.createObject?.s === "done" || s.findOrCreateObject?.s === "done";
}

/** Would these choices change this row? Choosing a value it already has is no change. */
export function rowChanges(r: Row, c: BulkChanges): boolean {
  return (Object.keys(c) as (keyof BulkChanges)[]).some((k) => {
    const have = k === "group" ? r.group ?? true : r[k];
    return JSON.stringify(have ?? null) !== JSON.stringify(c[k] ?? null);
  });
}

/** linking: the handlings that link to an object (only those documents can join the job's group). */
function rowProblem(r: Row, c: BulkChanges, linking?: Set<string>): Problem | null {
  if (!rowChanges(r, c)) return null;
  if (isDone(r)) return "done";
  if (!r.include) return "excluded";
  if (c.group !== undefined && c.group !== (r.group ?? true) && r.result?.steps?.addToGroup?.s === "done") return "grouped";
  if (isLocked(r)) return "created";
  if (c.handling !== undefined && c.handling !== r.handling && objectStepRan(r)) return "handling";
  if (c.group === true && linking && !linking.has(c.handling ?? r.handling)) return "nogroup";
  return null;
}

/** Apply to all: every document that still has work to do, skipping Done, Partial and excluded rows. */
export function applyAllTargets(rows: Row[]): Row[] {
  return rows.filter((r) => r.include && !isDone(r) && !isLocked(r));
}

export interface BulkVerdict {
  ok: boolean;
  picked: boolean;
  neutral?: boolean;
  why: string;
}

/** Can every target take every chosen change? If not, a one-line reason for the greyed-out buttons. */
export function bulkCheck(targets: Row[], c: BulkChanges, all: boolean, linking?: Set<string>): BulkVerdict {
  if (!Object.keys(c).length) return { ok: false, picked: false, why: "Choose a change first." };
  if (!targets.length) {
    return { ok: false, picked: true, why: all ? "No documents still to run: every document is done or excluded." : "No documents to change." };
  }
  const counts = new Map<Problem, number>();
  targets.forEach((r) => { const p = rowProblem(r, c, linking); if (p) counts.set(p, (counts.get(p) ?? 0) + 1); });
  const bad = [...counts.values()].reduce((a, b) => a + b, 0);
  if (!bad) {
    if (targets.some((r) => rowChanges(r, c))) return { ok: true, picked: true, why: "" };
    const who = all ? "documents still to run" : targets.length === 1 ? "selected document" : "selected documents";
    return { ok: false, picked: true, neutral: true,
      why: `Nothing to change: the ${who} already ${targets.length === 1 && !all ? "has" : "have"} these values.` };
  }
  const noun = all ? "documents still to run" : "selected documents";
  if (targets.length === 1) {
    const [p] = [...counts.keys()];
    return { ok: false, picked: true, why: `The ${all ? "one document still to run" : "selected document"} can’t take this change: it ${PROBLEM_TEXT[p][1]}.` };
  }
  const parts = [...counts.entries()].map(([p, n]) => `${n} ${PROBLEM_TEXT[p][n === 1 ? 1 : 0]}`).join("; ");
  const lead = bad === targets.length ? `None of the ${targets.length} ${noun} can take this change: `
                                      : `${bad} of the ${targets.length} ${noun} can’t take this change: `;
  return { ok: false, picked: true,
    why: lead + parts + (all ? ". Change your choice, or select the documents it fits." : `. Deselect ${bad === 1 ? "it" : "them"} or change your choice.`) };
}

/** Exclude selected / Include selected: the selected rows with work left whose exclusion would change. */
export function includeTargets(selected: Row[], include: boolean): Row[] {
  return selected.filter((r) => !isDone(r) && r.include !== include);
}
