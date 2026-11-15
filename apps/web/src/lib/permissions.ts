import type { User } from "./types";

// Presentation only; every server mutation independently enforces these boundaries.
export function canOperateService(user: User, type: string): boolean {
  return (user.roles.includes("PHARMACY") && type === "pharmacy") ||
    (user.roles.includes("TRIAGE_NURSE") && type === "triage") ||
    (user.roles.includes("CLINICIAN") && ["triage", "consultation", "laboratory", "discharge"].includes(type)) ||
    (user.roles.includes("SERVICE_PROVIDER") && ["consultation", "laboratory", "discharge"].includes(type));
}
