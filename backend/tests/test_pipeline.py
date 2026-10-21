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
from analyzer import DailyAnalysis, analyze_story, build_mock_analysis, cluster_lexical, verify_quotes  # noqa: E402
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
        fake = {
            "topic_title": "Dogovor", "international_baseline": "Ministri so se dogovorili.",
            "neutral_summary": "Dogovor sprejet.",
            "coverage_comparison": [
                {"media_name": "BBC World", "article_title": "x", "article_url": "https://evil.example",
                 "sensationalism_score": 2, "bias_leaning": "Sredina",
                 "bias_evidence_quotes": ["Ministers agreed a deal"], "omitted_facts": []},
                {"media_name": "Nova24TV", "article_title": "x", "article_url": "https://evil.example",
                 "sensationalism_score": 8, "bias_leaning": "Desno",
                 "bias_evidence_quotes": ["Citat, ki ga ni"], "omitted_facts": ["Datum dogovora."]},
                {"media_name": "Neznan", "article_title": "x", "article_url": "x",
                 "sensationalism_score": 1, "bias_leaning": "Levo",
                 "bias_evidence_quotes": ["q"], "omitted_facts": []},
            ],
        }
        client = SimpleNamespace(models=SimpleNamespace(
            generate_content=lambda **kw: SimpleNamespace(text=json.dumps(fake))))
        story = analyze_story(client, "test-model", cluster, 0)
        self.assertEqual(len(story.coverage_comparison), 2)
        bbc, n24 = story.coverage_comparison
        self.assertEqual(bbc.article_url, "https://example.org/BBC World")
        self.assertTrue(bbc.quotes_verified)
        self.assertFalse(n24.quotes_verified)
        self.assertTrue(story.has_international_source)

    def test_invalid_model_output_is_rejected(self):
        bad = {"topic_title": "t", "international_baseline": "b", "neutral_summary": "s",
               "coverage_comparison": [{"media_name": "A", "article_title": "x", "article_url": "u",
                                        "sensationalism_score": 42, "bias_leaning": "Zelo levo",
                                        "bias_evidence_quotes": [], "omitted_facts": []}]}
        client = SimpleNamespace(models=SimpleNamespace(
            generate_content=lambda **kw: SimpleNamespace(text=json.dumps(bad))))
        with mock.patch.object(analyzer.time, "sleep"), self.assertRaises(RuntimeError):
            analyzer._generate(client, "m", "p", analyzer.StoryAnalysis, retries=1)

    def test_mock_is_valid_schema(self):
        mock = build_mock_analysis()
        roundtrip = DailyAnalysis.model_validate_json(mock.model_dump_json())
        self.assertTrue(roundtrip.is_mock)
        self.assertGreaterEqual(len(roundtrip.stories), 3)


if __name__ == "__main__":
    unittest.main()
