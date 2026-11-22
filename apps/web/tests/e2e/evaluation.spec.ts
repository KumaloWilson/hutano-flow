import { test, expect } from '@playwright/test';
import { login, fullShot } from './login';

// Objective 4 evidence end to end: a baseline-calibrated simulation, one consented
// usability session with SUS and TAM, and the Evaluation view that gathers both.
test('calibrated simulation and usability feedback reach the objective evaluation', async ({page},testInfo)=>{
  await login(page,'research@showcase.hutano.test','DemoResearch1!');

  // The fictional clinic seeds a synthetic time-and-motion baseline (ADR-035).
  await page.getByRole('button',{name:'Simulation lab',exact:true}).click();
  await page.getByRole('button',{name:'Calibrated from baseline',exact:true}).click();
  const baseline=page.getByLabel('Baseline dataset');
  await expect(baseline.locator('option')).not.toHaveCount(0);
  await expect(baseline).toContainText('synthetic time-and-motion baseline');
  await page.getByLabel('Scenario name').fill('Calibrated check · browser test');
  await page.getByLabel('Simulated clinic days').fill('4');
  await page.getByRole('button',{name:'Fit from baseline and compare'}).click();
  // Either verdict is acceptable; the check itself must be shown before any policy result.
  await expect(page.getByText(/^(Simulated FCFS reproduces the measured baseline|Simulation does not reproduce the measured baseline)$/)).toBeVisible({timeout:110000});
  await expect(page.getByRole('heading',{name:'Paired comparison with first come, first served'})).toBeVisible();
  await expect(page.getByRole('cell',{name:/consultation · /}).first()).toBeVisible();
  await fullShot(page, testInfo.outputPath('calibrated-simulation.png'));

  await page.getByRole('button',{name:'Evaluation',exact:true}).click();
  const objectives=page.locator('article.objective');
  await expect(objectives).toHaveCount(4);
  for (const id of ['O1','O2','O3','O4']) await expect(page.locator(`article#${id}`)).toBeVisible();
  await expect(page.locator('article#O1')).toContainText('Research question');
  await expect(page.getByText(/synthetic/i).first()).toBeVisible();
  await expect(page.locator('article#O4').getByRole('heading',{name:'Waiting time: existing process vs system'})).toBeVisible();
  await expect(page.locator('article#O4')).toContainText('Calibrated from the measured baseline');
  await expect(page.getByRole('heading',{name:'Limitations'})).toBeVisible();

  // One usability session. SUS answers 4,2,4,2… score (3+3)×5×2.5 = 75.
  const form=page.locator('form').filter({has:page.getByRole('button',{name:'Record feedback'})});
  await form.getByLabel('Role group').fill('Nursing');
  await form.getByLabel('Task').selectOption('triage');
  await form.getByLabel('Consent reference').fill('P-07');
  await form.getByLabel('Duration (seconds)').fill('94');
  await form.getByLabel('Error count').fill('0');
  await form.getByText(/^System Usability Scale/).click();
  for (let i=0;i<10;i++) await form.locator(`input[name="sus${i}"][value="${i%2?2:4}"]`).check();
  await form.getByText(/^Acceptance \(TAM\)/).click();
  for (let i=0;i<4;i++){ await form.locator(`input[name="pu${i}"][value="6"]`).check(); await form.locator(`input[name="peou${i}"][value="5"]`).check(); }
  await form.getByRole('button',{name:'Record feedback'}).click();
  await expect(page.getByText('Consented research feedback recorded.',{exact:true})).toBeVisible();
  const session=page.locator('article').filter({has:page.getByRole('heading',{name:'Usability session'})});
  await expect(session.locator('.metric').filter({hasText:'Mean SUS'})).toContainText('75');
  await expect(session.locator('.metric').filter({hasText:'Tasks completed'})).toContainText('1/1');

  await page.getByRole('button',{name:'Refresh'}).click();
  const acceptance=page.locator('article#O4 .metric');
  await expect(acceptance.filter({hasText:'Mean SUS'})).toContainText('75');
  await expect(acceptance.filter({hasText:'Perceived usefulness'})).toContainText('6');
  await expect(acceptance.filter({hasText:'Perceived ease of use'})).toContainText('5');
  await fullShot(page, testInfo.outputPath('evaluation-objectives.png'));
});
