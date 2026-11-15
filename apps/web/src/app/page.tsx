"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { User } from "@/lib/types";
import { ServiceWorker } from "@/components/ServiceWorker";

const accounts = [
  ["Reception", "reception@demo.hutano.test", "DemoReception1!"],
  ["Clinician", "clinician@demo.hutano.test", "DemoClinician1!"],
  ["Research", "research@demo.hutano.test", "DemoResearch1!"],
  ["Admin", "admin@demo.hutano.test", "DemoAdmin1!"],
  ["Triage", "triage@demo.hutano.test", "DemoTriage1!"],
  ["Pharmacy", "pharmacy@demo.hutano.test", "DemoPharmacy1!"],
];

export default function LoginPage() {
  const router = useRouter();
  const [workspace,setWorkspace]=useState("showcase");
  const [email, setEmail] = useState("reception@showcase.hutano.test");
  const [password, setPassword] = useState(accounts[0][2]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api<User>("/api/v1/me").then(() => router.replace("/dashboard")).catch(() => undefined);
  }, [router]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      await api<{ user: User }>("/api/v1/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
      router.push("/dashboard");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Unable to sign in");
    } finally {
      setLoading(false);
    }
  }

  function choose(account: string[]) {
    setEmail(account[1].replace("@demo.",`@${workspace}.`));
    setPassword(account[2]);
  }

  return (
    <main className="login-shell">
      <ServiceWorker />
      <section className="login-intro">
        <div className="brand-mark">HF</div>
        <p className="eyebrow">Outpatient flow research</p>
        <h1>Careful queues.<br />Visible decisions.</h1>
        <p className="lead">Hutano Flow helps a demo clinic trace each stage, explain queue recommendations, and keep clinical authority exactly where it belongs.</p>
        <div className="safety-card">
          <span className="icon-shield" aria-hidden="true">◇</span>
          <div><strong>Clinician-supervised by design</strong><p>AI can suggest. It never assigns clinical urgency or treatment.</p></div>
        </div>
      </section>
      <section className="login-panel">
        <div className="login-card">
          <p className="eyebrow">Secure demo access</p>
          <h2>Welcome back</h2>
          <p>Choose a workspace and role. All clinic identities and histories are fictional.</p>
          <label>Demonstration workspace<select value={workspace} onChange={e=>{setWorkspace(e.target.value);setEmail(`reception@${e.target.value}.hutano.test`);setPassword("DemoReception1!");}}><option value="showcase">Hutano Community Clinic · fictional</option><option value="demo">Original research workspace</option></select></label><div className="account-pills" aria-label="Demo accounts">
            {accounts.map((account) => <button type="button" key={account[0]} onClick={() => choose(account)}>{account[0]}</button>)}
          </div>
          <form onSubmit={submit}>
            <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required /></label>
            <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></label>
            {error && <div className="error" role="alert">{error}</div>}
            <button className="primary wide" disabled={loading}>{loading ? "Signing in…" : "Sign in to workspace"}</button>
          </form>
          <a className="patient-link" href="/status">Checking your queue status? <strong>Use your private token →</strong></a>
        </div>
      </section>
    </main>
  );
}

