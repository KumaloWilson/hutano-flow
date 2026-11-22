"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DemoRoleSwitch } from "@/components/DemoRoleSwitch";
import { useRouter } from "next/navigation";
import { API_URL, api, ApiError } from "@/lib/api";
import type { ServicePoint, User, Visit } from "@/lib/types";
import { canOperateService } from "@/lib/permissions";
import { useIdleSession } from "@/lib/session";
import { ServiceWorker } from "@/components/ServiceWorker";
import { ActionDialogProvider } from "@/components/ActionDialog";
import { PatientWorkspace, HandoverInbox } from "@/components/PatientWorkspace";
import { OperationsConsole, PredictionPanel } from "@/components/Operations";
import { ExperimentsConsole } from "@/components/Experiments";
import { ResearchWorkbench } from "@/components/ResearchWorkbench";
import { ClinicOverview, DemoGuide, type ClinicSnapshot } from "@/components/ClinicOverview";
import { JourneyConsole, ResearchConsole, AdminConsole, ReviewPanel, FeedbackPanel, BaselinePanel } from "@/components/Workflows";
import { Registration, type Notice } from "@/components/FrontDesk";
import { Triage } from "@/components/Triage";
import { Queues, ServiceConsole } from "@/components/Queues";
import { DayClose, Downtime } from "@/components/FloorOps";
import { DisplayScreens, FhirExport, ServicePoints, SystemHealth } from "@/components/AdminPanels";
import { Analytics, Audit, Help, Simulation } from "@/components/Insights";
import { Evaluation } from "@/components/Evaluation";
import { LockScreen, MoreSheet, PasswordDialog, PasswordGate, Sidebar, TabBar, Topbar, type NavSection } from "@/components/shell/AppShell";
import { Icon } from "@/components/ui/Icon";
import { PageHeader } from "@/components/ui/primitives";

type Tab = "home" | "registration" | "triage" | "queues" | "service" | "patients" | "journeys" | "operations" | "dayclose" | "downtime"
  | "analytics" | "simulation" | "experiments" | "research" | "workbench" | "evaluation" | "admin" | "system" | "audit" | "demo" | "help";

// Accessible names are part of the browser-test contract; keep them stable.
const PAGES: Record<Tab, { label: string; icon: string; sub: string }> = {
  home: { label: "Overview", icon: "home", sub: "Today at a glance" },
  registration: { label: "Registration", icon: "desk", sub: "Register arrivals and print queue tickets" },
  triage: { label: "Triage", icon: "stethoscope", sub: "Clinician-confirmed priority, with optional research advisory" },
  queues: { label: "Live queues", icon: "queue", sub: "Every service point, in the order patients will be called" },
  service: { label: "Service console", icon: "door", sub: "Call, start, complete and route the patients in front of you" },
  patients: { label: "Patient workspace", icon: "patient", sub: "Repeat encounters, observations, notes and hand-overs" },
  journeys: { label: "Patient journeys", icon: "route", sub: "Each visit's stages, with preserved history" },
  operations: { label: "Staff & rooms", icon: "rooms", sub: "Shifts, breaks, outages and room reservations" },
  dayclose: { label: "Close the day", icon: "moon", sub: "Review open visits at closing so tomorrow starts clean" },
  downtime: { label: "Downtime kit", icon: "lifebuoy", sub: "Paper fallback for outages and back-entry afterwards" },
  analytics: { label: "Analytics", icon: "chart", sub: "Measured waits and throughput for a date range" },
  simulation: { label: "Simulation lab", icon: "flask", sub: "Compare queue policies on identical synthetic arrivals" },
  experiments: { label: "Experiments", icon: "sparkle", sub: "Finite-day staffing scenarios with replay" },
  research: { label: "AI research", icon: "book", sub: "Synthetic datasets and advisory model registry" },
  workbench: { label: "Research workbench", icon: "book", sub: "Protocols, calibration and independent review" },
  evaluation: { label: "Evaluation", icon: "file", sub: "Evidence for each proposal objective and research question" },
  admin: { label: "Facility admin", icon: "settings", sub: "Service points, staff, displays and policy" },
  system: { label: "System health", icon: "activity", sub: "Database, worker, backups, sessions and displays" },
  audit: { label: "Audit log", icon: "shield", sub: "Every command with actor, reason and correlation" },
  demo: { label: "Demo guide", icon: "compass", sub: "A guided walk through the fictional clinic" },
  help: { label: "Help & safety", icon: "help", sub: "What the prototype does — and never does" },
};

