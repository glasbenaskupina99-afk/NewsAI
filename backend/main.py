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
RUN_RESULT = DATA_DIR / "run_result.json"  # rezultat zadnjega samodejnega zagona (za ponovno objavo)
ARCHIVE_DIR = DATA_DIR / "archive"
MEDIA_STATS_OUTPUT = DATA_DIR / "media_stats.json"

LEAN_DEFAULT_SCORE = {"Levo": -2.5, "Sredina-Levo": -1.0, "Sredina": 0.0, "Sredina-Desno": 1.0, "Desno": 2.5}
AGENCY_COPY_THRESHOLD = 75
# Statistika se računa iz vseh člankov; v datoteko gre le toliko najnovejših (velikost ostane omejena)
STATS_MAX_ARTICLES = 30
STATS_MAX_POINTS = 100

log = logging.getLogger("pipeline")


def write_json(path: Path, payload: dict) -> None:
    """Atomarni zapis, da frontend nikoli ne prebere napol zapisane datoteke."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def build_media_stats(archive_dir: Path = ARCHIVE_DIR) -> dict:
    """Zbere statistiko po medijih iz vseh ne-demo dni v arhivu za hiter prikaz na spletni strani."""
    index_path = archive_dir / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        index = []

    by_media: dict[str, dict] = {}
    days_count = 0
    for entry in index:
        if entry.get("is_mock"):
            continue
        date = entry.get("date")
        if not date:
            continue
        try:
            day = json.loads((archive_dir / f"{date}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        days_count += 1
        for story in day.get("stories", []):
            for c in story.get("coverage_comparison", []):
                name = c["media_name"]
                score = c.get("lean_score")
                if not isinstance(score, (int, float)):
                    score = LEAN_DEFAULT_SCORE.get(c.get("bias_leaning", "Sredina"), 0.0)
                core = c.get("shared_core") or {}
                shared_pct = core.get("shared_percent")
                own_pct = core.get("own_percent")
                m = by_media.setdefault(name, {
                    "name": name,
                    "category": c.get("category", ""),
                    "lean": [],
                    "sens": [],
                    "words": [],
                    "own": [],
                    "one_sided": 0,
                    "agency_copies": 0,
                    "core_count": 0,
                    "articles": [],
                })
                m["lean"].append(round(float(score), 2))
                m["sens"].append(int(c.get("sensationalism_score", 1)))
                if c.get("word_count"):
                    m["words"].append(int(c["word_count"]))
                if isinstance(own_pct, (int, float)):
                    m["own"].append(int(own_pct))
                    m["core_count"] += 1
                    if isinstance(shared_pct, (int, float)) and shared_pct >= AGENCY_COPY_THRESHOLD:
                        m["agency_copies"] += 1
                if c.get("sides_represented") == "Samo ena stran":
                    m["one_sided"] += 1
                m["articles"].append({
                    "date": date,
                    "story_id": story.get("id", ""),
                    "topic_title": story.get("topic_title", ""),
                    "article_title": c.get("article_title", ""),
                    "article_url": c.get("article_url", ""),
                    "lean_score": round(float(score), 2),
                    "bias_leaning": c.get("bias_leaning", "Sredina"),
                    "sensationalism_score": int(c.get("sensationalism_score", 1)),
                    "sides_represented": c.get("sides_represented", ""),
                    "shared_percent": shared_pct,
                })

    media_rows = []
    for m in by_media.values():
        count = len(m["lean"])
        avg_lean = round(sum(m["lean"]) / count, 2)
        orientation = None
        if count >= 2:
            orientation = "levo" if avg_lean <= -0.5 else "desno" if avg_lean >= 0.5 else "sredina"
        media_rows.append({
            "name": m["name"],
            "category": m["category"],
            "count": count,
            "lean": m["lean"][:STATS_MAX_POINTS],  # arhiv je urejen od najnovejšega dne
            "avg_lean": avg_lean,
            "min_lean": min(m["lean"]),
            "max_lean": max(m["lean"]),
            "avg_sens": round(sum(m["sens"]) / count, 2),
            "one_sided_share": round(100 * m["one_sided"] / count),
            "avg_words": round(sum(m["words"]) / len(m["words"])) if m["words"] else None,
            "avg_own_percent": round(sum(m["own"]) / len(m["own"])) if m["own"] else None,
            "agency_copy_share": round(100 * m["agency_copies"] / m["core_count"]) if m["core_count"] else None,
            "orientation": orientation,
            "articles": sorted(m["articles"], key=lambda a: (a["date"], a["story_id"]), reverse=True)[:STATS_MAX_ARTICLES],
        })
    media_rows.sort(key=lambda r: r["avg_lean"])
    return {"days": days_count, "media": media_rows}


def _story_urls(story: dict) -> set[str]:
    return {c["article_url"] for c in story.get("coverage_comparison", []) if c.get("article_url")}


def _overlaps(a: dict, b: dict) -> bool:
    """Isti dogodek: vsaj dva skupna članka ali vsaj polovica člankov manjše zgodbe."""
    ua, ub = _story_urls(a), _story_urls(b)
    shared = len(ua & ub)
    return shared >= 2 or (shared >= 1 and shared * 2 >= min(len(ua), len(ub)))


def _merge_models(*models: str) -> str:
    parts = [p.strip() for m in models if m for p in m.split(" + ")]
    return " + ".join(dict.fromkeys(p for p in parts if p))


def merge_day(existing: dict | None, new: dict) -> dict:
    """Združi novo analizo z obstoječo za isti dan.

    Zgodbe istega izvora (ročne / samodejne) nova analiza zamenja, zgodbe drugega izvora ostanejo.
    Ročne zgodbe imajo prednost: samodejna zgodba o istem dogodku se izpusti.
    """
    if not existing or existing.get("is_mock") or new.get("is_mock"):
        return new
    new_origins = {bool(s.get("manual")) for s in new["stories"]}
    if not new_origins:
        return existing
    # starejši arhivi nimajo polja »manual«: izvor razberemo iz imena modela dneva
    day_is_manual = "ročn" in existing.get("model", "").lower()
    old_stories = [{**s, "manual": bool(s.get("manual", day_is_manual))} for s in existing.get("stories", [])]
    kept = [s for s in old_stories if s["manual"] not in new_origins]
    if not kept:
        return new
    combined = kept + new["stories"]
    manual = [s for s in combined if s.get("manual")]
    auto = [s for s in combined if not s.get("manual") and not any(_overlaps(s, m) for m in manual)]
    stories = manual + auto
    for i, story in enumerate(stories):
        story["id"] = f"story-{i + 1}"
    new_is_manual = True in new_origins
    # iz obstoječega opisa modela obdržimo le del drugega izvora (ročne analize imajo v imenu »ročn«)
    kept_models = [p for p in _merge_models(existing.get("model", "")).split(" + ")
                   if p and ("ročn" in p.lower()) != new_is_manual]
    still_other = (manual if not new_is_manual else auto)
    return {
        **new,
        "model": _merge_models(*(kept_models if still_other else []), new["model"]),
        "articles_scraped": max(existing.get("articles_scraped", 0), new.get("articles_scraped", 0)),
        "stories": stories,
    }


def publish(result, date: str | None = None) -> None:
    """Zapiše analizo kot najnovejšo in v arhiv po dnevih (data/archive/YYYY-MM-DD.json + index.json).

    Če za ta dan arhiv že obstaja, se zgodbi združita (merge_day): samodejni zagon ne prepiše ročnih analiz.
    """
    payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)
    date = date or payload["generated_at"][:10]
    day_path = ARCHIVE_DIR / f"{date}.json"
    try:
        existing = json.loads(day_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        existing = None
    payload = merge_day(existing, payload)
    write_json(day_path, payload)

    index_path = ARCHIVE_DIR / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        index = []
    index = [e for e in index if e["date"] != date] + [
        {"date": date, "stories": len(payload["stories"]), "model": payload["model"], "is_mock": payload["is_mock"]}
    ]
    index.sort(key=lambda e: e["date"], reverse=True)
    write_json(index_path, index)
    write_json(MEDIA_STATS_OUTPUT, build_media_stats(ARCHIVE_DIR))

    # daily_analysis.json je vedno najnovejši dan v arhivu
    if index[0]["date"] == date:
        write_json(OUTPUT, payload)


def _existing_is_real() -> bool:
    try:
        return not json.loads(OUTPUT.read_text(encoding="utf-8")).get("is_mock", True)
    except (OSError, ValueError):
        return False


def run(limit: int, force_mock: bool, max_stories: int, scrape_only: bool = False) -> int:
    load_dotenv(ROOT / ".env")
    has_key = bool(os.getenv("GEMINI_API_KEY"))

    if scrape_only:
        articles = scrape_all(limit=limit, fulltext=True)
        write_json(RAW_OUTPUT, {"articles": [a.model_dump() for a in articles]})
        log.info("Zajetih %d člankov → %s", len(articles), RAW_OUTPUT.relative_to(ROOT))
        return 0 if articles else 1

    if force_mock:
        result = build_mock_analysis()
    else:
        articles = scrape_all(limit=limit, fulltext=has_key)
        write_json(RAW_OUTPUT, {"articles": [a.model_dump() for a in articles]})
        log.info("Zajetih %d člankov", len(articles))

        if not has_key and _existing_is_real():
            log.warning("GEMINI_API_KEY ni nastavljen – obstoječa prava analiza ostane nespremenjena")
            return 0
        if not has_key:
            log.warning("GEMINI_API_KEY ni nastavljen – zapisujem demo podatke")
            result = build_mock_analysis(articles_scraped=len(articles))
        elif not articles:
            log.error("Noben vir ni vrnil člankov – obstoječa analiza ostane nespremenjena")
            return 1
        else:
            result = analyze(articles, max_stories=max_stories)
            if not result.stories:
                log.error("Analiza ni vrnila nobene zgodbe – obstoječa analiza ostane nespremenjena")
                return 1

    if result.is_mock:
        write_json(OUTPUT, result.model_dump())  # demo podatki ne gredo v arhiv
    else:
        # shranimo rezultat, da ga lahko CI ob sporu pri pushu objavi znova na novejšem stanju
        write_json(RUN_RESULT, result.model_dump())
        publish(result)
    log.info("Zapisano: %s (%d zgodb, mock=%s)", OUTPUT.relative_to(ROOT), len(result.stories), result.is_mock)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="NewsAI dnevni cevovod")
    parser.add_argument("--limit", type=int, default=20, help="največ člankov na vir")
    parser.add_argument("--max-stories", type=int, default=5, help="največ zgodb za analizo")
    parser.add_argument("--scrape-only", action="store_true",
                        help="samo zajem s polnim besedilom v data/raw_articles.json")
    parser.add_argument("--mock", action="store_true", help="zapiši demo podatke brez zajema")
    parser.add_argument("--republish", type=Path, metavar="RESULT_JSON",
                        help="brez zajema in analize znova objavi shranjen rezultat (npr. data/run_result.json)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.republish:
        publish(json.loads(args.republish.read_text(encoding="utf-8")))
        log.info("Znova objavljeno: %s", args.republish)
        sys.exit(0)
    sys.exit(run(args.limit, args.mock, args.max_stories, args.scrape_only))


if __name__ == "__main__":
    main()
