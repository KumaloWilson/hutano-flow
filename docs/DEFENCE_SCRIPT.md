# Hutano Flow — defence demonstration script

**Smart Healthcare Queue Optimisation and Patient Management System Using AI-Assisted Prioritisation**
Michelle Sambawamedza · R231851H · BBMIT · Catholic University of Zimbabwe · Supervisor: Mr Tandavara

This is the script for demonstrating the system to the panel and defending it. It tells you
what to say, what to click, what the panel should notice, and **why** each step matters to the
proposal. Questions you are likely to be asked, with model answers, are in Part 5.

How to read it:

- **Say:** words to speak, in your own voice. Learn the ideas, not the sentences.
- **Do:** what to click. Labels in **bold** are the exact on-screen names.
- **Point out:** what the panel should see.
- **Why:** the objective, research question or literature gap this step answers.

Timing: about 30 minutes of demonstration, then questions. Times are given per part. If you are
given only 15 minutes, do the steps marked ★ and skip the rest.

---

## Part 0 — The one idea to defend

The panel will remember one sentence. Make it this one:

> **"Prioritising a queue does not make the average patient wait less. It changes *who* waits.
> So I built a system that keeps clinicians in charge of urgency and measures the cost to the
> patient at the bottom of the queue. I did not hide that cost behind an average."**

Everything in the demonstration supports this sentence. It is also what the literature gap in
your proposal (§2.3, gap four) asks for: attention to *"the individual patient who ends up at the
bottom of a priority queue … rather than treating an improved average waiting time as
sufficient evidence."*

Three honesty rules. Breaking any of them is the fastest way to lose a distinction:

1. **Everything is synthetic.** No real patients, no fieldwork yet, no recruited clinicians.
   Say so before the panel asks.
2. **The AI is advisory and experimental.** It never sets a category. It is not clinically
   validated, and the system says so on every screen where it appears.
3. **Report results as they are.** The headline queue result is "no change in the average,
   and a large change in fairness". It is not "the system cut waiting time by X%".

---

## Part 1 — Before the defence

### The day before

1. Start the system: `make demo` (Linux/macOS) or `scripts\demo_up.cmd` (Windows).
2. Rehearse the whole script once, with a timer.
3. Write down the numbers *your* screen shows in the blank boxes in Part 4. Some depend on the
   preparation date.
4. Copy the backup material to the laptop desktop: `docs/evidence/*.png` (screenshots of every
   screen) and `docs/TEST_EVIDENCE.md`.

### On the day, 30–60 minutes before

1. Prepare the clinic **during clinic hours** (weekdays 07:00–16:00), so the morning looks like a
   morning. Sign in as **Admin** → **Demo guide** → **Prepare a fresh rehearsal**.
   - Leave **"Enable the advisory with a scripted review"** **unticked**. You will show the
     clinician review step live; it is one of your strongest points.
2. Wait until **Overview** shows **"Research results ready"** (a few minutes).
3. Pre-run the long comparison so you don't wait on stage: **Simulation lab** → **Manual
   parameters**: Scenario name `Morning comparison with research policies`, **Patients** `150`,
   **Seed** `2026`, **Consultation servers** `2`, **Arrivals per hour** `12`,
   **Mean consultation minutes** `12`, **Paired replications** `10`, tick **Include
   research-only arms**. Run it.
4. Also pre-run the calibrated comparison: **Simulation lab** → **Calibrated from baseline**,
   Scenario name `Calibrated baseline check`, **Simulated clinic days** `10`, run.
5. Record the advisory review (Step 7 explains why): use the **Demo role** menu to switch to
   **Clinician** → **Help & safety** → **Record clinician research review**, with reason
   "Reviewed for synthetic demonstration only". Do **not** activate it yet.
6. Open three browser windows:
   - **Window A (presenter):** signed in, on **Overview**.
   - **Window B ("the patient's phone"):** `http://localhost:3000/status`, narrowed to phone width.
   - **Window C (optional, second staff screen):** signed in as **Clinician**, on **Live queues**,
     to show live updates.
7. Turn off notifications. Zoom the browser to 110–125% so the panel can read it.

### If something fails live

| Problem | Recovery line and action |
|---|---|
| A page is slow or blank | "The system is waiting for the database. This is the live view." Press **Refresh**, or move to the next step. |
| A research job is still running | "This is a real background job, not a pre-recorded result." Show the saved run, or the screenshot in `docs/evidence/`. |
| Sign-in is refused | Wait 10 seconds (rate limiting is a deliberate security control) and retry. Say so: it is a feature. |
| Anything else | Open the matching screenshot in `docs/evidence/` and keep talking. Never debug in front of the panel. |

---

## Part 2 — Opening (3 minutes) ★

**Do:** Show the login page. Don't sign in yet.

**Say:**

> "In 2023, Link and colleagues followed 863 patient visits through three City of Harare
> polyclinics. On average, a patient waited **2 hours and 14 minutes** before seeing a provider.
> The biggest single block, **1 hour 14 minutes**, came before registration. The consultation
> lasted about **three minutes**. And **94%** of patients arrived in the morning.
>
> So the problem is not slow doctors. It is how patients flow through the clinic, and the fact
> that nobody, patient or staff, can see that flow.
>
> First-come-first-served is simple and feels fair, but it ignores urgency. It treats every
> consultation as the same length. It cannot react when a room closes. And patients cannot see
> where they stand.
>
> My aim was to **design, develop and evaluate** a queue and patient-management system that
> improves flow through **clinician-supervised, AI-assisted prioritisation**. I followed Peffers'
> Design Science Research Methodology: identify the problem, define objectives, build the
> artefact, demonstrate it, evaluate it, communicate it. Today is the demonstration and evaluation."

