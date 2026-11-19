"use strict";

const DATA_BASES = ["../data/", "data/"];

const LEANINGS = ["Levo", "Sredina-Levo", "Sredina", "Sredina-Desno", "Desno"];
const LEAN_STYLE = {
  "Levo":          { dot: "bg-red-600",   soft: "bg-red-50 text-red-800 ring-red-200 dark:bg-red-950 dark:text-red-200 dark:ring-red-900",       border: "border-red-600" },
  "Sredina-Levo":  { dot: "bg-red-300",   soft: "bg-red-50 text-red-700 ring-red-100 dark:bg-red-950/60 dark:text-red-300 dark:ring-red-900/60", border: "border-red-300" },
  "Sredina":       { dot: "bg-slate-400", soft: "bg-slate-100 text-slate-700 ring-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-700", border: "border-slate-400" },
  "Sredina-Desno": { dot: "bg-blue-300",  soft: "bg-blue-50 text-blue-700 ring-blue-100 dark:bg-blue-950/60 dark:text-blue-300 dark:ring-blue-900/60", border: "border-blue-300" },
  "Desno":         { dot: "bg-blue-600",  soft: "bg-blue-50 text-blue-800 ring-blue-200 dark:bg-blue-950 dark:text-blue-200 dark:ring-blue-900",   border: "border-blue-600" },
};
const CATEGORY_LABEL = {
  javni: "Javni servis",
  komercialni: "Komercialni",
  alternativni: "Alternativni",
  regionalni: "Regionalni",
  mednarodni: "Mednarodno sidro",
};

// ---------------------------------------------------------------- DOM pomočniki
// Vse vsebine gredo v DOM prek textContent – podatki prihajajo iz zunanjih virov.
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key === "class") el.className = value;
    else el.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

function safeUrl(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null;
  }
}

function leanStyle(leaning) {
  return LEAN_STYLE[leaning] || LEAN_STYLE["Sredina"];
}

// Številčna ocena −3 (levo) … +3 (desno); starejši podatki brez nje dobijo sredino razreda.
const LEAN_DEFAULT_SCORE = { "Levo": -2.5, "Sredina-Levo": -1, "Sredina": 0, "Sredina-Desno": 1, "Desno": 2.5 };

function leanScore(c) {
  return typeof c.lean_score === "number" ? c.lean_score : LEAN_DEFAULT_SCORE[c.bias_leaning] ?? 0;
}

