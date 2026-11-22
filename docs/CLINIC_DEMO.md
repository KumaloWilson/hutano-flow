# Hutano Community Clinic demonstration

This is an isolated, entirely fictional clinic. The original research workspace
and its evidence are preserved. These fixtures illustrate software behaviour;
they are not observed facility data, actual clinician assessments or fieldwork.

## Prepare and open

```bash
docker compose up -d --build
docker compose exec api python -m app.cli showcase
```

Open http://localhost:3000. Choose **Hutano Community Clinic** and a role.
Preparation creates 300 fictional people (about 60% women, a quarter children,
a fifth older adults), 24 completed journeys per weekday over the preceding 21
calendar days (normally 360 journeys), and up to 17 people in the clinic now.
Seeded SimPy stages generate coherent historical queue/service timestamps. Every
earlier visit has a plain-language reason for attending, triage vitals, a
consultation note and, where relevant, laboratory/pharmacy handovers. Five staffed
rooms include two occupied consultations and a future staff break.

Notes describe why someone came and what happened next. They never contain a
diagnosis, prescription or order ([ADR-037](DECISIONS.md)).

Preparation also submits real advisory training, operational duration training
and a ten-replication queue comparison to the durable worker. Check **Demo guide →
Computed research preparation** or **AI research → jobs** for actual outcomes.
The advisory model remains experimental and inactive. Its separate training
dataset is not presented as labels from the operational clinic history.

Running the same command again returns the existing rehearsal without duplicating
records. Before a new demonstration day, use:

```bash
docker compose exec api python -m app.cli showcase --fresh
```

This explicitly cancels unfinished scripted cases and releases their reservations,
preserves their history, adds missing historical days, and creates a new current
rehearsal. It preserves independently registered encounters and room reservations;
conflicting scripted patients/occupied rooms are skipped. It never resets the
original facility. Do not run it during an interactive demonstration. Queue ages
continue advancing; the guide flags preparations older than eight hours.

## Roles

All addresses below end in `@showcase.hutano.test`. These are public demo passwords.

| Account | Fictional staff member | Password | Demonstration |
|---|---|---|---|
| `reception` | Rudo Moyo | `DemoReception1!` | Find/register, receipt, follow-up |
| `triage` | Nurse Chipo Ndlovu | `DemoTriage1!` | Observations and human-confirmed urgency |
| `clinician` | Dr Nyasha Mupfumi | `DemoClinician1!` | Records, triage, rooms, service and handover |
| `provider` | Dr Farai Banda | `DemoProvider1!` | Second clinical workspace |
| `pharmacy` | Tendai Sibanda | `DemoPharmacy1!` | Pharmacy queue and completion |
| `laboratory` | Ruvimbo Chirwa | `DemoLaboratory1!` | Laboratory service-provider role |
| `research` | Kudzai Ncube | `DemoResearch1!` | De-identified reports, models and experiments |
| `admin` | Tariro Dube | `DemoAdmin1!` | Facility configuration and audit |

The laboratory account uses the existing SERVICE_PROVIDER permissions, which
cover consultation, laboratory and discharge; it is not a lab-only security role.
Use separate browser profiles/private windows for different staff sessions.

## Who is in the clinic this morning

Token numbers follow arrival order, as at a real front desk; tokens differ
per preparation. Arrivals are placed in the two to three hours before preparation,
so prepare shortly before the demonstration during clinic hours; prepared at night,
the morning appears at night. **Demo guide** lists the same people with their current state.

| Person | Where now | Why they came | What they show |
|---|---|---|---|
| Tawanda Gumbo, 34 | Registration | Twisted ankle at work | Completing a registration |
| Shamiso Marufu, 3 | Waiting for triage | Fever, feeding poorly | Recording vitals and a human-confirmed category |
| Lovemore Chinembiri, 67 | Waiting for triage | Regular check-up; dizzy this morning | Earlier visits in his record |
| Nokuthula Tshuma, 28 | Waiting for triage | Referral letter; abdominal pain | Referral visit type |
| Tinotenda Mlambo, 6 | Consultation queue · P2 | High fever, breathing fast | Top of the queue by confirmed urgency |
| Rutendo Chari, 41 | Consultation queue · P3 | Cut on her hand checked again | Earlier visit for the cut in her record |
| Brighton Nhamo, 52 | Consultation queue · P4 | Cough for three weeks | Long-wait warning and review prompt (over an hour) |
| Memory Hove, 23 | Consultation queue · P3 | Burning when passing urine | Calling and starting the next patient |
| Godknows Mutasa, 71 | Consultation queue · P5 | Routine repeat visit | Categories ordered before waiting time |
| Fadzai Kativhu, 36 | In Consultation room 1 | Headache, body aches | Completing and routing to pharmacy |
| Takudzwa Madziva, 19 | Paused in Consultation room 2 | Itchy rash | Fetching his clinic card; resume and finish |
| Charity Makoni, 30 | Laboratory | Tired and dizzy | Blood test, then return to consultation |
| Sibongile Mpofu, 63 | Pharmacy | Knee pain | Pharmacy handover ("explain in Shona") |
| Panashe Gwenzi, 9 | Pharmacy | Ear pain | Child collected by his mother |
| Givemore Chigumba, 45 | Escalated at triage · P1 | Chest pain for an hour | Escalation alert on the overview |
| Patience Mazarura, 48 | Finished | Back pain | A completed journey with every timestamp |
| Prosper Mushonga, 64 | Finished | Swollen feet, review | A completed visit without pharmacy |

