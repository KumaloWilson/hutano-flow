// Patient-facing copy in English, chiShona and isiNdebele.
// DRAFT TRANSLATIONS for usability testing only: they must be reviewed by native
// Shona and Ndebele speakers (ideally clinic staff) before any field use. See ADR-032.
export type Lang = "en" | "sn" | "nd";
export const LANGS: { code: Lang; label: string }[] = [
  { code: "en", label: "English" }, { code: "sn", label: "Shona" }, { code: "nd", label: "Ndebele" },
];

const en = {
  title: "Where am I in the queue?",
  intro: "Scan the QR code on your receipt, or type the private token printed on it. Your health details and priority are never shown here.",
  tokenLabel: "Private status token",
  check: "Check status",
  checking: "Checking…",
  aheadMany: "people ahead of you",
  aheadOne: "person ahead of you",
  aheadNone: "You are next",
  yourTurn: "It's your turn",
  goTo: "Please go to {place} now.",
  stage: "Current stage",
  estimate: "Estimated wait",
  noEstimate: "Not enough data yet",
  range: "{min}–{max} min",
  updated: "Updated {time}",
  offline: "Connection lost — this may be out of date. Retrying automatically.",
  done: "Complete",
  complete: "Your visit is complete. Thank you.",
  staff: "Please speak with a member of staff.",
  notFound: "Token not found. Check it and try again.",
  tooMany: "Too many attempts. Please wait a minute and try again.",
  preparing: "Preparing your next step",
  notice: "Research prototype — not for clinical use",
  staffSignIn: "Staff sign in",
  another: "Use another token",
  estimateNote: "This is an estimate and may change.",
  beingSeen: "You are being seen",
  paused: "Your service is paused — please stay nearby",
  nowCalling: "Now calling",
  waiting: "Waiting",
  ticketReady: "Please have your ticket ready",
  closed: "Closed",
  language: "Language",
};
export type Copy = typeof en;

const sn: Copy = {
  title: "Ndiri papi pamutsetse?",
  intro: "Tarisai QR kodhi iri parisiti yenyu, kana nyorai nhamba yakavanzika yakadhindwa pairi. Ruzivo rwehutano hwenyu nekukosha kwenyu hazviratidzwe pano.",
  tokenLabel: "Nhamba yenyu yakavanzika",
  check: "Tarisa mamiriro",
  checking: "Tiri kutarisa…",
  aheadMany: "vanhu vari pamberi penyu",
  aheadOne: "munhu ari pamberi penyu",
  aheadNone: "Ndimi munotevera",
  yourTurn: "Yave nguva yenyu",
  goTo: "Ndapota endai ku{place} izvozvi.",
  stage: "Danho riripo",
  estimate: "Nguva yekumirira inofungidzirwa",
  noEstimate: "Hapasati pane ruzivo rwakakwana",
  range: "{min}–{max} min",
  updated: "Yavandudzwa {time}",
  offline: "Kubatana kwadambuka — ruzivo urwu runogona kunge rwasara. Tichaedza zvakare.",
  done: "Zvapera",
  complete: "Kushanya kwenyu kwapera. Tatenda.",
  staff: "Ndapota taurai nemushandi.",
  notFound: "Hatina kuwana nhamba iyi. Itarisei muedze zvakare.",
  tooMany: "Maedza kakawanda. Mirai miniti imwe moedza zvakare.",
  preparing: "Tiri kugadzirira danho renyu rinotevera",
  notice: "Purototaipi yetsvakurudzo — haisi yekurapa",
  staffSignIn: "Kupinda kwevashandi",
  another: "Shandisai imwe nhamba",
  estimateNote: "Uku kufungidzira, kunogona kuchinja.",
  beingSeen: "Muri kubatsirwa",
  paused: "Rubatsiro rwamiswa kwechinguva — ndapota musaenda kure",
  nowCalling: "Vari kudaidzwa",
  waiting: "Vakamirira",
  ticketReady: "Gadzirirai tikiti yenyu",
  closed: "Yakavharwa",
  language: "Mutauro",
};

const nd: Copy = {
  title: "Ngikuphi emgqeni?",
  intro: "Skena ikhodi ye-QR kurisithi yakho, kumbe ubhale inombolo eyimfihlo ephrintiwe kuyo. Imininingwane yempilo yakho lokuqakatheka kwakho akutshengiswa lapha.",
  tokenLabel: "Inombolo yakho eyimfihlo",
  check: "Hlola isimo",
  checking: "Siyahlola…",
  aheadMany: "abantu abaphambi kwakho",
  aheadOne: "umuntu ophambi kwakho",
  aheadNone: "Nguwe olandelayo",
  yourTurn: "Sekuyisikhathi sakho",
  goTo: "Ake uye ku-{place} khathesi.",
  stage: "Isigaba samanje",
  estimate: "Isikhathi sokulinda esilinganisiweyo",
  noEstimate: "Akukabi lolwazi olwaneleyo",
  range: "{min}–{max} min",
  updated: "Kubuyekezwe {time}",
  offline: "Ukuxhumana kuqamukile — lokhu kungaba kudala. Sizazama njalo.",
  done: "Sekuphelile",
  complete: "Ukuvakatsha kwakho sekuphelile. Siyabonga.",
  staff: "Ake ukhulume lesisebenzi.",
  notFound: "Asiyitholanga leyo nombolo. Yihlole uzame futhi.",
  tooMany: "Uzame kanengi. Linda umzuzu owodwa uzame futhi.",
  preparing: "Silungiselela isinyathelo sakho esilandelayo",
  notice: "Uhlelo lokucwaninga — kalusetshenziselwa ukwelapha",
  staffSignIn: "Ukungena kwabasebenzi",
  another: "Sebenzisa enye inombolo",
  estimateNote: "Lokhu kuyalinganiswa, kungatshintsha.",
  beingSeen: "Uyasizwa khathesi",
  paused: "Usizo lumisiwe okwesikhatshana — ake ungayi khatshana",
  nowCalling: "Kubizwa",
  waiting: "Abalindileyo",
  ticketReady: "Lungisa ithikithi lakho",
  closed: "Kuvaliwe",
  language: "Ulimi",
};

export const COPY: Record<Lang, Copy> = { en, sn, nd };

export function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_, key) => String(values[key] ?? ""));
}

export function storedLang(): Lang {
  try {
    const value = localStorage.getItem("hutano-lang");
    if (value === "en" || value === "sn" || value === "nd") return value;
  } catch { /* storage unavailable: fall back */ }
  return "en";
}

export function storeLang(lang: Lang) {
  try { localStorage.setItem("hutano-lang", lang); } catch { /* best effort */ }
}
