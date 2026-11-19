"""Združevanje novic v skupne zgodbe in analiza pristranosti z Gemini API.

Vsak odgovor modela je omejen s Pydantic JSON shemo (structured output) in
ponovno validiran lokalno. Citati, ki naj utemeljujejo oceno pristranosti,
so preverjeni proti dejanskemu besedilu članka.
"""
from __future__ import annotations

import itertools
import json
import logging
import math
import os
import random
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from scraper import SOURCES, Article

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
MAX_STORIES = 5
MAX_BODY_CHARS = 15000
PARTIAL_MIN_WORDS = 150  # krajše besedilo je verjetno odrezano ali za plačljivim zidom

BiasLeaning = Literal["Levo", "Sredina-Levo", "Sredina", "Sredina-Desno", "Desno"]
SidesRepresented = Literal["Obe strani", "Pretežno ena stran", "Samo ena stran"]
Confidence = Literal["Visoka", "Srednja", "Nizka"]

# Agencije in mediji, na katere se članki pogosto sklicujejo (za samodejno zaznavo virov)
KNOWN_SOURCES = [
    "STA", "MMC", "AFP", "Reuters", "AP", "Bloomberg", "CNN", "CBS", "CNBC", "BBC", "Fox News",
    "New York Times", "New York Post", "Financial Times", "Politico", "Dnevnik",
    "Siol", "24ur", "N1", "Nova24TV", "Mladina", "Žurnal24", "Svet24", "Demokracija", "Tanjug", "Hina",
    "Info360", "Portal24", "NaDlani",
]


# --------------------------------------------------------------------------- #
# Sheme
# --------------------------------------------------------------------------- #
class LoadedTerm(BaseModel):
    quote: str = Field(description="DOBESEDNA beseda ali besedna zveza iz avtorjevega besedila (ne iz citata vira).")
    explanation: str = Field(description="Zakaj je izraz vrednostno obarvan in kaj sporoča bralcu.")
    verified: bool = Field(default=False, description="Izpolni sistem: ali je izraz najden v besedilu.")


class FactPresence(BaseModel):
    fact: str = Field(description="Ključno dejstvo zgodbe, kratko in nevtralno.")
    media: list[str] = Field(description="Imena medijev, ki to dejstvo navedejo (kjerkoli v članku).")
    prominent_in: list[str] = Field(
        default_factory=list,
        description="Podmnožica »media«: mediji, ki dejstvo postavijo v naslov ali uvod (prvi odstavek).",
    )


class SideWeight(BaseModel):
    side: str = Field(description="Stran v sporu, npr. »vlada«, »opozicija«, »ZZZS«, »sindikat«.")
    share_percent: int = Field(ge=0, le=100, description="Okviren delež besedila, namenjen tej strani.")
    direct_quotes: int = Field(ge=0, description="Število neposrednih citatov te strani.")
    in_lede: bool = Field(description="Ali stran dobi besedo v naslovu ali uvodu.")


CheckStatus = Literal["Potrjeno", "Delno potrjeno", "Vprašljivo", "V nasprotju z virom", "Ni preverljivo"]


class SourceLink(BaseModel):
    title: str
    url: str


class SourceCheck(BaseModel):
    """Trditev iz člankov, preverjena v izvirnem dokumentu (ročno, ne z jezikovnim modelom)."""
    claim: str
    claimed_by: list[str] = Field(default_factory=list, description="Mediji, ki trditev navedejo.")
    status: CheckStatus
    finding: str
    sources: list[SourceLink] = Field(default_factory=list)


class ContextItem(BaseModel):
    """Dejstvo iz izvirnih virov, ki ga ni navedel noben od primerjanih medijev."""
    text: str
    sources: list[SourceLink] = Field(default_factory=list)


class TextOverlap(BaseModel):
    media: str
    percent: int


class SharedCore(BaseModel):
    """Koliko avtorskega besedila (brez citatov) si medij deli z vsaj enim drugim medijem iste zgodbe."""
    shared_percent: int
    own_percent: int
    own_sentences: list[str] = Field(default_factory=list, description="Najdaljša stavka, ki ju ima samo ta medij.")


