"""Tworzy podzbior sgjp.tab zawierajacy wszystkie formy dla wybranych lematow
zwiazanych z lasem, natura i zwierzetami."""

import sys
from pathlib import Path

ROOT = Path(__file__).parent
SRC = ROOT / "sgjp.tab"
DST = ROOT / "test" / "sgjp_subset.tab"
LEMMA_LIST = ROOT / "test" / "subset_lemmas.txt"

NOUNS = [
    # drzewa i rosliny
    "drzewo", "las", "liść", "gałąź", "korzeń", "mech",
    "grzyb", "jagoda", "pień", "kwiat", "trawa",
    "dąb", "sosna", "brzoza", "świerk", "klon", "jodła", "lipa", "buk",
    "wierzba",
    # krajobraz i pogoda
    "dolina", "góra", "skała", "kamień", "rzeka",
    "jezioro", "łąka", "niebo", "ziemia", "woda",
    "deszcz", "śnieg", "mgła", "wiatr", "burza", "ogień",
    "słońce", "chmura",
    # zwierzeta
    "zwierzę", "ptak", "ryba", "jeleń", "dzik", "niedźwiedź",
    "wilk", "lis", "zając", "bóbr", "ryś", "żubr",
    "sowa", "dzięcioł", "kruk", "bocian", "orzeł",
    "pszczoła", "mrówka", "pająk", "żaba", "wąż",
]

VERBS = [
    # rosniecie, ruch w przyrodzie
    "rosnąć", "kwitnąć", "więdnąć", "opadać", "szumieć", "płynąć",
    "wschodzić", "zachodzić", "świecić", "padać", "wiać", "grzmieć",
    "topnieć", "kapać",
    # czynnosci zwierzat
    "biegać", "skakać", "latać", "pływać", "polować", "śpiewać",
    "wyć", "ryczeć", "syczeć", "pełzać", "kopać", "gniazdować",
    "karmić", "łowić", "tropić", "węszyć",
    # interakcje
    "sadzić", "zbierać", "łapać", "uciekać", "gonić", "chronić",
    "rąbać", "ciąć", "łamać", "budzić",
]

LEMMAS = sorted(set(NOUNS + VERBS))
assert len(LEMMAS) == 100, f"oczekiwano 100 lematow, jest {len(LEMMAS)}"

target = set(LEMMAS)
seen = set()
written = 0

with open(SRC, encoding="utf-8") as fin, open(DST, "w", encoding="utf-8") as fout:
    for line in fin:
        # lemma = pole 1 do pierwszego ':'
        try:
            tab1 = line.index("\t")
            tab2 = line.index("\t", tab1 + 1)
        except ValueError:
            continue
        lemma_field = line[tab1 + 1:tab2]
        lemma = lemma_field.split(":", 1)[0]
        if lemma in target:
            fout.write(line)
            seen.add(lemma)
            written += 1

missing = target - seen
print(f"Zapisano {written} wierszy do {DST}", file=sys.stderr)
print(f"Pokryto {len(seen)}/{len(target)} lematow", file=sys.stderr)
if missing:
    print(f"Brakujace lematy: {sorted(missing)}", file=sys.stderr)

with open(LEMMA_LIST, "w", encoding="utf-8") as f:
    for lemma in LEMMAS:
        f.write(lemma + "\n")
print(f"Zapisano liste lematow do {LEMMA_LIST}", file=sys.stderr)
