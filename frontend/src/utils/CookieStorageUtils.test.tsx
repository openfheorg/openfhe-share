import {
  clearCookie,
  deleteEntryFromCookie,
  deserializeFromJsonString,
  loadAllEntriesFromCookie,
  saveNamedDataToCookie,
  serializeToJsonString,
} from "./CookieStorageUtils";

describe("CookieStorageUtils", () => {
  beforeEach(() => {
    document.cookie.split(";").forEach((cookie) => {
      const name = cookie.split("=")[0].trim();
      if (name) document.cookie = `${name}=; path=/; max-age=0`;
    });
  });

  test("serializes and deserializes JSON", () => {
    const value = { projectId: 2, enabled: true };
    expect(deserializeFromJsonString(serializeToJsonString(value))).toEqual(value);
  });

  test("returns null for invalid JSON", () => {
    expect(deserializeFromJsonString("not json")).toBeNull();
  });

  test("stores multiple named entries in the same cookie", () => {
    saveNamedDataToCookie("share-test", "one", { id: 1 });
    saveNamedDataToCookie("share-test", "two", { id: 2 });

    const stored = loadAllEntriesFromCookie("share-test");
    expect(JSON.parse(stored.one)).toEqual({ id: 1 });
    expect(JSON.parse(stored.two)).toEqual({ id: 2 });
  });

  test("deletes one entry without removing the others", () => {
    saveNamedDataToCookie("share-test", "one", { id: 1 });
    saveNamedDataToCookie("share-test", "two", { id: 2 });
    deleteEntryFromCookie("share-test", "one");

    const stored = loadAllEntriesFromCookie("share-test");
    expect(stored.one).toBeUndefined();
    expect(JSON.parse(stored.two)).toEqual({ id: 2 });
  });

  test("clears a named cookie", () => {
    saveNamedDataToCookie("share-test", "one", { id: 1 });
    clearCookie("share-test");
    expect(loadAllEntriesFromCookie("share-test")).toEqual({});
  });

  test("returns an empty object for malformed cookie data", () => {
    document.cookie = "share-test=%7Bbroken; path=/";
    expect(loadAllEntriesFromCookie("share-test")).toEqual({});
  });
});
