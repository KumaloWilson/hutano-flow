import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { QrCode } from "./QrCode";

describe("QrCode", () => {
  it("renders a labelled SVG for a long status link", () => {
    const link = "https://192.168.1.20/status#t=" + "A-001." + "f".repeat(64);
    const { getByRole } = render(<QrCode value={link} label="Status QR" />);
    const svg = getByRole("img", { name: "Status QR" });
    expect(svg.querySelector("path")?.getAttribute("d")?.length).toBeGreaterThan(500);
  });
});
