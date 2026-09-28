/** Describe a structured date group from CollectionSpace's parser, as shown under the Date field. */
import { displayName } from "./refname";

export type DateGroup = Record<string, string>;

function ymd(y?: string, m?: string, d?: string): string {
  if (!y) return "";
  const p = (s: string) => s.padStart(2, "0");
  return [y, m && p(m), m && d && p(d)].filter(Boolean).join("-");
}

export function describeDate(g: DateGroup): string {
  const e = ymd(g.dateEarliestSingleYear, g.dateEarliestSingleMonth, g.dateEarliestSingleDay);
  const l = ymd(g.dateLatestYear, g.dateLatestMonth, g.dateLatestDay);
  if (!e) return "";
  const range = !l || l === e ? `Earliest and latest ${e}` : `Earliest ${e} · latest ${l}`;
  const cert = g.dateEarliestSingleCertainty || g.dateLatestCertainty;
  return range + (cert ? ` · ${displayName(cert)}` : "");
}
