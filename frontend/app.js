"use strict";

// Kandidatne poti do podatkov: lokalni strežnik v korenu repozitorija ali kopija ob frontendu.
const DATA_URLS = ["../data/daily_analysis.json", "data/daily_analysis.json"];

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
        h("span", { class: `h-2.5 w-2.5 rounded-full ${leanStyle(l).dot}`, "aria-hidden": "true" }), l))));
}

// Povprečje po medijih čez vse zgodbe dneva.
function renderProfile(data) {
  const byMedia = new Map();
  for (const story of data.stories) {
    for (const c of story.coverage_comparison) {
      const entry = byMedia.get(c.media_name) || { category: c.category, scores: [], leanings: [] };
      entry.scores.push(c.sensationalism_score);
      entry.leanings.push(c.bias_leaning);
      byMedia.set(c.media_name, entry);
    }
  }
  if (!byMedia.size) return;

  const rows = [...byMedia.entries()].map(([name, e]) => {
    const avg = e.scores.reduce((a, b) => a + b, 0) / e.scores.length;
    const avgLean = e.leanings.reduce((a, l) => a + LEANINGS.indexOf(l), 0) / e.leanings.length;
    return { name, category: e.category, avg, avgLean, count: e.scores.length, leanings: e.leanings };
  }).sort((a, b) => a.avgLean - b.avgLean);

  document.getElementById("profile").replaceChildren(
    h("div", { class: "rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900" },
      h("h2", { class: "mb-1 text-sm font-semibold uppercase tracking-wide text-slate-500" }, "Današnji profil medijev"),
      h("p", { class: "mb-4 text-xs text-slate-500 dark:text-slate-400" }, "Povprečje ocen vseh analiziranih člankov dneva. Položaj na lestvici je povprečni nagib."),
      h("div", { class: "space-y-3" }, rows.map((r) =>
        h("div", { class: "grid grid-cols-1 items-center gap-2 sm:grid-cols-[10rem_1fr_9rem]" },
          h("div", {},
            h("div", { class: "text-sm font-medium" }, r.name),
            h("div", { class: "text-[11px] text-slate-500" }, `${CATEGORY_LABEL[r.category] || r.category} · ${plural(r.count, WORDS.article)}`)),
          h("div", { class: "relative h-2 rounded-full bg-gradient-to-r from-red-500 via-slate-300 to-blue-500 dark:via-slate-600", title: `Povprečni nagib: ${LEANINGS[Math.round(r.avgLean)]}` },
            h("span", {
              class: "absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-slate-900 shadow dark:border-slate-900 dark:bg-white",
              style: `left:${(r.avgLean / 4) * 100}%`,
            })),
          h("div", { class: "text-xs text-slate-600 dark:text-slate-300 sm:text-right" },
            "Senzac. ", h("span", { class: "font-semibold tabular-nums" }, r.avg.toFixed(1)), "/10"))))));
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

function voicesBlock(c) {
  const voices = c.voices_heard || [];
  if (!voices.length && !c.sides_represented) return null;
  return h("div", { class: "space-y-1" },
    h("div", { class: "flex flex-wrap items-center justify-between gap-1 text-xs" },
      h("span", { class: "text-slate-500 dark:text-slate-400" }, "Kdo dobi besedo"),
      c.sides_represented
        ? h("span", { class: `rounded px-1.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${SIDES_STYLE[c.sides_represented] || SIDES_STYLE["Obe strani"]}` }, c.sides_represented)
        : null),
    voices.length
      ? h("div", { class: "flex flex-wrap gap-1" }, voices.map((v) =>
          h("span", { class: "rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-700 dark:bg-slate-800 dark:text-slate-300" }, v)))
      : null);
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
      leanBadge(c.bias_leaning)),
    url
      ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer", class: "text-sm font-medium leading-snug text-slate-800 underline decoration-slate-300 underline-offset-2 hover:decoration-slate-700 dark:text-slate-100 dark:decoration-slate-600" }, c.article_title)
      : h("p", { class: "text-sm font-medium leading-snug" }, c.article_title),
    sensationalismMeter(c.sensationalism_score),
    voicesBlock(c),
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

function storyCard(story, index) {
  // Mednarodni vir je vedno prvi stolpec, nato po nagibu od leve proti desni.
  const coverage = [...story.coverage_comparison].sort((a, b) =>
    (b.category === "mednarodni") - (a.category === "mednarodni") ||
    LEANINGS.indexOf(a.bias_leaning) - LEANINGS.indexOf(b.bias_leaning));

  return h("section", { id: story.id, class: "scroll-mt-24 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900" },
    h("div", { class: "border-b border-slate-100 p-5 dark:border-slate-800" },
      h("div", { class: "mb-2 flex flex-wrap items-center gap-2 text-xs" },
        h("span", { class: "font-semibold text-slate-400" }, `#${index + 1}`),
        h("span", { class: "rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300" }, plural(coverage.length, WORDS.source)),
        story.has_international_source
          ? h("span", { class: "rounded-full bg-emerald-100 px-2 py-0.5 font-medium text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100" }, "Z mednarodnim sidrom")
          : h("span", { class: "rounded-full bg-amber-100 px-2 py-0.5 font-medium text-amber-800 dark:bg-amber-900 dark:text-amber-100" }, "Brez mednarodnega vira")),
      h("h3", { class: "text-xl font-bold leading-tight sm:text-2xl" }, story.topic_title),
      h("p", { class: "mt-2 text-sm leading-relaxed text-slate-600 dark:text-slate-300" }, story.neutral_summary),
      h("div", { class: "mt-4" },
        h("div", { class: "mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500" }, "Pokritost po nagibu"),
        distributionBar(coverage),
        spectrum(coverage))),

    h("div", { class: "space-y-5 p-5" },
      h("div", { class: "rounded-xl bg-slate-900 p-4 text-slate-100 dark:bg-slate-800" },
        h("div", { class: "mb-1 text-xs font-semibold uppercase tracking-wide text-emerald-300" }, "Mednarodno izhodišče dejstev"),
        h("p", { class: "text-sm leading-relaxed" }, story.international_baseline)),
      h("div", {},
        h("h4", { class: "mb-3 text-sm font-semibold" }, "Kdo poroča in kaj je zamolčal"),
        h("div", { class: "grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" }, coverage.map(coverageColumn))),
      quotesCard(coverage)));
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

async function loadData() {
  let lastError = "";
  for (const url of DATA_URLS) {
    try {
      const res = await fetch(url, { cache: "no-store" });
      if (res.ok) return await res.json();
      lastError = `${url}: HTTP ${res.status}`;
    } catch (err) {
      lastError = `${url}: ${err.message}`;
    }
  }
  throw new Error(lastError);
}

async function init() {
  renderLegend();
  let data;
  try {
    data = await loadData();
  } catch (err) {
    renderError(err.message);
    return;
  }
  if (!Array.isArray(data.stories)) {
    renderError("Datoteka nima pričakovane strukture (manjka seznam »stories«).");
    return;
  }
  renderMeta(data);
  renderProfile(data);
  renderToc(data);
  const container = document.getElementById("stories");
  container.replaceChildren(...(data.stories.length
    ? data.stories.map(storyCard)
    : [h("p", { class: "py-16 text-center text-slate-500" }, "Danes ni zgodb, o katerih bi poročalo več medijev.")]));
}

init();