function formatScore(x) {
  const v = Math.round(x * 10) / 10;
  return (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toLocaleString("sl-SI", { minimumFractionDigits: 1 });
}

function scoreChip(c) {
  if (typeof c.lean_score !== "number") return null;
  return h("span", { class: "rounded bg-slate-100 px-1.5 py-0.5 text-[11px] font-semibold tabular-nums text-slate-700 dark:bg-slate-800 dark:text-slate-200", title: "Nagib na lestvici od −3 (levo) do +3 (desno)" }, formatScore(c.lean_score));
}

function leanBadge(leaning) {
  return h("span", { class: `inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${leanStyle(leaning).soft}` },
    h("span", { class: `h-2 w-2 rounded-full ${leanStyle(leaning).dot}`, "aria-hidden": "true" }), leaning);
}

function sensationalismMeter(score) {
  const s = Math.max(1, Math.min(10, Number(score) || 1));
  const tone = s >= 7 ? "bg-amber-500" : s >= 4 ? "bg-amber-300" : "bg-emerald-500";
  const label = s >= 7 ? "Senzacionalističen" : s >= 4 ? "Zmerno obarvan" : "Nevtralen";
  return h("div", { class: "space-y-1" },
    h("div", { class: "flex items-center justify-between text-xs" },
      h("span", { class: "text-slate-500 dark:text-slate-400" }, "Senzacionalizem naslova"),
      h("span", { class: "font-semibold tabular-nums" }, `${s}/10`)),
    h("div", { class: "flex gap-0.5", role: "meter", "aria-valuemin": "1", "aria-valuemax": "10", "aria-valuenow": String(s), "aria-label": `Senzacionalizem ${s} od 10` },
      Array.from({ length: 10 }, (_, i) =>
        h("span", { class: `h-1.5 flex-1 rounded-sm ${i < s ? tone : "bg-slate-200 dark:bg-slate-700"}` }))),
    h("div", { class: "text-[11px] text-slate-500 dark:text-slate-400" }, label));
}

// Slovenska dvojina/množina: 1 članek, 2 članka, 3–4 članki, 5+ člankov.
function plural(n, [one, two, few, many]) {
  const mod = Math.abs(n) % 100;
  const word = mod === 1 ? one : mod === 2 ? two : mod === 3 || mod === 4 ? few : many;
  return `${n} ${word}`;
}
const WORDS = {
  story: ["zgodba", "zgodbi", "zgodbe", "zgodb"],
  source: ["vir", "vira", "viri", "virov"],
  article: ["članek", "članka", "članki", "člankov"],
};

function formatDate(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso || "";
  return d.toLocaleString("sl-SI", { dateStyle: "long", timeStyle: "short" });
}

// ---------------------------------------------------------------- Sestavni deli
function renderMeta(data) {
  const meta = document.getElementById("meta");
  meta.replaceChildren(
    h("div", { class: "font-medium text-slate-700 dark:text-slate-200" }, formatDate(data.generated_at)),
    h("div", {}, `${plural(data.stories.length, WORDS.story)} · ${plural(new Set(data.stories.flatMap((st) => st.coverage_comparison.map((c) => c.media_name))).size, WORDS.source)} · model: ${data.model}`));

  if (data.is_mock) {
    document.getElementById("banner").replaceChildren(
      h("div", { class: "mb-6 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100", role: "status" },
        h("strong", {}, "Demo podatki. "),
        "Zgodbe, naslovi in citati so izmišljeni in služijo samo prikazu vmesnika. ",
        "Za resnično analizo nastavite ", h("code", { class: "font-mono" }, "GEMINI_API_KEY"), " in zaženite ",
        h("code", { class: "font-mono" }, "backend/main.py"), "."));
  }
}

function renderLegend() {
  document.getElementById("legend").replaceChildren(
    h("div", { class: "flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-slate-600 dark:text-slate-300" },
      h("span", { class: "font-semibold uppercase tracking-wide text-slate-500" }, "Lestvica nagiba"),
      LEANINGS.map((l) => h("span", { class: "inline-flex items-center gap-1.5" },
        h("span", { class: `h-2.5 w-2.5 rounded-full ${leanStyle(l).dot}`, "aria-hidden": "true" }), l)),
      h("span", { class: "text-slate-500 dark:text-slate-400" }, "Številka ob oceni: −3 levo … 0 uravnoteženo … +3 desno")));
}

const mean = (xs) => xs.reduce((a, b) => a + b, 0) / (xs.length || 1);
const scorePos = (x) => `${((Math.max(-3, Math.min(3, x)) + 3) / 6) * 100}%`;

// Statistika po medijih za seznam dni (en dan ali celoten arhiv).
function mediaStats(days) {
  const byMedia = new Map();
  for (const day of days) {
    for (const story of day.stories || []) {
      for (const c of story.coverage_comparison) {
        const e = byMedia.get(c.media_name) || { name: c.media_name, category: c.category, sens: [], lean: [], words: [], oneSided: 0, days: new Set() };
        e.sens.push(c.sensationalism_score);
        e.lean.push(leanScore(c));
        if (c.word_count) e.words.push(c.word_count);
        if (c.sides_represented === "Samo ena stran") e.oneSided += 1;
        e.days.add(day.date || "");
        byMedia.set(c.media_name, e);
      }
    }
  }
  return new Map([...byMedia].map(([name, e]) => [name, {
    ...e, count: e.lean.length, avgSens: mean(e.sens), avgLean: mean(e.lean),
    min: Math.min(...e.lean), max: Math.max(...e.lean),
    avgWords: e.words.length ? Math.round(mean(e.words)) : null,
    oneSidedShare: Math.round((100 * e.oneSided) / e.lean.length),
  }]));
}

let profileMode = "day";
try { profileMode = localStorage.getItem("profileMode") === "archive" ? "archive" : "day"; } catch { /* brez shrambe */ }

function renderProfile(data, archiveDays) {
  const canArchive = archiveDays.length > 1;
  const mode = canArchive ? profileMode : "day";
  const stats = mediaStats(mode === "archive" ? archiveDays : [data]);
  if (!stats.size) return;
  const rows = [...stats.values()].sort((a, b) => a.avgLean - b.avgLean);

  const toggle = (key, label) => h("button", {
    type: "button", "aria-pressed": String(mode === key),
    class: `rounded-md px-2.5 py-1 text-xs font-medium ${mode === key ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"}`,
  }, label);
  const dayBtn = toggle("day", "Ta dan");
  const archBtn = toggle("archive", `Celoten arhiv (${plural(archiveDays.length, ["dan", "dneva", "dnevi", "dni"])})`);
  for (const [btn, key] of [[dayBtn, "day"], [archBtn, "archive"]]) {
    btn.addEventListener("click", () => {
      profileMode = key;
      try { localStorage.setItem("profileMode", key); } catch { /* brez shrambe */ }
      renderProfile(data, archiveDays);
    });
  }

  document.getElementById("profile").replaceChildren(
    h("div", { class: "rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900" },
      h("div", { class: "mb-1 flex flex-wrap items-center justify-between gap-2" },
        h("h2", { class: "text-sm font-semibold uppercase tracking-wide text-slate-500" }, mode === "archive" ? "Profil medijev v celotnem arhivu" : "Profil medijev za ta dan"),
        canArchive ? h("div", { class: "flex gap-1 rounded-lg bg-slate-100 p-0.5 dark:bg-slate-800/60", role: "group", "aria-label": "Obdobje profila" }, dayBtn, archBtn) : null),
      h("p", { class: "mb-4 text-xs text-slate-500 dark:text-slate-400" },
        "Vsaka pika je en članek, črta kaže razpon od najbolj levo do najbolj desno ocenjenega članka, velik krog je povprečje (−3 levo … +3 desno). ",
        "»Samo ena stran« je delež člankov, v katerih je dobila besedo le ena stran."),
      h("div", { class: "space-y-4" }, rows.map((r) =>
        h("div", { class: "grid grid-cols-1 items-center gap-2 sm:grid-cols-[10rem_1fr_15rem]" },
          h("div", {},
            h("div", { class: "text-sm font-medium" }, r.name),
            h("div", { class: "text-[11px] text-slate-500" }, `${CATEGORY_LABEL[r.category] || r.category} · ${plural(r.count, WORDS.article)}`)),
          h("div", { class: "relative h-2 rounded-full bg-gradient-to-r from-red-500 via-slate-300 to-blue-500 dark:via-slate-600", role: "img",
            "aria-label": `Povprečni nagib ${formatScore(r.avgLean)}, razpon od ${formatScore(r.min)} do ${formatScore(r.max)}` },
            r.count > 1 && r.max > r.min
              ? h("span", { class: "absolute top-1/2 h-1 -translate-y-1/2 rounded-full bg-slate-900/70 dark:bg-white/70", style: `left:${scorePos(r.min)};width:calc(${scorePos(r.max)} - ${scorePos(r.min)})` })
              : null,
            r.count > 1 ? r.lean.map((x) => h("span", {
              class: "absolute top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white bg-slate-700 dark:border-slate-900 dark:bg-slate-200",
              style: `left:${scorePos(x)}`, title: formatScore(x),
            })) : null,
            h("span", {
              class: "absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-slate-900 shadow dark:border-slate-900 dark:bg-white",
              style: `left:${scorePos(r.avgLean)}`, title: `Povprečje ${formatScore(r.avgLean)}`,
            })),
          h("div", { class: "text-xs text-slate-600 dark:text-slate-300 sm:text-right" },
            h("div", { class: "whitespace-nowrap" },
              "Nagib ", h("span", { class: "font-semibold tabular-nums" }, formatScore(r.avgLean)),
              " · Senzac. ", h("span", { class: "font-semibold tabular-nums" }, r.avgSens.toFixed(1)), "/10"),
            h("div", { class: "whitespace-nowrap text-[11px] text-slate-500 dark:text-slate-400" },
              `Samo ena stran: ${r.oneSidedShare} %`, r.avgWords ? ` · ${r.avgWords} besed v povprečju` : "")))))));
}

// Usmerjenost medija = povprečni nagib njegovih člankov v arhivu (le ob vsaj dveh člankih).
function outletOrientation(archiveDays) {
  const result = new Map();
  for (const [name, s] of mediaStats(archiveDays)) {
    if (s.count >= 2) result.set(name, s.avgLean <= -0.5 ? "levo" : s.avgLean >= 0.5 ? "desno" : "sredina");
  }
  return result;
}

// Slepa pega: o zgodbi poročajo mediji ene strani, preverjeno odsotni pa so mediji druge strani.
function blindspot(story, orientation) {
  const domestic = story.coverage_comparison.filter((c) => c.category !== "mednarodni");
  const sideOf = (score) => score <= -0.5 ? "levo" : score >= 0.5 ? "desno" : null;
  const notes = [];
  for (const [side, other] of [["levo", "desno"], ["desno", "levo"]]) {
    const absent = (story.not_covered_by || []).filter((m) => orientation.get(m) === side);
    const coveredBySide = domestic.some((c) => orientation.get(c.media_name) === side);
    const coveredByOther = domestic.some((c) => orientation.get(c.media_name) === other);
    if (absent.length && !coveredBySide && coveredByOther) {
      notes.push({ side, text: `Ne poročajo mediji, ki so v arhivu v povprečju ${side === "levo" ? "levo" : "desno"} usmerjeni: ${absent.join(", ")}.` });
      continue;
    }
    const sideArticles = domestic.filter((c) => sideOf(leanScore(c)) === other);
    if (domestic.length >= 3 && sideArticles.length >= 2 && !domestic.some((c) => sideOf(leanScore(c)) === side)) {
      notes.push({ side, text: `Noben članek ni ocenjen ${side === "levo" ? "levo" : "desno"} od sredine, vsaj dva sta ${other === "levo" ? "levo" : "desno"}.` });
    }
  }
  if (!notes.length) return null;
  return h("div", { class: "mt-2 flex flex-wrap gap-2" }, notes.map((n) =>
    h("span", { class: "inline-flex items-center gap-1.5 rounded-md bg-violet-100 px-2 py-1 text-[11px] font-semibold text-violet-900 ring-1 ring-inset ring-violet-200 dark:bg-violet-950 dark:text-violet-200 dark:ring-violet-900", title: n.text },
      h("span", { "aria-hidden": "true" }, "◐"), `Slepa pega ${n.side === "levo" ? "levo" : "desno"}`,
      h("span", { class: "font-normal" }, `– ${n.text}`))));
}

function renderToc(data) {
  if (data.stories.length < 2) return;
  document.getElementById("toc").replaceChildren(
    h("div", { class: "flex flex-wrap gap-2" },
      data.stories.map((s, i) => h("a", {
        href: `#${s.id}`,
        class: "rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-700 hover:border-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200",
      }, `${i + 1}. ${s.topic_title}`))));
}

// Ground News slog: delež levih / sredinskih / desnih poročil.
function distributionBar(coverage) {
  const groups = [
    { label: "Levo", match: ["Levo", "Sredina-Levo"], cls: "bg-red-600", text: "text-white" },
    { label: "Sredina", match: ["Sredina"], cls: "bg-slate-300 dark:bg-slate-600", text: "text-slate-800 dark:text-slate-100" },
    { label: "Desno", match: ["Sredina-Desno", "Desno"], cls: "bg-blue-600", text: "text-white" },
  ];
  const total = coverage.length || 1;
  return h("div", { class: "flex h-6 overflow-hidden rounded-md text-[11px] font-semibold", role: "img",
    "aria-label": groups.map((g) => `${g.label} ${Math.round(coverage.filter((c) => g.match.includes(c.bias_leaning)).length / total * 100)} %`).join(", ") },
    groups.map((g) => {
      const n = coverage.filter((c) => g.match.includes(c.bias_leaning)).length;
      if (!n) return null;
      const pct = Math.round((n / total) * 100);
      return h("div", { class: `flex items-center justify-center ${g.cls} ${g.text}`, style: `width:${(n / total) * 100}%` },
        `${g.label} ${pct} %`);
    }));
}

function spectrum(coverage) {
  return h("div", { class: "mt-3" },
    h("div", { class: "grid grid-cols-5 gap-1" },
      LEANINGS.map((l) => {
        const here = coverage.filter((c) => c.bias_leaning === l);
        return h("div", { class: "flex min-h-[2.5rem] flex-col items-center justify-end gap-1 pb-1" },
          here.map((c) => h("span", {
            class: `max-w-full truncate rounded-md border-b-2 bg-white px-1.5 py-0.5 text-[11px] font-medium shadow-sm ring-1 ring-slate-200 dark:bg-slate-800 dark:ring-slate-700 ${leanStyle(l).border}`,
            title: `${c.media_name}: ${l}`,
          }, c.media_name)));
      })),
    h("div", { class: "grid grid-cols-5 gap-1" },
      LEANINGS.map((l) => h("div", { class: `h-1.5 rounded-full ${leanStyle(l).dot}` }))),
    h("div", { class: "mt-1 grid grid-cols-5 gap-1 text-center text-[10px] text-slate-500 dark:text-slate-400" },
      LEANINGS.map((l) => h("div", {}, l))));
}

const SIDES_STYLE = {
  "Obe strani": "bg-emerald-50 text-emerald-800 ring-emerald-200 dark:bg-emerald-950 dark:text-emerald-200 dark:ring-emerald-900",
  "Pretežno ena stran": "bg-amber-50 text-amber-800 ring-amber-200 dark:bg-amber-950 dark:text-amber-200 dark:ring-amber-900",
  "Samo ena stran": "bg-orange-100 text-orange-900 ring-orange-300 dark:bg-orange-950 dark:text-orange-200 dark:ring-orange-900",
};

// Barve strani v sporu niso politične (ne rdeča/modra), da jih ne zamenjamo z nagibom.
const SIDE_COLORS = ["bg-indigo-500", "bg-teal-500", "bg-amber-500", "bg-fuchsia-500", "bg-slate-400"];

function sideWeights(c, { compact = false } = {}) {
  const weights = c.side_weights || [];
  if (!weights.length) return null;
  const total = weights.reduce((a, w) => a + w.share_percent, 0) || 1;
  return h("div", { class: "space-y-1" },
    h("div", { class: "flex h-2.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700", role: "img",
      "aria-label": weights.map((w) => `${w.side} ${w.share_percent} %`).join(", ") },
      weights.map((w, i) => w.share_percent
        ? h("span", { class: SIDE_COLORS[i % SIDE_COLORS.length], style: `width:${(100 * w.share_percent) / total}%`, title: `${w.side}: ${w.share_percent} %` })
        : null)),
    h("ul", { class: compact ? "flex flex-wrap gap-x-3 gap-y-0.5" : "space-y-0.5" }, weights.map((w, i) =>
      h("li", { class: `flex items-center gap-1.5 text-[11px] ${w.share_percent ? "text-slate-700 dark:text-slate-300" : "text-slate-400 line-through decoration-slate-300 dark:text-slate-500"}` },
        h("span", { class: `h-2 w-2 shrink-0 rounded-sm ${SIDE_COLORS[i % SIDE_COLORS.length]}`, "aria-hidden": "true" }),
        h("span", {}, w.side),
        h("span", { class: "tabular-nums text-slate-500 dark:text-slate-400" },
          `${w.share_percent} %${compact ? "" : ` · ${plural(w.direct_quotes, ["citat", "citata", "citati", "citatov"])}`}`),
        w.in_lede ? h("span", { class: "rounded bg-slate-200 px-1 text-[10px] font-semibold text-slate-700 dark:bg-slate-700 dark:text-slate-200", title: "Ta stran dobi besedo v naslovu ali uvodu" }, "uvod") : null))));
}

function voicesBlock(c) {
  const voices = c.voices_heard || [];
  if (!voices.length && !c.sides_represented) return null;
  return h("div", { class: "space-y-1.5" },
    h("div", { class: "flex flex-wrap items-center justify-between gap-1 text-xs" },
      h("span", { class: "text-slate-500 dark:text-slate-400" }, (c.side_weights || []).length ? "Prostor po straneh" : "Kdo dobi besedo"),
      c.sides_represented
        ? h("span", { class: `rounded px-1.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${SIDES_STYLE[c.sides_represented] || SIDES_STYLE["Obe strani"]}` }, c.sides_represented)
        : null),
    sideWeights(c, { compact: true }),
    voices.length
      ? h("div", { class: "flex flex-wrap gap-1" }, voices.map((v) =>
          h("span", { class: "rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-700 dark:bg-slate-800 dark:text-slate-300" }, v)))
      : null);
}

function partialBadge(c) {
  return c.partial_text
    ? h("span", { class: "rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-semibold text-red-800 dark:bg-red-900 dark:text-red-100", title: "Besedilo je kratko, odrezano ali za plačljivim zidom; ocena je zato manj zanesljiva." }, "Delno besedilo")
    : null;
}

function coreBar(c) {
  const core = c.shared_core;
  if (!core) return null;
  return h("div", { class: "space-y-1", title: "Delež avtorskega besedila (brez citatov), ki ga ima vsaj še en primerjani medij – običajno skupna vest agencije." },
    h("div", { class: "flex items-center justify-between text-xs" },
      h("span", { class: "text-slate-500 dark:text-slate-400" }, "Skupno jedro / lastno besedilo"),
      h("span", { class: "tabular-nums font-semibold" }, `${core.shared_percent} % / ${core.own_percent} %`)),
    h("div", { class: "flex h-1.5 overflow-hidden rounded-full bg-emerald-400 dark:bg-emerald-600" },
      h("span", { class: "bg-slate-400 dark:bg-slate-500", style: `width:${core.shared_percent}%` })));
}

function listBlock(title, items, tone) {
  if (!items || !items.length) return null;
  return h("div", { class: `rounded-lg p-2 ${tone.box}` },
    h("div", { class: `mb-1 text-xs font-semibold ${tone.title}` }, title),
    h("ul", { class: "space-y-1" }, items.map((t) => h("li", { class: `text-xs ${tone.text}` }, t))));
}

function coverageColumn(c) {
  const url = safeUrl(c.article_url);
  const intl = c.category === "mednarodni";
  return h("article", { class: `flex flex-col gap-3 rounded-xl border p-4 ${intl ? "border-emerald-300 bg-emerald-50/50 dark:border-emerald-800 dark:bg-emerald-950/30" : "border-slate-200 bg-slate-50/60 dark:border-slate-800 dark:bg-slate-900/60"}` },
    h("div", { class: "flex items-start justify-between gap-2" },
      h("div", {},
        h("div", { class: "text-sm font-bold" }, c.media_name),
        h("div", { class: "text-[11px] uppercase tracking-wide text-slate-500" }, CATEGORY_LABEL[c.category] || c.category)),
      h("div", { class: "flex shrink-0 flex-wrap items-center justify-end gap-1" }, leanBadge(c.bias_leaning), scoreChip(c), partialBadge(c))),
    url
      ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer", class: "text-sm font-medium leading-snug text-slate-800 underline decoration-slate-300 underline-offset-2 hover:decoration-slate-700 dark:text-slate-100 dark:decoration-slate-600" }, c.article_title)
      : h("p", { class: "text-sm font-medium leading-snug" }, c.article_title),
    sensationalismMeter(c.sensationalism_score),
    c.main_frame
      ? h("div", { class: "text-xs text-slate-600 dark:text-slate-300" }, h("span", { class: "text-slate-500 dark:text-slate-400" }, "Okvir: "), c.main_frame)
      : null,
    c.headline_leaning && c.body_leaning && c.headline_leaning !== c.body_leaning
      ? h("div", { class: "text-xs text-slate-600 dark:text-slate-300" }, `Naslov: ${c.headline_leaning} · besedilo: ${c.body_leaning}`)
      : null,
    voicesBlock(c),
    coreBar(c),
    listBlock("Dejanska napaka", c.factual_errors, {
      box: "bg-red-50 ring-1 ring-inset ring-red-200 dark:bg-red-950 dark:ring-red-900",
      title: "text-red-800 dark:text-red-200", text: "text-red-900 dark:text-red-100" }),
    listBlock("Opomba", c.notes, {
      box: "bg-slate-100 dark:bg-slate-800",
      title: "text-slate-600 dark:text-slate-300", text: "text-slate-600 dark:text-slate-300" }),
    h("div", { class: "mt-auto" },
      h("div", { class: "mb-1 text-xs font-semibold text-slate-600 dark:text-slate-300" }, intl ? "Referenčni vir" : "Zamolčano ali minimizirano"),
      intl
        ? h("p", { class: "text-xs text-slate-500 dark:text-slate-400" }, "Izhodišče za primerjavo dejstev.")
        : c.omitted_facts.length
          ? h("ul", { class: "space-y-1" }, c.omitted_facts.map((f) =>
              h("li", { class: "flex gap-1.5 text-xs text-slate-700 dark:text-slate-300" },
                h("span", { class: "mt-0.5 text-amber-600", "aria-hidden": "true" }, "▲"), f)))
          : (c.notes || []).length
            ? h("p", { class: "text-xs text-slate-500 dark:text-slate-400" }, "Ni ocenjeno – glej opombo.")
            : h("p", { class: "text-xs text-emerald-700 dark:text-emerald-400" }, "Ni zaznanih izpuščenih ključnih dejstev.")));
}

const CONFIDENCE_STYLE = {
  "Visoka": "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100",
  "Srednja": "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-100",
  "Nizka": "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100",
};

function section(title, ...content) {
  const body = content.flat().filter(Boolean);
  if (!body.length) return null;
  return h("div", { class: "space-y-1.5" },
    h("h6", { class: "text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400" }, title),
    body);
}

function para(text) {
  return text ? h("p", { class: "text-sm leading-relaxed text-slate-700 dark:text-slate-200" }, text) : null;
}

function hasDetail(c) {
  return Boolean(c.reasoning || c.main_frame || c.headline_analysis || (c.loaded_language || []).length ||
    (c.editorial_statements || []).length || (c.unique_facts || []).length);
}

function overlapBlock(c) {
  const overlaps = c.text_overlap || [];
  const sources = c.cited_sources || [];
  return [
    sources.length
      ? h("div", { class: "flex flex-wrap items-center gap-1 text-xs text-slate-600 dark:text-slate-300" },
          "Navaja vire:", sources.map((s) => h("span", { class: "rounded bg-slate-100 px-1.5 py-0.5 dark:bg-slate-800" }, s)))
      : h("p", { class: "text-xs text-slate-500 dark:text-slate-400" }, "V besedilu ni navedenih agencij ali drugih medijev."),
    overlaps.length
      ? h("ul", { class: "space-y-0.5" }, overlaps.map((o) =>
          h("li", { class: "text-xs text-slate-700 dark:text-slate-200" },
            h("span", { class: "font-semibold tabular-nums" }, `${o.percent} %`), ` avtorskega besedila (brez citatov) je enakega kot pri mediju ${o.media}.`)))
      : h("p", { class: "text-xs text-slate-500 dark:text-slate-400" }, "Prevzemanja besedila od drugih primerjanih medijev ni zaznati (prag 5 %)."),
  ];
}

function detailCard(c) {
  const url = safeUrl(c.article_url);
  const published = c.published ? formatDate(c.published) : null;
  return h("article", { class: `rounded-xl border-l-4 bg-slate-50 p-4 dark:bg-slate-900/60 ${leanStyle(c.bias_leaning).border}` },
    h("div", { class: "mb-3 flex flex-wrap items-start justify-between gap-2" },
      h("div", {},
        h("div", { class: "text-base font-bold" }, c.media_name),
        url
          ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer", class: "text-sm underline decoration-slate-300 underline-offset-2 hover:decoration-slate-700 dark:decoration-slate-600" }, c.article_title)
          : h("p", { class: "text-sm" }, c.article_title),
        h("div", { class: "mt-1 text-[11px] text-slate-500 dark:text-slate-400" },
          [published, c.word_count ? `${c.word_count} besed` : null].filter(Boolean).join(" · "))),
      h("div", { class: "flex flex-wrap items-center gap-1.5" },
        leanBadge(c.bias_leaning), scoreChip(c), partialBadge(c),
        c.confidence ? h("span", { class: `rounded px-1.5 py-0.5 text-[11px] font-semibold ${CONFIDENCE_STYLE[c.confidence] || ""}` }, `Zanesljivost: ${c.confidence.toLowerCase()}`) : null)),

    h("div", { class: "grid gap-4 lg:grid-cols-2" },
      h("div", { class: "space-y-4" },
        section("Utemeljitev ocene", para(c.reasoning)),
        section("Naslov",
          h("div", { class: "flex flex-wrap gap-3 text-xs text-slate-600 dark:text-slate-300" },
            h("span", {}, "Naslov: ", leanBadge(c.headline_leaning || c.bias_leaning)),
            h("span", {}, "Besedilo: ", leanBadge(c.body_leaning || c.bias_leaning))),
          para(c.headline_analysis)),
        section("Okvir zgodbe",
          c.main_frame ? h("p", { class: "text-sm font-semibold" }, c.main_frame) : null,
          para(c.frame_description)),
        section("Kaj je v uvodu", para(c.lede_focus)),
        section("Prostor po straneh", sideWeights(c)),
        section("Viri in prevzemanje", overlapBlock(c), coreBar(c))),
      h("div", { class: "space-y-4" },
        section("Obremenjeno besedišče avtorja",
          (c.loaded_language || []).length
            ? h("ul", { class: "space-y-2" }, c.loaded_language.map((t) =>
                h("li", { class: "text-sm" },
                  h("span", { class: "rounded bg-amber-100 px-1 font-medium text-amber-900 dark:bg-amber-900 dark:text-amber-100" }, `»${t.quote}«`),
                  t.verified ? null : h("span", { class: "ml-1 text-[10px] font-semibold text-red-700 dark:text-red-300" }, "(ni najdeno v besedilu)"),
                  h("span", { class: "text-slate-600 dark:text-slate-300" }, ` — ${t.explanation}`))))
            : (c.reasoning ? h("p", { class: "text-xs text-emerald-700 dark:text-emerald-400" }, "Avtor ne uporablja vrednostno obarvanih izrazov; ti so le v citatih virov.") : null)),
        section("Avtorjeva mnenja v novici",
          (c.editorial_statements || []).map((e) =>
            h("blockquote", { class: "border-l-2 border-slate-300 pl-2 text-sm italic text-slate-700 dark:border-slate-600 dark:text-slate-200" }, `»${e}«`))),
        section("Samo v tem mediju",
          (c.unique_facts || []).length
            ? h("ul", { class: "space-y-1" }, c.unique_facts.map((f) =>
                h("li", { class: "flex gap-1.5 text-sm text-slate-700 dark:text-slate-200" },
                  h("span", { class: "text-emerald-600", "aria-hidden": "true" }, "+"), f)))
            : null),
        section("Kar je dodal samo ta medij (zunaj skupnega jedra)",
          (c.shared_core?.own_sentences || []).map((s) =>
            h("blockquote", { class: "border-l-2 border-emerald-400 pl-2 text-sm text-slate-700 dark:border-emerald-700 dark:text-slate-200" }, s))),
        section("Ne navaja, čeprav večina drugih medijev da",
          (c.matrix_gaps || []).length
            ? h("ul", { class: "space-y-1" }, c.matrix_gaps.map((f) =>
                h("li", { class: "flex gap-1.5 text-sm text-slate-700 dark:text-slate-200" },
                  h("span", { class: "text-amber-600", "aria-hidden": "true" }, "–"), f)))
            : null))));
}

const CHECK_STYLE = {
  "Potrjeno": "bg-emerald-100 text-emerald-800 ring-emerald-200 dark:bg-emerald-950 dark:text-emerald-200 dark:ring-emerald-900",
  "Delno potrjeno": "bg-lime-100 text-lime-900 ring-lime-200 dark:bg-lime-950 dark:text-lime-200 dark:ring-lime-900",
  "Vprašljivo": "bg-amber-100 text-amber-900 ring-amber-200 dark:bg-amber-950 dark:text-amber-200 dark:ring-amber-900",
  "V nasprotju z virom": "bg-red-100 text-red-800 ring-red-200 dark:bg-red-950 dark:text-red-200 dark:ring-red-900",
  "Ni preverljivo": "bg-slate-100 text-slate-700 ring-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-700",
};

function sourceLinks(sources) {
  const links = (sources || []).map((src) => ({ ...src, href: safeUrl(src.url) })).filter((src) => src.href);
  if (!links.length) return null;
  return h("div", { class: "flex flex-wrap gap-x-3 gap-y-1 text-xs" },
    h("span", { class: "text-slate-500 dark:text-slate-400" }, "Vir:"),
    links.map((src) => h("a", { href: src.href, target: "_blank", rel: "noopener noreferrer", class: "text-blue-700 underline underline-offset-2 hover:text-blue-900 dark:text-blue-300" }, src.title)));
}

function sourceChecks(story) {
  const checks = story.source_checks || [];
  const context = story.missing_context || [];
  if (!checks.length && !context.length) return null;
  return h("div", { class: "rounded-xl border border-blue-200 bg-blue-50/40 p-4 dark:border-blue-900 dark:bg-blue-950/20" },
    h("h4", { class: "mb-1 text-sm font-semibold" }, "Preverjeno v izvirnih virih"),
    h("p", { class: "mb-3 text-xs text-slate-500 dark:text-slate-400" },
      "Trditve iz člankov, ročno primerjane z izvirnimi dokumenti (sporočila institucij, analize, uradni podatki). Status velja glede na navedeni vir; pri vsaki je povezava, da jo lahko preverite sami."),
    checks.length
      ? h("ul", { class: "space-y-3" }, checks.map((c) => h("li", { class: "rounded-lg bg-white p-3 ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800" },
          h("div", { class: "mb-1 flex flex-wrap items-start justify-between gap-2" },
            h("p", { class: "text-sm font-medium" }, c.claim),
            h("span", { class: `shrink-0 rounded px-1.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${CHECK_STYLE[c.status] || CHECK_STYLE["Ni preverljivo"]}` }, c.status)),
          (c.claimed_by || []).length
            ? h("div", { class: "mb-1 text-[11px] text-slate-500 dark:text-slate-400" }, `Navajajo: ${c.claimed_by.join(", ")}`)
            : null,
          h("p", { class: "mb-1 text-sm text-slate-700 dark:text-slate-200" }, c.finding),
          sourceLinks(c.sources))))
      : null,
    context.length
      ? h("div", { class: "mt-4" },
          h("h5", { class: "mb-2 text-sm font-semibold" }, "Kontekst, ki ga ni navedel noben od primerjanih medijev"),
          h("ul", { class: "space-y-2" }, context.map((c) => h("li", { class: "rounded-lg bg-white p-3 ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800" },
            h("p", { class: "mb-1 text-sm text-slate-700 dark:text-slate-200" }, c.text),
            sourceLinks(c.sources)))))
      : null);
}

function factMark(f, m) {
  if ((f.prominent_in || []).includes(m)) return "prominent";
  return f.media.includes(m) ? "body" : "none";
}

const FACT_MARK = {
  prominent: { sign: "★", label: "v naslovu ali uvodu", cls: "font-bold text-amber-500" },
  body: { sign: "✓", label: "v besedilu", cls: "font-bold text-emerald-600" },
  none: { sign: "–", label: "ne navede", cls: "text-slate-300 dark:text-slate-600" },
};

function factMatrix(story, coverage) {
  const facts = story.fact_matrix || [];
  if (!facts.length) return null;
  const media = coverage.map((c) => c.media_name);
  const hasProminence = facts.some((f) => (f.prominent_in || []).length);
  return h("div", {},
    h("h4", { class: "mb-1 text-sm font-semibold" }, "Kdo navede katero dejstvo"),
    h("p", { class: "mb-2 text-xs text-slate-500 dark:text-slate-400" },
      hasProminence
        ? "★ dejstvo je v naslovu ali uvodu · ✓ v besedilu · – ga ne navede. Število pod imenom medija: koliko ključnih dejstev navede."
        : "✓ medij dejstvo navede · – ga ne navede. Število pod imenom medija: koliko ključnih dejstev navede."),
    h("div", { class: "relative overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-800" },
      h("table", { class: "w-full min-w-[32rem] text-left text-sm" },
        h("thead", { class: "bg-slate-50 text-xs text-slate-500 dark:bg-slate-800/60 dark:text-slate-400" },
          h("tr", {},
            h("th", { class: "px-3 py-2 font-semibold", scope: "col" }, "Dejstvo"),
            media.map((m) => h("th", { class: "px-2 py-2 text-center font-semibold", scope: "col" },
              h("div", {}, m),
              h("div", { class: "font-normal tabular-nums" }, `${facts.filter((f) => f.media.includes(m)).length}/${facts.length}`))))),
        h("tbody", { class: "divide-y divide-slate-100 dark:divide-slate-800" },
          facts.map((f) => h("tr", {},
            h("td", { class: "px-3 py-2 text-slate-700 dark:text-slate-200" }, f.fact),
            media.map((m) => {
              const mark = FACT_MARK[factMark(f, m)];
              return h("td", { class: `px-2 py-2 text-center ${mark.cls}`, title: `${m}: ${mark.label}` },
                h("span", { "aria-hidden": "true" }, mark.sign), h("span", { class: "sr-only" }, mark.label));
            })))))));
}

// Strnjen pregled naslovov: senzacionalizem in nagib naslova; poudarjeno, kjer se naslov razlikuje od besedila.
function headlineStrip(coverage) {
  return h("div", { class: "rounded-xl border border-slate-200 dark:border-slate-800" },
    h("h4", { class: "border-b border-slate-100 px-4 py-2 text-sm font-semibold dark:border-slate-800" }, "Naslovi na en pogled"),
    h("ul", { class: "divide-y divide-slate-100 dark:divide-slate-800" }, coverage.map((c) => {
      const differs = c.headline_leaning && c.body_leaning && c.headline_leaning !== c.body_leaning;
      const s = Number(c.sensationalism_score) || 1;
      return h("li", { class: `grid grid-cols-[1fr_auto] items-start gap-x-3 gap-y-1 px-4 py-2 sm:grid-cols-[8rem_1fr_auto] ${differs ? "bg-amber-50/70 dark:bg-amber-950/30" : ""}` },
        h("span", { class: "text-xs font-semibold text-slate-500 dark:text-slate-400" }, c.media_name),
        h("span", { class: "col-span-2 row-start-2 text-sm leading-snug sm:col-span-1 sm:row-start-auto" }, c.article_title,
          differs ? h("span", { class: "ml-2 whitespace-nowrap rounded bg-amber-200 px-1.5 py-0.5 text-[10px] font-semibold text-amber-900 dark:bg-amber-800 dark:text-amber-100" },
            `naslov ${c.headline_leaning.toLowerCase()} · besedilo ${c.body_leaning.toLowerCase()}`) : null),
        h("span", { class: "flex items-center gap-1.5 justify-self-end" },
          h("span", { class: `rounded px-1.5 py-0.5 text-[11px] font-semibold tabular-nums ${s >= 7 ? "bg-amber-500 text-white" : s >= 4 ? "bg-amber-200 text-amber-900 dark:bg-amber-800 dark:text-amber-100" : "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100"}`, title: "Senzacionalizem naslova (1–10)" }, `${s}/10`),
          leanBadge(c.headline_leaning || c.bias_leaning)));
    })));
}

// Časovnica objav: kdo je poročal prvi in s kakšnim zamikom.
function parseTime(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : { date: d, hasTime: /T\d/.test(iso) };
}

function formatDelay(ms) {
  const min = Math.round(ms / 60000);
  if (min < 60) return `+${min} min`;
  const hours = Math.floor(min / 60);
  if (hours < 48) return `+${hours} h${min % 60 ? ` ${min % 60} min` : ""}`;
  return `+${Math.round(hours / 24)} dni`;
}

function timeline(coverage) {
  const items = coverage.map((c) => ({ c, t: parseTime(c.published) })).filter((x) => x.t)
    .sort((a, b) => a.t.date - b.t.date);
  if (items.length < 2) return null;
  const first = items.find((x) => x.t.hasTime) || items[0];
  return h("div", { class: "rounded-xl border border-slate-200 p-4 dark:border-slate-800" },
    h("h4", { class: "mb-2 text-sm font-semibold" }, "Časovnica objav"),
    h("ol", { class: "relative space-y-2 border-l border-slate-200 pl-4 dark:border-slate-700" }, items.map(({ c, t }) =>
      h("li", { class: "relative text-sm" },
        h("span", { class: `absolute -left-[1.3rem] top-1.5 h-2.5 w-2.5 rounded-full ${leanStyle(c.bias_leaning).dot}`, "aria-hidden": "true" }),
        h("span", { class: "font-medium" }, c.media_name), " ",
        h("span", { class: "text-xs text-slate-500 dark:text-slate-400" },
          t.hasTime
            ? t.date.toLocaleString("sl-SI", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" })
            : `${t.date.toLocaleDateString("sl-SI", { day: "numeric", month: "numeric" })} (ura ni znana)`),
        t.hasTime && first.t.hasTime && t.date > first.t.date
          ? h("span", { class: "ml-2 text-xs tabular-nums text-slate-500 dark:text-slate-400" }, formatDelay(t.date - first.t.date))
          : null))),
    h("p", { class: "mt-2 text-[11px] text-slate-500 dark:text-slate-400" }, "Dejstva, ki so postala znana po objavi članka, se ne štejejo kot zamolčana."));
}

// Primerjava dveh medijev drug ob drugem.
function compareView(story, coverage) {
  if (coverage.length < 2) return h("p", { class: "text-sm text-slate-500" }, "Za primerjavo sta potrebna vsaj dva medija.");
  const names = coverage.map((c) => c.media_name);
  const domestic = coverage.filter((c) => c.category !== "mednarodni");
  const pickA = (domestic[0] || coverage[0]).media_name;
  const pickB = (domestic[domestic.length - 1] || coverage[1]).media_name;
  const state = { a: pickA, b: pickB === pickA ? names.find((n) => n !== pickA) : pickB };
  const body = h("div", {});

  const select = (key, label) => {
    const el = h("select", { class: "rounded-md border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900", "aria-label": label },
      names.map((n) => h("option", { value: n, selected: n === state[key] ? "selected" : null }, n)));
    el.addEventListener("change", () => { state[key] = el.value; draw(); });
    return el;
  };

  const row = (title, render) => h("div", { class: "grid gap-3 border-t border-slate-100 py-3 sm:grid-cols-[9rem_1fr_1fr] dark:border-slate-800" },
    h("div", { class: "text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400" }, title),
    [state.a, state.b].map((n) => h("div", { class: "min-w-0 text-sm text-slate-700 dark:text-slate-200" },
      h("div", { class: "mb-0.5 text-[11px] font-semibold text-slate-400 sm:hidden" }, n),
      render(coverage.find((c) => c.media_name === n)) || h("span", { class: "text-xs text-slate-400" }, "—"))));

  const factDiff = () => {
    const facts = story.fact_matrix || [];
    if (!facts.length) return null;
    const groups = [
      { title: `Samo ${state.a}`, items: facts.filter((f) => f.media.includes(state.a) && !f.media.includes(state.b)) },
      { title: "Oba", items: facts.filter((f) => f.media.includes(state.a) && f.media.includes(state.b)) },
      { title: `Samo ${state.b}`, items: facts.filter((f) => !f.media.includes(state.a) && f.media.includes(state.b)) },
    ];
    return h("div", { class: "border-t border-slate-100 pt-3 dark:border-slate-800" },
      h("div", { class: "mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400" }, "Razlika v dejstvih (★ = v naslovu ali uvodu)"),
      h("div", { class: "grid gap-3 sm:grid-cols-3" }, groups.map((g) =>
        h("div", { class: "rounded-lg bg-slate-50 p-3 dark:bg-slate-800/50" },
          h("div", { class: "mb-1 text-xs font-semibold" }, `${g.title} (${g.items.length})`),
          g.items.length
            ? h("ul", { class: "space-y-1" }, g.items.map((f) => h("li", { class: "text-xs text-slate-700 dark:text-slate-300" },
                [state.a, state.b].filter((n) => (f.prominent_in || []).includes(n)).length ? h("span", { class: "mr-1 text-amber-500", title: "v naslovu ali uvodu" }, "★") : null,
                f.fact)))
            : h("p", { class: "text-xs text-slate-400" }, "—")))));
  };

  const draw = () => {
    body.replaceChildren(
      row("Naslov", (c) => h("div", {}, h("p", { class: "font-medium" }, c.article_title),
        h("div", { class: "mt-1 flex flex-wrap items-center gap-1" }, leanBadge(c.bias_leaning), scoreChip(c), partialBadge(c),
          h("span", { class: "text-[11px] text-slate-500" }, `senzac. ${c.sensationalism_score}/10`)))),
      row("Uvod", (c) => c.lede_focus || null),
      row("Okvir", (c) => c.main_frame ? h("div", {}, h("p", { class: "font-semibold" }, c.main_frame), c.frame_description ? h("p", { class: "mt-0.5 text-xs text-slate-500 dark:text-slate-400" }, c.frame_description) : null) : null),
      row("Glasovi", (c) => h("div", { class: "space-y-1.5" },
        c.sides_represented ? h("span", { class: `rounded px-1.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${SIDES_STYLE[c.sides_represented] || ""}` }, c.sides_represented) : null,
        sideWeights(c),
        (c.voices_heard || []).length ? h("p", { class: "text-xs text-slate-500 dark:text-slate-400" }, c.voices_heard.join(" · ")) : null)),
      row("Obremenjeno besedišče", (c) => (c.loaded_language || []).length
        ? h("ul", { class: "space-y-1" }, c.loaded_language.map((t) => h("li", { class: "text-xs" },
            h("span", { class: "rounded bg-amber-100 px-1 font-medium text-amber-900 dark:bg-amber-900 dark:text-amber-100" }, `»${t.quote}«`),
            h("span", { class: "text-slate-500 dark:text-slate-400" }, ` — ${t.explanation}`))))
        : h("span", { class: "text-xs text-emerald-700 dark:text-emerald-400" }, "Ni zaznano")),
      row("Skupno jedro", (c) => coreBar(c)),
      factDiff());
  };
  draw();

  return h("div", {},
    h("div", { class: "mb-2 flex flex-wrap items-center gap-2 text-sm" }, "Primerjaj", select("a", "Prvi medij"), "z", select("b", "Drugi medij")),
    body);
}

// Zavihki znotraj zgodbe (vzorec WAI-ARIA tabs).
let tabCounter = 0;
function tabs(items) {
  const visible = items.filter((t) => t.content);
  const id = `tabs-${++tabCounter}`;
  const buttons = [];
  const panels = visible.map((t, i) => h("div", { id: `${id}-panel-${i}`, role: "tabpanel", "aria-labelledby": `${id}-tab-${i}`, class: "space-y-5 p-5", hidden: i ? "hidden" : null }, t.content));
  const select = (i, focus) => {
    buttons.forEach((b, j) => {
      b.setAttribute("aria-selected", String(i === j));
      b.tabIndex = i === j ? 0 : -1;
      b.className = `whitespace-nowrap border-b-2 px-3 py-2.5 text-sm font-medium ${i === j ? "border-slate-900 text-slate-900 dark:border-slate-100 dark:text-white" : "border-transparent text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"}`;
      panels[j].hidden = i !== j;
    });
    if (focus) buttons[i].focus();
  };
  visible.forEach((t, i) => {
    const b = h("button", { type: "button", role: "tab", id: `${id}-tab-${i}`, "aria-controls": `${id}-panel-${i}` }, t.label);
    b.addEventListener("click", () => select(i));
    b.addEventListener("keydown", (e) => {
      const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: visible.length - 1 }[e.key];
      if (next === undefined) return;
      e.preventDefault();
      select((next + visible.length) % visible.length, true);
    });
    buttons.push(b);
  });
  select(0);
  return h("div", {},
    h("div", { role: "tablist", "aria-label": "Pogledi zgodbe", class: "flex gap-1 overflow-x-auto border-b border-slate-100 px-3 dark:border-slate-800" }, buttons),
    panels);
}

function quotesCard(coverage) {
  return h("div", { class: "rounded-xl border border-slate-200 p-4 dark:border-slate-800" },
    h("h4", { class: "mb-1 text-sm font-semibold" }, "Dokazi za oceno nagiba"),
    h("p", { class: "mb-3 text-xs text-slate-500 dark:text-slate-400" }, "Dobesedni citati iz člankov, na katerih temelji ocena."),
    h("div", { class: "grid gap-3 md:grid-cols-2" },
      coverage.map((c) => h("figure", { class: `border-l-4 pl-3 ${leanStyle(c.bias_leaning).border}` },
        c.bias_evidence_quotes.map((q) => h("blockquote", { class: "mb-1 text-sm italic text-slate-700 dark:text-slate-200" }, `»${q}«`)),
        h("figcaption", { class: "flex flex-wrap items-center gap-2 text-xs text-slate-500" },
          h("span", { class: "font-semibold text-slate-700 dark:text-slate-300" }, `— ${c.media_name}`),
          leanBadge(c.bias_leaning),
          c.quotes_verified ? null : h("span", { class: "rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800 dark:bg-amber-900 dark:text-amber-100", title: "Citata ni bilo mogoče dobesedno najti v zajetem besedilu članka." }, "citat ni preverjen"))))));
}

function storyCard(story, index, orientation) {
  // Mednarodni vir je vedno prvi stolpec, nato po natančnem nagibu od leve proti desni.
  const coverage = [...story.coverage_comparison].sort((a, b) =>
    (b.category === "mednarodni") - (a.category === "mednarodni") || leanScore(a) - leanScore(b));

  return h("section", { id: story.id, class: "scroll-mt-24 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900" },
    h("div", { class: "border-b border-slate-100 p-5 dark:border-slate-800" },
      h("div", { class: "mb-2 flex flex-wrap items-center gap-2 text-xs" },
        h("span", { class: "font-semibold text-slate-400" }, `#${index + 1}`),
        h("span", { class: "rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300" }, plural(coverage.length, WORDS.source)),
        story.has_international_source
          ? h("span", { class: "rounded-full bg-emerald-100 px-2 py-0.5 font-medium text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100" }, "Z mednarodnim sidrom")
          : h("span", { class: "rounded-full bg-amber-100 px-2 py-0.5 font-medium text-amber-800 dark:bg-amber-900 dark:text-amber-100" }, "Brez mednarodnega vira"),
        story.blind_analysis
          ? h("span", { class: "rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300", title: "Model je ocenjeval besedila brez imen medijev (MEDIJ_A, MEDIJ_B …)." }, "Slepa ocena")
          : null),
      h("h3", { class: "text-xl font-bold leading-tight sm:text-2xl" }, story.topic_title),
      (story.not_covered_by || []).length
        ? h("p", { class: "mt-1 text-xs text-slate-500 dark:text-slate-400" }, `Niso poročali (preverjeno): ${story.not_covered_by.join(", ")}`)
        : null,
      h("p", { class: "mt-2 text-sm leading-relaxed text-slate-600 dark:text-slate-300" }, story.neutral_summary),
      story.context
        ? h("p", { class: "mt-2 text-sm leading-relaxed text-slate-500 dark:text-slate-400" }, h("span", { class: "font-semibold" }, "Ozadje: "), story.context)
        : null,
      h("div", { class: "mt-4" },
        h("div", { class: "mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500" }, "Pokritost po nagibu"),
        distributionBar(coverage),
        blindspot(story, orientation),
        spectrum(coverage))),

    tabs([
      { label: "Pregled", content: [
        h("div", { class: "rounded-xl bg-slate-900 p-4 text-slate-100 dark:bg-slate-800" },
          h("div", { class: "mb-1 text-xs font-semibold uppercase tracking-wide text-emerald-300" }, story.has_international_source ? "Mednarodno izhodišče dejstev" : "Izhodišče dejstev"),
          h("p", { class: "text-sm leading-relaxed" }, story.international_baseline)),
        (story.key_differences || []).length
          ? h("div", { class: "rounded-xl border border-slate-200 p-4 dark:border-slate-800" },
              h("h4", { class: "mb-2 text-sm font-semibold" }, "Ključne razlike v poročanju"),
              h("ol", { class: "list-decimal space-y-1.5 pl-5 text-sm text-slate-700 dark:text-slate-200" },
                story.key_differences.map((d) => h("li", {}, d))))
          : null,
        headlineStrip(coverage),
        h("div", {},
          h("h4", { class: "mb-3 text-sm font-semibold" }, "Kdo poroča in kaj je zamolčal"),
          h("div", { class: "grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" }, coverage.map(coverageColumn))),
        timeline(coverage),
      ].filter(Boolean) },
      { label: "Matrika dejstev", content: factMatrix(story, coverage) },
      { label: "Primerjaj dva medija", content: coverage.length >= 2 ? compareView(story, coverage) : null },
      { label: "Podrobno po medijih", content: [
        quotesCard(coverage),
        coverage.some(hasDetail) ? h("div", { class: "space-y-3" }, coverage.filter(hasDetail).map(detailCard)) : null,
      ].filter(Boolean) },
      { label: "Preverjanje virov", content: sourceChecks(story) },
    ]));
}

function renderError(message) {
  document.getElementById("stories").replaceChildren(
    h("div", { class: "rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-100", role: "alert" },
      h("p", { class: "font-semibold" }, "Analize ni bilo mogoče naložiti."),
      h("p", { class: "mt-1" }, message),
      h("p", { class: "mt-2" }, "Zaženite ", h("code", { class: "font-mono" }, "python backend/main.py"),
        " in strežnik v korenu repozitorija: ", h("code", { class: "font-mono" }, "python -m http.server 8000"),
        ", nato odprite ", h("code", { class: "font-mono" }, "http://localhost:8000/frontend/"), ".")));
}

// Mapa s podatki: lokalni strežnik v korenu repozitorija (../data/) ali kopija ob frontendu (data/).
let dataBase = null;

async function fetchJson(path) {
  const bases = dataBase ? [dataBase] : DATA_BASES;
  let lastError = "";
  for (const base of bases) {
    try {
      const res = await fetch(base + path, { cache: "no-store" });
      if (res.ok) {
        dataBase = base;
        return await res.json();
      }
      lastError = `${base}${path}: HTTP ${res.status}`;
    } catch (err) {
      lastError = `${base}${path}: ${err.message}`;
    }
  }
  throw new Error(lastError);
}

function formatDay(isoDate) {
  const d = new Date(`${isoDate}T12:00:00`);
  return Number.isNaN(d.getTime()) ? isoDate : d.toLocaleDateString("sl-SI", { day: "numeric", month: "long", year: "numeric" });
}

function renderDates(index, current) {
  if (!index || index.length < 2) return;
  document.getElementById("dates").replaceChildren(
    h("div", { class: "flex flex-wrap items-center gap-2" },
      h("span", { class: "text-xs font-semibold uppercase tracking-wide text-slate-500" }, "Arhiv"),
      index.map((e) => h("a", {
        href: `?datum=${encodeURIComponent(e.date)}`,
        "aria-current": e.date === current ? "page" : null,
        class: e.date === current
          ? "rounded-full bg-slate-900 px-3 py-1 text-xs font-medium text-white dark:bg-slate-100 dark:text-slate-900"
          : "rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-700 hover:border-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200",
      }, `${formatDay(e.date)} · ${plural(e.stories, WORDS.story)}`))));
}

async function init() {
  renderLegend();
  const requested = new URLSearchParams(location.search).get("datum");
  let index = null;
  try {
    index = await fetchJson("archive/index.json");
  } catch {
    // arhiva še ni – prikažemo samo najnovejšo analizo
  }
  const entry = index && requested ? index.find((e) => e.date === requested) : null;

  let data;
  try {
    data = await fetchJson(entry ? `archive/${entry.date}.json` : "daily_analysis.json");
  } catch (err) {
    renderError(err.message);
    return;
  }
  if (!Array.isArray(data.stories)) {
    renderError("Datoteka nima pričakovane strukture (manjka seznam »stories«).");
    return;
  }
  const currentDate = entry ? entry.date : index?.[0]?.date;
  data.date = currentDate;
  // Celoten arhiv za profil skozi čas in usmerjenost medijev (slepe pege)
  const archiveDays = index
    ? (await Promise.all(index.filter((e) => !e.is_mock).map((e) => e.date === currentDate
        ? Promise.resolve(data)
        : fetchJson(`archive/${e.date}.json`).then((d) => ({ ...d, date: e.date })).catch(() => null)))).filter(Boolean)
    : [data];
  renderDates(index, currentDate);
  renderMeta(data);
  renderProfile(data, archiveDays);
  renderToc(data);
  const orientation = outletOrientation(archiveDays);
  const container = document.getElementById("stories");
  container.replaceChildren(...(data.stories.length
    ? data.stories.map((s, i) => storyCard(s, i, orientation))
    : [h("p", { class: "py-16 text-center text-slate-500" }, "Danes ni zgodb, o katerih bi poročalo več medijev.")]));
}

init();
