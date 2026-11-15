import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ResearchWorkbench } from "./ResearchWorkbench";

const mocked = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: mocked.api, API_URL: "http://localhost:8000", formatTime: (value: string) => value || "—" }));
const root = "/api/v1/research/workbench";
const config = { seed: 2026, training_days: 40, test_days: 12, arrivals_per_day: 50, replications: 10, shift_strength: 1, missing_rate: 0 };
const protocol = { id: "protocol-one", name: "Synthetic test protocol", question: "A frozen synthetic question", dataset_id: "dataset-one", model_id: null, design: "MANUAL_ONLY", config_hash: "abc123", created_at: "2026-10-28T10:00:00Z", case_count: 24, operations_config: config };
const overview = { datasets: [{ id: "dataset-one", name: "Synthetic data", row_count: 1000, schema: {} }], models: [], protocols: [protocol], feature_schema: {}, warning: "Synthetic only" };
const studyCase = { id: "case-one", ordinal: 1, features: { hour: 9, recorded_measurement: 0.1 }, review_count: 0, own_review: null, adjudicated: false };
let detail: any;

beforeEach(() => {
  mocked.api.mockReset();
  detail = { protocol, cases: [studyCase], summary: {}, trials: [], runs: [] };
  mocked.api.mockImplementation(async (path: string) => {
    if (path.endsWith("/overview")) return overview;
    if (path.endsWith("/monitor")) return {};
    if (path === `${root}/protocols/protocol-one`) return detail;
    throw new Error(`Unexpected test request: ${path}`);
  });
});
afterEach(cleanup);

async function selectProtocol() {
  fireEvent.change(await screen.findByLabelText("Saved research protocol"), { target: { value: "protocol-one" } });
  await screen.findByRole("heading", { name: "Synthetic test protocol" });
}

it("publishes a frozen protocol using structured synthetic settings", async () => {
  mocked.api.mockImplementation(async (path: string, options?: RequestInit) => {
    if (path === `${root}/protocols` && options?.method === "POST") return protocol;
    if (path.endsWith("/overview")) return overview;
    if (path.endsWith("/monitor")) return {};
    return detail;
  });
  render(<ResearchWorkbench roles={["RESEARCHER"]} />);
  await screen.findByLabelText("Protocol name");
  fireEvent.change(screen.getByLabelText("Protocol name"), { target: { value: "Predeclared synthetic comparison" } });
  fireEvent.click(screen.getByRole("button", { name: "Save immutable research protocol" }));
  await waitFor(() => expect(mocked.api.mock.calls.some(([path, options]) => path === `${root}/protocols` && options?.method === "POST")).toBe(true));
  const call = mocked.api.mock.calls.find(([path, options]) => path === `${root}/protocols` && options?.method === "POST")!;
  const body = JSON.parse(call[1].body);
  expect(body.design).toBe("MANUAL_ONLY");
  expect(body.dataset_id).toBe("dataset-one");
  expect(body.operations_config.replications).toBe(10);
  expect(body.model_id).toBeNull();
  expect(screen.queryByRole("button", { name: "Save blinded independent review" })).toBeNull();
});

it("keeps independent reviewers away from consensus material until both reviews exist", async () => {
  render(<ResearchWorkbench roles={["CLINICIAN"]} />);
  await selectProtocol();
  expect((screen.getByRole("button", { name: "Open two-reviewer consensus" }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.queryByLabelText("Protocol name")).toBeNull();
  expect(screen.queryByText("Descriptive participant outcomes by assigned arm")).toBeNull();
  fireEvent.change(screen.getByLabelText("Independent review label"), { target: { value: "P2" } });
  fireEvent.change(screen.getByLabelText("Independent review rationale"), { target: { value: "Independent synthetic case response" } });
  mocked.api.mockImplementationOnce(async () => ({ recorded: true }));
  fireEvent.click(screen.getByRole("button", { name: "Save blinded independent review" }));
  await waitFor(() => expect(mocked.api.mock.calls.some(([path]) => path === `${root}/cases/case-one/reviews`)).toBe(true));
});

it("withholds shadow advice until the independent response has been saved", async () => {
  const trial = { id: "trial-one", case_id: "case-one", ordinal: 1, features: studyCase.features, arm: "SHADOW", status: "STARTED", started_at: "2026-10-28T10:00:00Z", advisory: { suggestion: "P1", confidence: .9, warning: "Synthetic model output" } };
  detail = { ...detail, protocol: { ...protocol, design: "SHADOW" }, trials: [trial] };
  mocked.api.mockImplementation(async (path: string, options?: RequestInit) => {
    if (path.endsWith("/overview")) return overview;
    if (path.endsWith("/complete") && options?.method === "POST") {
      const completed = { ...trial, status: "COMPLETED", final_label: "P3", elapsed_seconds: 12 };
      detail = { ...detail, trials: [completed] };
      return completed;
    }
    return detail;
  });
  render(<ResearchWorkbench roles={["CLINICIAN"]} />);
  await selectProtocol();
  expect(screen.queryByRole("heading", { name: "Experimental advisory" })).toBeNull();
  fireEvent.change(screen.getByLabelText("Participant final label"), { target: { value: "P3" } });
  fireEvent.change(screen.getByLabelText("Self-reported trust rating"), { target: { value: "2" } });
  fireEvent.change(screen.getByLabelText("Participant decision rationale"), { target: { value: "Independent answer before model reveal" } });
  fireEvent.change(screen.getByLabelText("Does the human retain final decision authority?"), { target: { value: "no" } });
  fireEvent.click(screen.getByRole("button", { name: "Save independent trial decision" }));
  await screen.findByRole("heading", { name: "Experimental advisory" });
  const call = mocked.api.mock.calls.find(([path]) => path.endsWith("/complete"))!;
  expect(JSON.parse(call[1].body).understands_authority).toBe(false);
});

it("requires explicit consent before starting an assigned trial", async () => {
  render(<ResearchWorkbench roles={["TRIAGE_NURSE"]} />);
  await selectProtocol();
  const start = screen.getByRole("button", { name: "Start assigned participant trial" }) as HTMLButtonElement;
  expect(start.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("Participant consent reference"), { target: { value: "CODED_FIXTURE_ONLY" } });
  expect(start.disabled).toBe(true);
  fireEvent.click(screen.getByLabelText("The participant has consented to this synthetic exercise"));
  expect(start.disabled).toBe(false);
});

it("shows an API error without claiming a protocol was saved", async () => {
  mocked.api.mockImplementation(async (path: string, options?: RequestInit) => {
    if (options?.method === "POST") throw new Error("Dataset hash does not match");
    return overview;
  });
  render(<ResearchWorkbench roles={["RESEARCHER"]} />);
  await screen.findByLabelText("Protocol name");
  fireEvent.click(screen.getByRole("button", { name: "Save immutable research protocol" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Dataset hash does not match");
  expect(screen.queryByText("Immutable research protocol saved.", { exact: false })).toBeNull();
});
