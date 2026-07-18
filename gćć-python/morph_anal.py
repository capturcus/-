import json
import sys
import time
from typing import NamedTuple

import lexer

CASES = {"nom", "gen", "dat", "acc", "inst", "loc", "voc"}
NUMBERS = {"sg", "pl"}
# SGJP rodzajowe tagi → znormalizowany rodzaj koarse (m/f/n).
# m1 (męskoosobowy), m2 (męskozwierzęcy), m3 (męskorzeczowy) → wszystkie m.
# n1/n2 → n. p1/p2/p3 (gramatyczne kategorie pluralne) ignorowane — nie są rodzajem słowa.
_GENDER_MAP = {
    "m1": "m", "m2": "m", "m3": "m", "m": "m",
    "f": "f",
    "n1": "n", "n2": "n", "n": "n",
}
PARTICIPLE_POS = {"pact", "ppas"}
# Imiesłowy i gerundia SGJP lematyzuje do bezokolicznika — przy ładowaniu
# zastępujemy lemmę formą cytowaną (mianownik sg: m1 dla imiesłowów, n dla
# gerundiów), żeby `administrujący` i `polubienie` były własnymi lemmami,
# a nie czasownikami.
CITATION_POS = PARTICIPLE_POS | {"ger"}
VERB_POS = frozenset({
    "fin", "impt", "inf", "imps", "praet", "pcon",
    "winien", "bedzie", "fut", "cond",
})


class MorphAnalysis(NamedTuple):
    pos: str
    case: frozenset
    number: str  # "sg" / "pl" / None (verby, prep, atom)
    gender: frozenset  # frozenset znormalizowanych rodzajów (m/f/n) lub None
    lemma: str
    tag: str  # surowy tag SGJP, np. "fin:sg:pri:imperf"
    qualifier: str  # SGJP qualifier (np. "ryb.", "przest.", "pot.") lub ""
    # Lemat czasownika bazowego dla gerundiów (pos == "ger"), inaczej None.
    # Re-lematyzacja form cytowanych podmienia `lemma` na rzeczownik
    # ("polubieniem" → "polubienie"); `base` zachowuje czasownik ("polubić"),
    # bo referencje gerundialne do funkcji potrzebują obu.
    base: str = None


_SENTINEL = object()

# ---------- własne hasła języka Ć ----------
#
# Słowa kluczowe języka, których nie ma w SGJP — wstrzykiwane po załadowaniu
# słownika, identycznie dla `load()` (sgjp.tab) i `load_redis()`. Dzięki temu
# działają niezależnie od wydania SGJP i trybu pracy; wpis wstrzyknięty
# PRZYKRYWA ewentualne przyszłe hasło słownikowe (determinizm).
# „literał" to nośnik przypadka dla literałów w wywołaniach funkcji
# (`zawieź literałem "samochód" psa do domu`) — regularna odmiana
# męskorzeczowa (m3), tagi w stylu SGJP.
WŁASNE_HASŁA = [
    ("literał", "literał", "subst:sg:nom.acc:m3"),
    ("literału", "literał", "subst:sg:gen:m3"),
    ("literałowi", "literał", "subst:sg:dat:m3"),
    ("literałem", "literał", "subst:sg:inst:m3"),
    ("literale", "literał", "subst:sg:loc.voc:m3"),
    ("literały", "literał", "subst:pl:nom.acc.voc:m3"),
    ("literałów", "literał", "subst:pl:gen:m3"),
    ("literałom", "literał", "subst:pl:dat:m3"),
    ("literałami", "literał", "subst:pl:inst:m3"),
    ("literałach", "literał", "subst:pl:loc:m3"),
]


def _własne_analizy():
    """dict[forma → [MorphAnalysis]] zbudowany z WŁASNE_HASŁA tą samą
    ścieżką co wpisy słownikowe (`_morpho_for_tag`)."""
    out = {}
    for form, lemma, tag in WŁASNE_HASŁA:
        pos = tag.partition(":")[0]
        case, number, gender = _morpho_for_tag(tag.split(":"))
        out.setdefault(form, []).append(MorphAnalysis(
            pos=pos, case=case, number=number, gender=gender,
            lemma=lemma, tag=tag, qualifier="", base=None,
        ))
    return out


def _morpho_for_tag(tag_parts):
    """Wyciąga (case, number, gender) z parts tagu SGJP.
    Iteruje raz po częściach — wykrywa po przynależności wartości do CASES,
    NUMBERS, _GENDER_MAP. Zwraca pierwsze trafienie każdej kategorii."""
    case = None
    number = None
    gender = None
    for tp in tag_parts[1:]:
        atoms = tp.split(".")
        if case is None:
            cases_here = frozenset(p for p in atoms if p in CASES)
            if cases_here:
                case = cases_here
                continue
        if number is None:
            for p in atoms:
                if p in NUMBERS:
                    number = p
                    break
            if number is not None:
                continue
        if gender is None:
            genders_here = frozenset(
                _GENDER_MAP[p] for p in atoms if p in _GENDER_MAP
            )
            if genders_here:
                gender = genders_here
                continue
    return case, number, gender


