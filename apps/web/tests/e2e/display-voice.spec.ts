import { test, expect } from '@playwright/test';
import { login, fullShot } from './login';

// The waiting-room display speaks each new call. Headless browsers have no speakers, so the
// page's speech engine is replaced with a recorder; everything else is the real system.
const recordSpeech = () => {
  (window as any).__spoken = [];
  const synth = { speak: (u: any) => { (window as any).__spoken.push(u.text); setTimeout(() => u.onend?.(), 0); },
    getVoices: () => [{ lang: 'en-GB', name: 'Recorder' }], resume() {}, cancel() {}, addEventListener() {} };
  Object.defineProperty(window, 'speechSynthesis', { value: synth, configurable: true });
  (window as any).SpeechSynthesisUtterance = class { text: string; constructor(text: string) { this.text = text; } };
};

test('the waiting-room display announces a call out loud, and asks for one tap after a reload', async ({ page, context }, testInfo) => {
  await login(page, 'admin@showcase.hutano.test', 'DemoAdmin1!');
  await page.getByRole('button', { name: 'Facility admin', exact: true }).click();
  await page.getByLabel('Screen name').fill('Main waiting area TV');
  await page.getByRole('button', { name: 'Create display link' }).click();
  const link = await page.getByRole('textbox', { name: 'Display link' }).inputValue();

  const tv = await context.newPage();
  await tv.addInitScript(recordSpeech);
  await tv.goto(link);
  await expect(tv.getByText(/Hutano Community Clinic/)).toBeVisible();
  await tv.getByRole('button', { name: 'Voice off' }).click();
  await expect(tv.getByRole('button', { name: 'Voice on' })).toBeVisible();
  await expect.poll(() => tv.evaluate(() => (window as any).__spoken)).toContain('Voice announcements are on.');
  await tv.getByRole('button', { name: 'Test voice' }).click();
  await expect.poll(() => tv.evaluate(() => (window as any).__spoken.join(' | '))).toContain('Ticket A, 0 1 4. Please go to Consultation, Consultation room 1.');

  // A triage nurse calls the next patient; the display speaks that ticket within a few seconds.
  await page.getByLabel('Switch demo role').selectOption('triage');
  await expect(page.getByText(/Welcome, Nurse Chipo Ndlovu/)).toBeVisible({ timeout: 30000 });
  await page.getByRole('button', { name: 'Live queues', exact: true }).click();
  const triage = page.locator('article').filter({ has: page.getByRole('heading', { name: 'Triage', exact: true }) });
  const ticket = (await triage.locator('.queue-list > li').first().locator('.ticket').first().innerText()).trim();
  await triage.getByRole('button', { name: 'Call', exact: true }).first().click();
  await page.getByRole('dialog').getByRole('button', { name: 'Assign room & call' }).click();
  await expect(page.getByText(/called to Triage desk/)).toBeVisible();
  const [letters, digits] = ticket.split('-');
  const spokenTicket = `${letters}, ${digits.split('').join(' ')}`;
  await expect.poll(() => tv.evaluate(() => (window as any).__spoken.join(' | ')), { timeout: 15000 })
    .toContain(`Ticket ${spokenTicket}. Please go to Triage, Triage desk.`);
  await fullShot(tv, testInfo.outputPath('display-voice.png'));

  // After a reload the setting is remembered, but browsers need one tap before playing sound.
  await tv.reload();
  await tv.getByRole('button', { name: 'Tap to turn on announcements' }).click();
  await expect.poll(() => tv.evaluate(() => (window as any).__spoken)).toContain('Announcements are on.');
  await expect(tv.getByRole('button', { name: 'Tap to turn on announcements' })).toHaveCount(0);
});
