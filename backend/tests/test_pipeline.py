import json
import sys
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analyzer  # noqa: E402
from analyzer import (  # noqa: E402
    DailyAnalysis, analyze_story, build_mock_analysis, cited_sources, cluster_lexical, text_overlaps,
    verify_quotes,
)
from add_article import clean_page  # noqa: E402
from scraper import Article, Source, fetch_feed  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class ScraperTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = partial(QuietHandler, directory=str(FIXTURES))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_fetch_feed_parses_items(self):
        articles = fetch_feed(Source("MMC RTV SLO", f"{self.base}/rtv.xml", "javni", "sl"))
        self.assertEqual(len(articles), 2)
        first = articles[0]
        self.assertEqual(first.title, "Ministri EU potrdili kompromis o azilnem sistemu")
        self.assertEqual(first.url, "https://www.rtvslo.si/a/1")
        self.assertNotIn("<p>", first.summary)
        self.assertTrue(first.published.startswith("2026-10-21T06:00"))

    def test_fallback_url_is_used(self):
        source = Source("MMC RTV SLO", f"{self.base}/missing.xml", "javni", "sl",
                        fallback_urls=(f"{self.base}/rtv.xml",))
        self.assertEqual(len(fetch_feed(source)), 2)

    def test_unreachable_feed_returns_empty(self):
        self.assertEqual(fetch_feed(Source("X", f"{self.base}/missing.xml", "javni", "sl")), [])

    def test_lexical_clustering_groups_across_sources(self):
        articles = fetch_feed(Source("MMC RTV SLO", f"{self.base}/rtv.xml", "javni", "sl"))
        articles += fetch_feed(Source("Nova24TV", f"{self.base}/n24.xml", "alternativni", "sl"))
        clusters = cluster_lexical(articles)
        self.assertEqual(len(clusters), 1)
        self.assertEqual({a.source for a in clusters[0]}, {"MMC RTV SLO", "Nova24TV"})


def _article(source, category, title, text):
    return Article(id=source[:3], source=source, category=category, language="sl",
                   title=title, url=f"https://example.org/{source}", text=text)


