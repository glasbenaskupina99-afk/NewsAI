"""Uvoz ročno pripravljene analize (npr. iz drugega jezikovnega modela) v data/daily_analysis.json.

Vhod je JSON z zgodbami v obliki StoryAnalysis in seznamom ID-jev člankov iz raw_articles.json:

    {"model": "...", "stories": [{"article_ids": ["ab12...", ...], "topic_title": ..., ...}]}

Neobvezno lahko zgodba vsebuje še "source_checks" (trditve, preverjene v izvirnih dokumentih)
in "missing_context" (dejstva iz izvirnih virov, ki jih ni navedel noben medij).

Slepa analiza: če so mediji v analizi navedeni s psevdonimi (MEDIJ_A, MEDIJ_B …), ki jih za zgodbo
na istem mestu in z istimi članki vrne analyzer.make_aliases, se psevdonimi preslikajo nazaj v imena
medijev, citati pa obnovijo v izvirni obliki (enako kot pri samodejni analizi). Zakrita besedila za
ročno analizo izpiše --print-prompts.

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

from analyzer import (
    _ALIAS, ContextItem, DailyAnalysis, SourceCheck, StoryAnalysis, build_story_report, leaning_from_score,
    make_aliases, source_infos, story_prompt, unmask_analysis,
)
from main import OUTPUT, RAW_OUTPUT, publish
from scraper import Article

log = logging.getLogger("manual")


def main() -> None:
    parser = argparse.ArgumentParser(description="Uvoz ročne analize")
    parser.add_argument("analysis", type=Path)
    parser.add_argument("--raw", type=Path, default=RAW_OUTPUT)
    parser.add_argument("--date", help="datum analize YYYY-MM-DD (privzeto današnji)")
    parser.add_argument("--print-prompts", action="store_true",
                        help="samo izpiše zakrita besedila (MEDIJ_A …) za slepo ročno analizo")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    raw = json.loads(args.raw.read_text(encoding="utf-8"))
    articles = {a["id"]: Article(**a) for a in raw["articles"]}
    spec = json.loads(args.analysis.read_text(encoding="utf-8"))

    if args.print_prompts:
        # Preslikave ne izpišemo: kdor analizira, je ne sme videti pred oceno. Shranimo jo ob analizi,
        # da jo uvoz lahko uporabi (polje »aliases« v zgodbi ima prednost).
        alias_maps = []
        for i, story in enumerate(spec["stories"]):
            cluster = [articles[aid] for aid in story["article_ids"]]
            aliases = story.get("aliases") or make_aliases(cluster, i)
            alias_maps.append({"article_ids": story["article_ids"], "aliases": aliases})
            print(f"===== ZGODBA {i + 1}\n{story_prompt(cluster, aliases)}\n")
        alias_path = args.analysis.with_suffix(".aliases.json")
        alias_path.write_text(json.dumps(alias_maps, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("Preslikava psevdonimov je shranjena v %s (ne odpirajte je pred oceno)", alias_path)
        return

    stories = []
    for i, story in enumerate(spec["stories"]):
        cluster = [articles[aid] for aid in story["article_ids"]]
        for cov in story["coverage_comparison"]:
            if cov.get("lean_score") is not None and "bias_leaning" not in cov:
                cov["bias_leaning"] = leaning_from_score(cov["lean_score"])
        analysis = StoryAnalysis.model_validate(story)
        blind = all(_ALIAS.fullmatch(c.media_name) for c in analysis.coverage_comparison)
        if blind:
            aliases = story.get("aliases") or make_aliases(cluster, i)
            analysis = unmask_analysis(analysis, aliases, cluster)
        report = build_story_report(analysis, cluster, i)
        report.blind_analysis = blind
        report.manual = True
        report.source_checks = [SourceCheck.model_validate(c) for c in story.get("source_checks", [])]
        report.missing_context = [ContextItem.model_validate(c) for c in story.get("missing_context", [])]
        report.not_covered_by = story.get("not_covered_by", [])
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
    publish(result, args.date)
    log.info("Zapisano: %s in arhiv (%d zgodb)", OUTPUT, len(stories))


if __name__ == "__main__":
    main()
