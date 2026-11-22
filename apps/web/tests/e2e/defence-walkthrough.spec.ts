import { test, expect, Page } from '@playwright/test';
import { login } from './login';

// Performs docs/DEFENCE_SCRIPT.md click by click, as the presenter would, on a freshly
// prepared fictional clinic. If this test fails, the matching script step would fail on stage.
const go = (page: Page, name: string) => page.getByRole('button', { name, exact: true }).first().click();
async function become(page: Page, role: string, welcome: RegExp) {
  await page.getByLabel('Switch demo role').selectOption(role);
  await expect(page.getByText(welcome)).toBeVisible({ timeout: 30000 });
}
const dialog = (page: Page) => page.getByRole('dialog');
async function confirm(page: Page, button: string | RegExp = /Confirm action|Assign room & call|Record review/) {
  await dialog(page).getByRole('button', { name: button }).click();
  await expect(dialog(page)).toHaveCount(0);
}
const panel = (page: Page, heading: string) => page.locator('article').filter({ has: page.getByRole('heading', { name: heading, exact: true }) });

test('the defence script works end to end', async ({ page, context }, testInfo) => {
  test.setTimeout(600_000);
  const shot = (name: string) => page.screenshot({ path: testInfo.outputPath(`defence-${name}.png`), fullPage: true });

  await test.step('Part 1: prepare a fresh rehearsal, pre-run comparisons, record the review', async () => {
    await login(page, 'admin@showcase.hutano.test', 'DemoAdmin1!');
    await go(page, 'Demo guide');
    await page.getByRole('button', { name: 'Prepare fresh rehearsal' }).click();
    await expect(page.getByText(/^Fresh rehearsal ready with 17 people in the clinic\./)).toBeVisible({ timeout: 60000 });
    await expect(page.getByRole('status', { name: 'Demonstration readiness' })).toContainText('Research results ready', { timeout: 180000 });
    // Practice registrations from earlier runs are closed: only the 15 unfinished scripted people remain.
    await go(page, 'Overview');
    await expect(page.getByText('15 active visits', { exact: true })).toBeVisible();
    await go(page, 'Simulation lab');
    await page.getByLabel('Scenario name').fill('Morning comparison with research policies');
    await page.getByLabel('Patients').fill('150');
    await page.getByLabel('Include research-only arms').check();
    await page.getByRole('button', { name: /Run paired comparison|Run simulation|Compare/ }).first().click();
    await expect(page.getByRole('heading', { name: 'The patient at the bottom of the queue' })).toBeVisible({ timeout: 120000 });
    await page.getByRole('button', { name: 'Calibrated from baseline', exact: true }).click();
    await page.getByLabel('Scenario name').fill('Calibrated baseline check');
    await page.getByLabel('Simulated clinic days').fill('10');
    await page.getByRole('button', { name: 'Fit from baseline and compare' }).click();
    await expect(page.getByText(/^(Simulated FCFS reproduces the measured baseline|Simulation does not reproduce the measured baseline)$/)).toBeVisible({ timeout: 120000 });
    await become(page, 'clinician', /Welcome, Dr Nyasha Mupfumi/);
    await go(page, 'Help & safety');
    // A model reviewed in an earlier rehearsal is retrained identically and stays reviewed.
    const experimental = page.getByText(/^Model .* EXPERIMENTAL$/);
    await expect(page.getByText(/^Model .* (EXPERIMENTAL|REVIEWED)$/).first()).toBeVisible();
    if (await experimental.count()) {
      await experimental.first().click();
      await page.getByRole('button', { name: 'Record clinician research review' }).click();
      await dialog(page).getByLabel('Reason', { exact: true }).fill('Reviewed for synthetic demonstration only');
      await confirm(page);
    }
  });

  await test.step('Step 2: Overview shows the morning at a glance', async () => {
    await become(page, 'admin', /Welcome, Tariro Dube/);
    await expect(page.getByText(/1 long wait at Consultation/)).toBeVisible();
    await expect(page.getByText(/1 escalation alert/)).toBeVisible();
    await shot('overview');
  });

  let token = '';
  await test.step('Step 3: Reception registers a walk-in and completes Tawanda at the desk', async () => {
    await become(page, 'reception', /Welcome, Rudo Moyo/);
    await go(page, 'Registration');
    await page.getByLabel('Pseudonym or internal ID (for search)').fill('Rejoice Mukanya');
    await page.getByLabel('Age band').selectOption('adult');
    await page.getByLabel('Recorded sex').selectOption('female');
    await page.getByLabel('Visit type').selectOption('walk_in');
    await page.getByRole('button', { name: 'Create visit and complete registration' }).click();
    token = await page.getByLabel('Opaque status token').inputValue();
    expect(token.length).toBeGreaterThan(20);
    const desk = page.getByRole('article', { name: 'Waiting at the front desk' });
    await desk.locator('.next-row').filter({ hasText: 'Tawanda Gumbo' }).getByRole('button', { name: 'Complete registration' }).click();
    await expect(page.getByText(/is now waiting for triage/)).toBeVisible();
    await shot('registration');
  });

  await test.step('Step 4: the patient\'s phone shows only their own status', async () => {
    const phone = await context.newPage();
    await phone.setViewportSize({ width: 390, height: 844 });
    await phone.goto('/status');
    await phone.getByLabel(/token/i).first().fill(token);
    await phone.getByRole('button', { name: /check|show|status/i }).first().click();
    await expect(phone.locator('main')).toContainText(/triage/i);
    await expect(phone.locator('main')).not.toContainText('Rejoice');
    await phone.screenshot({ path: testInfo.outputPath('defence-status.png'), fullPage: true });
    await phone.close();
  });

  await test.step('Step 5: enable the reviewed advisory, triage Shamiso, confirm the category', async () => {
    await become(page, 'admin', /Welcome, Tariro Dube/);
    await go(page, 'AI research');
    await page.getByRole('button', { name: 'Activate reviewed advisory' }).first().click();
    await dialog(page).getByLabel('Reason', { exact: true }).fill('Enabled for the synthetic demonstration');
    await confirm(page);
    await become(page, 'triage', /Welcome, Nurse Chipo Ndlovu/);
    await go(page, 'Triage');
    await page.locator('.next-row').filter({ hasText: 'Shamiso Marufu' }).getByRole('button').click();
    await page.getByLabel(/^Temperature/).fill('38.4');
    await page.getByLabel(/^Pulse/).fill('132');
    await page.getByLabel(/^Respiratory rate/).fill('36');
    await page.getByLabel(/^Oxygen saturation/).fill('96');
    await page.getByRole('button', { name: 'Request advisory explanation' }).click();
    await expect(page.locator('.advisory-result')).toContainText(/Suggests|No suggestion — clinician assessment only/);
    await page.getByLabel('Clinician-confirmed urgency').selectOption('P2');
    await page.getByLabel('Assessment rationale').fill('Fever and fast breathing; seen ahead of routine patients');
    await page.getByRole('button', { name: 'Confirm assessment' }).click();
    await confirm(page, 'Confirm clinician assessment');
    await expect(page.locator('.next-row').filter({ hasText: 'Shamiso Marufu' })).toHaveCount(0);
    await shot('triage');
  });

  await test.step('Step 6: live queue, review Brighton, override with a reason', async () => {
    await become(page, 'clinician', /Welcome, Dr Nyasha Mupfumi/);
    await go(page, 'Live queues');
    const brighton = page.locator('.queue-list > li').filter({ hasText: 'Brighton Nhamo' }).first();
    await expect(brighton.getByText('Review suggested').first()).toBeVisible();
    await brighton.getByRole('button', { name: 'Review', exact: true }).click();
    await confirm(page, 'Record review');
    const godknows = page.locator('.queue-list > li').filter({ hasText: 'Godknows Mutasa' }).first();
    await godknows.getByRole('button', { name: 'Override', exact: true }).click();
    await dialog(page).getByLabel('Reason', { exact: true }).fill('Clinician moved forward after reassessment');
    await confirm(page);
    await shot('queues');
  });

  await test.step('Step 7: consultation, laboratory and pharmacy', async () => {
    await go(page, 'Service console');
    const paused = page.locator('.service-card').filter({ hasText: 'Takudzwa Madziva' });
    await paused.getByRole('button', { name: 'Resume service' }).click();
    await dialog(page).getByLabel('Reason', { exact: true }).fill('Patient back with his clinic card');
    await confirm(page);
    await paused.getByRole('button', { name: 'Complete & route' }).click();
    await dialog(page).getByLabel('Next service').selectOption('');
    await dialog(page).getByLabel('Service completion note').fill('Reviewed; advised and discharged home.');
    await confirm(page);
    const fadzai = page.locator('.service-card').filter({ hasText: 'Fadzai Kativhu' });
    await fadzai.getByRole('button', { name: 'Complete & route' }).click();
    await dialog(page).getByLabel('Next service').selectOption({ label: 'Pharmacy' });
    await dialog(page).getByLabel('Service completion note').fill('Seen; to pharmacy to collect medicines.');
    await confirm(page);
    await panel(page, 'Consultation').getByRole('button', { name: 'Call next' }).click();
    await confirm(page, 'Assign room & call');
    await expect(page.getByText(/called to Consultation room/)).toBeVisible();

    await become(page, 'laboratory', /Welcome, Ruvimbo Chirwa/);
    await go(page, 'Live queues');
    // Laboratory staff see the ticket only, not the name: privacy by role.
    const labQueue = panel(page, 'Laboratory');
    await expect(labQueue).not.toContainText('Charity Makoni');
    await labQueue.getByRole('button', { name: 'Call', exact: true }).first().click();
    await confirm(page, 'Assign room & call');
    await go(page, 'Service console');
    const lab = page.locator('.service-card').first();
    await lab.getByRole('button', { name: 'Start service' }).click();
    await lab.getByRole('button', { name: 'Complete & route' }).click();
    await dialog(page).getByLabel('Next service').selectOption({ label: 'Consultation' });
    await dialog(page).getByLabel('Service completion note').fill('Blood test done; back to the doctor with the result.');
    await confirm(page);

    await become(page, 'pharmacy', /Welcome, Tendai Sibanda/);
    await go(page, 'Service console');
    const inbox = panel(page, 'Incoming service handovers');
    await inbox.locator('li, .handover, div').filter({ hasText: 'Shona' }).getByRole('button', { name: 'Acknowledge handover' }).first().click();
    await panel(page, 'Pharmacy').getByRole('button', { name: 'Call next' }).click();
    await confirm(page, 'Assign room & call');
    const sib = page.locator('.service-card').filter({ hasText: /A-\d+/ }).first();
    await sib.getByRole('button', { name: 'Start service' }).click();
    await sib.getByRole('button', { name: 'Complete & route' }).click();
    await dialog(page).getByLabel('Next service').selectOption('');
    await dialog(page).getByLabel('Service completion note').fill('Medicines collected; explained in Shona.');
    await confirm(page);
    await expect(page.getByText(/visit closed/i)).toBeVisible();
    await go(page, 'Patient journeys');
    await expect(page.getByRole('heading', { name: 'Journey timeline' })).toBeVisible();
    await shot('journey');
  });

  await test.step('Step 8: a room closes; nobody leaves the queue', async () => {
    await become(page, 'admin', /Welcome, Tariro Dube/);
    await go(page, 'Facility admin');
    const row = page.locator('div, li, tr').filter({ hasText: /^Consultation/ }).filter({ has: page.getByRole('button', { name: 'Change availability' }) }).last();
    await row.getByRole('button', { name: 'Change availability' }).click();
    await dialog(page).getByLabel('Capacity').fill('0');
    await dialog(page).getByLabel('Reason', { exact: true }).fill('Room flooded');
    await confirm(page);
    await go(page, 'Overview');
    await expect(page.getByText(/Consultation is unavailable/i)).toBeVisible();
    await go(page, 'Facility admin');
    await row.getByRole('button', { name: 'Change availability' }).click();
    await dialog(page).getByLabel('Capacity').fill('2');
    await dialog(page).getByLabel('Reason', { exact: true }).fill('Room reopened');
    await confirm(page);
  });

  await test.step('Step 9: the baseline report and analytics', async () => {
    await become(page, 'research', /Welcome, Kudzai Ncube/);
    await go(page, 'AI research');
    await page.getByText(/^Stored baseline: Fictional clinic · synthetic time-and-motion baseline/).click();
    await expect(page.locator('main')).toContainText(/registration/i);
    await go(page, 'Analytics');
    await page.getByRole('button', { name: 'Last 7 days', exact: true }).click();
    await expect(page.getByRole('link', { name: 'Export CSV' })).toBeVisible();
  });

  await test.step('Step 10: simulation results — calibrated, morning, research policies', async () => {
    await go(page, 'Simulation lab');
    const saved = page.getByLabel('Saved comparisons');
    for (const name of ['Calibrated baseline check', 'Fictional clinic · morning queue comparison', 'Morning comparison with research policies']) {
      const option = saved.locator('option').filter({ hasText: name }).first();
      await saved.selectOption({ label: (await option.textContent())!.trim() });
      await expect(page.getByText('SYNTHETIC SIMULATION — NOT CLINICAL EVIDENCE', { exact: true })).toBeVisible({ timeout: 30000 });
    }
    await expect(page.getByRole('heading', { name: 'The patient at the bottom of the queue' })).toBeVisible();
    await shot('simulation');
  });

  await test.step('Steps 11–12: the Evaluation view', async () => {
    await go(page, 'Evaluation');
    await expect(page.locator('article.objective')).toHaveCount(4);
    await expect(page.locator('article#O2')).toContainText('Macro-F1');
    await expect(page.getByRole('heading', { name: 'Usability session' })).toBeVisible();
    await shot('evaluation');
  });

  await test.step('Step 13: audit trail; switch the AI off and triage still works', async () => {
    await become(page, 'admin', /Welcome, Tariro Dube/);
    await go(page, 'Audit log');
    await expect(page.locator('main')).toContainText(/override/i);
    await go(page, 'AI research');
    await page.getByRole('button', { name: 'Disable advisory' }).first().click();
    await dialog(page).getByLabel('Reason', { exact: true }).fill('Showing the clinic works without the AI');
    await confirm(page);
    await become(page, 'triage', /Welcome, Nurse Chipo Ndlovu/);
    await go(page, 'Triage');
    await page.getByRole('button', { name: 'Request advisory explanation' }).click();
    await expect(page.locator('.advisory-result')).toContainText('Model unavailable');
  });
});