**Do:** Point to the four objectives on a slide or card, or just say them:

> "Four objectives:
> **O1** — measure the current process and its bottlenecks;
> **O2** — an *explainable* AI model for recommending priority from routinely collected data;
> **O3** — a system for dynamic prioritisation, patient-flow tracking and real-time visibility;
> **O4** — evaluate it against the existing process on waiting time, model performance,
> usability and clinician acceptance.
>
> I'll show each one working, then the evaluation evidence for each. I'll end with what the
> evidence does **not** show."

**Say (the safety frame):**

> "Two boundaries before I sign in. First, every person you will see is **fictional**. Ethics
> approval for fieldwork is a separate step, so I designed the system to be demonstrated and
> evaluated without real patient data. Second, the AI **never decides**. A clinician confirms
> every priority. The model can only suggest, explain, or decline to suggest."

**Why:** You set the rules of the conversation before the panel can question them.

---

## Part 3 — The walkthrough

The demonstration follows one morning at the fictional **Hutano Community Clinic**: front desk →
triage → queue → consultation → laboratory → pharmacy → home. Then you step back and evaluate it.

### Step 1 — Sign in and orientate (1 minute) ★

**Do:** Choose **Hutano Community Clinic (fictional)**, click the **Admin** pill, sign in.

**Point out:**
- The black banner on every page: *"Research prototype · Not for clinical use · Synthetic data ·
  Clinicians remain the decision-makers."*
- The role buttons: eight staff roles, each seeing only what its job needs. This is role-based
  access control, enforced on the server, not just hidden in the interface.
- The **Demo role** menu at the top: "So I can play every staff member without signing out."

**Why:** Proposal §1.10 requires role-based access control and audit logging. You show it in the
first ten seconds.

### Step 2 — The clinic at a glance (2 minutes) ★ — O3 real-time visibility

**Do:** **Overview**.

**Say:**

> "This is the morning at a glance: 17 people in the clinic, how many are waiting at each stage,
> the oldest wait at each, and what needs attention."

**Point out:**
- **Flow through the clinic:** Registration → Triage → Consultation → Laboratory → Pharmacy,
  with the waiting count and oldest wait at each.
- **Needs attention:** *"1 long wait at Consultation — Oldest has waited 72 minutes"* and *"1
  escalation alert"*.
- **Journeys in progress:** each person with a ticket number and current stage.

**Say:**

> "This answers the first complaint in the literature: nobody can see the flow. The counts come
> straight from the database and update live. There is no refresh button to press."

**Why:** O3 / RQ3: patient-flow tracking and real-time queue visibility.

### Step 3 — Registration: a walk-in arrives (2 minutes) ★ — O3, walk-in gap

**Do:** **Demo role** → **Reception**. Open **Registration** → **Register an arrival**. Enter a
new fictional person, for example **Pseudonym** `Rejoice Mukanya`, **Age band** Adult,
**Recorded sex** Female, **Visit type** Walk-in. Keep **Plan pharmacy after consultation**
ticked. Click **Create visit and complete registration**, then **Print receipt** and **Copy
private token**.

Then show the desk queue: **Live queues** → Registration. **Tawanda Gumbo** (twisted ankle) is
waiting there. **Call** → **Start service** → **Complete & route** → Triage. "Each of those
clicks is a timestamp. That's how the system measures the registration delay Link et al.
found to be the biggest."

**Say:**

> "Most queue-optimisation studies assume appointments. Public clinics in Zimbabwe are mostly
> walk-in; that is the first gap in my literature review. So the system starts where a walk-in
> starts: at the desk, with nothing booked.
>
> The receipt has a short ticket number for calling, and a **private token** for the patient's
> phone. The token is shown once and never put in a web address, so it can't leak through
> browser history. It is also long enough that it can't be guessed."

**Point out:** The system refuses to register someone twice while they already have an open
visit.

**Why:** Proposal gap 1 (walk-in settings); O3.

### Step 4 — The patient's view (2 minutes) ★ — transparency

**Do:** Switch to **Window B** (`/status`). Paste Rejoice's token. Show the language switch (English,
**Shona**, **Ndebele**).

**Say:**

> "Bidari Jafarnejad and Alaei Faradonbeh found that when patients can see the queue, the wait
> they *perceive* falls below the actual wait. Without it, perception runs ahead of reality.
> So the patient gets this: their stage, roughly how many people are ahead, and an estimated
> range, in their language.
>
> Notice what it does **not** show: no name, no priority category, nobody else's details. If
> someone guesses a token, it fails without revealing anything."

**Do (optional):** Type a made-up token and show it fail.

**Why:** Proposal §1.0 and §1.5 (transparent queue information); data protection.

### Step 5 — Triage and the AI advisory (5 minutes) ★ — O2, the centre of the AI story

**Do:** **Demo role** → **Clinician** (the advisory review needs a clinician; you recorded it
before the defence). Then **Demo role** → **Admin** → **AI research** → on the model card, click
**Activate reviewed advisory**.

**Say:**

> "Before the model can say anything, two people must act. A clinician records a research review,
> which I did before we started. Then an administrator switches it on. A model nobody has
> reviewed cannot reach the triage screen. That's governance designed into the software, not
> written in a policy document."

**Do:** **Demo role** → **Triage**. Open **Triage**, choose **Shamiso Marufu** (3 years old,
fever, poor feeding). Enter vitals: temperature `38.4`, pulse `132`, respiratory rate `36`,
oxygen saturation `96`; leave blood pressure blank. Click **Request advisory explanation**.

**Two possible outcomes. Both are good; have the line ready for each.**

*If it gives a suggestion:*

