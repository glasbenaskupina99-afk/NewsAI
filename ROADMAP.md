# Načrt nadgradenj · Medijsko ogledalo

Stanje ob pripravi načrta (21. 10. 2026): delujoč prototip s samodejnim zajemom (RTV SLO, 24ur, N1,
Nova24TV, BBC World), Gemini analizo s Pydantic shemo, ročnim uvozom analiz (`manual_analysis.py`),
preverjanjem dobesednih citatov in statično stranjo na GitHub Pages. Objavljene so 3 ročno
analizirane zgodbe z 11 mediji.

Obseg: **S** = do pol dneva, **M** = 1–3 dni, **L** = teden ali več.

---

## 1.1 Zanesljiv vsakodnevni zagon

Cilj: stran se vsak dan sama posodobi s pravimi podatki, brez ročnega dela.

| # | Naloga | Zakaj | Obseg |
|---|---|---|---|
| 1.1.1 | Dodati `GEMINI_API_KEY` v GitHub secrets in izvesti prvi samodejni zagon | Brez ključa samodejne analize ni | S |
| 1.1.2 | Preveriti RSS za N1 (`/feed/`) in poiskati pravi RSS za Mladino | N1 je dodan nepreverjeno, Mladina ne deluje | S |
| 1.1.3 | **Arhiv po dnevih**: `data/archive/YYYY-MM-DD.json` + `data/index.json` | Zdaj vsak zagon prepiše prejšnji dan | S |
| 1.1.4 | Samodejne in ročne analize se **združujejo**, ne prepisujejo (ročne imajo prednost) | Ročno dodani mediji (Delo, Svet24 …) bi se ob naslednjem zagonu izgubili | M |
| 1.1.5 | Opozorilo (GitHub issue), ko vir 2 dni zapored ne vrne člankov | Okvara vira zdaj ostane neopažena | S |
| 1.1.6 | Posodobitev GitHub Actions na Node 24 (`checkout@v5`, `setup-python@v6` …) | Actions že opozarjajo na opustitev Node 20 | S |

## 1.2 Več virov in lažji ročni vnos

Cilj: pokriti ključne slovenske medije, tudi tiste, ki samodejnega zajema ne dovolijo.

| # | Naloga | Zakaj | Obseg |
|---|---|---|---|
| 1.2.1 | Novi RSS viri: Delo, Večer, Dnevnik, Žurnal24, Svet24, Siol, Demokracija, Mladina, Necenzurirano | Pri učiteljski zbornici je bila slika popolna šele s 7 mediji | S |
| 1.2.2 | Drugo mednarodno sidro: **The Guardian API** (brezplačen ključ, dovoljuje uporabo) + DW/Euronews RSS | BBC pokrije malo slovenskih tem; Reuters ni na voljo | M |
| 1.2.3 | Orodje `add_article.py`: prilepiš besedilo s strani, samo odstrani menije, komentarje in oglase ter doda članek k zgodbi | Ročno čiščenje prilepljenih strani je zdaj zamudno | M |
| 1.2.4 | Označevanje plačljivih in delno dostopnih člankov (`partial_text: true`) | Pri Delu je ocena temeljila le na prvem odstavku | S |
| 1.2.5 | Dogovor z mediji (Pro Plus, Delo …) za dostop do vsebin | Zakonita pot za vire, ki blokirajo robote | L (neodvisno od kode) |

## 1.3 Natančnejša analiza

Cilj: ocene, ki jim bralec lahko zaupa in jih lahko preveri.

