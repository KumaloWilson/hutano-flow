import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import "./globals.css";

// Downloaded at build time and served from this origin: the app works on an offline clinic LAN.
const sans = IBM_Plex_Sans({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-sans", display: "swap" });
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: "Hutano Flow",
  description: "Clinician-supervised outpatient queue research prototype",
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [{ media: "(prefers-color-scheme: light)", color: "#f4f2ed" }, { media: "(prefers-color-scheme: dark)", color: "#0f1113" }],
};

// Applies a saved theme before first paint so there is no light/dark flash.
const themeScript = `try{var t=localStorage.getItem("hutano-theme");if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch(e){}`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`} suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: themeScript }} /></head>
      <body>
        <a className="skip-link" href="#main">Skip to content</a>
        <div className="research-banner" role="status">
          <strong>Research prototype</strong>
          <span>Not for clinical use · Synthetic data · Clinicians remain the decision-makers</span>
        </div>
        {children}
      </body>
    </html>
  );
}
