import { test, expect } from '@playwright/test';
import { login } from './login';

test('fictional clinic connects guide, patient history, queues and paused service', async ({page},testInfo)=>{
  await login(page,'clinician@showcase.hutano.test','DemoClinician1!');
  await expect(page.getByRole('heading',{name:'A clear view of today’s clinic.'})).toBeVisible();
  await expect(page.locator('.brand')).toContainText('Hutano Community Clinic');
  await page.screenshot({path:testInfo.outputPath('clinic-overview.png'),fullPage:true});
  await page.getByRole('button',{name:'Demo guide',exact:true}).click();
  await expect(page.getByText('All records fictional',{exact:true})).toBeVisible();
  // Scenarios read as plain-language attendances, not test labels.
  await expect(page.getByRole('row').filter({hasText:'Tawanda Gumbo'})).toContainText('front desk');
  await page.getByRole('row').filter({hasText:'Rutendo Chari'}).getByRole('button',{name:'Open record',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Longitudinal patient workspace'})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Rutendo Chari',exact:true})).toBeVisible();
  expect(await page.getByLabel('Encounter history').locator('option').count()).toBeGreaterThan(1);
  await page.screenshot({path:testInfo.outputPath('clinic-patient-history.png'),fullPage:true});
  await page.getByRole('button',{name:'Live queues',exact:true}).click();
  await page.getByLabel('Filter queue').fill('no-such-fictional-name');
  await expect(page.locator('.queue-list li')).toHaveCount(0);
  await page.getByLabel('Filter queue').fill('');
  await expect(page.locator('.queue-list li').first()).toBeVisible();
  await page.getByRole('button',{name:'Service console',exact:true}).click();
  const paused=page.locator('.service-card').filter({has:page.getByRole('button',{name:'Resume service',exact:true})});
  const id=await paused.getAttribute('data-visit-id');
  await paused.getByRole('button',{name:'Resume service',exact:true}).click();
  await page.getByRole('dialog').getByLabel('Reason',{exact:true}).fill('Fictional rehearsal: patient returned to room');
  await page.getByRole('dialog').getByRole('button',{name:'Confirm action'}).click();
  const card=page.locator(`.service-card[data-visit-id="${id}"]`);
  await expect(card.getByRole('button',{name:'Complete & route'})).toBeVisible();
  await card.getByRole('button',{name:'Complete & route'}).click();
  await page.getByRole('dialog').getByLabel('Next service').selectOption('');
  await page.getByRole('dialog').getByLabel('Service completion note').fill('Fictional demonstration completed; no treatment recorded.');
  await page.getByRole('dialog').getByRole('button',{name:'Confirm action'}).click();
  await expect(page.getByText('Service completed and visit closed.',{exact:true})).toBeVisible();
  await expect(card).toHaveCount(0);
  // Calling in a service with staffed rooms: one dialog picks the free room and calls.
  // Room 2 was released above; room 1 is still occupied by the scripted consultation.
  const consultation=page.locator('article.panel').filter({has:page.getByRole('heading',{name:'Consultation',exact:true})});
  await consultation.getByRole('button',{name:'Call next'}).click();
  const dialog=page.getByRole('dialog');
  await expect(dialog).toContainText('Call');
  await expect(dialog.getByRole('combobox',{name:'Room'})).toContainText('Consultation room 2');
  await expect(dialog.getByRole('combobox',{name:'Room'}).locator('option')).toHaveCount(1);
  await dialog.getByRole('button',{name:'Assign room & call'}).click();
  await expect(page.getByText(/called to Consultation room 2\./)).toBeVisible();
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('button',{name:'Overview',exact:true}).click();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
  await page.screenshot({path:testInfo.outputPath('clinic-mobile.png'),fullPage:true});
});

test('researcher sees dated evidence and real saved comparisons without patient identities',async({page},testInfo)=>{
  await login(page,'research@showcase.hutano.test','DemoResearch1!');
  await expect(page.getByRole('button',{name:'Patient workspace',exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'Analytics',exact:true}).click();
  await expect(page.getByText('377 completed',{exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'Last 7 days',exact:true}).click();
  await expect(page.getByRole('button',{name:'Apply dates'})).toBeEnabled();
  await expect(page.getByRole('heading',{name:'Daily arrival cohorts'})).toBeVisible();
  await expect(page.getByRole('link',{name:'Export CSV'})).toHaveAttribute('href',/from_date=/);
  await expect(page.locator('main')).not.toContainText('Rutendo Chari');
  await page.screenshot({path:testInfo.outputPath('clinic-analytics.png'),fullPage:true});
  await page.getByRole('button',{name:'Simulation lab',exact:true}).click();
  const saved=page.getByLabel('Saved comparisons');
  await expect(saved.locator('option')).toHaveCount(2,{timeout:90000});
  await saved.selectOption({index:1});
  await expect(page.locator('.policy-results > div')).toHaveCount(3);
  await expect(page.getByText('SYNTHETIC SIMULATION — NOT CLINICAL EVIDENCE',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Consultation outage',exact:true}).click();
  await expect(page.getByLabel('Scenario name')).toHaveValue('Consultation outage');
  await page.screenshot({path:testInfo.outputPath('clinic-simulation.png'),fullPage:true});
});