class AnalyzerTest(unittest.TestCase):
    def test_verify_quotes_tolerates_typographic_quotes(self):
        body = "Minister je dejal: „To je zgodovinski dogovor.“  Nato je odšel."
        quotes, ok = verify_quotes(['To je zgodovinski  dogovor.'], body)
        self.assertTrue(ok)
        _, ok = verify_quotes(["Izmišljen citat"], body)
        self.assertFalse(ok)

    def test_analyze_story_overrides_urls_and_flags_quotes(self):
        cluster = [
            _article("BBC World", "mednarodni", "Deal agreed", "Ministers agreed a deal on Tuesday."),
            _article("Nova24TV", "alternativni", "Sramotni dogovor", "Vlada ponižno kima Bruslju."),
        ]
        alias = {name: a for a, name in analyzer.make_aliases(cluster, 0).items()}
        prompts = []
        fake = {
            "topic_title": "Dogovor", "international_baseline": "Ministri so se dogovorili.",
            "neutral_summary": "Dogovor sprejet.",
            "coverage_comparison": [
                {"media_name": alias["BBC World"], "article_title": "x", "article_url": "https://evil.example",
                 "sensationalism_score": 2, "bias_leaning": "Sredina",
                 "bias_evidence_quotes": ["Ministers agreed a deal"], "omitted_facts": []},
                {"media_name": alias["Nova24TV"], "article_title": "x", "article_url": "https://evil.example",
                 "sensationalism_score": 8, "bias_leaning": "Desno",
                 "bias_evidence_quotes": ["Citat, ki ga ni"], "omitted_facts": ["Datum dogovora."]},
                {"media_name": "Neznan", "article_title": "x", "article_url": "x",
                 "sensationalism_score": 1, "bias_leaning": "Levo",
                 "bias_evidence_quotes": ["q"], "omitted_facts": []},
            ],
        }
        client = SimpleNamespace(models=SimpleNamespace(
            generate_content=lambda **kw: prompts.append(kw["contents"]) or SimpleNamespace(text=json.dumps(fake))))
        story = analyze_story(client, "test-model", cluster, 0)
        self.assertTrue(story.blind_analysis)
        self.assertNotIn("Nova24TV", prompts[0])
        self.assertNotIn("https://", prompts[0])
        self.assertEqual(len(story.coverage_comparison), 2)
        bbc, n24 = sorted(story.coverage_comparison, key=lambda c: c.media_name)
        self.assertEqual(n24.media_name, "Nova24TV")
        self.assertEqual(bbc.article_url, "https://example.org/BBC World")
        self.assertTrue(bbc.quotes_verified)
        self.assertFalse(n24.quotes_verified)
        self.assertTrue(story.has_international_source)

    def test_mask_and_restore_quote(self):
        cluster = [_article("MMC RTV SLO", "javni", "t", "Kot je za MMC povedal minister, RTV SLO ne bo ukinjena."),
                   _article("Nova24TV", "alternativni", "t", "Po pisanju Nova24TV je minister dejal ...")]
        aliases = analyzer.make_aliases(cluster, 3)
        rtv = next(a for a, n in aliases.items() if n == "MMC RTV SLO")
        masked = analyzer.mask_names(cluster[0].body, aliases)
        self.assertNotIn("MMC", masked)
        self.assertNotIn("RTV", masked)
        self.assertEqual(masked.count(rtv), 2)
        quote = masked.split(",")[0]
        restored = analyzer.restore_quote(quote, aliases, cluster[0].body)
        self.assertEqual(restored, "Kot je za MMC povedal minister")

    def test_mask_spelling_variants(self):
        cluster = [
            _article("Info360", "komercialni", "t", "x"),
            _article("Žurnal24", "komercialni", "t", "y"),
            _article("Delo", "komercialni", "t", "z"),
        ]
        aliases = analyzer.make_aliases(cluster, 0)
        masked = analyzer.mask_names(
            "Delo vlade je pohvalil. Kot so za Delo, Info 360 in Žurnala24 povedali ...",
            aliases,
        )
        self.assertTrue(masked.startswith("Delo vlade je pohvalil."))
        self.assertNotIn("za Delo", masked)
        self.assertNotIn("360", masked)
        self.assertNotIn("Žurnala24", masked)

    def test_make_aliases_is_invariant_to_story_index_and_order(self):
        a = _article("N1", "komercialni", "t", "x")
        b = _article("MMC RTV SLO", "javni", "t", "y")
        self.assertEqual(analyzer.make_aliases([a, b], 0), analyzer.make_aliases([b, a], 4))

    def test_clean_text_drops_ads_and_page_tail(self):
        from scraper import clean_text
        text = "Prvi odstavek.\nOglaševanje\nDrugi odstavek.\nKakšno je tvoje mnenje o tem?\nNajbolj brano\nDrug članek"
        self.assertEqual(clean_text(text), "Prvi odstavek.\nDrugi odstavek.")

    def test_prompt_has_publication_time_and_partial_flag(self):
        short = _article("Delo", "komercialni", "t", "Za nadaljevanje branja postanite naročnik.")
        short.published = "2026-11-18T08:00:00+01:00"
        long = _article("N1", "komercialni", "t", "beseda " * 300)
        prompt = analyzer.story_prompt([short, long], analyzer.make_aliases([short, long], 0))
        self.assertIn("OBJAVLJENO: 2026-11-18T08:00:00+01:00", prompt)
        self.assertEqual(prompt.count("DELNO BESEDILO"), 1)
        self.assertTrue(analyzer.is_partial(short))
        self.assertFalse(analyzer.is_partial(long))

    def test_sides_from_weights(self):
        W = analyzer.SideWeight
        f = analyzer.sides_from_weights
        self.assertEqual(f([W(side="vlada", share_percent=100, direct_quotes=3, in_lede=True),
                            W(side="opozicija", share_percent=0, direct_quotes=0, in_lede=False)], "Obe strani"),
                         "Samo ena stran")
        self.assertEqual(f([W(side="vlada", share_percent=80, direct_quotes=3, in_lede=True),
                            W(side="opozicija", share_percent=20, direct_quotes=1, in_lede=False)], "Obe strani"),
                         "Pretežno ena stran")
        self.assertEqual(f([W(side="vlada", share_percent=55, direct_quotes=2, in_lede=True),
                            W(side="opozicija", share_percent=45, direct_quotes=2, in_lede=True)], "Samo ena stran"),
                         "Obe strani")
        self.assertEqual(f([W(side="vlada", share_percent=50, direct_quotes=2, in_lede=True),
                            W(side="ZZZS", share_percent=50, direct_quotes=0, in_lede=False),
                            W(side="prejšnja vlada", share_percent=0, direct_quotes=0, in_lede=False)], "Obe strani"),
                         "Pretežno ena stran")
        self.assertEqual(f([], "Pretežno ena stran"), "Pretežno ena stran")

    def test_matrix_gaps_and_prominence(self):
        F = analyzer.FactPresence
        names = ["A", "B", "C", "D"]
        matrix = analyzer.clean_fact_matrix([
            F(fact="znesek", media=["B", "C"], prominent_in=["D"]),
            F(fact="datum", media=["A", "Neznan"]),
        ], names)
        self.assertEqual(matrix[0].media, ["B", "C", "D"])
        self.assertEqual(matrix[1].media, ["A"])
        self.assertEqual(analyzer.matrix_gaps(matrix, "A", names), ["znesek"])
        self.assertEqual(analyzer.matrix_gaps(matrix, "B", names), [])

        # Zgodnejši članek (dan prej) ne dobi očitanih dejstev iz poznejših člankov
        pub = {
            "A": "2026-11-17T14:00:00+00:00",
            "B": "2026-11-18T17:00:00+00:00",
            "C": "2026-11-18T18:00:00+00:00",
            "D": "2026-11-18",
        }
        self.assertEqual(analyzer.matrix_gaps(matrix, "A", names, pub), [])
        self.assertEqual(analyzer.matrix_gaps(matrix, "B", names, pub), [])

    def test_shared_core_and_own_sentences(self):
        agency = "Minister je danes na novinarski konferenci predstavil predlog proračuna za prihodnje leto in poudaril stabilnost."
        a = _article("A", "javni", "t", agency + " Opozicija je predlog označila za predvolilno darilo upokojencem in javnim uslužbencem.")
        b = _article("B", "komercialni", "t", agency)
        core = analyzer.shared_core(a, [a, b])
        self.assertGreater(core.shared_percent, 40)
        self.assertEqual(core.own_sentences, ["Opozicija je predlog označila za predvolilno darilo upokojencem in javnim uslužbencem."])

    def test_shared_core_ignores_multi_sentence_direct_quotes(self):
        agency = "Minister je danes na novinarski konferenci predstavil predlog proračuna za prihodnje leto in poudaril stabilnost."
        quote = "»Ker preiskovalni postopki še potekajo, je pomembno, da ne razkrivamo podrobnosti. O nadaljnjih korakih bomo obvestili javnost,« so zapisali."
        a = _article("A", "javni", "t", f"{agency} {quote}")
        b = _article("B", "komercialni", "t", f"{agency} {quote}")
        core = analyzer.shared_core(a, [a, b])
        self.assertEqual(core.own_sentences, [])

    def test_build_media_stats_aggregates_archive(self):
        import tempfile
        import main as pipeline_main
        with tempfile.TemporaryDirectory() as tmp:
            arch = Path(tmp)
            mock_day = build_mock_analysis()
            mock_day.is_mock = False
            (arch / "2026-11-18.json").write_text(mock_day.model_dump_json(), encoding="utf-8")
            (arch / "index.json").write_text(
                json.dumps([{"date": "2026-11-18", "stories": len(mock_day.stories), "model": "test", "is_mock": False}]),
                encoding="utf-8",
            )
            stats = pipeline_main.build_media_stats(arch)
            self.assertEqual(stats["days"], 1)
            by_name = {m["name"]: m for m in stats["media"]}
            self.assertIn("MMC RTV SLO", by_name)
            self.assertEqual(by_name["MMC RTV SLO"]["count"], 3)
            self.assertEqual(len(by_name["MMC RTV SLO"]["articles"]), 3)

    def test_own_sentences_ignore_paraphrase_of_quote_in_other_outlet(self):
        statement = "dogovor so dosegli ob upoštevanju nastalih okoliščin in odgovornosti za vodenje financ"
        a = _article("A", "javni", "t", f"Kot so pojasnili, so {statement}. Opozicija je zahtevala odstop celotne uprave in nadzornega sveta družbe.")
        b = _article("B", "komercialni", "t", f"V družbi so sporočili: »Ta {statement}.«")
        core = analyzer.shared_core(a, [a, b])
        self.assertEqual(core.own_sentences, ["Opozicija je zahtevala odstop celotne uprave in nadzornega sveta družbe."])

    def test_invalid_model_output_is_rejected(self):
        bad = {"topic_title": "t", "international_baseline": "b", "neutral_summary": "s",
               "coverage_comparison": [{"media_name": "A", "article_title": "x", "article_url": "u",
                                        "sensationalism_score": 42, "bias_leaning": "Zelo levo",
                                        "bias_evidence_quotes": [], "omitted_facts": []}]}
        client = SimpleNamespace(models=SimpleNamespace(
            generate_content=lambda **kw: SimpleNamespace(text=json.dumps(bad))))
        with mock.patch.object(analyzer.time, "sleep"), self.assertRaises(RuntimeError):
            analyzer._generate(client, "m", "p", analyzer.StoryAnalysis, retries=1)

    def test_text_overlap_ignores_shared_quotes(self):
        agency = "Minister je danes na novinarski konferenci predstavil predlog proračuna za prihodnje leto in poudaril stabilnost."
        quote = "„Proračun je stabilen in finance so varne, nikomur ne bomo nič vzeli,“ je dejal."
        a = _article("RTV", "javni", "t", agency + " " + quote)
        b = _article("N24", "alternativni", "t", "Uvod drugačen od drugih. " + agency)
        c = _article("X", "komercialni", "t", "Popolnoma drugačno besedilo brez skupnih delov. " + quote)
        overlaps = {o.media: o.percent for o in text_overlaps(a, [a, b, c])}
        self.assertGreaterEqual(overlaps["N24"], 80)
        self.assertNotIn("X", overlaps)

    def test_cited_sources_excludes_own_name(self):
        text = "Kot poroča STA, je minister po navedbah MMC in Reutersa dejal, da ..."
        self.assertEqual(cited_sources(text, "MMC RTV SLO"), ["STA", "Reuters"])

    def test_leaning_derived_from_score(self):
        from analyzer import leaning_from_score
        self.assertEqual([leaning_from_score(x) for x in (-2.5, -0.6, -0.4, 0, 0.4, 0.5, 1.9, 2)],
                         ["Levo", "Sredina-Levo", "Sredina", "Sredina", "Sredina", "Sredina-Desno", "Sredina-Desno", "Desno"])

    def test_mock_is_valid_schema(self):
        mock = build_mock_analysis()
        roundtrip = DailyAnalysis.model_validate_json(mock.model_dump_json())
        self.assertTrue(roundtrip.is_mock)
        self.assertGreaterEqual(len(roundtrip.stories), 3)


