"""Glavni cevovod: zajem → združevanje → analiza → data/daily_analysis.json.

    python main.py              # polni cikel (demo podatki, če GEMINI_API_KEY ni nastavljen)
    python main.py --mock       # vedno zapiše demo podatke
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from analyzer import analyze, build_mock_analysis
from scraper import scrape_all

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT = DATA_DIR / "daily_analysis.json"
RAW_OUTPUT = DATA_DIR / "raw_articles.json"

log = logging.getLogger("pipeline")


def write_json(path: Path, payload: dict) -> None:
    """Atomarni zapis, da frontend nikoli ne prebere napol zapisane datoteke."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def run(limit: int, force_mock: bool) -> int:
    load_dotenv(ROOT / ".env")
    has_key = bool(os.getenv("GEMINI_API_KEY"))

    if force_mock:
        result = build_mock_analysis()
    else:
        articles = scrape_all(limit=limit, fulltext=has_key)
        write_json(RAW_OUTPUT, {"articles": [a.model_dump() for a in articles]})
        log.info("Zajetih %d člankov", len(articles))

        if not has_key:
            log.warning("GEMINI_API_KEY ni nastavljen – zapisujem demo podatke")
            result = build_mock_analysis(articles_scraped=len(articles))
        elif not articles:
            log.error("Noben vir ni vrnil člankov – obstoječa analiza ostane nespremenjena")
            return 1
        else:
            result = analyze(articles)
            if not result.stories:
                log.error("Analiza ni vrnila nobene zgodbe – obstoječa analiza ostane nespremenjena")
                return 1

    write_json(OUTPUT, result.model_dump())
    log.info("Zapisano: %s (%d zgodb, mock=%s)", OUTPUT.relative_to(ROOT), len(result.stories), result.is_mock)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="NewsAI dnevni cevovod")
    parser.add_argument("--limit", type=int, default=20, help="največ člankov na vir")
    parser.add_argument("--mock", action="store_true", help="zapiši demo podatke brez zajema")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sys.exit(run(args.limit, args.mock))


if __name__ == "__main__":
    main()
