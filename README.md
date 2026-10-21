# NewsAI · Medijsko ogledalo

Prototip sistema, ki vsak dan zajame slovenske in mednarodne novice, poišče iste zgodbe v različnih medijih
in z Gemini API primerja, kako o njih poročajo: senzacionalizem naslova, politični nagib (utemeljen z
dobesednimi citati) in dejstva, ki jih mednarodni vir navaja, posamezen medij pa ne.

```
backend/
  scraper.py     RSS zajem (feedparser) + čisto besedilo (trafilatura)
  analyzer.py    Pydantic sheme, združevanje v zgodbe, Gemini structured output, preverjanje citatov, demo podatki
  main.py        cevovod → data/daily_analysis.json
  tests/         unit testi (lokalni RSS fixturji, lažni Gemini odjemalec)
frontend/        statična stran (HTML + prevedeni Tailwind CSS + vanilla JS)
data/            daily_analysis.json (bere ga frontend)
.github/workflows/daily.yml   cron ob 07:00 UTC
```

## Viri

| Medij | Vloga | RSS |
|---|---|---|
| MMC RTV SLO | javni servis | `https://www.rtvslo.si/feeds/00.xml` |
| 24ur | komercialni | `https://www.24ur.com/rss` |
| N1 | komercialni | `https://n1info.si/feed/` |
| Nova24TV | alternativni (desno profiliran) | `https://nova24tv.si/feed/` |
| Mladina | alternativni (levo profiliran) | `https://www.mladina.si/rss/` |
| BBC World | mednarodno sidro objektivnosti | `https://feeds.bbci.co.uk/news/world/rss.xml` |

Reuters javnih RSS virov ne objavlja več, zato je mednarodna referenca BBC World. Viri so definirani v `SOURCES` v `scraper.py`.

## Zagon

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env            # vpišite GEMINI_API_KEY (brez ključa se zapišejo demo podatki)

cd backend
python scraper.py --limit 5     # preizkus RSS virov
python main.py                  # celoten cikel → ../data/daily_analysis.json
python -m unittest discover -s tests

cd .. && python -m http.server 8000
# odprite http://localhost:8000/frontend/
```

CSS je že preveden (`frontend/styles.css`). Po spremembah razredov v `index.html`/`app.js`:
`cd frontend && npm install && npm run build:css`.

## Kako deluje analiza

1. **Zajem**: do 20 člankov na vir, polno besedilo s trafilatura (vzporedno).
2. **Združevanje**: Gemini prejme seznam naslovov/povzetkov in vrne 3–5 dogodkov, o katerih poročata vsaj
   dva medija (prednost imajo tisti z BBC). Če klic ne uspe, se uporabi leksikalno združevanje.
3. **Analiza**: za vsako zgodbo en klic z `response_schema=StoryAnalysis`; odgovor se lokalno ponovno
   validira s Pydantic (ocene 1–10, nagib iz zaprtega nabora, 1–2 citata).
4. **Varovalke**: naslov in URL članka se vedno vzameta iz zajetih podatkov (ne iz modela); vsak citat se
   preveri, ali dobesedno obstaja v besedilu članka – nepreverjeni citati so v UI označeni.

## GitHub Actions

Workflow `daily.yml` teče ob 07:00 UTC (in ročno prek *Run workflow*), zažene teste in cevovod ter
commita posodobljeni `data/daily_analysis.json`. V *Settings → Secrets and variables → Actions* dodajte
secret `GEMINI_API_KEY` (neobvezno variable `GEMINI_MODEL`, privzeto `gemini-2.5-flash`).

## Omejitve

Ocene ustvarja jezikovni model in veljajo za posamezen članek, ne za medij kot celoto. Mednarodni vir
o mnogih slovenskih notranjepolitičnih temah ne poroča; takrat je izhodišče skupno dejstveno jedro
slovenskih virov, kar je v UI označeno.