## A connected 15–20 minute walkthrough

1. **Clinician → Overview:** show today's arrivals, waiting, completed and the
   escalation alert for Givemore Chigumba. Totals cover the whole authorised
   facility, independent of the capped worklist. Open **Demo guide**, then
   **Open record** for Rutendo Chari: her earlier visit for the cut explains today's.
2. **Service console:** resume Takudzwa Madziva's paused consultation (he is back
   with his clinic card). Complete it with a note, choosing no next service to finish
   the visit. Show Consultation room 2 released in **Staff & rooms**. Complete Fadzai
   Kativhu in room 1 and route her to pharmacy.
3. **Live queues:** Tinotenda Mlambo (P2) heads consultation. Brighton Nhamo shows
   the long-wait warning and **Review suggested**: he has been overtaken by more
   urgent patients. Explain the ranks and their factors. Filtering never changes
   clinical priority. Use an authorised, reasoned override to show a different head.
4. **Reception → Registration:** finish Tawanda Gumbo's registration, or register a
   new fictional person as walk-in/follow-up/referral with the planned pharmacy step.
   Print the receipt and copy its private token. A person with an active visit cannot
   be registered twice. The token is shown once and kept out of URLs.
5. **Triage:** select Shamiso Marufu, record her vitals, read the optional advisory
   (it may suggest or abstain), then choose and confirm a P1–P5 category yourself.
   Changing patients clears the previous draft. AI unavailability does not block
   manual assessment.
6. **Staff & rooms → Laboratory → Pharmacy:** approve a staffed room for the queue
   head and start service. Log in as `laboratory`: complete Charity Makoni's blood
   test back to consultation; a new consultation episode preserves the first.
   Log in as `pharmacy`: acknowledge Sibongile Mpofu's handover, then call, start and
   complete her to close the visit. Acknowledging a handover and transferring a
   patient are distinct actions.
7. **Patient status:** open `/status` in a separate window and paste the receipt
   token. Show stage/status updates without patient name, priority or other people.
8. **Research → Analytics:** choose the last 7/21 days or exact dates. Historical
   metrics use visits arriving in that local-date cohort; waiting-now counts remain
   live. Export the same filtered cohort. Scripted preparation timings are labelled
   synthetic measurements, not baseline fieldwork.
9. **Simulation lab:** open the saved morning comparison, then choose surge or
   consultation-outage parameters and run another paired comparison. Review the
   actual mean/P90 results, confidence intervals and losses. Changes require a new
   run; an already displayed report always belongs to its saved configuration.
10. **Experiments / AI research / Research workbench:** run the 50-arrival staffing
    experiment, inspect calibrated model evidence and abstention, then create a
    frozen supporting protocol if desired. Follow [the research walkthrough](RESEARCH_DEPTH_DEMO.md)
    for independent case review, consent mechanics, shadow tasks and planning.
    No recruited participants, consent or clinician model review are prefilled.
11. **Admin → Audit:** inspect the recorded commands. Log into the original workspace
    to show that its research records are still present.

## Other devices on a trusted local network

Set `DEMO_HOST` to this computer's private LAN address, not the other device's:

```bash
export DEMO_HOST=192.168.1.50  # replace with this computer's actual LAN address
docker compose -f docker-compose.yml -f docker-compose.lan.yml up -d --build
```

Open `http://YOUR_LAN_ADDRESS:3000` on the second device. The web server proxies API,
exports and live events; browsers never need to reach port 8000. Only port 3000 is
additionally bound to the specified interface. Database/API ports stay loopback.
Origin validation accepts localhost and that exact LAN origin. No cloud publishing
or router port forwarding is needed. Local firewall/network isolation may still
prevent another physical device from connecting.

This optional HTTP profile is solely for fictional data on a trusted demo network
(documented in ADR-029). Browser PWA installation/service workers and automatic
clipboard access may be unavailable on HTTP LAN origins; normal pages, live API
workflows, manual token copying and printing still work. Do not use real data.
Return to loopback-only with `docker compose up -d`; changing the LAN IP requires
restarting the profile with the updated `DEMO_HOST`.