const OPERATIONAL = ["ADMIN", "RECEPTIONIST", "TRIAGE_NURSE", "CLINICIAN", "SERVICE_PROVIDER", "PHARMACY"];
const hasAny = (user: User | null, roles: string[]) => Boolean(user?.roles.some((role) => roles.includes(role)));

function allowedTabs(user: User | null): Tab[] {
  const result: Tab[] = ["home"];
  const add = (tab: Tab, roles: string[]) => { if (hasAny(user, roles)) result.push(tab); };
  add("registration", ["ADMIN", "RECEPTIONIST"]);
  add("triage", ["TRIAGE_NURSE", "CLINICIAN"]);
  add("queues", OPERATIONAL);
  add("service", ["CLINICIAN", "SERVICE_PROVIDER", "PHARMACY"]);
  add("patients", ["RECEPTIONIST", "CLINICIAN", "TRIAGE_NURSE"]);
  add("journeys", OPERATIONAL);
  add("operations", ["ADMIN", "MANAGER", "CLINICIAN", "TRIAGE_NURSE", "SERVICE_PROVIDER", "PHARMACY"]);
  add("dayclose", ["ADMIN", "CLINICIAN"]);
  add("downtime", OPERATIONAL);
  add("analytics", ["ADMIN", "MANAGER", "RESEARCHER"]);
  add("simulation", ["ADMIN", "MANAGER", "RESEARCHER"]);
  add("experiments", ["ADMIN", "MANAGER", "RESEARCHER"]);
  add("research", ["ADMIN", "RESEARCHER"]);
  add("workbench", ["ADMIN", "RESEARCHER", "CLINICIAN", "TRIAGE_NURSE"]);
  add("evaluation", ["ADMIN", "MANAGER", "RESEARCHER"]);
  add("admin", ["ADMIN", "CLINICIAN", "SERVICE_PROVIDER"]);
  add("system", ["ADMIN", "MANAGER"]);
  add("audit", ["ADMIN", "MANAGER", "RESEARCHER"]);
  result.push("demo", "help");
  return result;
}

// The four destinations each role reaches for most, for the phone tab bar.
function primaryTabs(user: User, tabs: Tab[]): Tab[] {
  const r = user.roles;
  const pick = r.includes("RECEPTIONIST") ? ["home", "registration", "queues", "patients"]
    : r.includes("CLINICIAN") ? ["home", "service", "queues", "triage"]
    : r.includes("TRIAGE_NURSE") ? ["home", "triage", "queues", "patients"]
    : r.some((x) => ["PHARMACY", "SERVICE_PROVIDER"].includes(x)) ? ["home", "service", "queues", "journeys"]
    : r.includes("ADMIN") ? ["home", "queues", "admin", "system"]
    : ["home", "evaluation", "analytics", "simulation"];
  return pick.filter((t) => tabs.includes(t as Tab)) as Tab[];
}