class MediaCoverage(BaseModel):
    media_name: str = Field(description="Ime medija, natančno kot je podano v vhodu.")
    article_title: str = Field(description="Naslov članka tega medija.")
    article_url: str = Field(description="URL članka, natančno kot je podan v vhodu.")
    sensationalism_score: int = Field(
        ge=1, le=10,
        description="Senzacionalizem NASLOVA: 1 = popolnoma nevtralen, 10 = klikabejt/čustven.",
    )
    bias_leaning: BiasLeaning = Field(description="Politični/ideološki nagib TEGA članka.")
    bias_evidence_quotes: list[str] = Field(
        min_length=1, max_length=2,
        description="1–2 DOBESEDNA citata iz besedila članka, ki utemeljujeta oceno nagiba.",
    )
    omitted_facts: list[str] = Field(
        description="Dejstva iz mednarodnega vira, ki jih ta medij ni navedel ali jih je minimiziral.",
    )
    voices_heard: list[str] = Field(
        default_factory=list,
        description="Osebe ali institucije, ki v članku dobijo besedo (neposredno ali posredno citirane).",
    )
    sides_represented: SidesRepresented = Field(
        default="Obe strani",
        description="Ali članek predstavi stališča vseh vpletenih strani ali le ene.",
    )
    factual_errors: list[str] = Field(
        default_factory=list,
        description="Trditve v članku, ki so v nasprotju z drugimi viri ali z istim člankom.",
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Pomembne opombe k oceni (npr. delno dostopno besedilo, drugačen datum objave).",
    )
    headline_leaning: BiasLeaning = Field(default="Sredina", description="Nagib samega naslova.")
    body_leaning: BiasLeaning = Field(default="Sredina", description="Nagib besedila brez naslova.")
    headline_analysis: str = Field(
        default="", description="Katere tehnike uporablja naslov (vprašanje, citat, pretiravanje …) in s kakšnim učinkom."
    )
    main_frame: str = Field(
        default="",
        description="Prevladujoči okvir: npr. konflikt, odgovornost, gospodarske posledice, človeška zgodba, "
        "škandal, moralnost, uradna izjava.",
    )
    frame_description: str = Field(default="", description="Kako je okvir uresničen v članku.")
    lede_focus: str = Field(default="", description="Kaj članek postavi v uvod (prvi odstavek) in kaj s tem poudari.")
    loaded_language: list[LoadedTerm] = Field(
        default_factory=list, description="Vrednostno obarvani izrazi AVTORJA članka (ne citiranih virov)."
    )
    editorial_statements: list[str] = Field(
        default_factory=list,
        description="DOBESEDNI stavki, v katerih avtor izraža lastno mnenje ali sodbo, ne poročanja.",
    )
    unique_facts: list[str] = Field(
        default_factory=list, description="Dejstva, ki jih navaja samo ta medij med primerjanimi."
    )
    reasoning: str = Field(default="", description="Utemeljitev ocene nagiba v 2–4 stavkih.")
    confidence: Confidence = Field(default="Srednja", description="Zanesljivost ocene.")
    side_weights: list[SideWeight] = Field(
        default_factory=list,
        description="Za vsako stran v sporu: delež prostora, število citatov in ali je v uvodu. Deleži skupaj ~100.",
    )
    lean_score: float | None = Field(
        default=None, ge=-3, le=3,
        description="Nagib na lestvici od -3 (levo) do +3 (desno); 0 = povsem uravnoteženo. "
        "Določa bias_leaning: |x| < 0,5 Sredina, do ±2 Sredina-Levo/-Desno, sicer Levo/Desno.",
    )


class StoryAnalysis(BaseModel):
    topic_title: str = Field(description="Kratek, nevtralen naslov dogodka v slovenščini.")
    international_baseline: str = Field(
        description="Kratek povzetek ključnih dejstev po navedbah mednarodnega vira."
    )
    coverage_comparison: list[MediaCoverage]
    neutral_summary: str = Field(description="Kratek nevtralen povzetek celotne zgodbe.")
    context: str = Field(default="", description="Ozadje, potrebno za razumevanje zgodbe (2–4 stavki).")
    key_differences: list[str] = Field(
        default_factory=list, description="3–6 najpomembnejših razlik v poročanju med mediji."
    )
    fact_matrix: list[FactPresence] = Field(
        default_factory=list, description="6–12 ključnih dejstev in kateri mediji jih navedejo."
    )


class StoryCluster(BaseModel):
    topic_label: str = Field(description="Delovni naslov teme.")
    article_ids: list[str] = Field(description="ID-ji člankov, ki poročajo o ISTEM dogodku.")


class ClusterResult(BaseModel):
    stories: list[StoryCluster]


# Izhodni modeli (dodatna polja, ki jih model ne generira)
class CoverageReport(MediaCoverage):
    category: str = ""
    quotes_verified: bool = Field(
        default=False, description="Ali so vsi citati dobesedno najdeni v besedilu članka."
    )
    published: str | None = None
    word_count: int = 0
    cited_sources: list[str] = Field(default_factory=list, description="Agencije in mediji, navedeni v besedilu.")
    text_overlap: list[TextOverlap] = Field(
        default_factory=list, description="Delež avtorskega besedila (brez citatov), enakega besedilu drugega medija."
    )
    shared_core: SharedCore | None = None
    partial_text: bool = Field(default=False, description="Besedilo je kratko, odrezano ali za plačljivim zidom.")
    matrix_gaps: list[str] = Field(
        default_factory=list,
        description="Dejstva iz matrike, ki jih navaja večina drugih medijev, ta pa ne (izračunano).",
    )


class StoryReport(StoryAnalysis):
    id: str
    coverage_comparison: list[CoverageReport]
    has_international_source: bool = False
    # Preverjanje v izvirnih virih se ne generira z modelom; doda ga manual_analysis.py
    source_checks: list[SourceCheck] = Field(default_factory=list)
    missing_context: list[ContextItem] = Field(default_factory=list)
    not_covered_by: list[str] = Field(
        default_factory=list, description="Preverjeni mediji, ki o dogodku niso objavili članka."
    )
    blind_analysis: bool = Field(default=False, description="Model ni videl imen medijev (MEDIJ_A, MEDIJ_B …).")


class SourceInfo(BaseModel):
    name: str
    category: str
    url: str


class DailyAnalysis(BaseModel):
    generated_at: str
    model: str
    is_mock: bool
    sources: list[SourceInfo]
    articles_scraped: int = 0
    stories: list[StoryReport]


