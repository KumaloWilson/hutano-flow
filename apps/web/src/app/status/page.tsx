"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, ApiError, formatClock } from "@/lib/api";
import { ServiceWorker } from "@/components/ServiceWorker";
import { Icon } from "@/components/ui/Icon";
import { Rail, Ticket } from "@/components/ui/primitives";
import { COPY, fill, LANGS, storedLang, storeLang, type Lang } from "@/lib/i18n";

type Status = {
  token: string; stage: string; status: string; people_ahead: number | null; room?: string | null;
  estimated_wait: { minimum_minutes: number; maximum_minutes: number; warning: string } | null;
  journey?: { name: string; state: "done" | "current" | "next" }[]; updated_at: string;
};
const SESSION_KEY = "hutano-status-token";

export default function StatusPage() {
  const [lang, setLang] = useState<Lang>("en");
  const t = COPY[lang];
  const [token, setToken] = useState("");
  const [active, setActive] = useState("");
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
  const [busy, setBusy] = useState(false);

  const lookup = useCallback(async (value: string) => {
    const result = await api<Status>("/api/v1/patient-status/lookup", { method: "POST", body: JSON.stringify({ token: value }) });
    setStatus(result); setStale(false); setError("");
  }, []);

  const begin = useCallback(async (value: string) => {
    setBusy(true); setError("");
    try {
      await lookup(value);
      setActive(value);
      try { sessionStorage.setItem(SESSION_KEY, value); } catch { /* private mode */ }
    } catch (e) {
      setStatus(null);
      setError(e instanceof ApiError && e.status === 429 ? "tooMany" : "notFound");
    } finally { setBusy(false); }
  }, [lookup]);

  // A receipt QR opens /status#t=<token>. The fragment never reaches the server; we read it,
  // then remove it from the address bar and history so the token is not left behind.
  useEffect(() => {
    setLang(storedLang());
    const fromHash = new URLSearchParams(window.location.hash.slice(1)).get("t");
    let saved = "";
    try { saved = sessionStorage.getItem(SESSION_KEY) || ""; } catch { /* ignore */ }
    const initial = fromHash || saved;
    if (fromHash) window.history.replaceState(null, "", window.location.pathname);
    if (initial) { setToken(initial); begin(initial); }
  }, [begin]);

  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => { lookup(active).catch(() => setStale(true)); }, 10000);
    return () => clearInterval(timer);
  }, [active, lookup]);

  function choose(code: Lang) { setLang(code); storeLang(code); document.documentElement.lang = code; }
  function reset() { setActive(""); setStatus(null); setToken(""); try { sessionStorage.removeItem(SESSION_KEY); } catch { /* ignore */ } }
  async function submit(event: FormEvent) { event.preventDefault(); await begin(token.trim()); }

  const called = status?.status === "CALLED";
  const ahead = status?.people_ahead;
  return (
    <main className="status-shell" id="main">
      <ServiceWorker />
      <div className="status-top">
        <a href="/" className="back-link"><Icon name="arrow" size={14} className="flip" />{t.staffSignIn}</a>
        <div className="lang-switch" role="group" aria-label={t.language}>
          {LANGS.map((item) => <button key={item.code} type="button" aria-pressed={lang === item.code} onClick={() => choose(item.code)} lang={item.code}>{item.label}</button>)}
        </div>
      </div>
      <section className="status-card" aria-live="polite">
        {!status ? <>
          <h1>{t.title}</h1>
          <p>{t.intro}</p>
          <form onSubmit={submit}>
            <label>{t.tokenLabel}<input value={token} onChange={(e) => setToken(e.target.value)} minLength={20} autoComplete="off" autoCapitalize="none" spellCheck={false} required placeholder="A-001.••••••••" /></label>
            {error && <div className="error" role="alert">{t[error as "notFound" | "tooMany"]}</div>}
            <button className="primary wide large" disabled={busy}>{busy ? t.checking : t.check}</button>
          </form>
        </> : <div className="patient-result">
          {called && <div className="called-banner" role="alert"><strong>{t.yourTurn}</strong><span>{fill(t.goTo, { place: status.room ? `${status.stage} · ${status.room}` : status.stage })}</span></div>}
          <div className="status-hero">
            <Ticket token={status.token} large />
            <h2 className="stage-name">{status.status === "COMPLETED" ? t.done : status.status === "STAFF_ASSISTANCE" ? t.staff : status.status === "IN_SERVICE" ? t.beingSeen : status.status === "PAUSED" ? t.paused : status.stage === "Preparing next stage" ? t.preparing : status.stage}</h2>
            {status.status === "COMPLETED" && <p style={{ margin: 0 }}>{t.complete}</p>}
            {status.status === "WAITING" && ahead != null && <div className="ahead">
              <strong>{ahead === 0 ? "—" : ahead}</strong><span>{ahead === 0 ? t.aheadNone : ahead === 1 ? t.aheadOne : t.aheadMany}</span>
            </div>}
          </div>
          {!!status.journey?.length && <Rail label={t.stage} stops={status.journey.map((step) => ({ label: step.name, state: step.state === "next" ? "todo" : step.state }))} />}
          <dl className="status-facts">
            <div><dt>{t.stage}</dt><dd>{status.stage}</dd></div>
            <div><dt>{t.estimate}</dt><dd>{status.estimated_wait ? fill(t.range, { min: status.estimated_wait.minimum_minutes, max: status.estimated_wait.maximum_minutes }) : t.noEstimate}</dd></div>
          </dl>
          {status.estimated_wait && <p className="privacy-note">{t.estimateNote}</p>}
          {stale && <p className="callout caution" role="status">{t.offline}</p>}
          <div className="split">
            <small>{fill(t.updated, { time: formatClock(status.updated_at) })}</small>
            <button className="ghost small" onClick={reset}>{t.another}</button>
          </div>
        </div>}
      </section>
      <p className="status-foot">{t.notice}</p>
    </main>
  );
}
