"use client";
import qrcode from "qrcode-generator";
import { useMemo } from "react";

/** Crisp SVG QR code (error correction M) rendered locally — nothing leaves the device. */
export function QrCode({ value, label }: { value: string; label: string }) {
  const { cells, size } = useMemo(() => {
    const qr = qrcode(0, "M");
    qr.addData(value, "Byte");
    qr.make();
    const count = qr.getModuleCount();
    const rects: string[] = [];
    for (let row = 0; row < count; row++) {
      let run = -1;
      for (let col = 0; col <= count; col++) {
        const dark = col < count && qr.isDark(row, col);
        if (dark && run < 0) run = col;
        if (!dark && run >= 0) { rects.push(`M${run + 4} ${row + 4}h${col - run}v1h-${col - run}z`); run = -1; }
      }
    }
    return { cells: rects.join(""), size: count + 8 };
  }, [value]);
  return <svg viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label} shapeRendering="crispEdges">
    <rect width={size} height={size} fill="#fff" /><path d={cells} fill="#000" />
  </svg>;
}
