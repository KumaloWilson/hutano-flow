import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Hutano Flow",
  description: "Smart healthcare queue research prototype",
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = { themeColor: "#12372f", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <div className="research-banner" role="status">
          <strong>Research prototype</strong>
          <span>Not for clinical use · Synthetic data by default · Clinicians remain the decision-makers</span>
        </div>
        {children}
      </body>
    </html>
  );
}