> "It suggests a category, gives a calibrated confidence, and shows **which inputs pushed it
> there**. That follows Miller's explanation theory: *contrastive*, why this category rather than
> the next one, and *selective*, the few factors that mattered most. It also lists every input
> it used and where each came from. The blank blood pressure shows as **'not recorded'**; it is
> never assumed normal."

*If it declines ("No suggestion — clinician assessment only"):*

> "This is the behaviour I'm most proud of. A respiratory rate of 36 is normal for a feverish
> toddler, but it is outside what this model was trained on. So the model **declines to
> answer** instead of guessing. On held-out data it abstains on about **55%** of cases. When it
> does answer, its error rate drops from **44% to 34%**. A model that knows when it doesn't know
> is safer than one that always answers."

**Do:** Whatever it said, choose the category yourself (for example **P2**), write a short
rationale ("Fever and fast breathing; seen ahead of routine patients"), and click **Confirm
assessment**.

**Say:**

> "The decision is mine. Accepting a suggestion only pre-fills the box. I still have to confirm,
> and my decision, the model's suggestion and whether I accepted it are all recorded."

**Why:** O2 / RQ2 (explainable, routinely collected data); explainable-AI theory (Miller 2019);
proposal §1.5 (*"The AI component ranks and explains; it does not decide."*); gap 2
(explainability built, not just discussed).

### Step 6 — The live queue and the patient at the bottom (4 minutes) ★ — O3 and gap 4

**Do:** **Live queues** → Consultation.

**Point out the order:** Tinotenda Mlambo (**P2**) first; then two **P3**s, the longer wait
first; then **Brighton Nhamo (P4)**; then **Godknows Mutasa (P5)**.

**Say:**

> "The order is the clinician's urgency first, then time waited within each category. The
> system never changes a category. Each row says *why* it is where it is."

**Do:** Point at Brighton Nhamo: the long-wait warning and **Review suggested**.

**Say:**

> "Brighton is the patient my fourth research gap is about. He has waited over an hour and seen
> **seven** later arrivals called before him. A queue that only reports the average would never
> notice him. This one flags him and asks a clinician to look again. It doesn't move him
> automatically, because a computer changing someone's priority on a timer is a clinical
> decision. It **prompts a human**."

**Do:** **Review** on Brighton → record a short review. Then **Override** on a patient, give a
reason (for example "Clinician moved forward after reassessment"), and confirm.

**Say:**

> "Overriding is one action with a required reason, and every override is logged, which my
> proposal promised."

**Do (if Window C is open):** Show that Window C updated on its own.

**Why:** O3 (dynamic prioritisation); gap 4 (the patient at the bottom of the queue); proposal
§1.5 (*"Every override is one action and every override is logged."*).

### Step 7 — Consultation, laboratory and pharmacy (4 minutes) — O3 patient-flow tracking

**Do:**
1. **Demo role** → **Clinician** → **Service console**. Find **Takudzwa Madziva**, whose
   consultation is *paused*: "he went home to fetch his clinic card". Click **Resume service**,
   then **Complete & route**, choose no next service, add a note, confirm. The visit closes.
2. Find **Fadzai Kativhu**, in Consultation room 1. **Complete & route** → **Pharmacy**.
3. **Demo role** → **Laboratory** → **Live queues** → Laboratory. For **Charity Makoni** (blood
   test): **Call** → **Start service** → **Complete & route** → **Consultation**.
4. **Demo role** → **Pharmacy**. Open **Sibongile Mpofu**'s handover ("explain the medicines in
   Shona; she prefers it"), acknowledge it, then **Call**, **Start service**, **Complete &
   route**. The visit closes.

**Say:**

> "Every move is timestamped: queued, called, started, ended. Each stage is its own record, so
> Charity's return to the doctor is a **new** consultation and the first one is never
> overwritten. These timestamps are exactly what a time-and-motion study measures by hand. Here
> they are a by-product of doing the work."

**Do:** **Patient journeys** → open Sibongile's visit and show the timeline with every
timestamp. Switch to **Window B**: Rejoice's page has moved on by itself from registration to "waiting for triage". Nobody at the desk had to answer a question.

**Why:** O3 (patient-flow tracking); proposal §1.7 measures (waiting and service time per point)
collected automatically; this is the data O1 and O4 need.

### Step 8 — When things go wrong (2 minutes) — gap 3, constrained settings

**Do:** **Demo role** → **Admin** → **Facility admin** → Consultation → **Change availability**
→ capacity `0`, reason "Room flooded", confirm. Show **Overview**: the consultation outage is
flagged, and the waiting list is unchanged.

**Say:**

> "Static queues can't react when a room closes. Here, capacity zero pauses new calls, but
> **nobody is removed from the queue** and nobody loses their place."

**Do:** Restore the capacity to `2`.

**Say (no clicks needed, or show briefly):**

> "Many published systems assume reliable networks and RFID. My third gap was designs for
> intermittent connectivity. If the connection drops, staff screens say so and **pause actions**
> instead of showing stale data as if it were live. The **Downtime kit** prints a paper sheet for
> the outage, and the visits are back-entered afterwards with their real times. The whole system
> runs on one ordinary laptop with no internet."