def _story(title, urls, manual):
    return {"id": "x", "topic_title": title, "manual": manual,
            "coverage_comparison": [{"media_name": u, "article_url": f"https://e.si/{u}"} for u in urls]}


def _day(model, stories, **extra):
    return {"generated_at": "2026-11-20T07:00:00+00:00", "model": model, "is_mock": False, "sources": [],
            "articles_scraped": 10, "stories": stories, **extra}


class PublishMergeTest(unittest.TestCase):
    def test_auto_run_keeps_manual_and_drops_overlapping_auto_story(self):
        import main
        manual = _day("Claude (ročna analiza)", [_story("Ročna", ["a", "b", "c"], True)])
        auto = _day("gemini-2.5-flash", [_story("Isti dogodek", ["a", "b"], False), _story("Druga", ["x", "y"], False)])
        merged = main.merge_day(manual, auto)
        self.assertEqual([s["topic_title"] for s in merged["stories"]], ["Ročna", "Druga"])
        self.assertEqual([s["id"] for s in merged["stories"]], ["story-1", "story-2"])
        self.assertEqual(merged["model"], "Claude (ročna analiza) + gemini-2.5-flash")

    def test_new_auto_run_replaces_old_auto_stories_only(self):
        import main
        day = _day("Claude (ročna analiza) + gemini-2.5-flash",
                   [_story("Ročna", ["a", "b"], True), _story("Stara samodejna", ["x", "y"], False)])
        merged = main.merge_day(day, _day("gemini-3", [_story("Nova samodejna", ["p", "q"], False)]))
        self.assertEqual([s["topic_title"] for s in merged["stories"]], ["Ročna", "Nova samodejna"])
        self.assertEqual(merged["model"], "Claude (ročna analiza) + gemini-3")

    def test_old_archive_without_flag_counts_as_manual_by_model_name(self):
        import main
        old = _day("Claude (ročna analiza)", [{k: v for k, v in _story("Ročna", ["a"], True).items() if k != "manual"}])
        merged = main.merge_day(old, _day("gemini", [_story("Samodejna", ["z", "w"], False)]))
        self.assertEqual([s["topic_title"] for s in merged["stories"]], ["Ročna", "Samodejna"])

    def test_publish_merges_into_existing_archive_and_caps_stats(self):
        import tempfile
        import main
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive = tmp / "archive"
            patches = [mock.patch.object(main, "ARCHIVE_DIR", archive), mock.patch.object(main, "OUTPUT", tmp / "daily.json"),
                       mock.patch.object(main, "MEDIA_STATS_OUTPUT", tmp / "stats.json"),
                       mock.patch.object(main, "STATS_MAX_ARTICLES", 1)]
            for p in patches:
                p.start()
            try:
                main.publish(_day("Claude (ročna analiza)", [_story("Ročna", ["a", "b"], True)]), "2026-11-20")
                main.publish(_day("gemini", [_story("Samodejna", ["x", "y"], False)]), "2026-11-20")
                day = json.loads((archive / "2026-11-20.json").read_text(encoding="utf-8"))
                index = json.loads((archive / "index.json").read_text(encoding="utf-8"))
                stats = json.loads((tmp / "stats.json").read_text(encoding="utf-8"))
            finally:
                for p in patches:
                    p.stop()
        self.assertEqual([s["topic_title"] for s in day["stories"]], ["Ročna", "Samodejna"])
        self.assertEqual(index[0]["stories"], 2)
        self.assertTrue(all(len(m["articles"]) <= 1 for m in stats["media"]))