# --------------------------------------------------------------------------- #
# Gemini pomožne funkcije
# --------------------------------------------------------------------------- #
ANALYSIS_RULES = """Si strog, nepristranski medijski analitik. Pravila:
1. Ocene pristranosti (bias_leaning) MORAJO temeljiti IZKLJUČNO na konkretnih citatih in izbiri
   besedišča v podanem besedilu članka – nikoli na splošnem slovesu medija ali pavšalnih sodbah.
2. bias_evidence_quotes so DOBESEDNI izseki iz podanega besedila (kopiraj znak za znakom,
   brez prevajanja, brez parafraziranja, največ ~30 besed na citat).
3. Če besedilo ne vsebuje vrednostno obarvanega besedišča, je ocena "Sredina".
4. sensationalism_score ocenjuje samo naslov: čustvene besede, pretiravanje, vprašalni/klikabejt
   naslovi, velike črke in klicaji zvišujejo oceno.
5. omitted_facts navaja samo dejstva, ki jih mednarodni (referenčni) vir dejansko navaja, ta medij pa ne.
   Če mednarodnega vira ni, primerjaj z dejstvi, ki jih navaja večina drugih virov, in to
   povej v international_baseline. Prazen seznam je dovoljen. Vsako dejstvo v omitted_facts mora
   biti tudi v fact_matrix (brez tega medija). Dejstvo, ki se je zgodilo ali je bilo znano šele PO
   času objave članka (OBJAVLJENO), ni zamolčano – takega ne navajaj.
6. Mediji so anonimizirani (MEDIJ_A, MEDIJ_B …). media_name prepiši natančno iz vhoda; ne ugibaj,
   kateri medij je kateri, in ocene ne opiraj na domnevno identiteto.
7. voices_heard našteje, kdo v članku dobi besedo. side_weights za vsako stran v sporu oceni delež
   prostora, število neposrednih citatov in ali je v uvodu; navedi tudi strani, ki so v članku omenjene
   ali kritizirane, a ne dobijo besede (delež 0). sides_represented: "Samo ena stran", če besedo dobi le
   ena stran; "Pretežno ena stran", če katera od strani ostane brez besede, ena dobi 75 % ali več prostora
   ali sama uvod (pri 65 % ali več); sicer "Obe strani". To ocenjuj ločeno od besedišča.
8. factual_errors navaja samo trditve, ki so v nasprotju z drugimi viri ali z istim člankom.
9. headline_leaning in body_leaning ocenjuj ločeno: naslov je lahko obarvan, besedilo pa ne.
10. loaded_language in editorial_statements vsebujeta SAMO avtorjevo besedilo, nikoli izjav
   citiranih oseb (citat politika ni obarvanost medija). Vse prepiši dobesedno.
11. main_frame, lede_focus in unique_facts opisujejo izbiro poudarkov: kaj je v uvodu, kaj je
   samo v tem mediju, katera zgodba se pripoveduje.
12. fact_matrix: 6–12 ključnih dejstev zgodbe in za vsakega imena medijev, ki ga navedejo; v
   prominent_in tiste, ki ga postavijo v naslov ali uvod.
   key_differences: 3–6 najpomembnejših razlik med mediji.
13. lean_score določi vedno, tudi za sredinske članke: tudi uravnotežen članek se lahko rahlo nagiba
   z izbiro sogovornikov (kdo dobi več prostora, kdo uvod), dejstev (kaj izpusti) in naslova. Na slovenski
   politični osi je levo sedanja opozicija (Svoboda, Levica, SD), sindikati in levo usmerjene NVO, desno
   sedanja koalicija (SDS, NSi, Demokrati …). 0 dodeli samo, če sta strani res enakovredni ali politične
   razsežnosti ni. Vsak odklon od 0 utemelji v reasoning s konkretnim dokazom.
14. reasoning v 2–4 stavkih poveže oceno s konkretnimi dokazi; confidence je "Nizka", če je
   besedilo kratko, delno dostopno (oznaka DELNO BESEDILO) ali so dokazi šibki.
15. Vsa besedila (razen citatov) piši v slovenščini.
"""


def _client():
    from google import genai

    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def _generate(client, model: str, prompt: str, schema: type[BaseModel], retries: int = 3):
    from google.genai import types

    config = types.GenerateContentConfig(
        system_instruction=ANALYSIS_RULES,
        response_mime_type="application/json",
        response_schema=schema,
        temperature=0.2,
    )
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            response = client.models.generate_content(model=model, contents=prompt, config=config)
            # Strogo lokalno validiramo tudi, če je SDK že razčlenil odgovor.
            return schema.model_validate_json(response.text)
        except (ValidationError, json.JSONDecodeError) as exc:
            log.warning("Neveljaven JSON odgovor (poskus %d): %s", attempt + 1, exc)
            last_exc = exc
        except Exception as exc:  # omrežne napake, kvote
            log.warning("Gemini napaka (poskus %d): %s", attempt + 1, exc)
            last_exc = exc
        time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"Gemini klic ni uspel: {last_exc}")


# --------------------------------------------------------------------------- #
# Združevanje v zgodbe
# --------------------------------------------------------------------------- #
_STOP = set(
    "in je v na za se z s da so ki od po pri bo ter tudi o iz the a an of to in on for and is are".split()
)


def _tokens(text: str) -> set[str]:
    words = re.findall(r"\w+", text.lower())
    # grobo "korenjenje" za slovenske sklone: prvih 5 znakov
    return {w[:5] for w in words if len(w) > 3 and w not in _STOP}


