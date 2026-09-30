import type { Row, TenantInfo } from "../types";

/** The fields a handling option can preset (design: Handling per document), as the server's PRESETTABLE. */
export const PRESETTABLE = ["type", "contributor", "copyright", "language"] as const;
export type Presettable = (typeof PRESETTABLE)[number];

const same = (a: unknown, b: unknown) => JSON.stringify(a ?? "") === JSON.stringify(b ?? "");

/**
 * The field still holds what a preset put there, so it is marked PRESET: the user hasn't edited it, and it
 * equals its handling's preset or, for Language without one, the tenant's default language (as the server's
 * from_preset). The server fills presets (when a row is added and when its handling changes); this only tells
 * which values came from them.
 */
export function isPreset(row: Row, tenant: TenantInfo, field: Presettable): boolean {
  if ((row.touched ?? []).includes(field)) return false;
  const value = (row as unknown as Record<string, unknown>)[field];
  let preset: unknown = tenant.handling.find((h) => h.id === row.handling)?.presets?.[field];
  if (field === "language" && !(preset as string[] | undefined)?.length && tenant.languageDefault) preset = [tenant.languageDefault];
  return !!preset && (preset as string | string[]).length > 0 && same(value, preset);
}
