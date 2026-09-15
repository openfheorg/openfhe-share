// CookieStorageUtils.tsx
// Generic utility for storing structured data into named cookie entries

export function saveNamedDataToCookie<T>(
  cookieName: string,
  entryKey: string,
  data: T
): void {
  const allEntries: Record<string, string> = loadAllEntriesFromCookie(cookieName);
  allEntries[entryKey] = JSON.stringify(data);
  document.cookie = `${cookieName}=${encodeURIComponent(JSON.stringify(allEntries))}; path=/; max-age=31536000`;
}

export function loadAllEntriesFromCookie<T = unknown>(cookieName: string): Record<string, string> {
  const match = document.cookie.match(new RegExp(`(?:^| )${cookieName}=([^;]+)`));
  if (!match) return {};
  try {
    return JSON.parse(decodeURIComponent(match[1]));
  } catch {
    return {};
  }
}

export function deleteEntryFromCookie(cookieName: string, entryKey: string): void {
  const allEntries: Record<string, string> = loadAllEntriesFromCookie(cookieName);
  delete allEntries[entryKey];
  document.cookie = `${cookieName}=${encodeURIComponent(JSON.stringify(allEntries))}; path=/; max-age=31536000`;
}

export function clearCookie(cookieName: string): void {
  document.cookie = `${cookieName}=; path=/; max-age=0`;
}

export function serializeToJsonString<T>(obj: T): string {
  return JSON.stringify(obj);
}

export function deserializeFromJsonString<T>(raw: string): T | null {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}