def cluster_lexical(articles: list[Article], max_stories: int = MAX_STORIES) -> list[list[Article]]:
    """Rezervno združevanje po prekrivanju besed v naslovu in povzetku (brez LLM)."""
    toks = {a.id: _tokens(f"{a.title} {a.summary[:300]}") for a in articles}
    clusters: list[list[Article]] = []
    for article in articles:
        for cluster in clusters:
            seed = toks[cluster[0].id]
            overlap = len(seed & toks[article.id]) / max(1, min(len(seed), len(toks[article.id])))
            if overlap >= 0.35 and article.source not in {a.source for a in cluster}:
                cluster.append(article)
                break
        else:
            clusters.append([article])
    multi = [c for c in clusters if len({a.source for a in c}) >= 2]
    multi.sort(key=lambda c: len(c), reverse=True)
    return multi[:max_stories]


def cluster_with_gemini(
    client, model: str, articles: list[Article], max_stories: int = MAX_STORIES
) -> list[list[Article]]:
    by_id = {a.id: a for a in articles}
    listing = "\n".join(
        f"[{a.id}] ({a.source}, {a.language}) {a.title} — {a.summary[:200]}" for a in articles
    )
    prompt = f"""Spodaj so današnji članki iz slovenskih in mednarodnih medijev (različni jeziki).
Poišči do {max_stories} najpomembnejših dogodkov dneva, o katerih poroča VSAJ 2 različna medija.
Prednost imajo dogodki, o katerih poroča tudi mednarodni vir (BBC World).
Za vsak dogodek naštej ID-je člankov, ki govorijo o ISTEM konkretnem dogodku (ne le o podobni temi).
Iz vsakega medija izberi največ en članek na dogodek.

ČLANKI:
{listing}"""
    result = _generate(client, model, prompt, ClusterResult)

    clusters: list[list[Article]] = []
    for story in result.stories:
        seen_sources: set[str] = set()
        cluster = []
        for aid in story.article_ids:
            a = by_id.get(aid.strip("[] "))
            if a and a.source not in seen_sources:
                cluster.append(a)
                seen_sources.add(a.source)
        if len(seen_sources) >= 2:
            clusters.append(cluster)
    return clusters[:max_stories]


