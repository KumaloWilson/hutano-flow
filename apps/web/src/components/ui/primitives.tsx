"use client";
import { ReactNode, useEffect, useState } from "react";
import { Icon } from "./Icon";

const human = (value: string) => value.replaceAll("_", " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());

/** Status chip: colour, dot and words together, never colour alone. */
export function StatusChip({ status, label }: { status: string; label?: string }) {
  return <span className={`badge ${status.toLowerCase()}`}>{label ?? human(status)}</span>;
}

/** Neutral ordering label (ADR-002): an ink-intensity ramp, not an alarm palette. */
export function Urgency({ level }: { level?: string | null }) {
  if (!level) return <span className="urgency" data-level="none" title="Awaiting clinician assessment">Unassessed</span>;
  return <span className="urgency" data-level={level} title={`Clinician-confirmed category ${level}`}>{level}</span>;
}

export function Ticket({ token, large = false }: { token: string; large?: boolean }) {
  return <span className={`ticket${large ? " lg" : ""}`}>{token}</span>;
}

export function Stat({ label, value, note, warning = false }: { label: string; value: ReactNode; note?: ReactNode; warning?: boolean }) {
  return <article className={`metric ${warning ? "metric-alert" : ""}`}><p>{label}</p><strong>{value}</strong>{note && <small>{note}</small>}</article>;
}

export function Empty({ text, icon = "check", action }: { text: string; icon?: string; action?: ReactNode }) {
  return <div className="empty"><span><Icon name={icon} /></span><p>{text}</p>{action}</div>;
}

export function Loading({ text = "Loading…" }: { text?: string }) {
  return <div className="center compact" role="status"><div className="spinner" /><p>{text}</p></div>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return <header className="workspace-head"><div><h1>{title}</h1>{subtitle && <p className="page-sub">{subtitle}</p>}</div>{actions && <div className="row-actions">{actions}</div>}</header>;
}

/** Minutes waited, with a short bar that saturates at the long-wait threshold. */
export function Wait({ minutes, long, threshold = 60 }: { minutes: number; long?: boolean; threshold?: number }) {
  const pct = Math.min(100, Math.round((minutes / threshold) * 100));
  const text = minutes >= 60 ? `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m` : `${minutes} min`;
  return <span className={`wait${long ? " long" : ""}`} title={long ? "Long wait — remains flagged until seen" : "Time waiting at this stage"}>
    <span className="wait-bar" aria-hidden="true"><i style={{ width: `${pct}%` }} /></span>{text}
  </span>;
}

/** Live ticking minutes since a timestamp, for service elapsed time. */
export function Elapsed({ since }: { since?: string | null }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 15000); return () => clearInterval(t); }, []);
  if (!since) return <span className="num">—</span>;
  const minutes = Math.max(0, Math.floor((now - new Date(since).getTime()) / 60000));
  return <span className="num">{minutes} min</span>;
}

export type RailStop = { label: string; value?: ReactNode; note?: ReactNode; state?: "done" | "current" | "busy" | "alert" | "todo" };
/** The journey rail: stations along a line, used for clinic flow and patient progress. */
export function Rail({ stops, large = false, label }: { stops: RailStop[]; large?: boolean; label: string }) {
  return <ol className={`rail${large ? " flow-rail" : ""}`} aria-label={label} style={{ listStyle: "none", padding: 0 }}>
    {stops.map((stop, index) => <li key={stop.label} className={`rail-stop ${stop.state ?? "todo"}`} aria-current={stop.state === "current" ? "step" : undefined}>
      <span className="station">{stop.value ?? (stop.state === "done" ? "✓" : index + 1)}</span>
      <strong>{stop.label}</strong>{stop.note && <small>{stop.note}</small>}
    </li>)}
  </ol>;
}
