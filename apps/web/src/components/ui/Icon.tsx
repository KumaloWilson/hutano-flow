// Small, dependency-free stroke icon set (24px grid, 1.75 stroke). Decorative by
// default: pass `label` only when the icon is the sole content of a control.
const paths: Record<string, string> = {
  home: "M3 10.5 12 3l9 7.5M5 9v11h5v-6h4v6h5V9",
  desk: "M3 8h18M5 8v12M19 8v12M8 4h8v4H8zM9 13h6",
  stethoscope: "M6 3v6a5 5 0 0 0 10 0V3M6 3H4m2 0h2m8 0h-2m2 0h2M11 14v2a5 5 0 0 0 10 0v-1m0 0a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  queue: "M4 6h16M4 12h16M4 18h10",
  door: "M5 21V4a1 1 0 0 1 1-1h9l4 2v16M3 21h18M13 12h.01",
  patient: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
  route: "M6 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM6 15V9a3 3 0 0 1 3-3h7M18 9v6a3 3 0 0 1-3 3H8",
  rooms: "M3 21V7l9-4 9 4v14M9 21v-6h6v6M3 21h18",
  moon: "M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z",
  lifebuoy: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM5.6 5.6l3.6 3.6M14.8 14.8l3.6 3.6M18.4 5.6l-3.6 3.6M9.2 14.8l-3.6 3.6",
  chart: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  flask: "M9 3h6M10 3v6L4.5 18.5A1.5 1.5 0 0 0 5.8 21h12.4a1.5 1.5 0 0 0 1.3-2.5L14 9V3M7 15h10",
  sparkle: "M12 3v4M12 17v4M3 12h4M17 12h4M6.3 6.3l2.5 2.5M15.2 15.2l2.5 2.5M17.7 6.3l-2.5 2.5M8.8 15.2l-2.5 2.5",
  book: "M4 4.5A1.5 1.5 0 0 1 5.5 3H20v15H5.5A1.5 1.5 0 0 0 4 19.5v-15zM4 19.5A1.5 1.5 0 0 0 5.5 21H20",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  activity: "M22 12h-4l-3 9L9 3l-3 9H2",
  shield: "M12 21s8-4 8-10V5l-8-3-8 3v6c0 6 8 10 8 10z",
  compass: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM16 8l-2 6-6 2 2-6 6-2z",
  help: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3",
  logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9",
  key: "M15 7a4 4 0 1 0-3.9 5L4 19v2h3v-2h2v-2h2l1.1-1.1A4 4 0 0 0 15 7zM16 7h.01",
  lock: "M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  monitor: "M3 4h18v12H3zM8 20h8M12 16v4",
  printer: "M6 9V3h12v6M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2M6 14h12v7H6z",
  qr: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h3v3h-3zM20 14v.01M14 20h.01M17 17h4v4h-4z",
  check: "M20 6 9 17l-5-5",
  x: "M18 6 6 18M6 6l12 12",
  alert: "M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01",
  megaphone: "M3 11v2a1 1 0 0 0 1 1h3l5 4V6L7 10H4a1 1 0 0 0-1 1zM16 8a5 5 0 0 1 0 8M19 5a9 9 0 0 1 0 14",
  pause: "M8 5v14M16 5v14",
  play: "M6 4l14 8-14 8z",
  arrow: "M5 12h14M13 6l6 6-6 6",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
  wifi: "M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0M2 9a15 15 0 0 1 20 0M12 20h.01",
  "wifi-off": "M2 2l20 20M8.5 16a5 5 0 0 1 7 0M5 12.5a10 10 0 0 1 4.2-2.6M16.7 10.1A10 10 0 0 1 19 12.5M2 9a15 15 0 0 1 4.6-3M10.7 5.1A15 15 0 0 1 22 9M12 20h.01",
  plus: "M12 5v14M5 12h14",
  refresh: "M21 12a9 9 0 0 1-15.5 6.3L3 16M3 12a9 9 0 0 1 15.5-6.3L21 8M21 3v5h-5M3 21v-5h5",
  download: "M12 3v12M7 10l5 5 5-5M5 21h14",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  menu: "M4 6h16M4 12h16M4 18h16",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
  hourglass: "M6 3h12M6 21h12M7 3c0 5 10 5 10 9s-10 4-10 9M17 3c0 5-10 5-10 9",
  file: "M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8zM14 3v5h5M9 13h6M9 17h6",
  undo: "M9 14 4 9l5-5M4 9h11a5 5 0 0 1 0 10h-3",
};

export type IconName = keyof typeof paths;

export function Icon({ name, size = 18, label, className }: { name: IconName | string; size?: number; label?: string; className?: string }) {
  const d = paths[name] ?? paths.more;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round"
      strokeLinejoin="round" className={className} aria-hidden={label ? undefined : true} role={label ? "img" : undefined} aria-label={label} focusable="false">
      {name === "play" ? <path d={d} fill="currentColor" stroke="none" /> : <path d={d} />}
    </svg>
  );
}
