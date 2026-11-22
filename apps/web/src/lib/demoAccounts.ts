// Public demonstration credentials (also listed in the README). They exist only in the
// fictional clinic and the original synthetic workspace; never reuse them with real data.
export type DemoAccount = { label: string; role: string; password: string; showcaseOnly?: boolean };

export const DEMO_ACCOUNTS: DemoAccount[] = [
  { label: "Reception", role: "reception", password: "DemoReception1!" },
  { label: "Triage", role: "triage", password: "DemoTriage1!" },
  { label: "Clinician", role: "clinician", password: "DemoClinician1!" },
  { label: "Second clinician", role: "provider", password: "DemoProvider1!", showcaseOnly: true },
  { label: "Laboratory", role: "laboratory", password: "DemoLaboratory1!", showcaseOnly: true },
  { label: "Pharmacy", role: "pharmacy", password: "DemoPharmacy1!" },
  { label: "Research", role: "research", password: "DemoResearch1!" },
  { label: "Admin", role: "admin", password: "DemoAdmin1!" },
];

export const SHOWCASE_DOMAIN = "showcase.hutano.test";
export const accountsFor = (workspace: string) => DEMO_ACCOUNTS.filter((a) => workspace === "showcase" || !a.showcaseOnly);
export const emailFor = (account: DemoAccount, workspace: string) => `${account.role}@${workspace}.hutano.test`;
export const isShowcaseUser = (email: string) => email.toLowerCase().endsWith(`@${SHOWCASE_DOMAIN}`);
