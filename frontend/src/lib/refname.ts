/** The display part of a CollectionSpace refName: urn:...:item:name(x)'Display Name' → Display Name. */
export function displayName(refName: string | null | undefined): string {
  if (!refName) return "";
  const end = refName.length - 1;
  if (refName[end] === "'") {
    const start = refName.indexOf("'");
    if (start >= 0 && start < end) return refName.slice(start + 1, end);
  }
  return refName;
}

export function isRefName(value: string): boolean {
  return value.startsWith("urn:cspace:");
}
