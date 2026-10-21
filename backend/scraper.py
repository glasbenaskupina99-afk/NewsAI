"""Zajem novic iz RSS virov in ekstrakcija čistega besedila s trafilatura.

Uporaba iz terminala:
    python scraper.py                  # vsi viri, s polnim besedilom
    python scraper.py --limit 5 --no-fulltext
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import html
import logging
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser
import trafilatura
from pydantic import BaseModel

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; NewsAI-BiasAnalyzer/0.1; +https://github.com/glasbenaskupina99-afk/NewsAI)"
MAX_TEXT_CHARS = 15000


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    category: str  # "javni", "komercialni", "alternativni", "mednarodni"
    language: str
    fallback_urls: tuple[str, ...] = ()

    @property
    def is_international(self) -> bool:
        return self.category == "mednarodni"


SOURCES: list[Source] = [
    Source("MMC RTV SLO", "https://www.rtvslo.si/feeds/00.xml", "javni", "sl"),
    Source("24ur", "https://www.24ur.com/rss", "komercialni", "sl"),
    Source("Nova24TV", "https://nova24tv.si/feed/", "alternativni", "sl"),
    Source("Mladina", "https://www.mladina.si/rss/", "alternativni", "sl",
           fallback_urls=("https://www.mladina.si/rss.xml", "https://www.mladina.si/feed/")),
    Source("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml", "mednarodni", "en"),
]


class Article(BaseModel):
    id: str
    source: str
    category: str
    language: str
    title: str
    url: str
    published: str | None = None
    summary: str = ""
    text: str = ""

    @property
    def body(self) -> str:
        """Najboljše razpoložljivo besedilo (polno besedilo ali RSS povzetek)."""
        return self.text or self.summary


def _clean(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _published(entry) -> str | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc).isoformat()


def fetch_feed(source: Source, limit: int = 15) -> list[Article]:
    """Prebere RSS vir in vrne do `limit` člankov (brez polnega besedila)."""
    for url in (source.url, *source.fallback_urls):
        feed = feedparser.parse(url, agent=USER_AGENT)
        if feed.entries:
            break
        log.warning(
            "%s: RSS ni berljiv: %s (HTTP %s, %s, %s)", source.name, url, feed.get("status"),
            feed.get("headers", {}).get("content-type"), feed.get("bozo_exception"),
        )
    else:
        return []

    articles = []
    for entry in feed.entries[:limit]:
        url = entry.get("link", "").strip()
        title = _clean(entry.get("title", ""))
        if not url or not title:
            continue
        articles.append(
            Article(
                id=hashlib.sha1(url.encode()).hexdigest()[:10],
                source=source.name,
                category=source.category,
                language=source.language,
                title=title,
                url=url,
                published=_published(entry),
                summary=_clean(entry.get("summary", ""))[:1000],
            )
        )
    log.info("%s: %d člankov", source.name, len(articles))
    return articles


def extract_text(url: str) -> str:
    """Prenese stran in vrne čisto besedilo članka (prazen niz ob napaki)."""
    try:
        # urllib (namesto trafilatura.fetch_url) upošteva sistemski HTTP(S)_PROXY
        # bbc.co.uk izven VB tako ali tako preusmeri na bbc.com
        url = url.replace("://www.bbc.co.uk/", "://www.bbc.com/")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=20) as response:
            downloaded = response.read()
        text = trafilatura.extract(
            downloaded, include_comments=False, include_tables=False, favor_precision=True
        )
        return (text or "")[:MAX_TEXT_CHARS]
    except Exception as exc:  # trafilatura lahko vrže različne napake omrežja/parserja
        log.debug("Ekstrakcija ni uspela za %s: %s", url, exc)
        return ""


def enrich_with_text(articles: list[Article], workers: int = 8) -> list[Article]:
    """Vzporedno doda polno besedilo vsem člankom."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        texts = list(pool.map(extract_text, [a.url for a in articles]))
    for article, text in zip(articles, texts):
        article.text = text
    ok = sum(1 for t in texts if t)
    log.info("Polno besedilo pridobljeno za %d/%d člankov", ok, len(articles))
    return articles


def scrape_all(
    sources: list[Source] = SOURCES, limit: int = 15, fulltext: bool = True
) -> list[Article]:
    articles: list[Article] = []
    for source in sources:
        try:
            articles.extend(fetch_feed(source, limit))
        except Exception as exc:
            log.warning("%s: napaka pri zajemu: %s", source.name, exc)
    if fulltext and articles:
        enrich_with_text(articles)
    return articles


def main() -> None:
    parser = argparse.ArgumentParser(description="Preizkus RSS zajema")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--no-fulltext", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    articles = scrape_all(limit=args.limit, fulltext=not args.no_fulltext)
    for a in articles:
        print(f"[{a.source:12}] {a.title[:80]:80} | besedilo: {len(a.text):5} zn.")
    print(f"\nSkupaj: {len(articles)} člankov iz {len({a.source for a in articles})} virov")


if __name__ == "__main__":
    main()