class AddArticleTest(unittest.TestCase):
    def test_drops_counters_bylines_and_bulleted_end_marker(self):
        page = "Naslov članka\n197\nPrvi odstavek članka z vsebino.\nC. Š., STA\nM. D.\n* OZNAKE\n* [Oznaka](https://x/)\nNoga strani"
        self.assertEqual(clean_page(page, "Naslov članka"), "Prvi odstavek članka z vsebino.")

    def test_24ur_page_keeps_body_and_drops_page_furniture(self):
        page = (FIXTURES / "paste_24ur.txt").read_text(encoding="utf-8")
        text = clean_page(page, "Štrukelj kritičen do učiteljske zbornice: To je projekt politike")
        lines = text.splitlines()
        self.assertTrue(lines[0].startswith("Ministrstvo za izobraževanje bo učiteljsko zbornico"))
        self.assertIn("Odziv ministrstva", lines)
        self.assertTrue(lines[-1].startswith("Na ministrstvu so v odzivu zapisali"))
        for junk in ("Otok ljubezni", "Deli zgodbo", "Avtor", "prednostni vir", "filipinskih", "Ronćevića", "FOTO", "min branja"):
            self.assertNotIn(junk, text)

    def test_n1_page_drops_related_links_inside_body(self):
        page = (FIXTURES / "paste_n1.txt").read_text(encoding="utf-8")
        text = clean_page(page, "Rusija mirovna pogajanja z Ukrajino in ZDA pripravljena obnoviti novembra")
        self.assertIn("predlagal nova mirovna pogajanja", text)
        self.assertIn("Vladimirju Putinu predlagal", text)  # povezava v besedilu ostane kot besedilo
        self.assertIn("Zelenski za zamrznitev fronte v vojni z Rusijo", text)
        for junk in ("Moharič", "Golob", "pred 10 h", "Forbes", "komentarjev", "Foto:", "16:46", "pogajanja\n"):
            self.assertNotIn(junk, text)
        self.assertEqual(len(text.splitlines()), 5)


if __name__ == "__main__":
    unittest.main()