def load(path):
    print(f"Loading {path}...", file=sys.stderr)
    t0 = time.time()
    db = {}
    preps = {}
    citation = {}
    morpho_cache = {}
    morpho_cache_get = morpho_cache.get
    # Bind w lokalnej zmiennej żeby zminimalizować dispatch w gorącej pętli.
    tuple_new = tuple.__new__
    Ma = MorphAnalysis
    verb_pos = VERB_POS
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            form, lemma_field, tag = parts[0], parts[1], parts[2]
            qualifiers = parts[4] if len(parts) > 4 else ""
            lemma = lemma_field.partition(":")[0]
            # partition jest szybsze od full split gdy chcemy tylko pos
            pos = tag.partition(":")[0]
            # Cache po tagu — jeden lookup zwraca (case, number, gender).
            cached = morpho_cache_get(tag, _SENTINEL)
            tag_parts = None  # leniwe — split tylko gdy potrzebny
            if cached is _SENTINEL:
                tag_parts = tag.split(":")
                if pos in verb_pos:
                    cached = (None, None, None)
                else:
                    cached = _morpho_for_tag(tag_parts)
                morpho_cache[tag] = cached
            case, number, gender = cached
            # tuple.__new__ omija NamedTuple.__new__ (walidację argumentów
            # I defaulty pól!) — `base` musi być podany jawnie jako None.
            db.setdefault(form, []).append(
                tuple_new(Ma, (pos, case, number, gender, lemma, tag,
                               qualifiers, None))
            )
            if pos == "prep" and case:
                preps.setdefault(lemma, set()).update(case)
            if pos in CITATION_POS:
                if tag_parts is None:
                    tag_parts = tag.split(":")
                # Forma cytowana: mianownik sg, aff; imiesłowy dodatkowo m1
                # (gerundia są zawsze nijakie — bez warunku na rodzaj).
                gender_ok = pos == "ger" or (
                    len(tag_parts) >= 4 and "m1" in tag_parts[3].split(".")
                )
                if (
                    len(tag_parts) >= 3
                    and tag_parts[1] == "sg"
                    and "nom" in tag_parts[2].split(".")
                    and gender_ok
                    and tag_parts[-1] == "aff"
                ):
                    citation[(pos, lemma)] = form
    for anas in db.values():
        for i, ana in enumerate(anas):
            if ana.pos in CITATION_POS:
                # `ana.lemma` to tu JESZCZE oryginalny lemat SGJP (czasownik) —
                # dla gerundiów zachowujemy go w `base` zanim podmienimy.
                anas[i] = ana._replace(
                    lemma=citation.get((ana.pos, ana.lemma), ana.lemma),
                    base=ana.lemma if ana.pos == "ger" else None,
                )
    db.update(_własne_analizy())
    print(f"Loaded {len(db)} forms in {time.time() - t0:.1f}s", file=sys.stderr)
    return db, preps


def analyze(tokens, db):
    out = []
    for tok in tokens:
        kind, value = tok[0], tok[1]
        line = getattr(tok, "line", None)
        if kind is lexer.Token.WORD:
            # SGJP keyed by lowercase; surface może być mixed-case po refaktorze.
            seg_analyses = [db.get(seg.lower(), []) for seg in value]
            out.append(lexer.Tok(kind, value, seg_analyses, line=line))
        else:
            out.append(lexer.Tok(kind, value, None, line=line))
    return out


_ADJ_LIKE_POS = {"adj", "pact", "ppas"}


def _cap_lemma(lemma, surface_seg):
    """Capitalize lemma jeśli surface zaczynał się wielką literą.
    Pozwala rozróżnić typ (`Forma` → `("Forma",)`) od zmiennej (`forma` →
    `("forma",)`) w przestrzeni lemm."""
    if surface_seg and surface_seg[0].isupper() and lemma:
        return lemma[:1].upper() + lemma[1:]
    return lemma


def canonical(token):
    """Kanonikalizacja tokenu do tuple lemm per segment (tryb lenient).

    Per-segment preferuj analizy adj-like, matchuj citation form
    (`a.lemma == seg.lower()`), inaczej fallback do `pool[0]`. Używane dla
    keywordów (`canonical(t) == ("aby",)`) i prepów — surface zwykle
    citation, fallback rzadko odpala.

    Segmenty bez analiz (non-Polish, single-letter) → użyj surface.
    Kapitalizacja: `_cap_lemma` per-segment na finalny lemmat.

    Walidacja nazw typów (głowa-rzeczownik w wymaganym przypadku, reszta
    passthrough, min-rest tie-break) jest w `identifier.canonical_type` —
    używa tej samej logiki co identyfikatory zmiennych/pól."""
    _, value, analyses = token[0], token[1], token[2]
    out = []
    for seg, anas in zip(value, analyses):
        if not anas or len(seg) == 1:
            out.append(seg)  # zachowaj oryginalny case (np. single-letter "X")
            continue
        # adj-priority + citation match + pool[0] fallback. seg.lower() chroni
        # przed pułapką homograficzną dla capital surface (`Pora` → "pora").
        pool = [a for a in anas if a.pos in _ADJ_LIKE_POS] or anas
        chosen = next((a for a in pool if a.lemma == seg.lower()), pool[0])
        out.append(_cap_lemma(chosen.lemma, seg))
    return tuple(out)


