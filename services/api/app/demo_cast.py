"""Readable, internally consistent fictional content for the Hutano Community Clinic.

Everything here is invented. Names are common Zimbabwean given names and surnames combined
at random; they do not describe real people. Reasons for attendance are written in plain
language as a receptionist or nurse would hear them. Following ADR-017 and ADR-037 the
seeded record contains no diagnoses, prescriptions or orders: notes say
why the person came and what happened next, not what they have or what was prescribed.
Urgency categories remain the configurable neutral P1–P5 labels (ADR-002), set by the
fictional triage nurse, never derived from these vital signs by any rule.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

FEMALE = ("Rudo Chipo Rumbidzai Vimbai Ruvimbo Natsai Tsitsi Fadzai Rutendo Chiedza Memory Precious "
          "Loveness Patience Nomsa Thandiwe Nokuthula Sibongile Mercy Ropafadzo Shamiso Nyarai Charity "
          "Primrose Grace Tariro Fungai Tsungai Rejoice Sithembile").split()
MALE = ("Tinashe Tapiwa Tatenda Simbarashe Tafadzwa Farai Munashe Takudzwa Tonderai Brighton Prosper "
        "Tichaona Tawanda Blessed Godknows Lovemore Innocent Givemore Takunda Panashe Themba Sipho "
        "Bongani Sibusiso Nkosana Tendekai Ngonidzashe Kelvin Trust Liberty").split()
SURNAMES = ("Moyo Dube Ndlovu Ncube Sibanda Nyathi Mpofu Chikore Maposa Mavhunga Chikomo Mathe Zhou "
            "Mupunga Chuma Shava Gumbo Marufu Chinembiri Makoni Mutasa Chigumba Nhamo Mushonga Hove "
            "Mazarura Chari Madziva Kativhu Gwenzi Tshuma Khumalo Mlambo Banda Phiri Mukanya Zvobgo "
            "Nyamande Chidzambwa Musarurwa").split()

# Rough outpatient mix: more women than men, a quarter children, a fifth older adults.
AGE_BANDS = (("child", 0, 14, .25), ("adult", 15, 59, .55), ("older_adult", 60, 86, .20))

CONCERNS = {
    "child": ["Fever and cough since yesterday", "Diarrhoea since last night", "Ear pain and crying at night",
              "Itchy rash on the arms", "Not feeding well for two days", "Routine weighing and immunisation check",
              "Runny nose and mild fever", "Fell at school; sore wrist"],
    "adult": ["Headache and body aches for three days", "Cough for over a week", "Burning on passing urine",
              "Lower back pain after lifting", "Abdominal pain since this morning", "Repeat visit for monthly medicines",
              "Wound check after a cut on the hand", "Painful tooth for four days", "Dizziness and tiredness",
              "Family-planning review"],
    "older_adult": ["Monthly review and repeat medicines", "Pain in both knees", "Swollen feet in the evenings",
                    "Blurred vision when reading", "Cough at night", "Dizziness on standing up",
                    "Poor sleep and headaches"],
}


def plan_text(route_after: list[str]) -> str:
    """What happened next, described as logistics only."""
    if not route_after:
        return "Advised and discharged home; no further services today."
    if route_after[0] == "laboratory":
        return "Sent to the laboratory for a blood test; to return to consultation with the result."
    if route_after[0] == "pharmacy":
        return "Sent to pharmacy to collect medicines."
    return f"Sent on to {route_after[0]}."


def triage_reason(category: str, concern: str) -> str:
    lead = {"P1": "Escalated for immediate clinician review.", "P2": "To be seen ahead of routine patients.",
            "P3": "Routine queue; vitals recorded.", "P4": "Routine queue; vitals recorded.",
            "P5": "Routine visit; can wait for the next free room."}[category]
    return f"{concern}. {lead}"


def sample_vitals(rng: random.Random, age_band: str, category: str) -> dict[str, float | None]:
    """Plausible recorded values; unwell categories run warmer and faster. Not physiology."""
    unwell = {"P1": 1.0, "P2": .8, "P3": .3, "P4": 0, "P5": 0}[category]
    base = {"child": (36.9, 104, 24, 98, None, None), "adult": (36.7, 78, 16, 98, 122, 78),
            "older_adult": (36.6, 76, 17, 96, 138, 82)}[age_band]
    temp = round(rng.gauss(base[0] + 1.4 * unwell, .3), 1)
    pulse = round(rng.gauss(base[1] + 22 * unwell, 9))
    resp = round(rng.gauss(base[2] + 6 * unwell, 2))
    spo2 = min(100, round(rng.gauss(base[3] - 3 * unwell, 1)))
    if base[4] is None or rng.random() < .05:
        sbp = dbp = None   # often not measured in children; occasionally the cuff is in use elsewhere
    else:
        sbp = round(rng.gauss(base[4], 14)); dbp = round(rng.gauss(base[5], 8))
    values = {"temperature": temp, "pulse": pulse, "respiratory_rate": resp, "oxygen_saturation": spo2,
              "systolic_pressure": sbp, "diastolic_pressure": dbp}
    for code in ("temperature", "pulse", "respiratory_rate", "oxygen_saturation"):
        if rng.random() < .04: values[code] = None   # device unavailable
    return values


def background_identity(index: int, seed: int = 2026) -> dict:
    """Deterministic identity for background patient `index` (cast members excluded)."""
    rng = random.Random(f"{seed}:person:{index}")
    sex = "female" if rng.random() < .58 else "male"
    taken = {c.name for c in CAST}
    name = None
    while name is None or name in taken:
        name = f"{rng.choice(FEMALE if sex == 'female' else MALE)} {rng.choice(SURNAMES)}"
    roll, band = rng.random(), AGE_BANDS[-1]
    for candidate in AGE_BANDS:
        if roll < candidate[3]: band = candidate; break
        roll -= candidate[3]
    return {"name": name, "sex": sex, "age_band": band[0], "age": rng.randint(band[1], band[2])}


@dataclass(frozen=True)
class Case:
    stage: str              # current service point
    state: str              # current episode state
    category: str | None    # urgency confirmed by the fictional triage nurse
    wait: int               # minutes since joining the current queue
    name: str
    sex: str
    age_band: str
    age: int
    visit_type: str         # walk_in | follow_up | referral
    concern: str            # reason for attendance, in the patient's words
    story: str              # what this case shows during the walkthrough
    note: str = ""          # consultation note, written when consultation has started
    handover: str = ""      # message from consultation to the next service
    vitals: dict = field(default_factory=dict)
    history: str = ""       # reason for their most recent earlier visit (returning patients)

    @property
    def returning(self) -> bool:
        return self.visit_type == "follow_up"


def v(t, p, r, s, sbp=None, dbp=None):
    return {"temperature": t, "pulse": p, "respiratory_rate": r, "oxygen_saturation": s,
            "systolic_pressure": sbp, "diastolic_pressure": dbp}


# Listed in the order a visitor meets them on the floor: front desk → triage → consultation
# → laboratory/pharmacy → escalation → finished. Waits are minutes in the current queue.
CAST = [
    Case("registration", "WAITING", None, 4, "Tawanda Gumbo", "male", "adult", 34, "walk_in",
         "Twisted his ankle at work this morning; it is swollen",
         "Just arrived at the front desk. Reception completes his registration and gives him a token."),
    Case("triage", "WAITING", None, 11, "Shamiso Marufu", "female", "child", 3, "follow_up",
         "Mother says she has had a fever and been feeding poorly since last night",
         "Known to the clinic. Waiting for triage: record her vitals and confirm a category.",
         history="Routine weighing and immunisation check"),
    Case("triage", "WAITING", None, 18, "Lovemore Chinembiri", "male", "older_adult", 67, "follow_up",
         "Back for his regular check-up; felt dizzy getting out of bed this morning",
         "Regular patient waiting for triage. Compare today with his earlier visits in his record.",
         history="Regular check-up and repeat medicines"),
    Case("triage", "WAITING", None, 25, "Nokuthula Tshuma", "female", "adult", 28, "referral",
         "Referred from the outreach post with a letter; abdominal pain for two days",
         "Referral waiting for triage. Shows referral as the visit type."),
    Case("consultation", "WAITING", "P2", 27, "Tinotenda Mlambo", "male", "child", 6, "walk_in",
         "High fever since yesterday and breathing fast",
         "Triage nurse placed him ahead of routine patients. Watch him sit at the top of the consultation queue.",
         vitals=v(38.9, 128, 34, 95)),
    Case("consultation", "WAITING", "P3", 45, "Rutendo Chari", "female", "adult", 41, "follow_up",
         "Back to have the cut on her hand checked, as asked at her last visit",
         "Follow-up visit with earlier encounters in her record. Open her record to see the history.",
         vitals=v(36.6, 80, 16, 99, 118, 76), history="Cut on the left hand while cooking; wound cleaned and dressed"),
    Case("consultation", "WAITING", "P4", 72, "Brighton Nhamo", "male", "adult", 52, "walk_in",
         "Dry cough for three weeks; otherwise feels well",
         "Has waited over an hour while more urgent patients were called. Shows the long-wait warning and review prompt.",
         vitals=v(36.8, 84, 18, 97, 134, 86)),
    Case("consultation", "WAITING", "P3", 31, "Memory Hove", "female", "adult", 23, "walk_in",
         "Burning when passing urine for two days",
         "Routine consultation patient. Use her to call the next patient and start a consultation.",
         vitals=v(37.2, 88, 16, 99, 112, 70)),
    Case("consultation", "WAITING", "P5", 22, "Godknows Mutasa", "male", "older_adult", 71, "follow_up",
         "Routine repeat visit; no new complaints",
         "Least urgent patient in the queue. Shows how the queue orders categories before waiting time.",
         vitals=v(36.5, 72, 16, 96, 142, 84), history="Regular check-up and repeat medicines"),
    Case("consultation", "IN_SERVICE", "P3", 17, "Fadzai Kativhu", "female", "adult", 36, "walk_in",
         "Headache and body aches for three days",
         "With Dr Mupfumi in Consultation room 1 now. Complete the consultation and route her to pharmacy.",
         note="Headache and body aches for three days. History taken and examined.",
         vitals=v(37.6, 92, 18, 98, 120, 80)),
    Case("consultation", "PAUSED", "P4", 21, "Takudzwa Madziva", "male", "adult", 19, "walk_in",
         "Itchy rash on both arms for a week",
         "Consultation paused while he fetches his clinic card from home; Consultation room 2 is held. Resume and finish it.",
         note="Itchy rash on both arms for a week. Consultation paused: patient went home to fetch his clinic card.",
         vitals=v(36.7, 76, 15, 99, 126, 74)),
    Case("pharmacy", "WAITING", "P3", 12, "Sibongile Mpofu", "female", "older_adult", 63, "walk_in",
         "Pain in both knees, worse on the stairs",
         "Seen by the doctor and now waiting at pharmacy. Log in as pharmacy to call and complete her.",
         note="Pain in both knees, worse on the stairs. History taken and examined. Sent to pharmacy to collect medicines.",
         handover="Please explain how to take the medicines in Shona; she prefers it.",
         vitals=v(36.6, 74, 16, 97, 146, 88)),
    Case("pharmacy", "WAITING", "P4", 19, "Panashe Gwenzi", "male", "child", 9, "walk_in",
         "Ear pain since the weekend",
         "Child waiting at pharmacy with his mother after consultation.",
         note="Ear pain since the weekend; seen with his mother. Examined. Sent to pharmacy to collect medicines.",
         handover="Mother will collect; please confirm she understands the timing.",
         vitals=v(37.4, 102, 22, 98)),
    Case("laboratory", "WAITING", "P3", 9, "Charity Makoni", "female", "adult", 30, "walk_in",
         "Tired and dizzy for two weeks",
         "Sent from consultation for a blood test. Laboratory completes it and routes her back to the doctor as a new consultation.",
         note="Tired and dizzy for two weeks. Examined. Sent to the laboratory for a finger-prick blood test; to return with the result.",
         handover="Finger-prick blood test, then send her back to consultation with the result.",
         vitals=v(36.7, 96, 17, 98, 104, 66)),
    Case("triage", "ESCALATION_REQUIRED", "P1", 6, "Givemore Chigumba", "male", "adult", 45, "walk_in",
         "Chest pain that started an hour ago",
         "Triage nurse escalated him for immediate clinician review. Shows the escalation alert on the overview.",
         vitals=v(36.8, 112, 24, 93, 158, 96)),
    Case("pharmacy", "COMPLETED", "P4", 36, "Patience Mazarura", "female", "adult", 48, "walk_in",
         "Lower back pain after lifting a bucket",
         "Finished: seen, collected medicines and went home. Open her journey to see every timestamp.",
         note="Lower back pain after lifting. History taken and examined. Sent to pharmacy to collect medicines.",
         handover="Routine collection.",
         vitals=v(36.6, 78, 15, 99, 128, 82)),
    Case("consultation", "COMPLETED", "P3", 43, "Prosper Mushonga", "male", "older_adult", 64, "follow_up",
         "Back as asked; feet still swell in the evenings",
         "Finished review visit; asked to come back in a month. Shows a completed visit without pharmacy.",
         note="Back as asked; feet still swell in the evenings. Examined. Advised and discharged home; review in one month.",
         vitals=v(36.5, 70, 16, 96, 148, 90), history="Swollen feet in the evenings for a week"),
]