**Why:** Gap 3 (connectivity and hardware); proposal problem statement (*"cannot respond … when
a service point goes down"*).

### Step 9 — O1: measuring the current process (3 minutes) ★

**Do:** **Demo role** → **Research**. Open **AI research** → **Anonymous baseline timing
import**, and expand the stored baseline (*"Fictional clinic · synthetic time-and-motion
baseline"*).

**Say:**

> "Objective 1 is measuring the existing first-come-first-served process. The real study will
> collect at least 300 journeys over three weeks. Before going into a clinic, I needed the
> analysis to exist and be tested. So the system imports time-and-motion data in an anonymous
> format and reports every measure in proposal §1.7."

**Point out (read your own values from the screen; seed-2026 values are in Part 4):**
- Waiting and service time **per service point**, mean and 90th percentile.
- **Bottleneck:** registration, the same shape as Link et al., where the biggest delay comes
  before registration.
- **Morning arrival share:** about 89%, comparable to Link et al.'s 94%.
- **Share of visit time spent waiting.**
- **Little's Law check**, wait × arrival rate against measured queue length. "It's a sense-check
  on the data, as Chapter 2 says. Where the queue is too short to test, it says 'not
  assessable' instead of pretending."

**Then:** **Analytics** → **Last 7 days**: the same measures from the clinic's own recorded
timestamps, with **Export CSV**.

**Why:** O1 / RQ1; queueing theory (Little 1961); proposal §1.7 measures.

### Step 10 — O4: does it reduce waiting time? The honest answer (6 minutes) ★ — the climax

**Do:** **Simulation lab** → **Saved comparisons** → choose **"Calibrated baseline check"**.

**Say:**

> "My proposal says the simulator must first **reproduce the measured baseline** before any
> result is trusted. Here it does: every stage's average and 90th-percentile wait is within
> tolerance."

**Point out:** *"Simulated FCFS reproduces the measured baseline"* and the table of observed
against simulated values.

> "And in this light clinic, about 38 patients a day, changing the order of the consultation
> queue makes **no difference at all**. The queue at consultation is too short for ordering to
> matter. The delay is at registration. **Reordering cannot fix a registration bottleneck.**
> That is a design finding, not a failure."

**Do:** Now open **"Fictional clinic · morning queue comparison"**: a busy morning, 150
patients, two doctors, ten paired days.

**Say:**

> "Under pressure: the same simulated patients go through each policy, with identical arrivals,
> so the comparison is fair. These are paired, common-random-number replications."

**Point out the numbers (they will match Part 4):**
- Mean journey wait: FCFS **89.4** min; urgency-first and hybrid **88.8** min.
  Difference **−0.6 min**, 95% CI **−2.1 to +0.8**, p = 0.35. **No real change.**
- P1 (most urgent) mean consultation wait: **47 min → 4 min**.
- P5 (least urgent), 95th-percentile wait: **137 min → 461 min**.

**Say (slowly, this is the key moment):**

> "This is the most important result in my project. Prioritising **did not reduce the average
> wait**. Queueing theory predicts this: Kleinrock's conservation law says that with the same
> doctors and the same work, reordering moves waiting between people. It doesn't remove it.
>
> What prioritising did was move the most urgent patients from **47 minutes to 4**, and push
> the slowest least-urgent patients from **2¼ hours to almost 8**. If I had reported only the
> average, you would see 'no effect'. If I had reported only P1, you would see 'a miracle'.
> **Both would be misleading.** This is why my fourth gap matters."

**Do:** Open your pre-run **"Morning comparison with research policies"** and scroll to **"The
patient at the bottom of the queue"**.

**Say:**

> "So I tested two alternatives, **only in the simulator**, because changing the live order on a
> timer is a clinical-governance decision, not mine.
> **Bounded ageing** promotes a patient one category for each period waited, up to a limit.
> P1 patients still wait about **5 minutes**. The worst P5 wait **halves**, from 461 to **236
> minutes**. The overall 90th percentile returns to first-come-first-served levels. The mean
> even improves slightly: **−1.2 min**, 95% CI −2.1 to −0.3.
> **Duration-aware** ordering, shortest predicted consultation first within a category, gives
> the best mean (**−2.2 min**), but it does nothing for the patient at the bottom.
>
> My recommendation from this evidence is that if a facility ever adopted dynamic ordering,
> bounded ageing is the defensible trade-off, *subject to clinical governance*. The live system
> stays clinician-confirmed until then."

**Why:** O4 / RQ4 (waiting time compared with the existing process); queueing theory (priority
trade-off, Chapter 2.1.1); proposal §1.5 (*"examine under-triage … rather than assuming that an
improvement in average waiting time is sufficient"*); gap 4.

**Optional, if asked "so what *does* reduce waiting?":** Open **Experiments**. The recorded
50-arrival / 3-room experiment shows that **pooling rooms**, sending the next patient to the next
free room, cut mean completed-journey wait by about **18 minutes** (95% CI −26.4 to −9.0) against
fixed room assignment. "Waiting falls when you change **capacity and flow**, not only order. That
is consistent with the Tanzanian study, where scheduling and process changes cut median waits by
45%."

### Step 11 — O4: how good is the model? (4 minutes) ★

**Do:** **Evaluation** → **O2**, or **AI research** → the model card.

**Say:**

> "Objective 2's evaluation. The labels here are **synthetic**, and the screen says so. These
> numbers show the method works. They do not show clinical accuracy."

**Point out (seed 2026; matches Part 4):**
- **Macro-F1 0.56**, against **0.07** for always predicting the most common category and **0.43**
  for a random forest. "I report macro-F1 because a model that ignores rare urgent patients can
  still score high accuracy. Macro-F1 weights every category equally."
- **P1 precision 0.84, recall 0.65.** "When it says P1 it's usually right, but it misses a third
  of P1 cases. That's exactly why it can't be allowed to decide."
- **Under-triage: 42 of 200 held-out cases (21%)** are placed less urgent than their label. "My
  proposal promised to report under-triage explicitly, so here it is. Under-triage is the
  dangerous error."
- **Coverage ≈ 45% at the chosen threshold**, with the error rate falling from 44% to 34% on the
  cases it does answer.
- **Calibration:** confidence is temperature-scaled, so "70% confident" should mean right about
  70% of the time. The reliability bins are shown.

**Say:**

> "The data was split by time, not at random: the model trains on earlier visits and is tested
> on later ones, as it would be used. Model choice, calibration, the abstention threshold and the
> final test each used separate data, so the test numbers were never used to tune anything."

**Why:** O2 and O4 (model performance); proposal §1.5 (under-triage); §1.8 (missing data
handled, not imputed silently).

### Step 12 — O4: usability and acceptance (2 minutes)

**Do:** **Evaluation** → **O4**, and the **Usability session** panel below it.

**Say:**

> "Usability is measured with the **System Usability Scale**, with standard scoring, and
> acceptance with the **Technology Acceptance Model**: perceived usefulness and perceived ease of
> use, as in Chapter 2.1.4. Cronbach's alpha is reported for each scale.
>
> I'll be direct: **no real participants have been recruited yet**. That needs ethics approval.
> What I can show is that the instruments, consent references and analysis are built and tested.
> The day the sessions happen, the results appear here, next to the waiting-time evidence."

**Do (optional):** Show the form: the ten SUS items and eight TAM items.

**Point out:** For each objective, the Evaluation view lists what the proposal requires, which
requirements are met, the evidence held, and **"Outside the software"**: interviews, approvals,
fieldwork.

**Why:** O4 (usability, clinician acceptance); TAM (Davis 1989); SUS (Brooke 1996).

### Step 13 — Accountability: the audit trail (1 minute)

**Do:** **Audit log**. Filter or scroll to your override, the advisory activation and the
outage.

**Say:**

> "Every command you saw today is here: who, when, what changed, and the reason given. The audit
> records can't be edited, even by the database's own application account."

Then, to close the AI story:

**Do:** **AI research** → **Disable advisory**. **Demo role** → **Triage** → show that triage
still works: *"Model unavailable — clinician assessment required."*

> "If the AI is switched off, or fails, the clinic carries on. The AI is an addition to the
> system, not a dependency."

**Why:** Proposal §1.10 (audit logging); spec invariant: the queue works without AI.

### Step 14 — Close (2 minutes) ★

**Say:**

> "To summarise against my objectives:
>
> **O1:** the system measures waiting and service time per stage, bottlenecks, arrival patterns
> and queue length, checks them against Little's Law, and calibrates a simulator that reproduces
> the baseline.
> **O2:** an explainable, calibrated model built on routinely collected data that reports its
> inputs, its reasons, its under-triage and its uncertainty, and declines when unsure.
> **O3:** a working system with real-time visibility for staff and patients, dynamic
> clinician-confirmed prioritisation, full journey tracking, and safe behaviour in outages.
> **O4:** an evaluation that compares policies on identical patients and shows that ordering
> moves waiting rather than removing it. It measures the cost to the patient at the bottom, and
> identifies bounded ageing as a fairer trade-off.
>
> What it does **not** show: real-world effectiveness. That needs the approved fieldwork at a
> facility, recruited clinicians and clinician-reviewed labels. The system is ready for that
> study. It is not ready for patient care, and it says so on every screen.
>
> Thank you. I'm happy to take questions."

---

## Part 4 — Numbers card (keep this in your hand)

All figures are synthetic, generated with seed 2026. Values marked ◻ depend on the preparation
date: copy them from your own screen during rehearsal.

**Context (Link, Tshimanga, Cochrane & Kasprzyk, 2023; Harare polyclinics, 863 visits)**
Arrival → provider 2 h 14 min · arrival → registration 1 h 14 min · registration → provider
49 min · consultation ≈ 3 min · dispensing < 2 min · 94% arrive in the morning.

**O1 — synthetic baseline (15 days, FCFS)**

| Measure | Seed-2026 value | Your screen |
|---|---|---|
| Journeys | 573 | ◻ |
| Bottleneck stage | Registration | ◻ |
| Registration wait, mean / P90 | 8.4 / 25.9 min | ◻ |
| Arrival → provider, mean | 21.4 min | ◻ |
| Total visit, mean | 32.7 min | ◻ |
| Morning arrival share | 89% | ◻ |
| Share of visit time spent waiting | 37% | ◻ |
| Calibrated simulator reproduces baseline | Yes, 10 of 10 checks within max(25%, 5 min) | ◻ |

**O4 — busy morning: 150 patients, 2 doctors, 10 paired replications, seed 2026**

| Policy | Mean wait | P90 | P1 mean wait | P5 95th pct | Most times a P5 was overtaken |
|---|---|---|---|---|---|
| First come, first served | 89.4 | 171.9 | 47.1 | 136.6 | 0 |
| Urgency first / Hybrid (live) | 88.8 | 235.7 | 4.4 | 461.4 | 91 |
| Bounded ageing (research only) | 88.2 | 174.6 | 5.4 | 235.8 | 37 |
| Duration-aware (research only) | 87.2 | 238.3 | 4.8 | 453.1 | 91 |

Paired difference against FCFS (mean journey wait):
- Hybrid **−0.63** min, 95% CI (−2.07, +0.82), t-test p = 0.35, Wilcoxon p = 0.49
- Bounded ageing **−1.22**, CI (−2.13, −0.31), p = 0.014
- Duration-aware **−2.22**, CI (−3.33, −1.11), p = 0.001

p-values are descriptive across 10 replications, with no correction for multiple comparisons.
Even the "significant" differences are about 1–2 minutes on a 90-minute wait.

**Staffing experiment (recorded 26 Oct; 50 arrivals, 3 rooms, 5 replications)**
Fixed room 94.2 · next available 76.7 · capacity-aware 76.5 min.
Capacity-aware − fixed = **−17.7 min**, 95% CI (−26.4, −9.0).
Capacity-aware was only 0.14 min better than next-available, and its P90 was slightly worse.

**O2 — advisory model (logistic regression, clinical features v3, synthetic labels, seed 2026)**

| Metric | Value |
|---|---|
| Held-out test rows (later in time) | 200; trained on 800 earlier |
| Macro-F1 | **0.563** (majority 0.071 · random forest 0.431 · ordinal 0.537) |
| P1 precision / recall | 0.84 / 0.65 |
| Under-triage / over-triage (against synthetic labels) | 42 / 46 of 200 |
| Abstention threshold | 0.55 |
| Coverage at threshold | 45% (95% CI 38–52%) |
| Error when answering | 34% (95% CI 25–45%), against 44% with no abstention |
| Calibration | Temperature scaling improved held-out log loss (1.01) |
| Inputs | Age band, visit type, arrival mode, arrival hour, 6 vital signs |

**Engineering (`docs/TEST_EVIDENCE.md`, 22 Nov 2026)**
150 backend tests including real PostgreSQL concurrency · 22 frontend unit tests · 12
full-browser end-to-end tests · clean boot and backup/restore verified · 38 recorded design
decisions (`docs/DECISIONS.md`).

---

## Part 5 — Questions and model answers

Answer in three moves: **direct answer → evidence → limit**. Never bluff. "I don't know, but
here is how I would find out" is a strong answer.

### A. Problem, scope and contribution

**Q1. What exactly is new here? Queue systems already exist.**
> "Three things, together. First, it's built for **walk-in** clinics, where most of the
> optimisation literature assumes appointments. Second, explainability is **built and
> evaluated**: inputs, reasons, calibrated confidence and abstention, not promised in a
> discussion section. Third, the evaluation measures the **cost to the patient at the bottom of
> the queue** as well as the average. My main finding, that ordering redistributes waiting
> rather than reducing it, comes from that third point. A system that only reported averages
> could not have found it."

**Q2. Why not just use the South African Triage Scale?**
> "SATS is the regional reference, and a facility using it can enter its categories directly.
> The categories are configurable, neutral P1–P5 labels. But I'm not authorised to encode SATS
> decision rules as if the software performs triage. That is a clinical protocol, and the
> proposal says the system doesn't replace emergency triage. The software supports the triage
> decision. It doesn't make it."

**Q3. Isn't this just an electronic queue ticket system?**
> "The ticketing is the visible part. Underneath are clinician-confirmed priority ordering with
> explanations, long-wait review prompts, full journey timestamps for time-and-motion analysis,
> a calibrated discrete-event simulator, an explainable model with abstention, and an evaluation
> framework for the four objectives. A ticket system can't tell you whether reordering helped or
> who paid for it."

**Q4. Who would actually use this, and on what hardware?**
> "Reception, triage nurses, clinicians, laboratory, pharmacy and management, each with their
> own view. It runs on one ordinary laptop with Docker and no internet. Other devices on the
> clinic network can connect through a browser, including phones. That matters for my third
> gap: no RFID and no cloud."

### B. Methodology and data

**Q5. All your data is synthetic. Haven't you shown nothing?**
> "I've shown that the **artefact works and that the evaluation method works**. In Design Science
> Research, that is the build-and-demonstrate stage, and it comes before the field evaluation.
> Ethics approval for patient data is outside my control. The proposal anticipated that, and
> says no patient data before approval. So I built the system to run end to end on synthetic
> data, and every screen labels it. What I don't claim is real-world effectiveness. The day the
> baseline data arrives, it goes through the same import and the same calibrated simulation, and
> nothing needs rebuilding."

**Q6. How do you know the synthetic data is realistic?**
> "I don't claim it represents any real clinic. It is designed to have the *shape* the
> literature reports: morning-heavy arrivals, about 89% against Link's 94%; a bottleneck before
> the doctor; long-tailed consultation times. Its job is to exercise the methods, not to stand
> in for findings. The calibration step exists so that with real data, the simulator must
> reproduce what was measured before any result is believed."

**Q7. Why Design Science Research and not an experiment?**
> "Because the research question is *how can such a system be designed, developed and
> evaluated*. That is a design question, and Peffers' DSRM is built for it. The evaluation
> inside it is quantitative: paired simulation, model metrics, SUS/TAM. The interviews in the
> fieldwork add the qualitative side. That's why the proposal describes it as mixed methods."

**Q8. What about the interviews and the 300 journeys from your methodology?**
> "Those are the fieldwork stage and need approval. They haven't happened, and I don't present
> them as done. The system is the instrument for them: it already accepts anonymous
> time-and-motion data, needs 300 journeys over three weeks, records usability sessions with
> consent references, and produces the analysis."

### C. The AI model

**Q9. Macro-F1 of 0.56. Isn't the model poor?**
> "Against synthetic labels with deliberate noise, it is moderate, and I report it as moderate.
> It beats the baselines clearly: 0.07 for always guessing the most common category, 0.43 for a
> random forest. Two things matter more than the headline. It misses a third of P1 cases, which
> is exactly why it can never decide. And it **abstains** when unsure, which drops its error
> rate from 44% to 34% on the cases it does answer. I would rather defend a moderate, honest
> model than an impressive number on data I generated myself."

**Q10. Why logistic regression and not deep learning?**
> "Three reasons. Explainability: each input's contribution to the decision can be computed
> exactly, not approximated. Small data: a clinic will have hundreds or a few thousand labelled
> visits, not millions. Calibration: its probabilities can be calibrated reliably. I compared it
> with a random forest and an ordinal model. The random forest did worse, and the ordinal model
> was close. A deep model would cost explainability and gain nothing on data this size."

**Q11. How is the explanation produced? Is it SHAP?**
> "No. For logistic regression I don't need an approximation. Each feature's contribution to the
> score is exact. The screen shows the top factors and a contrast between the suggested category
> and the runner-up, which is Miller's *contrastive* and *selective* explanation. It also lists
> every input and its source, so a clinician can see if something was missing. These are
> explanations of the **model**, not medical reasons, and the screen says that."

**Q12. What is under-triage and why does it matter?**
> "Under-triage is placing a patient in a less urgent category than they should be. It's the
> dangerous error, because it delays someone who needed to be seen. Accuracy hides it. So I
> report it separately: 42 of 200 held-out cases against synthetic labels. That number is why
> the clinician confirms every category."

**Q13. Why does the model refuse to answer sometimes? Isn't that a weakness?**
> "It's a safety feature. It declines when three or more vital signs are missing, when an input
> is outside the range it was trained on, or when its confidence is below the threshold. A
> clinician gets *'no suggestion'* instead of a confident guess. The threshold was chosen on
> separate data, with the cost of an error and the cost of abstaining stated as an explicit
> engineering assumption, not a clinical one."

**Q14. How did you handle missing data?**
> "Missing vital signs are **not** filled in with normal values. That would make a sick patient
> look healthy. The model has explicit 'not recorded' indicators, missingness is reported per
> field before training, and the screen shows the clinician what was missing. That follows
> proposal §1.8. Systolic and diastolic count as one measurement, because they come from one cuff
> reading."

**Q15. Could the model be biased?**
> "Any model trained on historical records inherits their biases, and Garba et al. warn about
> exactly this. The system reports performance by slice, such as age band, and hides slices too
> small to judge (under 30 cases). It also keeps the clinician in charge. With real data, the
> slice reports are where bias would show up first. On synthetic data I can't make a fairness
> claim about real people, and I don't."

**Q16. How did you avoid overfitting or data leakage?**
> "The data is split by **time**, with tied timestamps kept together: earlier visits for
> training, later ones for testing. Fitting, model selection, calibration, threshold choice and
> the final test each use separate data. The final test was never used to tune anything."

**Q17. What labels would you use in a real clinic?**
> "Clinician-assigned triage categories where they exist. Where they don't, proxy labels from
> recorded fields, with a sample independently reviewed by a clinician, which is proposal §1.8.
> The Research workbench already supports blinded independent review by two reviewers, with
> consensus. The model evaluation then reports which kind of label it was tested on."

### D. Queue policy and simulation

**Q18. Your hybrid policy didn't reduce waiting time. Didn't you fail Objective 4?**
> "Objective 4 is to **evaluate** against the existing process, not to guarantee an improvement.
> The evaluation found something real: prioritisation reduced the most urgent patients' wait
> from 47 to 4 minutes, didn't change the average, and the least urgent paid for it. Queueing
> theory predicts that, through the conservation law. Reporting it is what proposal §1.5 asks
> for. And the evaluation also found what *does* move the average: pooling rooms and fixing
> capacity, about 18 minutes in the staffing experiment."

**Q19. Why are "hybrid" and "urgency-first" identical in the results?**
> "Good catch. The live hybrid policy ages patients **within** their confirmed category. Within a
> category, ageing gives the same order as first-come-first-served, so in the simulator it equals
> urgency-first. Ageing **across** categories, the research arm called bounded ageing, is a
> different policy. I kept it out of the live queue on purpose, because moving someone up a
> category on a timer is a clinical decision. Live, the hybrid adds the review prompts, reasoned
> overrides and missed-call handling that the simulator doesn't model."

**Q20. How do you know the simulation is valid?**
> "Two checks. First, the calibrated simulator must reproduce the measured baseline, every stage's
> average and 90th-percentile wait, within max(25%, 5 minutes) before any policy result is shown.
> If it doesn't, the screen says *'does not reproduce'*. Second, controls: a scenario where
> every patient has the same urgency shows no difference between policies, as it must. And every
> policy sees identical simulated patients, so differences come from the policy, not luck."

**Q21. Why only 10 replications? Are your p-values meaningful?**
> "Ten paired days. Because each pair uses the same patients, the paired differences are precise.
> The confidence intervals are narrow, about ±1.5 minutes. I treat p-values as descriptive, and
> the screen says no multiple-comparison correction is applied. The interpretation rests on the
> effect sizes and intervals: 1–2 minutes on a 90-minute wait is practically nothing, whatever
> the p-value."

**Q22. What is Little's Law doing in your system?**
> "It's a consistency check on the baseline data, as in Chapter 2.1.1: average queue length
> should equal arrival rate times average wait. If measured queue lengths and measured waits
> disagree, the data collection has a problem. When a queue is too short to test, it says 'not
> assessable' instead of pretending."

**Q23. Why discrete-event simulation instead of queueing formulas?**
> "The closed-form formulas assume simple arrivals and one stage. A clinic has several stages,
> morning surges, long-tailed consultations, outages, laboratory returns and priority classes.
> A discrete-event simulation, SimPy here, handles all of that, and the calibration step ties it
> to measured data."

### E. The system and engineering

**Q24. Walk us through the architecture.**
> "A web interface in Next.js and TypeScript, a FastAPI service in Python, PostgreSQL for
> storage, and a separate worker for the heavy jobs: model training and simulations. Screens
> update live through server-sent events. Everything is packaged with Docker Compose, so one
> command starts it. The AI and simulation are separate modules. The live queue never depends on
> them."

**Q25. What happens if two staff call the same patient at the same moment?**
> "Only one succeeds. Each command carries a version number and an idempotency key, the database
> locks the row, and a duplicate or stale command is rejected with a clear message. This is
> tested against a real PostgreSQL database with simultaneous requests. No duplicate
> allocations."

**Q26. How is patient data protected?**
> "Role-based access enforced on the server: reception can't read clinical notes, and
> researchers see de-identified aggregates only. Passwords are hashed, sessions expire when idle,
> and accounts lock after repeated failures. The patient's status token is a keyed secret, never
> stored in plain text and never in a URL. Audit records are append-only. The application runs as
> a restricted database account, ports are bound to the local machine, and backups are encrypted.
> This follows the Cyber and Data Protection Act's principles of minimisation and security. A
> formal compliance assessment would be part of any real deployment."

**Q27. What if the power or network goes down?**
> "Staff screens show they're disconnected and pause actions, so nobody acts on stale data. The
> Downtime kit prints a paper sheet, and visits are back-entered later with their real times and
> marked as back-entered. When the service comes back, everything is recovered from the
> database. Backups and restores are tested."

**Q28. Can it connect to national systems?**
> "There's a FHIR-shaped export for interoperability, but full integration with national health
> information systems is out of scope, as the proposal states. FHIR conformance would need
> formal validation against a target version."

**Q29. How did you test it?**
> "150 backend tests, including concurrency on a real PostgreSQL database; 22 frontend unit tests;
> 12 end-to-end browser tests that drive the real system, including the full patient journey,
> the private token page, offline behaviour and the evaluation view. There is also a fresh-machine
> boot test, which starts from nothing and restores a backup. The evidence report links each
> acceptance criterion to its test."

**Q30. How does it scale to a bigger hospital?**
> "It's designed for a single outpatient facility, which is the proposal's scope. Commands are
> serialised per facility, which is deliberately conservative: correctness over throughput.
> That's comfortable for hundreds of visits a day. A large hospital would need a review of that
> choice and load testing. I'd present that as future work, not a claim."

### F. Ethics, safety and responsibility

**Q31. If a patient is harmed, who is responsible?**
> "The clinician, as now, because the clinician makes every priority decision. That's
> deliberate. The system never sets a category, recommendations are clearly labelled
> experimental, and every decision records who made it and whether a suggestion was accepted.
> Any real deployment would also need a clinical safety case and approval, which the proposal
> states in §1.8."

**Q32. Won't staff just click 'accept' on whatever the AI says (automation bias)?**
> "That's a real risk, and the design pushes against it. Accepting only pre-fills the box: the
> clinician still confirms. The model abstains on uncertain cases, so it can't be relied on for
> everything. The explanation shows *why*, which invites disagreement. And the system can record
> how often suggestions are accepted, which is exactly what the shadow-evaluation tools in the
> Research workbench are for, measuring trust without exposing patients."

**Q33. Is it ready to deploy in a clinic tomorrow?**
> "No, and it says so on every screen. It is ready for the **approved field study**: baseline
> measurement, usability sessions and clinician review of labels. Deployment for patient care
> would need ethics approval, a clinical safety case, validation on real labelled data and
> governance sign-off."

### G. Reflection

**Q34. What would you do differently?**
> "Start the ethics application earlier, so real baseline data could shape the model. And I
> would have measured the conservation trade-off before designing the live policy. It changed my
> recommendation from 'prioritise' to 'prioritise with bounded ageing, under governance'."

**Q35. What is your main limitation?**
> "Real-world evidence. Everything is shown on synthetic data from one fictional clinic. The
> methods are tested, but the effect sizes are conditional on assumptions I made. The second
> limitation is single-site generalisability, which the proposal already acknowledges."

**Q36. What is the future work?**
> "1. The approved fieldwork: three weeks, 300 or more journeys, 8–12 interviews.
> 2. Retrain and recalibrate on clinician-reviewed labels.
> 3. Usability sessions with real staff, using the SUS and TAM instruments already built.
> 4. A governance review of bounded ageing as a live option.
> 5. Load testing for larger facilities."

### Questions you should not try to "win"

If a panel member pushes on a real limitation, **agree first**, then show it is handled:

> "You're right that [limitation]. That's why the system [label / abstention / clinician
> confirmation / calibration check]. In the field study I would [specific next step]."

---

## Part 6 — How each objective is evidenced (for your examiners' checklist)

| Objective / RQ | Shown live in | Evidence and where to find it |
|---|---|---|
| O1 / RQ1 — current practice, waiting times, bottlenecks | Steps 7, 9 | Baseline report: per-stage waits, bottleneck, morning share, Little's Law; Analytics + CSV export; ADR-035 |
| O2 / RQ2 — explainable AI from routine data | Steps 5, 11 | Advisory with inputs, sources, factors and abstention; model metrics, under-triage, calibration; ADR-033, ADR-023 |
| O3 / RQ3 — dynamic prioritisation, flow tracking, visibility | Steps 2–8 | Live queues, review prompts, overrides, journey timelines, patient status page, outage handling; ADR-034 |
| O4 / RQ4 — waiting time, model, usability, acceptance against existing process | Steps 10–12 | Calibrated simulation reproducing the baseline; paired policy comparison with fairness; model evaluation; SUS/TAM instruments; Evaluation view; ADR-036 |
| Clinician authority (§1.5, §1.7) | Steps 5, 6, 13 | Category always human-confirmed; one-action logged overrides; AI disable leaves triage working |
| Gap 1 — walk-in settings | Step 3 | Walk-in registration, morning-surge baseline |
| Gap 2 — explainability built | Step 5 | Exact factor contributions, contrast, inputs and sources |
| Gap 3 — connectivity and hardware | Step 8 | Offline labelling, downtime kit, single laptop, no RFID or cloud |
| Gap 4 — patient at the bottom | Steps 6, 10 | Long-wait review prompts; per-category tails and overtaking; bounded-ageing comparison |