# --------------------------------------------------------------------------- #
# Analiza zgodbe
# --------------------------------------------------------------------------- #
def _normalize(text: str) -> str:
    text = re.sub(r"[„“”«»\"]", '"', text)
    text = re.sub(r"[‘’‚`]", "'", text)
    text = re.sub(r"[–—]", "-", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def quote_in_text(quote: str, body: str) -> bool:
    return _normalize(quote).strip("\"'. »«") in _normalize(body)


_QUOTED = re.compile(r"[„“”\"»«][^„“”\"»«]{0,600}[„“”\"»«]")
_WORDS = re.compile(r"\w+")


def _shingles(text: str, n: int = 6) -> set[tuple[str, ...]]:
    """n-gramska množica avtorskega besedila; citirane izjave so izločene."""
    words = _WORDS.findall(_QUOTED.sub(" ", text).lower())
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def text_overlaps(article: Article, others: list[Article]) -> list[TextOverlap]:
    """Koliko avtorskega besedila članka je enakega besedilu drugih člankov iste zgodbe."""
    own = _shingles(article.body)
    result = []
    for other in others:
        if other.id == article.id or other.language != article.language or not own:
            continue
        shared = len(own & _shingles(other.body))
        percent = round(100 * shared / len(own))
        if percent >= 5:
            result.append(TextOverlap(media=other.source, percent=percent))
    return sorted(result, key=lambda o: -o.percent)


def cited_sources(text: str, own_name: str) -> list[str]:
    # dovoli slovenske sklonske končnice (Reutersa, AFP-ja, CNN-a)
    found = [s for s in KNOWN_SOURCES if re.search(rf"(?<!\w){re.escape(s)}(?:-?[a-zčšž]{{0,3}})(?!\w)", text)]
    return [s for s in found if s.lower() not in own_name.lower()]


def verify_quotes(quotes: list[str], body: str) -> tuple[list[str], bool]:
    """Vrne citate, ki dobesedno obstajajo v besedilu; drugi element pove, ali so preverjeni vsi."""
    norm_body = _normalize(body)
    verified = [q for q in quotes if _normalize(q).strip("\"'. ") in norm_body]
    if verified:
        return verified, len(verified) == len(quotes)
    return quotes, False


# --------------------------------------------------------------------------- #
# Slepo ocenjevanje: model vidi MEDIJ_A, MEDIJ_B … namesto imen medijev
# --------------------------------------------------------------------------- #
# Dodatne oblike imen, pod katerimi se medij omenja v lastnih in tujih člankih
NAME_VARIANTS = {
    "MMC RTV SLO": ["MMC RTV SLO", "RTV SLO", "RTV Slovenija", "RTVSLO.si", "rtvslo.si", "MMC"],
    "24ur": ["24ur.com", "24UR", "24ur"],
    "N1": ["n1info.si", "N1 Slovenija", "N1"],
    "Nova24TV": ["nova24tv.si", "Nova24TV", "Nova24 TV", "Nova24"],
    "Mladina": ["mladina.si", "Mladina", "Mladine", "Mladini"],
    "BBC World": ["BBC News", "BBC World", "bbc.com", "BBC"],
    "Žurnal24": ["zurnal24.si", "Žurnal24", "Žurnal 24"],
    "Svet24": ["svet24.si", "Svet24"],
    "Delo": ["delo.si", "Delo", "Dela", "Delu"],
    "Info360": ["info360.si", "Info360"],
    "Portal24": ["portal24.si", "Portal24"],
}


def _alias_letters(n: int) -> list[str]:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return [f"MEDIJ_{letters[i]}" if i < 26 else f"MEDIJ_{i + 1}" for i in range(n)]


def make_aliases(cluster: list[Article], index: int) -> dict[str, str]:
    """Psevdonim za vsak medij v zgodbi (alias -> ime medija). Vrstni red je premešan, a ponovljiv."""
    names = list(dict.fromkeys(a.source for a in cluster))
    random.Random(f"story-{index}").shuffle(names)
    return dict(zip(_alias_letters(len(names)), names))


def _variants(name: str) -> list[str]:
    base = NAME_VARIANTS.get(name, [name])
    return sorted(set(base) | {name}, key=len, reverse=True)


def _name_pattern(variants: list[str]) -> re.Pattern:
    return re.compile(r"(?<![\w.])(?:" + "|".join(re.escape(v) for v in variants) + r")(?!\w)")


def mask_names(text: str, aliases: dict[str, str]) -> str:
    """V besedilu zamenja imena medijev iz zgodbe z njihovimi psevdonimi."""
    # najprej najdaljše oblike, da »RTV SLO« ne ostane po zamenjavi »MMC«
    pairs = sorted(((v, a) for a, name in aliases.items() for v in _variants(name)), key=lambda p: -len(p[0]))
    lookup = {v: a for v, a in pairs}
    pattern = _name_pattern([v for v, _ in pairs])
    return pattern.sub(lambda m: lookup[m.group(0)], text)


_ALIAS = re.compile(r"MEDIJ_[A-Z0-9]+")


def unmask(value, aliases: dict[str, str]):
    """Rekurzivno zamenja psevdonime nazaj z imeni medijev (v odgovoru modela)."""
    if isinstance(value, str):
        return _ALIAS.sub(lambda m: aliases.get(m.group(0), m.group(0)), value)
    if isinstance(value, list):
        return [unmask(v, aliases) for v in value]
    if isinstance(value, dict):
        return {k: unmask(v, aliases) for k, v in value.items()}
    return value


def restore_quote(quote: str, aliases: dict[str, str], original: str) -> str:
    """Dobesedni citat iz zakritega besedila vrne v izvirno obliko (npr. MEDIJ_B -> »MMC«, ne »MMC RTV SLO«)."""
    found = list(dict.fromkeys(_ALIAS.findall(quote)))
    if not found:
        return quote
    options = [[(a, v) for v in _variants(aliases.get(a, a))] for a in found]
    for combo in itertools.islice(itertools.product(*options), 200):
        candidate = quote
        for alias, variant in combo:
            candidate = candidate.replace(alias, variant)
        if quote_in_text(candidate, original):
            return candidate
    return unmask(quote, aliases)


def unmask_analysis(analysis: StoryAnalysis, aliases: dict[str, str], cluster: list[Article]) -> StoryAnalysis:
    """Odgovor modela s psevdonimi pretvori v odgovor z imeni medijev; dobesedne citate obnovi iz izvirnika."""
    originals = {a.source: f"{a.title}\n{a.body}" for a in cluster}
    data = analysis.model_dump()
    for cov in data["coverage_comparison"]:
        name = aliases.get(cov["media_name"], cov["media_name"])
        text = originals.get(name, "")
        cov["bias_evidence_quotes"] = [restore_quote(q, aliases, text) for q in cov["bias_evidence_quotes"]]
        cov["editorial_statements"] = [restore_quote(q, aliases, text) for q in cov["editorial_statements"]]
        for term in cov["loaded_language"]:
            term["quote"] = restore_quote(term["quote"], aliases, text)
    return StoryAnalysis.model_validate(unmask(data, aliases))


# --------------------------------------------------------------------------- #
# Delno dostopna besedila
# --------------------------------------------------------------------------- #
_PAYWALL = re.compile(
    r"postanite naročnik|za naročnike|samo za naročnike|plačljiv[ao] vsebin|preberite celoten članek"
    r"|za nadaljevanje branja|nadaljujte z branjem|vsebina je na voljo samo|subscribe to (?:read|continue)"
    r"|already a subscriber",
    re.IGNORECASE,
)
TRUNCATED_CHARS = 15000  # enako kot scraper.MAX_TEXT_CHARS


def is_partial(article: Article) -> bool:
    """Besedilo je verjetno nepopolno: kratko, za plačljivim zidom ali odrezano."""
    body = article.body
    return (
        len(_WORDS.findall(body)) < PARTIAL_MIN_WORDS
        or bool(_PAYWALL.search(body))
        or len(body) >= min(TRUNCATED_CHARS, MAX_BODY_CHARS)
    )


def story_prompt(cluster: list[Article], aliases: dict[str, str]) -> str:
    """Poziv za analizo zgodbe: brez imen medijev, URL-jev in kategorij."""
    alias_of = {name: alias for alias, name in aliases.items()}
    blocks = []
    for a in sorted(cluster, key=lambda a: alias_of[a.source]):
        role = " [REFERENČNI MEDNARODNI VIR]" if a.category == "mednarodni" else ""
        partial = "\nOPOMBA: DELNO BESEDILO (kratko, odrezano ali za plačljivim zidom)" if is_partial(a) else ""
        blocks.append(
            f"### {alias_of[a.source]}{role}\nOBJAVLJENO: {a.published or 'neznano'}{partial}\n"
            f"NASLOV: {mask_names(a.title, aliases)}\n"
            f"BESEDILO:\n{mask_names(a.body[:MAX_BODY_CHARS], aliases)}"
        )
    return (
        "Primerjaj, kako spodnji mediji poročajo o istem dogodku. Za vsak medij vrni en element "
        "v coverage_comparison; media_name je psevdonim (npr. MEDIJ_A).\n\n" + "\n\n".join(blocks)
    )


def analyze_story(client, model: str, cluster: list[Article], index: int) -> StoryReport:
    aliases = make_aliases(cluster, index)
    analysis = _generate(client, model, story_prompt(cluster, aliases), StoryAnalysis)
    report = build_story_report(unmask_analysis(analysis, aliases, cluster), cluster, index)
    report.blind_analysis = True
    return report


def leaning_from_score(score: float) -> str:
    """Ime ocene iz številčne lestvice; meje so enake v navodilih modelu in na strani."""
    if score <= -2:
        return "Levo"
    if score <= -0.5:
        return "Sredina-Levo"
    if score < 0.5:
        return "Sredina"
    if score < 2:
        return "Sredina-Desno"
    return "Desno"


def sides_from_weights(weights: list[SideWeight], fallback: str) -> str:
    """Izpelje sides_represented iz deležev prostora; brez deležev ostane ocena modela."""
    active = [w for w in weights if w.share_percent > 0 or w.direct_quotes > 0]
    if len(weights) < 2:
        return fallback
    if len(active) <= 1:
        return "Samo ena stran"
    top = max(active, key=lambda w: w.share_percent)
    in_lede = [w for w in active if w.in_lede]
    silent = len(active) < len(weights)  # stran v sporu, ki ne dobi besede
    if silent or top.share_percent >= 75 or (len(in_lede) == 1 and in_lede[0] is top and top.share_percent >= 65):
        return "Pretežno ena stran"
    return "Obe strani"


def clean_fact_matrix(matrix: list[FactPresence], names: list[str]) -> list[FactPresence]:
    """Obdrži samo znane medije; mediji z dejstvom v naslovu/uvodu so vedno tudi med »media«."""
    lookup = {n.lower(): n for n in names}
    result = []
    for row in matrix:
        media = [lookup[m.lower()] for m in row.media if m.lower() in lookup]
        prominent = [lookup[m.lower()] for m in row.prominent_in if m.lower() in lookup]
        media = list(dict.fromkeys(media + prominent))
        result.append(FactPresence(fact=row.fact, media=media, prominent_in=list(dict.fromkeys(prominent))))
    return result


def matrix_gaps(matrix: list[FactPresence], name: str, names: list[str]) -> list[str]:
    """Dejstva, ki jih navaja vsaj polovica DRUGIH medijev (in vsaj dva), ta medij pa ne."""
    others = [n for n in names if n != name]
    if len(others) < 2:
        return []
    need = max(2, math.ceil(len(others) / 2))
    return [row.fact for row in matrix if name not in row.media and sum(m in others for m in row.media) >= need]


_SENTENCE = re.compile(r"(?<=[.!?…])\s+(?=[A-ZČŠŽĆĐ„\"»0-9])|\n+")


def shared_core(article: Article, cluster: list[Article]) -> SharedCore | None:
    """Delež avtorskega besedila, ki ga ima vsaj še en medij (agencijsko jedro), in stavka, ki ju ima samo ta medij."""
    others = [o for o in cluster if o.id != article.id and o.language == article.language]
    own = _shingles(article.body)
    if not others or not own:
        return None
    other_shingles = set().union(*(_shingles(o.body) for o in others))
    shared = round(100 * len(own & other_shingles) / len(own))
    unique = []
    for sentence in _SENTENCE.split(article.body):
        sentence = sentence.strip()
        grams = _shingles(sentence)
        if len(_WORDS.findall(sentence)) >= 8 and grams and not grams & other_shingles:
            unique.append(sentence)
    best = sorted(sorted(unique, key=len, reverse=True)[:2], key=article.body.find)
    return SharedCore(shared_percent=shared, own_percent=100 - shared, own_sentences=[s[:400] for s in best])


def build_story_report(analysis: StoryAnalysis, cluster: list[Article], index: int) -> StoryReport:
    """Poveže analizo z zajetimi članki: preveri citate, naslove in URL-je vzame iz zajema."""
    by_source = {a.source.lower(): a for a in cluster}
    names = [a.source for a in cluster if any(c.media_name.lower() == a.source.lower()
                                              for c in analysis.coverage_comparison)]
    matrix = clean_fact_matrix(analysis.fact_matrix, names)
    coverage: list[CoverageReport] = []
    for item in analysis.coverage_comparison:
        article = by_source.get(item.media_name.lower())
        if article is None:
            log.warning("Model je vrnil neznan medij %r – izpuščam", item.media_name)
            continue
        full_text = f"{article.title}\n{article.body}"
        quotes, all_ok = verify_quotes(item.bias_evidence_quotes, full_text)
        for term in item.loaded_language:
            term.verified = quote_in_text(term.quote, full_text)
        editorial = [e for e in item.editorial_statements if quote_in_text(e, full_text)]
        if len(editorial) < len(item.editorial_statements):
            log.warning("%s: izpuščenih %d nedobesednih avtorskih stavkov", item.media_name,
                        len(item.editorial_statements) - len(editorial))
        if item.lean_score is not None:
            item.bias_leaning = leaning_from_score(item.lean_score)
        item.sides_represented = sides_from_weights(item.side_weights, item.sides_represented)
        partial = is_partial(article)
        if partial:
            item.confidence = "Nizka"
        coverage.append(
            CoverageReport(
                **item.model_dump(exclude={"article_title", "article_url", "bias_evidence_quotes",
                                           "editorial_statements"}),
                editorial_statements=editorial,
                published=article.published,
                word_count=len(_WORDS.findall(article.body)),
                cited_sources=cited_sources(article.body, article.source),
                text_overlap=text_overlaps(article, cluster),
                shared_core=shared_core(article, cluster),
                partial_text=partial,
                matrix_gaps=matrix_gaps(matrix, article.source, names),
                # naslov in URL vedno vzamemo iz zajetih podatkov, ne iz modela
                article_title=article.title,
                article_url=article.url,
                bias_evidence_quotes=quotes,
                category=article.category,
                quotes_verified=all_ok,
            )
        )

    return StoryReport(
        id=f"story-{index + 1}",
        topic_title=analysis.topic_title,
        international_baseline=analysis.international_baseline,
        neutral_summary=analysis.neutral_summary,
        context=analysis.context,
        key_differences=analysis.key_differences,
        fact_matrix=matrix,
        coverage_comparison=coverage,
        has_international_source=any(a.category == "mednarodni" for a in cluster),
    )


def source_infos() -> list[SourceInfo]:
    return [SourceInfo(name=s.name, category=s.category, url=s.url) for s in SOURCES]


def analyze(
    articles: list[Article], model: str | None = None, max_stories: int = MAX_STORIES
) -> DailyAnalysis:
    """Celotna analiza z Gemini. Zahteva GEMINI_API_KEY."""
    model = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    client = _client()

    try:
        clusters = cluster_with_gemini(client, model, articles, max_stories)
    except RuntimeError as exc:
        log.warning("Združevanje z Gemini ni uspelo (%s) – uporabljam leksikalno metodo", exc)
        clusters = []
    if not clusters:
        clusters = cluster_lexical(articles, max_stories)
    log.info("Najdenih %d skupnih zgodb", len(clusters))

    stories: list[StoryReport] = []
    for i, cluster in enumerate(clusters):
        try:
            stories.append(analyze_story(client, model, cluster, i))
            log.info("Analizirana zgodba %d: %s", i + 1, stories[-1].topic_title)
        except RuntimeError as exc:
            log.error("Analiza zgodbe %d ni uspela: %s", i + 1, exc)

    return DailyAnalysis(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        model=model,
        is_mock=False,
        sources=source_infos(),
        articles_scraped=len(articles),
        stories=stories,
    )


# --------------------------------------------------------------------------- #
# Demo podatki (brez API ključa)
# --------------------------------------------------------------------------- #
def _cov(media, category, title, url, sens, lean, quotes, omitted) -> CoverageReport:
    return CoverageReport(
        media_name=media, category=category, article_title=title, article_url=url,
        sensationalism_score=sens, bias_leaning=lean, bias_evidence_quotes=quotes,
        omitted_facts=omitted, quotes_verified=True,
    )


def build_mock_analysis(articles_scraped: int = 0) -> DailyAnalysis:
    """Ilustrativni podatki za razvoj frontenda. Zgodbe in citati so IZMIŠLJENI."""
    rtv, ur, n24, mla, bbc = (
        "https://www.rtvslo.si", "https://www.24ur.com", "https://nova24tv.si",
        "https://www.mladina.si", "https://www.bbc.com/news/world",
    )
    stories = [
        StoryReport(
            id="story-1",
            topic_title="EU ministri dosegli dogovor o skupni migracijski politiki",
            international_baseline=(
                "Notranji ministri EU so po dvodnevnih pogajanjih potrdili kompromis o porazdelitvi "
                "prosilcev za azil. Države, ki prosilcev ne sprejmejo, plačajo prispevek v skupni sklad. "
                "Proti so glasovale tri države članice, dogovor mora potrditi še Evropski parlament."
            ),
            neutral_summary=(
                "Ministri EU so sprejeli kompromis o solidarnostnem mehanizmu za azil, ki državam omogoča "
                "izbiro med sprejemom prosilcev in finančnim prispevkom. Slovenija je dogovor podprla; "
                "končno besedilo mora potrditi še parlament."
            ),
            has_international_source=True,
            coverage_comparison=[
                _cov("BBC World", "mednarodni", "EU ministers agree migration burden-sharing deal", bbc,
                     2, "Sredina",
                     ["The deal was backed by a qualified majority, with three member states voting against."],
                     []),
                _cov("MMC RTV SLO", "javni", "Ministri EU potrdili kompromis o azilnem sistemu", rtv,
                     2, "Sredina",
                     ["Dogovor mora potrditi še Evropski parlament, pogajanja pa naj bi se začela jeseni."],
                     ["Število držav, ki so glasovale proti."]),
                _cov("24ur", "komercialni", "Bruselj odločil: kdor ne sprejme migrantov, bo plačal", ur,
                     6, "Sredina",
                     ["Kdor ne bo sprejel migrantov, bo moral globoko seči v žep."],
                     ["Da dogovor še ni dokončen in ga mora potrditi Evropski parlament."]),
                _cov("Nova24TV", "alternativni", "Bruselj Sloveniji vsiljuje kvote – vlada molči!", n24,
                     9, "Desno",
                     ["Bruseljska birokracija nam znova vsiljuje nezakonite migrante.",
                      "vlada pa kot vedno ponižno kima"],
                     ["Da gre za izbiro med sprejemom in finančnim prispevkom, ne za obvezne kvote.",
                      "Da je dogovor podprla kvalificirana večina držav članic."]),
                _cov("Mladina", "alternativni", "Evropa se odkupuje od solidarnosti", mla,
                     5, "Sredina-Levo",
                     ["Namesto solidarnosti z ljudmi v stiski je Evropa izbrala računovodstvo."],
                     ["Da mora dogovor potrditi še Evropski parlament."]),
            ],
        ),
        StoryReport(
            id="story-2",
            topic_title="Vlada predstavila predlog proračuna za prihodnje leto",
            international_baseline=(
                "Mednarodni vir o dogodku ne poroča; izhodišče so dejstva, ki jih navaja večina virov: "
                "predlog predvideva višje izdatke za zdravstvo in obrambo ter primanjkljaj okoli 2,8 % BDP."
            ),
            neutral_summary=(
                "Vlada je v parlamentarni postopek poslala predlog proračuna z višjimi izdatki za zdravstvo "
                "in obrambo. Opozicija kritizira višino primanjkljaja, fiskalni svet bo mnenje podal prihodnji teden."
            ),
            has_international_source=False,
            coverage_comparison=[
                _cov("MMC RTV SLO", "javni", "Vlada sprejela predlog proračuna, primanjkljaj 2,8 odstotka BDP", rtv,
                     1, "Sredina",
                     ["Primanjkljaj bo po napovedih znašal 2,8 odstotka BDP."],
                     []),
                _cov("24ur", "komercialni", "Koliko denarja bo šlo za zdravstvo? Vse o novem proračunu", ur,
                     4, "Sredina",
                     ["Največji kos pogače bo tokrat dobilo zdravstvo."],
                     ["Kritike fiskalnega sveta glede vzdržnosti javnih financ."]),
                _cov("Nova24TV", "alternativni", "Rekordno zadolževanje: vlada zapravlja kot še nikoli", n24,
                     8, "Desno",
                     ["Vlada brezglavo zapravlja denar davkoplačevalcev."],
                     ["Povečanje izdatkov za obrambo, ki ga je zahtevala tudi opozicija.",
                      "Da je primanjkljaj pod mejo 3 % BDP."]),
                _cov("Mladina", "alternativni", "Proračun, ki končno pomisli na bolnike", mla,
                     4, "Levo",
                     ["Po letih varčevanja na plečih najšibkejših je to proračun, ki končno pomisli na ljudi."],
                     ["Višino primanjkljaja in opozorila o zadolževanju."]),
            ],
        ),
        StoryReport(
            id="story-3",
            topic_title="Močan potres v vzhodnem Sredozemlju, več žrtev",
            international_baseline=(
                "Potres z magnitudo 6,4 je prizadel obalno območje; oblasti potrjujejo najmanj 14 žrtev in "
                "več kot 200 poškodovanih. Reševalne ekipe iščejo preživele pod ruševinami, EU je ponudila pomoč."
            ),
            neutral_summary=(
                "Potres z magnitudo 6,4 je zahteval najmanj 14 življenj. Slovenskih državljanov med žrtvami "
                "po podatkih ministrstva za zunanje zadeve ni, EU je aktivirala mehanizem civilne zaščite."
            ),
            has_international_source=True,
            coverage_comparison=[
                _cov("BBC World", "mednarodni", "Deadly earthquake strikes eastern Mediterranean", bbc,
                     3, "Sredina",
                     ["At least 14 people have been confirmed dead, officials said."],
                     []),
                _cov("MMC RTV SLO", "javni", "Potres z magnitudo 6,4: najmanj 14 mrtvih", rtv,
                     3, "Sredina",
                     ["Na ministrstvu za zunanje zadeve pravijo, da med žrtvami ni slovenskih državljanov."],
                     []),
                _cov("24ur", "komercialni", "GROZLJIVI POSNETKI: Zemlja se je stresla, ljudje bežali na ulice", ur,
                     9, "Sredina",
                     ["Prizori, ob katerih zastane dih."],
                     ["Uradno število žrtev in poškodovanih.", "Da je EU aktivirala mehanizem pomoči."]),
                _cov("Nova24TV", "alternativni", "Potres v Sredozemlju terjal življenja", n24,
                     3, "Sredina",
                     ["Reševalci še vedno iščejo preživele pod ruševinami."],
                     ["Da je EU ponudila pomoč prizadetemu območju."]),
            ],
        ),
    ]
    return DailyAnalysis(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        model="mock",
        is_mock=True,
        sources=source_infos(),
        articles_scraped=articles_scraped,
        stories=stories,
    )