export default function Dashboard() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [tab, setTab] = useState<Tab>("home");
  const [visits, setVisits] = useState<Visit[]>([]);
  const [points, setPoints] = useState<ServicePoint[]>([]);
  const [notice, setNotice] = useState<Notice>(null);
  const [online, setOnline] = useState(true);
  const [lastSync, setLastSync] = useState<Date | null>(null);
  const [clinic, setClinic] = useState<ClinicSnapshot | null>(null);
  const [requestedPatient, setRequestedPatient] = useState("");
  const [focusVisit, setFocusVisit] = useState("");
  const [moreOpen, setMoreOpen] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const refreshing = useRef<Promise<void> | null>(null);
  const main = useRef<HTMLElement>(null);

  const tabs = useMemo(() => allowedTabs(user), [user]);
  const navigate = useCallback((value: string, patientId?: string) => {
    if (!(value in PAGES)) return;
    if (patientId) setRequestedPatient(patientId);
    setTab(value as Tab);
    setNotice(null);
    window.history.replaceState(null, "", `/dashboard?view=${value}`);
    main.current?.focus({ preventScroll: true });
    window.scrollTo({ top: 0 });
  }, []);

  const refresh = useCallback(async () => {
    if (refreshing.current) return refreshing.current;
    const work = (async () => {
      try {
        const current = await api<User>("/api/v1/me");
        setUser((previous) => (previous && JSON.stringify(previous) === JSON.stringify(current) ? previous : current));
        if (current.must_change_password) return;
        const canSeeVisits = hasAny(current, OPERATIONAL);
        const [visitData, pointData, snapshot] = await Promise.all([canSeeVisits ? api<Visit[]>("/api/v1/visits") : Promise.resolve([]), api<ServicePoint[]>("/api/v1/service-points"), api<ClinicSnapshot>("/api/v1/clinic/snapshot")]);
        setClinic(snapshot);
        setVisits(visitData);
        setPoints(hasAny(current, ["ADMIN", "RECEPTIONIST", "CLINICIAN", "MANAGER", "RESEARCHER"]) ? pointData : pointData.filter((p) => canOperateService(current, p.type) || (current.roles.includes("TRIAGE_NURSE") && p.type === "consultation")));
        setLastSync(new Date());
        setOnline(true);
      } catch (caught) {
        if (caught instanceof ApiError && caught.status === 401) router.replace("/");
        else setOnline(false);
      }
    })();
    refreshing.current = work;
    try { await work; } finally { if (refreshing.current === work) refreshing.current = null; }
  }, [router]);

  useEffect(() => {
    refresh();
    const updateOnline = () => { if (!navigator.onLine) setOnline(false); else refresh(); };
    window.addEventListener("online", updateOnline);
    window.addEventListener("offline", updateOnline);
    return () => { window.removeEventListener("online", updateOnline); window.removeEventListener("offline", updateOnline); };
  }, [refresh]);

  const ready = Boolean(user && !user.must_change_password);
  useEffect(() => {
    if (!ready) return;
    const polling = setInterval(refresh, 5000);
    let timer: ReturnType<typeof setTimeout> | undefined;
    const changed = () => { if (!timer) timer = setTimeout(() => { timer = undefined; refresh(); }, 100); };
    const stream = new EventSource(`${API_URL}/api/v1/events`, { withCredentials: true });
    stream.onmessage = changed;
    ["visit.created", "visit.state_changed", "episode.queued", "episode.called", "episode.started", "episode.completed", "clinician.override_recorded", "service_point.capacity_changed", "simulation.completed", "queue.rank_changed", "reset"].forEach((topic) => stream.addEventListener(topic, changed));
    return () => { stream.close(); clearInterval(polling); if (timer) clearTimeout(timer); };
  }, [ready, refresh]);

  useEffect(() => {
    const view = new URLSearchParams(window.location.search).get("view") as Tab;
    if (user && view && tabs.includes(view)) setTab(view);
  }, [user, tabs]);

  const logout = useCallback(async () => {
    await api("/api/v1/auth/logout", { method: "POST" }).catch(() => undefined);
    router.replace("/");
  }, [router]);
  const idle = useIdleSession({ idleMinutes: user?.session_idle_minutes ?? 30, onExpire: logout });

  function find(query: string) {
    const q = query.toLowerCase();
    const match = visits.find((v) => v.public_token.toLowerCase() === q) || visits.find((v) => v.public_token.toLowerCase().includes(q) || v.patient?.pseudonym?.toLowerCase().includes(q));
    if (!match) { setNotice({ kind: "error", text: `No visit matching “${query}” in your current worklist.` }); return; }
    setFocusVisit(match.id);
    navigate("journeys");
  }

  if (!user) return <main className="center"><div className="spinner" /><p>Opening your workspace…</p></main>;
  if (user.must_change_password) return <PasswordGate user={user} onDone={refresh} onSignOut={logout} />;

  const badgeFor = (id: Tab) => id === "queues" ? clinic?.counts.long_waits || 0 : id === "triage" ? visits.filter((v) => v.status === "AWAITING_TRIAGE").length : 0;
  const item = (id: Tab) => ({ id, label: PAGES[id].label, icon: PAGES[id].icon, badge: badgeFor(id) });
  const sections: NavSection[] = [
    { title: "Clinic", items: (["home", "registration", "triage", "queues", "service", "patients", "journeys"] as Tab[]).filter((t) => tabs.includes(t)).map(item) },
    { title: "Operations", items: (["operations", "dayclose", "downtime", "analytics"] as Tab[]).filter((t) => tabs.includes(t)).map(item) },
    { title: "Research", items: (["evaluation", "simulation", "experiments", "research", "workbench"] as Tab[]).filter((t) => tabs.includes(t)).map(item) },
    { title: "Workspace", items: (["admin", "system", "audit", "demo", "help"] as Tab[]).filter((t) => tabs.includes(t)).map(item) },
  ];
  const page = PAGES[tab];

  return (
    <div className="app-shell">
      <ServiceWorker />
      <Sidebar sections={sections} current={tab} onNavigate={navigate} facility={clinic?.facility.name} user={user} onSignOut={logout} />
      <main className="workspace" id="main" ref={main} tabIndex={-1} style={{ outline: "none" }}>
        <Topbar online={online} lastSync={lastSync} user={user} onSignOut={logout} onPassword={() => setPasswordOpen(true)} onFind={hasAny(user, OPERATIONAL) ? find : undefined}><DemoRoleSwitch user={user} /></Topbar>
        <PageHeader title={page.label} subtitle={page.sub} actions={tab === "registration" ? <a className="button secondary small" href="/status" target="_blank" rel="noreferrer"><Icon name="qr" />Patient status page</a> : undefined} />
        {notice && <div className={`notice ${notice.kind}`} role="status"><span className="cluster" style={{ gap: 10 }}><span className="notice-icon"><Icon name={notice.kind === "success" ? "check" : "alert"} /></span><span>{notice.text}</span></span><button onClick={() => setNotice(null)} aria-label="Dismiss"><Icon name="x" size={16} /></button></div>}
        {!online && <div className="callout caution" role="status">Connection lost. Showing the last update; actions are paused until the connection returns; nothing is queued to send later.</div>}
        {tab === "home" && <ClinicOverview snapshot={clinic} user={user} visits={visits} navigate={navigate} tabs={tabs} />}
        {tab === "demo" && <DemoGuide snapshot={clinic} navigate={navigate} tabs={tabs} onPrepared={refresh} />}
        <fieldset disabled={!online} className="workspace-actions"><ActionDialogProvider>
          {tab === "patients" && <PatientWorkspace user={user} points={points} refresh={refresh} requestedPatient={requestedPatient} />}
          {tab === "operations" && <OperationsConsole user={user} points={points} refresh={refresh} />}
          {tab === "experiments" && <ExperimentsConsole />}
          {tab === "workbench" && <ResearchWorkbench roles={user.roles} />}
          {tab === "registration" && <Registration onDone={refresh} setNotice={setNotice} />}
          {tab === "triage" && <Triage visits={visits} onDone={refresh} setNotice={setNotice} />}
          {tab === "queues" && <Queues points={points} visits={visits} user={user} onDone={refresh} setNotice={setNotice} navigate={navigate} />}
          {tab === "journeys" && <JourneyConsole visits={visits} user={user} refresh={refresh} focusVisitId={focusVisit} />}
          {tab === "service" && <><ServiceConsole visits={visits} points={points} user={user} onDone={refresh} setNotice={setNotice} /><HandoverInbox /></>}
          {tab === "dayclose" && <DayClose setNotice={setNotice} onDone={refresh} />}
          {tab === "downtime" && <Downtime user={user} points={points} setNotice={setNotice} onDone={refresh} />}
          {tab === "analytics" && <><Analytics /><PredictionPanel user={user} /></>}
          {tab === "simulation" && <Simulation />}
          {tab === "research" && <><ResearchConsole user={user} /><BaselinePanel /></>}
          {tab === "admin" && <div className="stack">
            <ServicePoints points={points} user={user} onDone={refresh} setNotice={setNotice} />
            {user.roles.includes("ADMIN") && <DisplayScreens setNotice={setNotice} />}
            <AdminConsole user={user} />
            {user.roles.includes("ADMIN") && <FhirExport />}
            <ReviewPanel user={user} />
          </div>}
          {tab === "system" && <SystemHealth />}
          {tab === "evaluation" && <Evaluation />}
          {tab === "audit" && <Audit />}
          {tab === "help" && <><Help /><ReviewPanel user={user} />{hasAny(user, ["ADMIN", "RESEARCHER", "MANAGER"]) && <FeedbackPanel />}</>}
        </ActionDialogProvider></fieldset>
      </main>
      <TabBar items={primaryTabs(user, tabs).map(item)} current={tab} onNavigate={navigate} onMore={() => setMoreOpen(true)} />
      <MoreSheet open={moreOpen} sections={sections} current={tab} onNavigate={navigate} onClose={() => setMoreOpen(false)} />
      <PasswordDialog open={passwordOpen} onClose={() => setPasswordOpen(false)} onDone={() => { setNotice({ kind: "success", text: "Password changed. Other devices have been signed out." }); refresh(); }} />
      {idle.locked && <LockScreen user={user} remaining={idle.remaining} onResume={idle.resume} onSignOut={logout} />}
    </div>
  );
}