| # | Naloga | Zakaj | Obseg |
|---|---|---|---|
| 1.3.1 | **Zaznava agencijskih vesti (STA)**: podobnost besedil med mediji, oznaka »X % enako besedilu STA« | Večina razlik je bila v tem, kaj je medij k vesti STA dodal ali izpustil | M |
| 1.3.2 | Prikaz **razlik glede na skupno jedro** (kaj je medij dodal / odvzel), ne le glede na BBC | Pri slovenskih temah mednarodnega sidra pogosto ni | M |
| 1.3.3 | Ločena ocena naslova in besedila (`headline_leaning`, `body_leaning`) | Pri Nova24TV (ESČP) je bil obarvan predvsem naslov | S |
| 1.3.4 | Pisna lestvica za senzacionalizem in nagib (z zgledi za vsako stopnjo) v navodilih modelu | Doslednost ocen med dnevi in zgodbami | S |
| 1.3.5 | Testni nabor 20–30 ročno ocenjenih člankov in merjenje ujemanja modela | Brez tega ne vemo, kako dober je model | M |
| 1.3.6 | Navzkrižno preverjanje z drugim modelom; ob neskladju oznaka »negotova ocena« | Zmanjša vpliv posamezne napačne ocene | M |
| 1.3.7 | Združevanje zgodb z vektorskimi vložitvami (embeddings) namesto le z LLM | Cenejše, stabilnejše, deluje tudi med jeziki | M |

## 1.4 Spletna stran

Cilj: bralec hitro najde, primerja in razume.

| # | Naloga | Zakaj | Obseg |
|---|---|---|---|
| 1.4.1 | Izbira datuma (arhiv) in povezava na posamezno zgodbo (`#story-…` z datumom) | Deljenje in pregled za nazaj | S (po 1.1.3) |
| 1.4.2 | Filter po mediju in pogled »vse zgodbe izbranega medija« | Primerjava enega medija skozi čas | M |
| 1.4.3 | **Profil medija skozi čas**: povprečni senzacionalizem, nagib, delež »samo ena stran« po tednih | Vzorci postanejo vidni šele čez več dni | M |
| 1.4.4 | Stran **»Metodologija«**: kako nastanejo ocene, omejitve, kdo jih je pripravil (model / ročno) | Preglednost in zaupanje | S |
| 1.4.5 | Strnjen pogled kartic (razširi ob kliku) za zgodbe s 5+ mediji | Zgodba s 7 mediji je zelo dolga | S |
| 1.4.6 | Gumb »Prijavi napako v oceni« (GitHub issue ali obrazec) | Popravki bralcev in medijev | S |

## 1.5 Kakovost kode in delovanje

| # | Naloga | Zakaj | Obseg |
|---|---|---|---|
| 1.5.1 | Testi v CI ob vsakem pushu/PR (ne le v dnevnem zagonu) + preverjanje sheme `daily_analysis.json` | Napake se ujamejo pred objavo | S |
| 1.5.2 | Testi za frontend (Playwright: izris, brez napak v konzoli, mobilni pogled) | Zdaj se preverja le ročno | S |
| 1.5.3 | Omejitev porabe API (največ N klicev na zagon) in beleženje stroškov | Predvidljivi stroški | S |
| 1.5.4 | Ločitev podatkov od kode (veja `data` ali GitHub Pages artefakt namesto commitov v glavno vejo) | Zgodovina kode ni zasuta z dnevnimi commiti | M |

---

## 2.0 Razširitve (dolgoročno)

- **Tedensko poročilo** (e-pošta ali PDF): najbolj in najmanj uravnoteženo pokrite zgodbe tedna.
- **Teme in ključne besede**: sledenje temi skozi več dni (npr. »šolska reforma«).
- **Druge države regije** (HR, AT, IT) z istim pristopom.
- **Javni API / odprti podatki** za raziskovalce in novinarje.
- **Pravni pregled**: avtorske pravice (citati, povzetki), pravica do odgovora medijev, izjava o omejitvah.

---

## Priporočen vrstni red

1. **1.1.1 → 1.1.3 → 1.1.4**: samodejni zagon, arhiv, varno združevanje ročnih in samodejnih analiz
2. **1.2.1 + 1.2.3**: več virov in hitrejši ročni vnos
3. **1.3.1 + 1.3.3**: zaznava STA in ločena ocena naslova/besedila (največ nove vrednosti glede na dosedanje ugotovitve)
4. **1.4.4 + 1.4.1**: metodologija in arhiv na strani
5. Nato 1.3.5 (testni nabor) pred širšo objavo projekta
