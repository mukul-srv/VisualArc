export const DEFAULT_STEM = "fixture_a";

// Allowlist blocks path traversal: the stem is interpolated into a URL path.
export function isValidStem(s: string): boolean {
  return /^[A-Za-z0-9_-]+$/.test(s);
}

/** null query param -> default; present but invalid -> null. */
export function resolveStem(param: string | null): string | null {
  if (param === null) return DEFAULT_STEM;
  return isValidStem(param) ? param : null;
}
