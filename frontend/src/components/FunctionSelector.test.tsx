import { FUNCTION_ENUM_TO_ID, FUNCTION_METADATA } from "./FunctionSelector";

describe("FunctionSelector metadata", () => {
  test("uses unique function IDs", () => {
    const ids = FUNCTION_METADATA.map((fn) => fn.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  test("maps every exported function enum to known metadata", () => {
    const ids = new Set(FUNCTION_METADATA.map((fn) => fn.id));
    Object.values(FUNCTION_ENUM_TO_ID).forEach((id) => expect(ids.has(id)).toBe(true));
  });

  test("enabled functions provide user-facing titles and descriptions", () => {
    FUNCTION_METADATA.filter((fn) => !fn.disabled).forEach((fn) => {
      expect(fn.title.trim()).not.toBe("");
      expect(fn.description.trim()).not.toBe("");
    });
  });
});
