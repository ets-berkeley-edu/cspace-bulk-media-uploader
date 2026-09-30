/**
 * Paging, sorting and filtering for every table (design: User interface, Large jobs). A 1,000-document job is
 * a few hundred KB, so the whole job is in the browser and this all runs here.
 *
 * Sorting cycles ascending, descending, then back to the original order; ties keep the original order.
 */
import { reactive } from "vue";

export const PAGE_SIZES = [25, 50, 100] as const;

export interface TableState {
  page: number;
  size: number;
  sort: string | null;
  dir: 1 | -1;
  filter: string;
}

export function tableState(size = 25): TableState {
  return reactive({ page: 1, size, sort: null, dir: 1, filter: "all" }) as TableState;
}

export type SortKey<T> = (x: T) => string | number;

export interface View<T> {
  all: T[]; // every item that passes the filter, in display order
  shown: T[]; // the current page
  total: number; // items passing the filter
  of: number; // items before filtering
  pages: number;
  start: number; // index of the first shown item in `all`
}

export function compareValues(a: string | number, b: string | number): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

/** Filter, sort (stable) and page a list. Without paging (lists of jobs), pass paged = false. */
export function tableView<T>(items: T[], st: TableState, keys: Record<string, SortKey<T>>,
                             filter?: (x: T, f: string) => boolean, paged = true): View<T> {
  let idx = items.map((x, i) => ({ x, i }));
  if (filter && st.filter !== "all") idx = idx.filter(({ x }) => filter(x, st.filter));
  const key = st.sort ? keys[st.sort] : undefined;
  if (key) {
    const k = new Map(idx.map(({ x, i }) => [i, key(x)]));
    idx.sort((a, b) => compareValues(k.get(a.i)!, k.get(b.i)!) * st.dir || a.i - b.i);
  }
  const all = idx.map(({ x }) => x);
  if (!paged) return { all, shown: all, total: all.length, of: items.length, pages: 1, start: 0 };
  const pages = Math.max(1, Math.ceil(all.length / st.size));
  if (st.page > pages) st.page = pages;
  if (st.page < 1) st.page = 1;
  const start = (st.page - 1) * st.size;
  return { all, shown: all.slice(start, start + st.size), total: all.length, of: items.length, pages, start };
}

/** A click on a column heading: ascending, then descending, then the original order. */
export function cycleSort(st: TableState, key: string): void {
  if (st.sort !== key) { st.sort = key; st.dir = 1; }
  else if (st.dir === 1) st.dir = -1;
  else { st.sort = null; st.dir = 1; }
  st.page = 1;
}

/**
 * The editor's document table: preview, select, expand, document, handling, publish, public portal, status and
 * exclude, plus the Group column when the job has a group and the Delete column while the job can be edited.
 * Detail rows and empty-table rows span all of them.
 */
export function editorColumns(groupOn: boolean, deletable: boolean): number {
  return 9 + (groupOn ? 1 : 0) + (deletable ? 1 : 0);
}
