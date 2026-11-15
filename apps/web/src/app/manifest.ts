import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Hutano Flow Research Prototype",
    short_name: "Hutano Flow",
    description: "Clinician-supervised outpatient queue research prototype",
    start_url: "/",
    display: "standalone",
    background_color: "#f5f2e9",
    theme_color: "#12372f",
    icons: [{ src: "/icon.svg", sizes: "any", type: "image/svg+xml" }],
  };
}

