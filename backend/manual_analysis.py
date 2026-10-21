"""Uvoz ročno pripravljene analize (npr. iz drugega jezikovnega modela) v data/daily_analysis.json.

Vhod je JSON z zgodbami v obliki StoryAnalysis in seznamom ID-jev člankov iz raw_articles.json:

    {"model": "...", "stories": [{"article_ids": ["ab12...", ...], "topic_title": ..., ...}]}

Za vsako zgodbo se uporabi ista validacija kot pri Gemini: Pydantic shema, preverjanje
dobesednih citatov ter naslovi in URL-ji iz zajetih podatkov.

    python manual_analysis.py analysis.json [--raw ../data/raw_articles.json]
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from analyzer import DailyAnalysis, StoryAnalysis, build_story_report, source_infos
from main import OUTPUT, RAW_OUTPUT, write_json
from scraper import Article

log = logging.getLogger("manual")


def main() -> None:
    parser = argparse.ArgumentParser(description="Uvoz ročne analize")
    parser.add_argument("analysis", type=Path)
    parser.add_argument("--raw", type=Path, default=RAW_OUTPUT)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    raw = json.loads(args.raw.read_text(encoding="utf-8"))
    articles = {a["id"]: Article(**a) for a in raw["articles"]}
    spec = json.loads(args.analysis.read_text(encoding="utf-8"))

    stories = []
    for i, story in enumerate(spec["stories"]):
        cluster = [articles[aid] for aid in story["article_ids"]]
        report = build_story_report(StoryAnalysis.model_validate(story), cluster, i)
        for c in report.coverage_comparison:
            if not c.quotes_verified:
                log.warning("%s: citat ni dobesedno najden v besedilu", c.media_name)
        stories.append(report)

    result = DailyAnalysis(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        model=spec.get("model", "ročna analiza"),
        is_mock=False,
        sources=source_infos(),
        articles_scraped=len(articles),
        stories=stories,
    )
    write_json(OUTPUT, result.model_dump())
    log.info("Zapisano: %s (%d zgodb)", OUTPUT, len(stories))


if __name__ == "__main__":
    main()