# ---------- tryb redisowy (gćć.py --redis) ----------
#
# Zamiast ładować sgjp.tab do pamięci (~8 s), analizy leżą w lokalnym
# Redisie pod kluczami `sgjp:f:<forma>` — zmigrowane jednorazowo przez
# `sgjp_do_redisa.py`. Migracja zapisuje GOTOWE analizy (po passie
# re-lematyzacji imiesłowów/gerundiów do form cytowanych), więc semantyka
# jest identyczna z `load()`.

REDIS_PREFIX = "sgjp:"
REDIS_SCHEMA = 2


def analysis_to_jsonable(ana):
    """MorphAnalysis → lista JSON-owalna (frozensety jako posortowane listy).
    Jedyna para serializacyjna — używana przez migrację i `RedisDb`."""
    return [
        ana.pos,
        sorted(ana.case) if ana.case is not None else None,
        ana.number,
        sorted(ana.gender) if ana.gender is not None else None,
        ana.lemma,
        ana.tag,
        ana.qualifier,
        ana.base,
    ]


def analysis_from_jsonable(lst):
    pos, case, number, gender, lemma, tag, qualifier, base = lst
    return tuple.__new__(MorphAnalysis, (
        pos,
        frozenset(case) if case is not None else None,
        number,
        frozenset(gender) if gender is not None else None,
        lemma,
        tag,
        qualifier,
        base,
    ))


def source_fingerprint(path):
    """Odcisk źródła sgjp.tab do wykrywania zmian przez migrator:
    (wersja schematu, rozmiar, mtime). Nowe wydanie SGJP → inny odcisk →
    ponowna migracja; zgodny odcisk → migracja jest no-opem."""
    import os
    st = os.stat(path)
    return {"schemat": REDIS_SCHEMA, "rozmiar": st.st_size,
            "mtime": int(st.st_mtime)}


class RedisDb:
    """Drop-in dla pamięciowego `db` w `analyze()` — jedyny używany
    interfejs to `get(forma, default)`. Memo-cache per proces: każda forma
    pytana w Redisie najwyżej raz."""

    def __init__(self, client):
        self.client = client
        self.cache = {}

    def get(self, form, default=None):
        if form in self.cache:
            return self.cache[form]
        raw = self.client.get(f"{REDIS_PREFIX}f:{form}")
        if raw is None:
            result = default
        else:
            result = [analysis_from_jsonable(a) for a in json.loads(raw)]
        self.cache[form] = result
        return result


def load_redis(url):
    """Łączy z Redisem i zwraca (RedisDb, preps) — odpowiednik `load()`,
    ale bez ładowania czegokolwiek do pamięci (poza przyimkami).
    Czytelne błędy: brak modułu redis, brak połączenia, brak/nieaktualna
    migracja (klucz `sgjp:meta`)."""
    from ast_nodes import InterpreterError
    try:
        import redis
    except ModuleNotFoundError:
        raise InterpreterError(
            "tryb --redis wymaga klienta Pythona: pip3 install redis")
    client = redis.Redis.from_url(url)
    try:
        client.ping()
    except redis.exceptions.ConnectionError as e:
        raise InterpreterError(
            f"nie można połączyć z Redisem pod {url} ({e}); "
            f"uruchom redis-server albo popraw --redis-url")
    meta_raw = client.get(f"{REDIS_PREFIX}meta")
    if meta_raw is None:
        raise InterpreterError(
            f"Redis pod {url} nie zawiera zmigrowanego SGJP — uruchom: "
            f"python3 gćć-python/sgjp_do_redisa.py")
    meta = json.loads(meta_raw)
    if meta.get("schemat") != REDIS_SCHEMA:
        raise InterpreterError(
            f"schemat danych w Redisie ({meta.get('schemat')}) nie pasuje "
            f"do interpretera ({REDIS_SCHEMA}) — uruchom ponownie: "
            f"python3 gćć-python/sgjp_do_redisa.py")
    preps_raw = client.get(f"{REDIS_PREFIX}preps")
    preps = {lemma: set(cases)
             for lemma, cases in json.loads(preps_raw).items()}
    db = RedisDb(client)
    # Własne hasła siedzą w memo-cache — mają pierwszeństwo przed Redisem
    # (get sprawdza cache przed siecią), więc semantyka = `load()`.
    db.cache.update(_własne_analizy())
    return db, preps
