"""Združevanje novic v skupne zgodbe in analiza pristranosti z Gemini API.

Vsak odgovor modela je omejen s Pydantic JSON shemo (structured output) in
ponovno validiran lokalno. Citati, ki naj utemeljujejo oceno pristranosti,
so preverjeni proti dejanskemu besedilu članka.
"""
from __future__ import annotations

import json
import logging
import os
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
MAX_BODY_CHARS = 3500

BiasLeaning = Literal["Levo", "Sredina-Levo", "Sredina", "Sredina-Desno", "Desno"]
SidesRepresented = Literal["Obe strani", "Pretežno ena stran", "Samo ena stran"]


# --------------------------------------------------------------------------- #
# Sheme
# --------------------------------------------------------------------------- #
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


class StoryAnalysis(BaseModel):
    topic_title: str = Field(description="Kratek, nevtralen naslov dogodka v slovenščini.")
    international_baseline: str = Field(
        description="Kratek povzetek ključnih dejstev po navedbah mednarodnega vira."
    )
    coverage_comparison: list[MediaCoverage]
    neutral_summary: str = Field(description="Kratek nevtralen povzetek celotne zgodbe.")


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


class StoryReport(StoryAnalysis):
    id: str
    coverage_comparison: list[CoverageReport]
    has_international_source: bool = False


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
5. omitted_facts navaja samo dejstva, ki jih mednarodni vir dejansko navaja, ta medij pa ne.
   Če mednarodnega vira ni, primerjaj z dejstvi, ki jih navaja večina drugih virov, in to
   povej v international_baseline. Prazen seznam je dovoljen.
6. media_name, article_title in article_url prepiši natančno iz vhoda.
7. voices_heard našteje, kdo v članku dobi besedo; sides_represented pove, ali so predstavljena
   stališča vseh vpletenih strani. To ocenjuj ločeno od besedišča.
8. factual_errors navaja samo trditve, ki so v nasprotju z drugimi viri ali z istim člankom.
9. Vsa besedila (razen citatov) piši v slovenščini.
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


def verify_quotes(quotes: list[str], body: str) -> tuple[list[str], bool]:
    """Vrne citate, ki dobesedno obstajajo v besedilu; drugi element pove, ali so preverjeni vsi."""
    norm_body = _normalize(body)
    verified = [q for q in quotes if _normalize(q).strip("\"'. ") in norm_body]
    if verified:
        return verified, len(verified) == len(quotes)
    return quotes, False


def analyze_story(client, model: str, cluster: list[Article], index: int) -> StoryReport:
    blocks = []
    for a in cluster:
        role = "MEDNARODNI VIR (sidro objektivnosti)" if a.category == "mednarodni" else a.category
        blocks.append(
            f"### MEDIJ: {a.source} [{role}]\nNASLOV: {a.title}\nURL: {a.url}\n"
            f"BESEDILO:\n{a.body[:MAX_BODY_CHARS]}"
        )
    prompt = (
        "Primerjaj, kako spodnji mediji poročajo o istem dogodku. Za vsak medij vrni en element "
        "v coverage_comparison.\n\n" + "\n\n".join(blocks)
    )
    analysis = _generate(client, model, prompt, StoryAnalysis)
    return build_story_report(analysis, cluster, index)


def build_story_report(analysis: StoryAnalysis, cluster: list[Article], index: int) -> StoryReport:
    """Poveže analizo z zajetimi članki: preveri citate, naslove in URL-je vzame iz zajema."""
    by_source = {a.source.lower(): a for a in cluster}
    coverage: list[CoverageReport] = []
    for item in analysis.coverage_comparison:
        article = by_source.get(item.media_name.lower())
        if article is None:
            log.warning("Model je vrnil neznan medij %r – izpuščam", item.media_name)
            continue
        quotes, all_ok = verify_quotes(item.bias_evidence_quotes, f"{article.title}\n{article.body}")
        coverage.append(
            CoverageReport(
                **item.model_dump(exclude={"article_title", "article_url", "bias_evidence_quotes"}),
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
