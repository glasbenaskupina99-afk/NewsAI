"""Doda ročno prilepljen članek (celotno kopirano spletno stran) v zbirko člankov za analizo.

Za medije, ki samodejnega zajema ne dovolijo: v brskalniku kopirate celotno stran, jo shranite v
datoteko (ali prilepite na standardni vhod), orodje pa odstrani menije, povezave, »Preberi še«,
oglase in komentarje ter članek doda v data/raw_articles.json.

    python add_article.py stran.txt --source 24ur --url https://www.24ur.com/... \\
        --title "Štrukelj kritičen do učiteljske zbornice: To je projekt politike" --date 2026-10-21
    pbpaste | python add_article.py - --source Delo --url ... --title ... --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from main import RAW_OUTPUT, write_json
from scraper import SOURCES, Article

# Kategorije medijev, ki niso med samodejnimi viri
MEDIA_CATEGORIES = {s.name: s.category for s in SOURCES} | {
    "Delo": "komercialni", "Večer": "komercialni", "Dnevnik": "komercialni", "Žurnal24": "komercialni",
    "Svet24": "komercialni", "Siol": "komercialni", "N1": "komercialni", "Demokracija": "alternativni",
    "Mladina": "alternativni", "Necenzurirano": "alternativni", "Reporter": "alternativni",
    "Moja Dolenjska": "regionalni", "Primorske novice": "regionalni",
    "Portal24": "komercialni", "Info360": "komercialni", "NaDlani": "komercialni", "Lokalec": "regionalni",
}

_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_LINK_ONLY = re.compile(r"^\s*(?:[*\-|]\s*)?(?:!?\[[^\]]*\]\([^)]*\)\s*\|?\s*)+$")
_BULLET_EMPTY = re.compile(r"^\s*[*\-|·]?\s*$")
_BULLET = re.compile(r"^\s*[*\-·]\s+")
_NUMBERS_ONLY = re.compile(r"^[\d\s.,|/:+-]+$")
# podpisi z začetnicami, npr. »M. D.«, »Ž. N.«, »C. Š., STA«
_BYLINE = re.compile(r"^(?:[A-ZČŠŽĆĐ]{1,2}\.\s?){1,3}(?:,\s*\w+)?$")

# Vrstice, ki niso del članka (meta podatki, gumbi, oglasi)
_JUNK = re.compile(
    r"^(?:preberi(?:te)? (?:še|tudi)|deli(?: zgodbo| članek)?:?$|avtor:?$|foto:|vir:|oglas(?:no sporočilo)?$"
    r"|report this ad|animated$|offensive$|misleading$|brez oglasov$|velikost pisave$|galerija$"
    r"|spremljajte .* prednostni vir|izberite .* prednostni vir|dodajte .* prednostni vir|ste izvedeli kaj koristnega"
    r"|nastavi$|sem že izbral$|čas branja|\d+:\d+$|pred \d+ (?:urami|uro|minutami|h|min)|\d+ min branja"
    r"|berite naprej brezplačno|pridobite dostop|registrirajte se|postanite naročnik|naročite se"
    r"|prijavi(?:te)? se|e-novice|ad$)",
    re.IGNORECASE,
)

# Od te vrstice naprej je samo še okolica članka (komentarji, priporočila, noga strani)
_END = re.compile(
    r"^(?:komentarj(?:i|ev)\b|komentarji\d|število komentarjev|opozorilo: .*kazensk|pravila za objavo komentarjev"
    r"|najbolj brano|sorodni članki|priporoča$|priporočene vsebine|preberite tudi$|več novic$|več iz teme"
    r"|ne spreglejte|predstavitvene vsebine|prejšnji članek|naslednji članek|oznake$|teme$|bodite obveščeni"
    r"|prva stran dneva|šala dneva|anketa)",
    re.IGNORECASE,
)


def _is_dateline(line: str) -> bool:
    if len(line.split()) > 12:
        return False
    has_year = re.search(r"\b20\d\d\b", line)
    has_time = re.search(r"\b\d{1,2}[.:]\d{2}\b|\bpred \d+ ?(?:urami|uro|minutami|min|h)\b|min branja", line)
    return bool(has_year and (has_time or len(line) < 45))


def _normalize(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def clean_page(page: str, title: str | None = None) -> str:
    """Iz kopirane spletne strani izlušči besedilo članka."""
    lines = page.splitlines()

    # Začetek: prva vrstica, ki je enaka naslovu (brez povezav); sicer začetek strani
    start = 0
    if title:
        wanted = _normalize(title).lower()
        for i, raw in enumerate(lines):
            if _normalize(_LINK.sub(r"\1", raw)).lower() == wanted:
                start = i + 1
                break

    body: list[str] = []
    for raw in lines[start:]:
        if _LINK_ONLY.match(raw) or _BULLET_EMPTY.match(raw):
            continue
        line = _normalize(_BULLET.sub("", _LINK.sub(r"\1", raw)))
        if _END.match(line):
            break
        if _JUNK.search(line) or len(line) < 3 or _NUMBERS_ONLY.match(line) or _BYLINE.match(line):
            continue
        # vrstice z datumom in uro objave (npr. »21. 10. 2026 | 18:36«, »Ljubljana, 21. 10. 2026 15.15pred 6 urami«)
        if _is_dateline(line):
            continue
        body.append(line)

    # odstrani zaporedne podvojene vrstice (podnaslovi, ki se ponovijo v galeriji)
    deduped = [ln for i, ln in enumerate(body) if i == 0 or ln != body[i - 1]]
    return "\n".join(deduped).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Doda ročno prilepljen članek v zbirko za analizo")
    parser.add_argument("page", help="datoteka s kopirano stranjo ali - za standardni vhod")
    parser.add_argument("--source", required=True, help="ime medija, npr. 24ur")
    parser.add_argument("--url", required=True)
    parser.add_argument("--title", required=True, help="naslov članka, natanko kot na strani")
    parser.add_argument("--date", help="datum objave, npr. 2026-11-13 ali 2026-11-13T14:26:00+01:00")
    parser.add_argument("--category", help="javni / komercialni / alternativni / regionalni / mednarodni")
    parser.add_argument("--language", default="sl")
    parser.add_argument("--raw", type=Path, default=RAW_OUTPUT, help="zbirka člankov (privzeto data/raw_articles.json)")
    parser.add_argument("--dry-run", action="store_true", help="samo izpiše očiščeno besedilo")
    args = parser.parse_args()

    page = sys.stdin.read() if args.page == "-" else Path(args.page).read_text(encoding="utf-8")
    text = clean_page(page, args.title)
    category = args.category or MEDIA_CATEGORIES.get(args.source)
    if not category:
        parser.error(f"neznan medij {args.source!r}: podajte --category")

    article = Article(
        id=hashlib.sha1(args.url.encode()).hexdigest()[:10], source=args.source, category=category,
        language=args.language, title=args.title, url=args.url, published=args.date, text=text,
    )
    words = len(text.split())
    print(text)
    print(f"\n--- {article.source} | {words} besed | id {article.id}", file=sys.stderr)
    if words < 80:
        print("Opozorilo: zelo kratko besedilo – je članek morda za plačljivim zidom?", file=sys.stderr)
    if args.dry_run:
        return

    try:
        raw = json.loads(args.raw.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {"articles": []}
    raw["articles"] = [a for a in raw["articles"] if a["id"] != article.id] + [article.model_dump()]
    write_json(args.raw, raw)
    print(f"Dodano v {args.raw} (skupaj {len(raw['articles'])} člankov)", file=sys.stderr)


if __name__ == "__main__":
    main()
