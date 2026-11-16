"use client";
import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import { api, errorText, formatClock } from "@/lib/api";
import type { User } from "@/lib/types";
import { applyTheme, storedTheme, useClock, type Theme } from "@/lib/session";
import { Icon } from "../ui/Icon";

export type NavItem = { id: string; label: string; icon: string; badge?: number };
export type NavSection = { title: string; items: NavItem[] };

const initials = (name: string) => name.split(" ").map((part) => part[0]).join("").slice(0, 2).toUpperCase();
const roleText = (roles: string[]) => roles.map((r) => r.replaceAll("_", " ").toLowerCase()).join(" · ");

export function Sidebar({ sections, current, onNavigate, facility, user, onSignOut }: {
  sections: NavSection[]; current: string; onNavigate: (id: string) => void; facility?: string; user: User; onSignOut: () => void;
}) {
  return <aside className="sidebar">
    <div className="brand"><span><Icon name="route" /></span><div><strong>Hutano Flow</strong><small>{facility || "Outpatient workspace"}</small></div></div>
    <nav aria-label="Main navigation">
      {sections.filter((s) => s.items.length).map((section) => <div className="nav-group" key={section.title}>
        <span className="nav-heading">{section.title}</span>
        {section.items.map((item) => <span key={item.id} style={{ display: "contents" }}>
          {/* The count is a description, not part of the name, so "Live queues" stays its exact accessible name. */}
          <button aria-current={current === item.id ? "page" : undefined} className={current === item.id ? "active" : ""} onClick={() => onNavigate(item.id)} aria-describedby={item.badge ? `nav-badge-${item.id}` : undefined}>
            <Icon name={item.icon} />{item.label}{!!item.badge && <span className="nav-badge" aria-hidden="true">{item.badge}</span>}
          </button>
          {!!item.badge && <span id={`nav-badge-${item.id}`} className="sr-only">{item.badge} need attention</span>}
        </span>)}
      </div>)}
    </nav>
    <div className="sidebar-foot"><div className="avatar" aria-hidden="true">{initials(user.display_name)}</div><div><strong>{user.display_name}</strong><small>{roleText(user.roles)}</small></div>
      <button className="ghost icon-button small" onClick={onSignOut} aria-label="Sign out" title="Sign out"><Icon name="logout" /></button></div>
  </aside>;
}

export function LiveIndicator({ online, lastSync }: { online: boolean; lastSync: Date | null }) {
  return <span className={`live-pill${online ? "" : " offline"}`} role="status" aria-live="polite">
    <span className={`dot ${online ? "online" : "offline"}`} aria-hidden="true" />
    {online ? "Live" : "Offline — read-only"}
    <small>{lastSync ? formatClock(lastSync) : "…"}</small>
  </span>;
}

export function Topbar({ online, lastSync, user, onSignOut, onPassword, onFind, children }: {
  online: boolean; lastSync: Date | null; user: User; onSignOut: () => void; onPassword: () => void; onFind?: (q: string) => void; children?: ReactNode;
}) {
  const now = useClock();
  const [query, setQuery] = useState("");
  const find = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "/" && !(e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLSelectElement)) { e.preventDefault(); find.current?.focus(); }
    };
    window.addEventListener("keydown", key); return () => window.removeEventListener("keydown", key);
  }, []);
  return <header className="topbar">
    <span className="mobile-brand brand-mark"><Icon name="route" /></span>
    {children}
    {onFind && <form className="quick-find" role="search" onSubmit={(e) => { e.preventDefault(); if (query.trim()) { onFind(query.trim()); setQuery(""); } }}>
      <Icon name="search" size={16} />
      <input ref={find} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find ticket, e.g. A-014" aria-label="Find a visit by ticket number" />
      <kbd aria-hidden="true">/</kbd>
    </form>}
    <LiveIndicator online={online} lastSync={lastSync} />
    <span className="clock" aria-label="Local time">{now ? formatClock(now) : ""}</span>
    <UserMenu user={user} onSignOut={onSignOut} onPassword={onPassword} />
  </header>;
}

function UserMenu({ user, onSignOut, onPassword }: { user: User; onSignOut: () => void; onPassword: () => void }) {
  const [open, setOpen] = useState(false);
  const [theme, setTheme] = useState<Theme>("system");
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => setTheme(storedTheme()), []);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close); document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, [open]);
  function pick(next: Theme) { setTheme(next); applyTheme(next); }
  return <div className="menu" ref={box}>
    <button className="menu-trigger" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((v) => !v)} aria-label="Account menu">
      <span className="avatar" aria-hidden="true">{initials(user.display_name)}</span>
    </button>
    {open && <div className="menu-panel" role="menu">
      <div className="menu-head"><strong>{user.display_name}</strong><small>{roleText(user.roles)}</small></div>
      <div style={{ padding: "6px 6px 8px" }}>
        <div className="segmented" role="group" aria-label="Theme">
          {(["system", "light", "dark"] as Theme[]).map((value) => <button key={value} type="button" aria-pressed={theme === value} onClick={() => pick(value)}>{value[0].toUpperCase() + value.slice(1)}</button>)}
        </div>
      </div>
      <button role="menuitem" onClick={() => { setOpen(false); onPassword(); }}><Icon name="key" />Change password</button>
      <button role="menuitem" onClick={() => { setOpen(false); window.open("/status", "_blank"); }}><Icon name="qr" />Patient status page</button>
      <button role="menuitem" onClick={onSignOut}><Icon name="logout" />Sign out</button>
    </div>}
  </div>;
}

