"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { COPY, type Lang } from "@/lib/i18n";
import { Icon } from "@/components/ui/Icon";

type Board = {
  facility: string; label: string; local_time: string; generated_at: string; research_notice: string;
  now_calling: { token: string; service: string; room: string | null; announced_at: string; recall_count: number }[];
  queues: { service: string; service_type: string; waiting: number; open: boolean }[];
};
const KEY_STORE = "hutano-display-key";
const ROTATION: Lang[] = ["en", "sn", "nd"];

/** Short two-tone chime generated locally (no audio files, works offline). */
function chime() {
  try {
    const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new AudioCtx();
    [[660, 0], [880, 0.22]].forEach(([freq, at]) => {
      const osc = ctx.createOscillator(), gain = ctx.createGain();
      osc.frequency.value = freq; osc.type = "sine";
      gain.gain.setValueAtTime(0.0001, ctx.currentTime + at);
      gain.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + at + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + at + 0.5);
      osc.connect(gain).connect(ctx.destination); osc.start(ctx.currentTime + at); osc.stop(ctx.currentTime + at + 0.55);
    });
  } catch { /* audio unavailable */ }
}

/** Spells tokens out ("A, zero one four") so they are intelligible in a noisy room. */
function announce(token: string, place: string) {
  if (!("speechSynthesis" in window)) return;
  const spoken = token.replace("-", ", ").split("").map((c) => (/\d/.test(c) ? ` ${c}` : c)).join("");
  const utterance = new SpeechSynthesisUtterance(`Ticket ${spoken}. Please go to ${place}.`);
  utterance.rate = 0.85;
  window.speechSynthesis.speak(utterance);
}

export default function DisplayPage() {
  const [key, setKey] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
  const [langIndex, setLangIndex] = useState(0);
  const [sound, setSound] = useState(false);
  const [voice, setVoice] = useState(false);
  const seen = useRef<Map<string, string>>(new Map());
  const first = useRef(true);
  const t = COPY[ROTATION[langIndex]];

  useEffect(() => {
    const fromHash = new URLSearchParams(window.location.hash.slice(1)).get("key");
    if (fromHash) {
      try { localStorage.setItem(KEY_STORE, fromHash); } catch { /* kiosk without storage keeps it in memory */ }
      window.history.replaceState(null, "", window.location.pathname);
      setKey(fromHash);
      return;
    }
    try { setKey(localStorage.getItem(KEY_STORE)); } catch { setKey(null); }
  }, []);

  const load = useCallback(async (value: string) => {
    try {
      const next = await api<Board>("/api/v1/display/board", { method: "POST", body: JSON.stringify({ key: value }) });
      const fresh = next.now_calling.filter((item) => seen.current.get(item.token) !== item.announced_at);
      next.now_calling.forEach((item) => seen.current.set(item.token, item.announced_at));
      if (!first.current && fresh.length) {
        if (sound) chime();
        if (voice) fresh.forEach((item) => announce(item.token, item.room ? `${item.service}, ${item.room}` : item.service));
      }
      first.current = false;
      setBoard(next); setStale(false); setError("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) { setError("This display key is not valid or was revoked. Ask an administrator for a new display link."); setKey(null); try { localStorage.removeItem(KEY_STORE); } catch { /* ignore */ } }
      else setStale(true);
    }
  }, [sound, voice]);

  useEffect(() => {
    if (!key) return;
    load(key);
    const poll = setInterval(() => load(key), 4000);
    return () => clearInterval(poll);
  }, [key, load]);

  useEffect(() => { const t = setInterval(() => setLangIndex((i) => (i + 1) % ROTATION.length), 10000); return () => clearInterval(t); }, []);

  // Keep a wall-mounted screen awake where the browser allows it.
  useEffect(() => {
    let lock: { release: () => Promise<void> } | null = null;
    const nav = navigator as Navigator & { wakeLock?: { request: (type: "screen") => Promise<{ release: () => Promise<void> }> } };
    nav.wakeLock?.request("screen").then((l) => { lock = l; }).catch(() => undefined);
    return () => { lock?.release().catch(() => undefined); };
  }, [key]);

  function save(event: FormEvent) {
    event.preventDefault();
    const value = draft.trim().replace(/^.*#key=/, "");
    try { localStorage.setItem(KEY_STORE, value); } catch { /* ignore */ }
    setKey(value);
  }

  if (!key) return <main className="display-setup" id="main"><section className="panel"><h1>Set up this display</h1>
    <p className="page-sub">Open the display link created in Administration → Display screens, or paste its key here. The key only allows this screen to show ticket numbers being called.</p>
    {error && <p className="error" role="alert">{error}</p>}
    <form onSubmit={save}><label>Display key<input value={draft} onChange={(e) => setDraft(e.target.value)} required minLength={20} autoComplete="off" /></label><button className="primary wide">Start display</button></form>
  </section></main>;

  const now = board?.now_calling ?? [];
  const recentCut = Date.now() - 60_000;
  return (
    <main className="display-shell" id="main" lang={ROTATION[langIndex]}>
      <header className="display-head">
        <div><h1>{board?.facility ?? "Hutano Flow"}</h1><span style={{ color: "#8f949b" }}>{board?.label}</span></div>
        <div className="cluster">
          <button className="ghost small" style={{ color: "#8f949b" }} onClick={() => { setSound((v) => !v); if (!sound) chime(); }} aria-pressed={sound}><Icon name="megaphone" />{sound ? "Chime on" : "Chime off"}</button>
          <button className="ghost small" style={{ color: "#8f949b" }} onClick={() => setVoice((v) => !v)} aria-pressed={voice}>{voice ? "Voice on" : "Voice off"}</button>
          <span className="clock">{board?.local_time ?? "--:--"}</span>
        </div>
      </header>
      <section className="display-main">
        <div className="calling">
          <p className="display-label">{t.nowCalling}</p>
          {now.length ? now.slice(0, 6).map((item, index) => {
            const fresh = new Date(item.announced_at).getTime() > recentCut;
            return <div key={item.token} className={`call-row${fresh ? " fresh" : index > 2 ? " older" : ""}`}>
              <span className="ticket">{item.token}</span>
              <div className="dest"><strong>{item.room ?? item.service}</strong><span>{item.room ? item.service : t.ticketReady}{item.recall_count > 0 ? ` · ${item.recall_count + 1}×` : ""}</span></div>
            </div>;
          }) : <div className="display-empty"><Icon name="clock" size={40} />{t.ticketReady}</div>}
        </div>
        <aside className="display-queues">
          <p className="display-label">{t.waiting}</p>
          {board?.queues.map((queue) => <div key={queue.service} className={`display-queue${queue.open ? "" : " closed"}`}>
            <div><strong>{queue.service}</strong>{!queue.open && <small>{t.closed}</small>}</div><span>{queue.waiting}</span>
          </div>)}
        </aside>
      </section>
      <footer className="display-foot">
        <span>{board?.research_notice ?? "Research prototype"}</span>
        <span>{stale ? "Connection lost — retrying" : "Live"}</span>
      </footer>
    </main>
  );
}
