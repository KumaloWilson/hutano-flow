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
Preparation creates 300 fictional people, 24 completed journeys per weekday
over the preceding 21 calendar days (normally 360 journeys), and up to 17 current
cases. Seeded SimPy stages generate coherent historical queue/service timestamps;
repeat encounters, consultation returns, notes and handovers make records useful.
Five staffed rooms include two occupied consultations and a future staff break.

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

## A connected 15–20 minute walkthrough

1. **Clinician → Overview:** show today's arrivals, waiting, completed and alerts.
   Totals cover the whole authorised facility, independent of the capped worklist.
   Open **Demo guide** and a patient's record; compare current and earlier encounters.
2. **Service console:** resume Kudzai Maposa's paused consultation. Complete it with
   a non-diagnostic note and finish the visit. Show the released room in **Staff &
   rooms**. Complete the other occupied consultation when another room is needed.
3. **Reception → Registration:** find an existing patient or enter a clearly
   fictional name, choose walk-in/follow-up/referral and the planned pharmacy step.
   Register, print the receipt and copy its private token. A person with an active
   visit cannot be registered twice. The token is shown once and kept out of URLs.
4. **Triage:** select that visit, enter optional synthetic observations, choose a
   neutral P1–P5 category and confirm the human assessment. Changing patients clears
   the previous draft. AI unavailability does not block manual assessment.
5. **Live queues:** filter by service, token/name or long-wait warning. Explain the
   original ranks and their factors; filtering never changes clinical priority.
   Use an authorised, reasoned override when demonstrating a different queue head.
6. **Staff & rooms:** review alternatives for the queue head and approve an available
   staffed room. Start service, append a note or handover, then complete and route
   to laboratory/pharmacy. For a lab return, complete laboratory to consultation;
   a new consultation episode preserves the earlier one. Acknowledging a handover
   and transferring a patient are distinct actions.
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
