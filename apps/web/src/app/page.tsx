"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { User } from "@/lib/types";
import { ServiceWorker } from "@/components/ServiceWorker";
import { Icon } from "@/components/ui/Icon";

const accounts = [
  ["Reception", "reception@demo.hutano.test", "DemoReception1!"],
  ["Clinician", "clinician@demo.hutano.test", "DemoClinician1!"],
  ["Triage", "triage@demo.hutano.test", "DemoTriage1!"],
  ["Pharmacy", "pharmacy@demo.hutano.test", "DemoPharmacy1!"],
  ["Research", "research@demo.hutano.test", "DemoResearch1!"],
  ["Admin", "admin@demo.hutano.test", "DemoAdmin1!"],
];

/** Abstract journey rail: tickets moving through four stations. Purely decorative. */
function FlowArt() {
  const stations = [40, 200, 360, 520];
  return (
    <div className="flow-art" aria-hidden="true">
      <svg viewBox="0 0 560 150" fill="none">
        <line x1="40" y1="96" x2="520" y2="96" stroke="#2a2f35" strokeWidth="3" />
        <line x1="40" y1="96" x2="300" y2="96" stroke="#3dbd93" strokeWidth="3" />
        {stations.map((x, i) => <g key={x}>
          <circle cx={x} cy="96" r="11" fill={i < 2 ? "#3dbd93" : "#0f1113"} stroke={i < 2 ? "#3dbd93" : "#3a4047"} strokeWidth="3" />
          <text x={x} y="132" fill="#7d828a" fontSize="12" textAnchor="middle" fontFamily="var(--font-ui)">{["Arrive", "Triage", "Consult", "Pharmacy"][i]}</text>
        </g>)}
        {[["A-012", 112, "#f2f0ea"], ["A-013", 268, "#3dbd93"], ["A-014", 430, "#f2f0ea"]].map(([label, x, fill]) => <g key={String(label)} transform={`translate(${Number(x) - 34} 34)`}>
          <rect width="68" height="30" rx="6" fill={String(fill)} />
          <line x1="9" y1="6" x2="9" y2="24" stroke="#0f1113" strokeOpacity=".35" strokeDasharray="2 3" strokeWidth="2" />
          <text x="38" y="20" fill="#0f1113" fontSize="13" fontWeight="600" textAnchor="middle" fontFamily="var(--font-num)">{label}</text>
        </g>)}
      </svg>
    </div>
  );
}

export default function LoginPage() {
  const router = useRouter();
  const [workspace, setWorkspace] = useState("showcase");
  const [email, setEmail] = useState("reception@showcase.hutano.test");
  const [password, setPassword] = useState(accounts[0][2]);
  const [chosen, setChosen] = useState("Reception");
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
    setChosen(account[0]);
    setEmail(account[1].replace("@demo.", `@${workspace}.`));
    setPassword(account[2]);
  }

  return (
    <main className="login-shell" id="main">
      <ServiceWorker />
      <section className="login-intro">
        <div className="brand-row"><span className="brand-mark"><Icon name="route" /></span>Hutano Flow</div>
        <div>
          <h1>Every patient, every stage, in view.</h1>
          <p className="lead">A queue workspace for outpatient clinics. Staff see who is waiting and for how long, call patients in a fair order, and every decision is recorded.</p>
          <FlowArt />
        </div>
        <div className="safety-card">
          <span className="icon-shield"><Icon name="shield" /></span>
          <div><strong>Clinicians stay in charge</strong><p>Only a clinician sets a patient&apos;s priority. Any model output is advisory and labelled experimental.</p></div>
        </div>
      </section>
      <section className="login-panel">
        <div className="login-card">
          <h2>Sign in</h2>
          <p>Demonstration workspace. Every patient and history here is fictional.</p>
          <label>Workspace<select value={workspace} onChange={(e) => { setWorkspace(e.target.value); setEmail(`reception@${e.target.value}.hutano.test`); setPassword("DemoReception1!"); setChosen("Reception"); }}>
            <option value="showcase">Hutano Community Clinic (fictional)</option>
            <option value="demo">Original research workspace</option>
          </select></label>
          <div className="account-pills" role="group" aria-label="Demo accounts">
            {accounts.map((account) => <button type="button" key={account[0]} aria-pressed={chosen === account[0]} onClick={() => choose(account)}>{account[0]}</button>)}
          </div>
          <form onSubmit={submit}>
            <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required /></label>
            <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></label>
            {error && <div className="error" role="alert">{error}</div>}
            <button className="primary wide large" disabled={loading}>{loading ? "Signing in…" : "Sign in to workspace"}</button>
          </form>
          <a className="patient-link" href="/status"><span>Waiting for care? Check your place in the queue.</span><strong>Open <Icon name="arrow" size={16} /></strong></a>
        </div>
      </section>
    </main>
  );
}
