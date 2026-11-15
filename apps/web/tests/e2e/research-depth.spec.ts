import { expect, Page, test } from "@playwright/test";

const API = process.env.E2E_API_URL || "http://localhost:8000";
const ROOT = "/api/v1/research/workbench";
import { login } from "./login";
async function command(page: Page, path: string, body: unknown) {
  const csrf = (await page.context().cookies()).find(c => c.name === "hutano_csrf")!.value;
  const response = await page.request.post(API + path, { data: body, headers: { "X-CSRF-Token": csrf, "Idempotency-Key": crypto.randomUUID() } });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}
async function read(page: Page, path: string) {
  const response = await page.request.get(API + path);
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}
async function createProtocol(page: Page, name: string, modelId?: string) {
  await page.getByRole("button", { name: "Research workbench", exact: true }).click();
  await page.getByLabel("Protocol name", { exact: true }).fill(name);
  await page.getByLabel("Cases reserved for this protocol").fill("12");
  await page.getByLabel("Synthetic development days").fill("28");
  await page.getByLabel("Held-out synthetic evaluation days").fill("4");
  await page.getByLabel("Mean synthetic arrivals / day").fill("20");
  await page.getByLabel("Paired operational replications").fill("2");
  if (modelId) {
    await page.getByLabel("Frozen advisory model", { exact: true }).selectOption(modelId);
    await page.getByLabel("Human study design", { exact: true }).selectOption("SHADOW");
  }
  const saved = page.waitForResponse(r => r.url() === API + ROOT + "/protocols" && r.request().method() === "POST");
  await page.getByRole("button", { name: "Save immutable research protocol" }).click();
  const response = await saved;
  expect(response.status(), await response.text()).toBe(201);
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  return response.json();
}
async function openProtocol(page: Page, id: string) {
  await page.getByRole("button", { name: "Research workbench", exact: true }).click();
  await page.getByLabel("Saved research protocol").selectOption(id);
  await expect(page.getByRole("heading", { name: "Blinded synthetic-case review", exact: true })).toBeVisible();
}