export function TabBar({ items, current, onNavigate, onMore }: { items: NavItem[]; current: string; onNavigate: (id: string) => void; onMore: () => void }) {
  return <nav className="tabbar" aria-label="Quick navigation">
    {items.map((item) => <button key={item.id} aria-current={current === item.id ? "page" : undefined} onClick={() => onNavigate(item.id)}><Icon name={item.icon} size={20} />{item.label.split(" ")[0]}</button>)}
    <button onClick={onMore} aria-haspopup="dialog"><Icon name="menu" size={20} />More</button>
  </nav>;
}

export function MoreSheet({ open, sections, current, onNavigate, onClose }: { open: boolean; sections: NavSection[]; current: string; onNavigate: (id: string) => void; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { if (open) ref.current?.showModal(); else ref.current?.close(); }, [open]);
  return <dialog ref={ref} className="sheet" aria-label="All sections" onCancel={(e) => { e.preventDefault(); onClose(); }} onClick={(e) => { if (e.target === ref.current) onClose(); }}>
    <div style={{ padding: 18 }}>
      <div className="split" style={{ marginBottom: 8 }}><h2 style={{ margin: 0 }}>All sections</h2><button className="ghost icon-button" onClick={onClose} aria-label="Close"><Icon name="x" /></button></div>
      {sections.filter((s) => s.items.length).map((section) => <div key={section.title} style={{ marginTop: 12 }}>
        <p className="eyebrow">{section.title}</p>
        <div className="quick-actions" style={{ marginTop: 6, gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
          {section.items.map((item) => <button key={item.id} className="quick-action" style={{ minHeight: 56 }} aria-current={current === item.id ? "page" : undefined} onClick={() => { onNavigate(item.id); onClose(); }}>
            <strong><span style={{ display: "inline-flex", gap: 8, alignItems: "center", color: "var(--ink)" }}><Icon name={item.icon} />{item.label}</span></strong>
          </button>)}
        </div>
      </div>)}
    </div>
  </dialog>;
}

export function LockScreen({ user, remaining, onResume, onSignOut }: { user: User; remaining: number; onResume: () => void; onSignOut: () => void }) {
  const resume = useRef<HTMLButtonElement>(null);
  useEffect(() => { resume.current?.focus(); }, []);
  return <div className="lock-screen" role="alertdialog" aria-modal="true" aria-labelledby="lock-title" aria-describedby="lock-desc">
    <div className="panel lock-card">
      <span className="brand-mark"><Icon name="lock" /></span>
      <h2 id="lock-title">Still there, {user.display_name.split(" ")[0]}?</h2>
      <p id="lock-desc">This shared workstation signs out automatically to protect patient information.</p>
      <span className="countdown" aria-live="assertive">{remaining}s</span>
      <div className="row-actions"><button ref={resume} className="primary" onClick={onResume}>I&apos;m still here</button><button className="secondary" onClick={onSignOut}>Sign out now</button></div>
    </div>
  </div>;
}

export function PasswordForm({ forced, onDone, onCancel }: { forced?: boolean; onDone: () => void; onCancel?: () => void }) {
  const [error, setError] = useState(""), [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    if (form.get("next") !== form.get("confirm")) { setError("The new passwords do not match."); return; }
    setBusy(true); setError("");
    try {
      await api("/api/v1/auth/password", { method: "POST", body: JSON.stringify({ current_password: form.get("current"), new_password: form.get("next") }) });
      onDone();
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  return <form onSubmit={submit} className="stack">
    <label>{forced ? "Temporary password" : "Current password"}<input name="current" type="password" autoComplete="current-password" required /></label>
    <label>New password<input name="next" type="password" autoComplete="new-password" minLength={12} required aria-describedby="pw-hint" /><span id="pw-hint" className="form-hint">At least 12 characters. A short phrase is easier to remember than symbols. Avoid your name.</span></label>
    <label>Confirm new password<input name="confirm" type="password" autoComplete="new-password" minLength={12} required /></label>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="row-actions end">{onCancel && <button type="button" className="secondary" onClick={onCancel}>Cancel</button>}<button className="primary" disabled={busy}>{busy ? "Saving…" : "Save new password"}</button></div>
    <small>Saving signs you out on every other device.</small>
  </form>;
}

export function PasswordDialog({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { if (open) ref.current?.showModal(); else ref.current?.close(); }, [open]);
  return <dialog ref={ref} className="action-dialog" aria-labelledby="pw-title" onCancel={(e) => { e.preventDefault(); onClose(); }}>
    {open && <div style={{ padding: 22, display: "grid", gap: 12 }}><h2 id="pw-title" style={{ margin: 0 }}>Change password</h2><PasswordForm onDone={() => { onDone(); onClose(); }} onCancel={onClose} /></div>}
  </dialog>;
}

export function PasswordGate({ user, onDone, onSignOut }: { user: User; onDone: () => void; onSignOut: () => void }) {
  return <main className="display-setup" id="main"><section className="panel" style={{ width: "min(460px, 100%)" }}>
    <span className="brand-mark" style={{ marginBottom: 14 }}><Icon name="key" /></span>
    <h1 style={{ fontSize: "1.35rem" }}>Choose your own password</h1>
    <p className="page-sub" style={{ marginBottom: 16 }}>Welcome, {user.display_name}. An administrator gave you a temporary password. Set a private one before you continue.</p>
    <PasswordForm forced onDone={onDone} />
    <button className="ghost small" style={{ marginTop: 10 }} onClick={onSignOut}>Sign out</button>
  </section></main>;
}
