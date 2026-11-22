"use client";
import { useState } from "react";
import { api, errorText } from "@/lib/api";
import type { User } from "@/lib/types";
import { accountsFor, emailFor, isShowcaseUser } from "@/lib/demoAccounts";

/** One-step role change for a presenter, shown only inside the fictional clinic. */
export function DemoRoleSwitch({ user }: { user: User }) {
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  if (!isShowcaseUser(user.email)) return null;
  const current = user.email.split("@")[0];
  async function change(role: string) {
    const account = accountsFor("showcase").find((a) => a.role === role);
    if (!account || role === current) return;
    setBusy(true); setError("");
    try {
      await api("/api/v1/auth/logout", { method: "POST" }).catch(() => undefined);
      await api("/api/v1/auth/login", { method: "POST", body: JSON.stringify({ email: emailFor(account, "showcase"), password: account.password }) });
      window.location.assign("/dashboard");
    } catch (e) { setError(errorText(e)); setBusy(false); }
  }
  return <label className="demo-switch" title="Fictional clinic only: sign in as another demo role">
    <span>Demo role</span>
    <select aria-label="Switch demo role" value={current} disabled={busy} onChange={(e) => change(e.target.value)}>
      {accountsFor("showcase").map((a) => <option key={a.role} value={a.role}>{a.label}</option>)}
    </select>
    {error && <small role="alert" className="error">{error}</small>}
  </label>;
}