test("frozen research protocol, held-out waiting/planning worker and reproducible exports", async ({ page }, info) => {
  await login(page, "research@demo.hutano.test", "DemoResearch1!");
  const protocol = await createProtocol(page, `Synthetic operations verification ${Date.now()}`);
  expect(protocol.design).toBe("MANUAL_ONLY");
  await page.getByRole("button", { name: "Run saved operations study", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Held-out operations study results", exact: true })).toBeVisible({ timeout: 90000 });
  await expect(page.getByRole("heading", { name: "Direct waiting-time prediction", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Equal-budget resource planning", exact: true })).toBeVisible();
  await page.getByLabel("Planning sensitivity scenario").selectOption("ROOM_OUTAGE");
  const resultPanel = page.locator("article").filter({ has: page.getByRole("heading", { name: "Held-out operations study results", exact: true }) });
  const exported = await page.request.get((await resultPanel.getByRole("link", { name: "Export JSON", exact: true }).getAttribute("href"))!);
  expect(exported.ok()).toBeTruthy();
  const evidence = await exported.json();
  expect(evidence.protocol_hash).toBe(protocol.config_hash);
  expect(evidence.results.priority_effect).toBe("NONE");
  expect(evidence.results.live_schedule_mutations).toBe(false);
  expect(Object.keys(evidence.results.resource_planning.sensitivities[0].policies)).toHaveLength(4);
  expect(evidence.results.wait_prediction.test.rows).toBeGreaterThan(0);
  for (const row of Object.values(evidence.results.resource_planning.sensitivities[0].policies) as any[]) {
    expect(row.paid_staff_minutes).toBe(1080);
    expect(row.all_constraints_valid).toBe(true);
  }
  await page.screenshot({ path: info.outputPath("research-operations-study.png"), fullPage: true });
});

test("independent blinded labels, consensus and shadow reveal only after saved assessment", async ({ browser }, info) => {
  const contexts = await Promise.all([browser.newContext(), browser.newContext(), browser.newContext()]);
  const [research, clinician, triage] = await Promise.all(contexts.map(c => c.newPage()));
  try {
    await login(research, "research@demo.hutano.test", "DemoResearch1!");
    await login(clinician, "clinician@demo.hutano.test", "DemoClinician1!");
    await login(triage, "triage@demo.hutano.test", "DemoTriage1!");
    // Real API setup for a separate synthetic artifact; never activate it.
    const job = await command(research, "/api/v1/research/models/train", { seed: 2028 });
    await expect.poll(async () => (await read(research, `/api/v1/research/jobs/${job.job_id}`)).status, { timeout: 90000 }).toBe("COMPLETED");
    const complete = await read(research, `/api/v1/research/jobs/${job.job_id}`);
    await command(clinician, `/api/v1/research/models/${complete.result_ref}/lifecycle`, { action: "REVIEW", reason: "Automated synthetic browser fixture only; no real clinician endorsement or clinical validation" });
    const protocol = await createProtocol(research, `Synthetic shadow verification ${Date.now()}`, complete.result_ref);
    await research.getByText("Calibration, selective prediction & model diagnostics", { exact: true }).click();
    await research.getByLabel("Inspect research model").selectOption(complete.result_ref);
    await expect(research.getByRole("heading", { name: "Risk–coverage trade-off", exact: true })).toBeVisible();
    await research.screenshot({ path: info.outputPath("research-calibration.png"), fullPage: true });
    await openProtocol(clinician, protocol.id);
    const cases = (await read(clinician, `${ROOT}/protocols/${protocol.id}`)).cases;
    await clinician.getByLabel("Blinded case", { exact: true }).selectOption(cases[0].id);
    await clinician.getByLabel("Independent review label", { exact: true }).selectOption("P2");
    await clinician.getByLabel("Independent review rationale", { exact: true }).fill("Automated first independent synthetic reference fixture");
    await clinician.getByRole("button", { name: "Save blinded independent review" }).click();
    await expect(clinician.getByText("Your saved review: P2.", { exact: false })).toBeVisible();
    await openProtocol(triage, protocol.id);
    expect((await read(triage, `${ROOT}/protocols/${protocol.id}`)).cases[0].own_review).toBeNull();
    await triage.getByLabel("Blinded case", { exact: true }).selectOption(cases[0].id);
    await triage.getByLabel("Independent review label", { exact: true }).selectOption("P3");
    await triage.getByLabel("Independent review rationale", { exact: true }).fill("Automated second blinded synthetic reference fixture");
    await triage.getByRole("button", { name: "Save blinded independent review" }).click();
    await triage.getByRole("button", { name: "Open two-reviewer consensus" }).click();
    await triage.getByLabel("Consensus reference label", { exact: true }).selectOption("P2");
    await triage.getByLabel("Consensus reference rationale", { exact: true }).fill("Automated synthetic consensus fixture, not clinical ground truth");
    await triage.getByRole("button", { name: "Save two-reviewer consensus" }).click();
    await expect(triage.getByText("Reference consensus has already been recorded.", { exact: true })).toBeVisible();
    await clinician.getByLabel("Participant consent reference", { exact: true }).fill("AUTOMATED_SOFTWARE_FIXTURE_NOT_RECRUITED");
    await clinician.getByLabel("The participant has consented to this synthetic exercise", { exact: true }).check();
    await clinician.getByRole("button", { name: "Start assigned participant trial", exact: true }).click();
    const assigned = clinician.getByRole("region", { name: "Assigned participant case" });
    await expect(assigned).toContainText("Shadow mode: the model output is hidden");
    await expect(assigned.getByRole("heading", { name: "Experimental advisory" })).toHaveCount(0);
    const before = await read(clinician, `${ROOT}/protocols/${protocol.id}`);
    expect(before.trials[0].advisory).toBeNull();
    expect(before.trials[0].case_id).not.toBe(cases[0].id);
    await clinician.getByLabel("Participant final label", { exact: true }).selectOption("P3");
    await clinician.getByLabel("Self-reported trust rating", { exact: true }).selectOption("2");
    await clinician.getByLabel("Participant decision rationale", { exact: true }).fill("Automated independent response fixture before shadow reveal");
    await clinician.getByLabel("Does the human retain final decision authority?", { exact: true }).selectOption("yes");
    await clinician.getByRole("button", { name: "Save independent trial decision", exact: true }).click();
    await expect(assigned.getByRole("heading", { name: "Experimental advisory" })).toBeVisible();
    await expect(assigned.getByText("Decision saved: P3.", { exact: false })).toBeVisible();
    await clinician.screenshot({ path: info.outputPath("research-shadow-workflow.png"), fullPage: true });
    expect((await clinician.request.get(API + `${ROOT}/protocols/${protocol.id}/monitor`)).status()).toBe(403);
    const report = await read(research, `${ROOT}/protocols/${protocol.id}/export`);
    expect(report.summary.paired_cases).toBe(1);
    expect(report.summary.adjudicated_cases).toBe(1);
    expect(report.monitor.shadow_completed).toBe(1);
    expect(JSON.stringify(report)).not.toContain("AUTOMATED_SOFTWARE_FIXTURE_NOT_RECRUITED");
    expect((await read(research, "/api/v1/research/models")).find((m: any) => m.id === complete.result_ref).active).toBe(false);
  } finally {
    await Promise.all(contexts.map(c => c.close()));
  }
});
