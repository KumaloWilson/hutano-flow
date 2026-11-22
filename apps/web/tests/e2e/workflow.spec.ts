import {test, expect, Page} from '@playwright/test';

import { login } from "./login";

test('complete database-backed journey, two tabs, private status and offline controls',async ({browser},testInfo)=>{
  const reception = await browser.newContext();
  const clinical = await browser.newContext();
  const pharmacy = await browser.newContext();
  const patient = await browser.newContext({viewport:{width:390,height:844}});
  const r=await reception.newPage(),c=await clinical.newPage(),p=await pharmacy.newPage(),s=await patient.newPage();
  await login(r,'reception@demo.hutano.test','DemoReception1!');
  await login(c,'clinician@demo.hutano.test','DemoClinician1!');
  await c.getByRole('button',{name:'Triage',exact:true}).click();
  await r.getByRole('button',{name:'Registration',exact:true}).click();
  const pseudonym=`Synthetic browser ${Date.now()}`;
  await r.getByLabel('Pseudonym or internal ID (for search)').fill(pseudonym);
  await r.getByRole('button',{name:'Create visit and complete registration'}).click();
  await expect(r.getByText('Synthetic visit registered and queued for triage.')).toBeVisible();
  const secret=await r.getByLabel('Opaque status token').inputValue();
  const token=secret.split('.')[0];
  // Clinician tab was already open; no navigation or manual reload after registration.
  await expect(c.getByRole('combobox',{name:'Visit',exact:true})).toContainText(pseudonym,{timeout:15000});
  const option=await c.getByRole('combobox',{name:'Visit',exact:true}).locator('option').filter({hasText:pseudonym}).getAttribute('value');
  await c.getByRole('combobox',{name:'Visit',exact:true}).selectOption(option!);
  await c.getByRole('button',{name:'Request advisory explanation'}).click();
  await expect(c.getByText('Model unavailable — clinician assessment required',{exact:true})).toBeVisible();
  await c.getByLabel('Clinician-confirmed urgency').selectOption('P2');
  await c.getByLabel('Assessment rationale').fill('Synthetic demonstration; clinician confirmed.');
  await c.getByRole('button',{name:'Confirm assessment',exact:true}).click();
  await c.getByRole('dialog').getByRole('button',{name:'Confirm clinician assessment'}).click();
  await expect(c.getByText('Clinician urgency confirmed; consultation queue updated.')).toBeVisible();
  await c.getByRole('button',{name:'Live queues',exact:true}).click();
  const consult=c.locator('article').filter({has:c.getByRole('heading',{name:'Consultation',exact:true})});
  const queued=consult.locator(`li[data-visit-id="${option}"]`);
  await expect(queued).toBeVisible();
  await queued.getByRole('button',{name:'Override',exact:true}).click();
  await c.getByRole('dialog').getByLabel('Reason',{exact:true}).fill('Synthetic clinician override demonstration');
  await c.getByRole('dialog').getByRole('button',{name:'Confirm action'}).click();
  await expect(c.getByText('Override pinned and audited.')).toBeVisible();
  await c.screenshot({path:testInfo.outputPath('queue.png'),fullPage:true});
  await s.goto('/status');
  await s.getByLabel('Private status token').fill(secret);
  await s.getByRole('button',{name:'Check status',exact:true}).click();
  await expect(s.getByRole('heading',{name:'Consultation',exact:true})).toBeVisible();
  await expect(s.locator('.patient-result')).not.toContainText(pseudonym);
  await expect(s.locator('.patient-result')).not.toContainText('P2');
  expect(s.url()).not.toContain(secret);
  await queued.getByRole('button',{name:'Call',exact:true}).click();
  await c.getByRole('dialog').getByRole('button',{name:'Confirm action'}).click();
  await expect(c.getByText(`${token} called atomically.`)).toBeVisible();
  await c.getByRole('button',{name:'Service console',exact:true}).click();
  const card=c.locator(`.service-card[data-visit-id="${option}"]`);
  await card.getByRole('button',{name:'Start service',exact:true}).click();
  await expect(card.getByRole('button',{name:'Complete & route',exact:true})).toBeVisible();
  await card.getByRole('button',{name:'Complete & route',exact:true}).click();
  await c.getByRole('dialog').getByRole('combobox',{name:'Next service',exact:true}).selectOption('pharmacy');
  await c.getByRole('dialog').getByRole('button',{name:'Confirm action'}).click();
  await expect(c.getByText('Service completed and routed to pharmacy.')).toBeVisible();
  await login(p,'pharmacy@demo.hutano.test','DemoPharmacy1!');
  await expect(p.getByRole('button',{name:'AI research',exact:true})).toHaveCount(0);
  await p.getByRole('button',{name:'Live queues',exact:true}).click();
  await p.locator(`li[data-visit-id="${option}"]`).getByRole('button',{name:'Call',exact:true}).click();
  await p.getByRole('dialog').getByRole('button',{name:'Confirm action'}).click();
  await p.getByRole('button',{name:'Service console',exact:true}).click();
  await p.locator(`.service-card[data-visit-id="${option}"]`).getByRole('button',{name:'Start service'}).click();
  await p.locator(`.service-card[data-visit-id="${option}"]`).getByRole('button',{name:'Complete & route'}).click();
  await p.getByRole('dialog').getByRole('combobox',{name:'Next service',exact:true}).selectOption('');
  await p.getByRole('dialog').getByRole('button',{name:'Confirm action'}).click();
  await expect(p.getByText('Service completed and visit closed.')).toBeVisible();
  // Patient page polls the stored database status without re-entering the token.
  await expect(s.getByRole('heading',{name:'Complete',exact:true})).toBeVisible({timeout:20000});
  await s.screenshot({path:testInfo.outputPath('patient-mobile.png'),fullPage:true,mask:[s.getByLabel('Private status token')]});
  await c.getByRole('button',{name:'Patient journeys',exact:true}).click();
  await c.getByRole('combobox',{name:'Visit',exact:true}).selectOption(option!);
  await expect(c.locator('.timeline li')).toHaveCount(4);
  await expect(c.locator('.timeline')).toContainText('COMPLETED');
  await c.screenshot({path:testInfo.outputPath('completed-journey.png'),fullPage:true});
  await clinical.setOffline(true);
  await expect(c.getByText('Offline — read-only',{exact:false})).toBeVisible();
  await expect(c.locator('fieldset.workspace-actions')).toHaveAttribute('disabled','');
  await expect(c.getByRole('button',{name:'Audited timestamp correction'}).first()).toBeDisabled();
  await clinical.setOffline(false);
  await expect(c.locator('fieldset.workspace-actions')).not.toHaveAttribute('disabled','',{timeout:15000});
  await expect(c.getByRole('button',{name:'Audited timestamp correction'}).first()).toBeEnabled();
  await Promise.all([reception.close(),clinical.close(),pharmacy.close(),patient.close()]);
});

