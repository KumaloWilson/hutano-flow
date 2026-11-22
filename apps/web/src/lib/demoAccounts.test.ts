import { describe, expect, it } from "vitest";
import { accountsFor, emailFor, isShowcaseUser } from "./demoAccounts";

describe("demo accounts", () => {
  it("offers laboratory and second clinician only in the fictional clinic", () => {
    const roles = (w: string) => accountsFor(w).map((a) => a.role);
    expect(roles("showcase")).toEqual(expect.arrayContaining(["laboratory", "provider"]));
    expect(roles("demo")).not.toContain("laboratory");
    expect(roles("demo")).not.toContain("provider");
  });
  it("builds workspace addresses and recognises fictional-clinic users only", () => {
    const lab = accountsFor("showcase").find((a) => a.role === "laboratory")!;
    expect(emailFor(lab, "showcase")).toBe("laboratory@showcase.hutano.test");
    expect(isShowcaseUser("Triage@Showcase.Hutano.Test")).toBe(true);
    expect(isShowcaseUser("triage@demo.hutano.test")).toBe(false);
    expect(isShowcaseUser("someone@showcase.hutano.test.example.org")).toBe(false);
  });
});
