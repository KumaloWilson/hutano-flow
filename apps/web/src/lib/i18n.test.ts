import { describe, expect, it } from "vitest";
import { COPY, fill } from "./i18n";

describe("patient-facing copy", () => {
  it("has every English key in Shona and Ndebele, with the same placeholders", () => {
    const keys = Object.keys(COPY.en) as (keyof typeof COPY.en)[];
    for (const lang of ["sn", "nd"] as const) {
      for (const key of keys) {
        expect(COPY[lang][key], `${lang}.${key}`).toBeTruthy();
        const placeholders = (text: string) => (text.match(/\{\w+\}/g) || []).sort().join();
        expect(placeholders(COPY[lang][key]), `${lang}.${key}`).toBe(placeholders(COPY.en[key]));
      }
    }
  });
  it("fills placeholders", () => {
    expect(fill(COPY.en.range, { min: 5, max: 20 })).toBe("5–20 min");
  });
});
