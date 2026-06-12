"""Testy trybu redisowego (`gćć.py --redis`).

Dwie warstwy:
- serializacja analiz (czyste funkcje, bez Redisa),
- testy integracyjne (marker `redis`): migrują `test/sgjp_subset.tab` do
  OSOBNEGO logicznego DB Redisa (db=15, żeby nie dotykać zmigrowanego
  pełnego SGJP w db=0) i porównują wyniki z backendem pamięciowym.
  Pomijane w całości, gdy Redis jest niedostępny.
"""

import io
import contextlib
import os
import re

import pytest

import lexer
import morph_anal
import preprocess
import parser as parser_mod
import expression
import typechecker

SUBSET_PATH = os.path.join(os.path.dirname(__file__), "..", "test",
                           "sgjp_subset.tab")
TEST_URL = "redis://localhost:6379/15"


# ---------- serializacja (bez Redisa) ----------

def test_analysis_serialization_roundtrip(db):
    """Round-trip JSON-owalnej serializacji na realnych analizach —
    w tym frozensety przypadków/rodzajów oraz None (czasowniki)."""
    for word in ("kota", "wybrałbyś", "polubieniem", "dla"):
        for ana in db.get(word, []):
            back = morph_anal.analysis_from_jsonable(
                morph_anal.analysis_to_jsonable(ana))
            assert back == ana
            assert isinstance(back, morph_anal.MorphAnalysis)


# ---------- integracja z Redisem (db=15, subset) ----------

def _redis_or_skip():
    try:
        import redis
    except ModuleNotFoundError:
        pytest.skip("brak modułu redis")
    client = redis.Redis.from_url(TEST_URL)
    try:
        client.ping()
    except Exception:
        pytest.skip("Redis niedostępny")
    return client


@pytest.fixture(scope="module")
def redis_subset():
    """Subset SGJP zmigrowany do db=15; sprzątanie prefiksu po module."""
    client = _redis_or_skip()
    from sgjp_do_redisa import migrate, _clear_prefix
    migrate(SUBSET_PATH, TEST_URL, force=True, quiet=True)
    yield TEST_URL
    _clear_prefix(client)


@pytest.mark.redis
def test_redis_analyze_matches_memory(redis_subset):
    """`analyze()` przez RedisDb daje IDENTYCZNE analizy co backend
    pamięciowy na tym samym subsecie."""
    mem_db, mem_preps = morph_anal.load(SUBSET_PATH)
    red_db, red_preps = morph_anal.load_redis(redis_subset)
    toks = lexer.lex("dąb las liście sosną grzybami wilkiem nieistniejące")
    mem = morph_anal.analyze(toks, mem_db)
    red = morph_anal.analyze(toks, red_db)
    for m, r in zip(mem, red):
        assert m[1] == r[1]
        assert m[2] == r[2], f"rozjazd analiz dla {m[1]}"
    assert mem_preps == red_preps


@pytest.mark.redis
def test_redis_db_caches_lookups(redis_subset):
    red_db, _ = morph_anal.load_redis(redis_subset)
    first = red_db.get("las", [])
    assert first and "las" in {a.lemma for a in first}
    assert red_db.get("las", []) is first  # memo-cache, nie drugi GET
    assert red_db.get("niemasłowa", []) == []


@pytest.mark.redis
def test_redis_full_pipeline_matches_memory(redis_subset):
    """Pełny pipeline (parse+resolve+typecheck) na słownictwie subsetu —
    ten sam wynik na obu backendach."""
    # Wyłącznie słownictwo subsetu (leśne); `zwrócić` jako bezokolicznik
    # działa nawet bez analiz (passthrough canonical), `zwróć` by nie działał.
    src = (
        "definicja Lasu:\n"
        "    dąb (Tekst)\n"
        "\n"
        "aby tropić las (Las) -> Tekst:\n"
        "    zwrócić dąb lasu\n"
        "\n"
        "aby polować las (Las) -> Tekst:\n"
        "    trawa to trop las\n"
        "    zwrócić trawa\n"
    )
    outs = []
    for backend in ("mem", "redis"):
        typechecker.last_type = 0
        typechecker.fun_decls = []
        typechecker.module = None
        if backend == "mem":
            db, preps = morph_anal.load(SUBSET_PATH)
        else:
            db, preps = morph_anal.load_redis(redis_subset)
        module = parser_mod.parse(
            preprocess.preprocess(morph_anal.analyze(lexer.lex(src), db)),
            preps)
        expression.resolve_module(module, preps)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            typechecker.resolve_module(module)
        outs.append(buf.getvalue())
    assert _normalize_frozensets(outs[0]) == _normalize_frozensets(outs[1])


_FROZENSET = re.compile(r"frozenset\(\{([^}]*)\}\)")


def _normalize_frozensets(text):
    """Kolejność wyświetlania frozensetu zależy od HISTORII WSTAWIEŃ przy
    kolizjach hashy (mem wstawia w kolejności pliku, redis z posortowanego
    JSON-a), więc przy pechowym PYTHONHASHSEED dumpy różnią się wyłącznie
    kolejnością elementów — porównujemy modulo tę kolejność."""
    return _FROZENSET.sub(
        lambda m: "frozenset({%s})" % ", ".join(sorted(m.group(1).split(", "))),
        text)


@pytest.mark.redis
def test_redis_migration_is_idempotent(redis_subset):
    """Drugie uruchomienie migracji przy zgodnym odcisku źródła to no-op."""
    from sgjp_do_redisa import migrate
    assert migrate(SUBSET_PATH, redis_subset, quiet=True) is False
    assert migrate(SUBSET_PATH, redis_subset, force=True, quiet=True) is True


@pytest.mark.redis
def test_redis_without_migration_raises():
    """Brak `sgjp:meta` (np. świeży Redis) → czytelny błąd z instrukcją."""
    client = _redis_or_skip()
    from sgjp_do_redisa import _clear_prefix
    _clear_prefix(client)
    from ast_nodes import InterpreterError
    with pytest.raises(InterpreterError, match="sgjp_do_redisa"):
        morph_anal.load_redis(TEST_URL)


def test_gerund_base_survives_serialization(db):
    """Pole `base` (czasownik bazowy gerundium) przeżywa round-trip —
    referencje gerundialne działają identycznie w trybie redisowym."""
    gers = [a for a in db.get("polubieniem", []) if a.pos == "ger"]
    assert gers
    for ana in gers:
        back = morph_anal.analysis_from_jsonable(
            morph_anal.analysis_to_jsonable(ana))
        assert back.base == "polubić"
        assert back.lemma == "polubienie"