test('invalid login and guessed token fail visibly',async({page})=>{
  await login(page,'admin@demo.hutano.test','WrongPassword123!',401);
  await expect(page.locator('.error[role="alert"]')).toContainText('Invalid email or password');
  await page.goto('/status');
  await page.getByLabel('Private status token').fill('A-001.guessed-private-secret-1234');
  await page.getByRole('button',{name:'Check status',exact:true}).click();
  await expect(page.locator('.error[role="alert"]')).toContainText('not found');
});

test('researcher runs paired simulation without seeing patient identifiers',async({page},testInfo)=>{
  await login(page,'research@demo.hutano.test','DemoResearch1!');
  // The one-step role switcher exists only inside the fictional clinic.
  await expect(page.getByLabel('Switch demo role')).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Patient journeys',exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'Simulation lab',exact:true}).click();
  await page.getByLabel('Patients',{exact:true}).fill('30');
  await page.getByRole('button',{name:'Compare FCFS, urgency-first & hybrid'}).click();
  await expect(page.getByText('SYNTHETIC SIMULATION — NOT CLINICAL EVIDENCE',{exact:true})).toBeVisible({timeout:90000});
  await expect(page.locator('.policy-results > div')).toHaveCount(3);
  await page.screenshot({path:testInfo.outputPath('simulation.png'),fullPage:true});
});

test('research training job produces an inactive model with inspectable evaluation',async({page},testInfo)=>{
  await login(page,'research@demo.hutano.test','DemoResearch1!');
  await page.getByRole('button',{name:'AI research',exact:true}).click();
  await expect(page.getByRole('button',{name:'Train selected dataset'})).toBeEnabled();
  await page.getByRole('button',{name:'Train selected dataset'}).click();
  await expect(page.getByRole('button',{name:'Train selected dataset'})).toBeEnabled({timeout:90000});
  await expect(page.locator('.model-card').first()).toContainText('EXPERIMENTAL');
  await expect(page.locator('.model-card').first()).toContainText('Disabled');
  await page.getByRole('button',{name:'Metrics & confusion matrix'}).first().click();
  await expect(page.getByText('Rows: reference; columns: model prediction')).toBeVisible();
  await expect(page.getByText('EXPERIMENTAL — NOT VALIDATED FOR PATIENT CARE',{exact:true})).toBeVisible();
  await page.screenshot({path:testInfo.outputPath('model-evaluation.png'),fullPage:true});
});
