import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { OperationsConsole } from "./Operations";
import { ActionDialogProvider } from "./ActionDialog";
import type { User, ServicePoint } from "@/lib/types";

const mocked = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: mocked.api, formatTime: (v: string) => v, waitForJob: vi.fn() }));
afterEach(() => { cleanup(); mocked.api.mockReset(); });

it("keeps the selected service queue when an earlier service response arrives last", async () => {
  let resolveConsult!: (value: unknown) => void;
  const consultation = new Promise(resolve => { resolveConsult = resolve; });
  mocked.api.mockImplementation((path: string) => {
    if (path.endsWith("/board")) return Promise.resolve({ rooms: [], staff: [], shifts: [], blocks: [] });
    if (path.endsWith("/consult/queue")) return consultation;
    if (path.endsWith("/lab/queue")) return Promise.resolve({ entries: [{ public_token: "LAB-001", confirmed_urgency: "P2" }] });
    throw new Error(`Unexpected request: ${path}`);
  });
  const user = { id: "provider", roles: ["SERVICE_PROVIDER"] } as User;
  const points = [{ id: "consult", type: "consultation", name: "Consultation" }, { id: "lab", type: "laboratory", name: "Laboratory" }] as ServicePoint[];
  render(<ActionDialogProvider><OperationsConsole user={user} points={points} refresh={async () => {}} /></ActionDialogProvider>);
  fireEvent.change(screen.getByLabelText("Assignment service"), { target: { value: "lab" } });
  await screen.findByText("Next: LAB-001 · P2");
  await act(async () => { resolveConsult({ entries: [{ public_token: "CONSULT-001", confirmed_urgency: "P1" }] }); await consultation; });
  expect(screen.getByText("Next: LAB-001 · P2")).toBeTruthy();
  expect(screen.queryByText("Next: CONSULT-001 · P1")).toBeNull();
  // While switching again, the old service head must not remain actionable.
  fireEvent.change(screen.getByLabelText("Assignment service"), { target: { value: "consult" } });
  expect((screen.getByRole("button", { name: "Review room alternatives" }) as HTMLButtonElement).disabled).toBe(true);
});
