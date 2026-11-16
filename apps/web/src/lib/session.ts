"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

const ACTIVITY = ["pointerdown", "keydown", "touchstart", "wheel"] as const;

/**
 * Shared-workstation session handling (ADR-027).
 * - Genuine input (not background polling) refreshes the server's idle window
 *   at most every 4 minutes, so an unattended screen expires server-side.
 * - After `lockAfterMinutes` without input, a lock screen counts down and then
 *   signs out, protecting reception PCs that staff walk away from.
 */
export function useIdleSession({ idleMinutes, onExpire }: { idleMinutes: number; onExpire: () => void }) {
  const lockAfter = Math.max(2, Math.min(15, idleMinutes - 2)) * 60_000;
  const graceSeconds = 60;
  const lastInput = useRef(Date.now());
  const lastRefresh = useRef(Date.now());
  const [locked, setLocked] = useState(false);
  const [remaining, setRemaining] = useState(graceSeconds);
  const expire = useRef(onExpire);
  expire.current = onExpire;

  const touch = useCallback(() => {
    lastInput.current = Date.now();
    if (Date.now() - lastRefresh.current > 4 * 60_000) {
      lastRefresh.current = Date.now();
      api("/api/v1/auth/refresh", { method: "POST" }).catch(() => undefined);
    }
  }, []);

  useEffect(() => {
    const handler = () => { if (!locked) touch(); };
    ACTIVITY.forEach((name) => window.addEventListener(name, handler, { passive: true }));
    const timer = setInterval(() => {
      const idle = Date.now() - lastInput.current;
      if (!locked && idle >= lockAfter) { setLocked(true); setRemaining(graceSeconds); }
    }, 5000);
    return () => { ACTIVITY.forEach((name) => window.removeEventListener(name, handler)); clearInterval(timer); };
  }, [locked, lockAfter, touch]);

  useEffect(() => {
    if (!locked) return;
    const timer = setInterval(() => setRemaining((value) => {
      if (value <= 1) { clearInterval(timer); expire.current(); return 0; }
      return value - 1;
    }), 1000);
    return () => clearInterval(timer);
  }, [locked]);

  const resume = useCallback(() => { setLocked(false); lastRefresh.current = 0; touch(); }, [touch]);
  return { locked, remaining, resume };
}

export function useClock(intervalMs = 15000) {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => { setNow(new Date()); const t = setInterval(() => setNow(new Date()), intervalMs); return () => clearInterval(t); }, [intervalMs]);
  return now;
}

export type Theme = "system" | "light" | "dark";
export function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", theme);
  try { localStorage.setItem("hutano-theme", theme); } catch { /* best effort */ }
}
export function storedTheme(): Theme {
  try { const v = localStorage.getItem("hutano-theme"); if (v === "light" || v === "dark") return v; } catch { /* ignore */ }
  return "system";
}
