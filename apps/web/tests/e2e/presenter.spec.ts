import { test, expect } from '@playwright/test';
import { login } from './login';

// A presenter's path: prepare a fresh rehearsal from the browser, wait for research
// results, switch roles without signing out, and see the advisory at triage.
// Runs after the other fictional-clinic specs because it replaces the rehearsal.
test('admin prepares a fresh rehearsal, roles switch in one step and the advisory answers at triage', async ({page},testInfo)=>{
  test.setTimeout(240_000);
  await login(page,'admin@showcase.hutano.test','DemoAdmin1!');
  await page.getByRole('button',{name:'Demo guide',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Prepare a fresh rehearsal'})).toBeVisible();
  await page.getByLabel(/Enable the advisory with a scripted review/).check();
  await page.getByRole('button',{name:'Prepare fresh rehearsal'}).click();
  await expect(page.getByText(/^Fresh rehearsal ready with \d+ people in the clinic\./)).toBeVisible({timeout:60000});

  // Background training and the queue comparison finish on their own; the guide updates itself.
  const readiness=page.getByRole('status',{name:'Demonstration readiness'});
  await expect(readiness).toContainText('Research results ready',{timeout:150000});
  await expect(readiness).toContainText('Advisory enabled by a scripted preparation review');
  await page.screenshot({path:testInfo.outputPath('demo-guide-ready.png'),fullPage:true});

  // One-step role change, only offered inside the fictional clinic.
  await page.getByLabel('Switch demo role').selectOption('triage');
  await expect(page.getByText(/Welcome, Nurse Chipo Ndlovu/)).toBeVisible({timeout:30000});
  await expect(page.getByLabel('Switch demo role')).toHaveValue('triage');

  await page.getByRole('button',{name:'Triage',exact:true}).click();
  const row=page.locator('.next-row').filter({hasText:'Shamiso Marufu'});
  await row.getByRole('button').click();
  await page.getByLabel(/^Temperature/).fill('38.4');
  await page.getByLabel(/^Pulse/).fill('132');
  await page.getByLabel(/^Respiratory rate/).fill('36');
  await page.getByLabel(/^Oxygen saturation/).fill('96');
  await page.getByRole('button',{name:'Request advisory explanation'}).click();
  // Either a suggestion or an explicit abstention: the model answered, it was not "unavailable".
  await expect(page.locator('.advisory-result')).toContainText(/Suggests|No suggestion — clinician assessment only/,{timeout:30000});
  await expect(page.locator('.advisory-result')).not.toContainText('Model unavailable');
  await page.screenshot({path:testInfo.outputPath('triage-advisory.png'),fullPage:true});

  // Back to the administrator for the rest of the demonstration.
  await page.getByLabel('Switch demo role').selectOption('admin');
  await expect(page.getByText(/Welcome, Tariro Dube/)).toBeVisible({timeout:30000});
});
