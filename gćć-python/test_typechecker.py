"""Testy typecheckera MLsub (simple-sub z niepełną kratą nominalną).

Pisane pod ZACHOWANIA nowego rdzenia, nie pod jego wnętrzności:
- jednostkowe: krata nominalna, biunifikacja (granice, przechodniość,
  inwariancja pól, polaryzacja strzałek), materializacja;
- integracyjne (pełny pipeline, SGJP z sesyjnej fixtury): literały,
  przypisania, struktury (w tym NIEZALEŻNOŚĆ OD KOLEJNOŚCI PÓL),
  unie i dopasowania, łańcuchy, aliasy i aplikacja nazwana, funkcje
  (polimorfizm, rekursja wzajemna w SCC, externy), try-calle,
  zastosowania, grounding i komunikaty.

Testy flagowe nowego rdzenia: `wskazać` (ekstrakcja elementu generycznej
listy) typuje się BEZ adnotacji; kolejność pól konstrukcji nie wpływa
na wynik; wielokrotne wywołania externów nie gubią granic (regresja
po reużyciu id() przez odśmiecone Konkrety).
"""

import os

import pytest

import lexer
import morph_anal
import preprocess
import parser as parser_mod
import expression
import ast_nodes as ast
import typechecker
from typechecker import (
    Konkret, TypeCheckError, ogranicz, new_type, ARROW,
)


@pytest.fixture(autouse=True)
def _reset_typechecker():
    typechecker.last_type = 0
    typechecker.fun_decls = []
    typechecker.fun_scopes = []
    typechecker.module = None
    typechecker._pary.clear()
    typechecker._pary_żywe.clear()
    yield
    typechecker.last_type = 0
    typechecker.fun_decls = []
    typechecker.fun_scopes = []
    typechecker.module = None
    typechecker._pary.clear()
    typechecker._pary_żywe.clear()


@pytest.fixture
def parse(db, preps):
    def _parse(text):
        morphs = preprocess.preprocess(
            morph_anal.analyze(lexer.lex(text), db))
        module = parser_mod.parse(morphs, preps)
        expression.resolve_module(module, preps)
        return module
    return _parse


_PRZYGRYWKA = open(
    os.path.join(os.path.dirname(__file__), "..", "biblioteki", "przygrywka.ć"),
    encoding="utf-8",
).read() + "\n"


def ty(t):
    """Materializacja typu do porównywalnego stringa; '?' dla wolnej.
    Argumenty konstruktorów też są materializowane (Ogniwo[Liczba],
    nie Ogniwo[t5])."""
    return _render(t, set())


def _render(t, widziane):
    if isinstance(t, typechecker.Zmienna):
        if t in widziane:
            return "…"
        widziane.add(t)
        m = typechecker._zmaterializuj(t)
        return _render(m, widziane) if m is not None else "?"
    if t is None:
        return "?"
    if not t.args:
        return t.głowa
    return (t.głowa + "["
            + ", ".join(_render(a, widziane) for a in t.args) + "]")


def _var_types(lenient=False):
    """`lenient=True` pomija zmienne bez materializacji (np. sygnaturowe
    dysjunkcje polimorficznych helperów — legalne poza `działać`)."""
    pairs = {}
    for _decl, scope in typechecker.fun_scopes:
        for s in scope.walk():
            for v, t in s.types:
                try:
                    pairs["_".join(v.surface)] = ty(t)
                except TypeCheckError:
                    if not lenient:
                        raise
    return pairs


def _moduł_kraty():
    """Minimalny moduł deklaracji dla testów jednostkowych kraty."""
    typechecker.module = ast.Module(body=[
        ast.StructDef(name=("Kot",), fields=[], params=[]),
        ast.StructDef(name=("Pies",), fields=[], params=[]),
        ast.StructDef(name=("Chomik",), fields=[], params=[]),
        ast.UnionDef(name=("Zwierzę",), members=[("Kot",), ("Pies",)]),
        ast.UnionDef(name=("Futrzak",), members=[("Kot",), ("Chomik",)]),
    ])


# =====================================================================
# Krata nominalna (jednostkowo)
# =====================================================================

def test_struktura_jest_podtypem_swojej_unii():
    _moduł_kraty()
    assert typechecker.czy_głowa_podtypem("Kot", "Zwierzę")
    assert typechecker.czy_głowa_podtypem("Pies", "Zwierzę")
    assert typechecker.czy_głowa_podtypem("Kot", "Kot")


def test_struktura_nie_jest_podtypem_obcej_unii():
    _moduł_kraty()
    assert not typechecker.czy_głowa_podtypem("Chomik", "Zwierzę")
    assert not typechecker.czy_głowa_podtypem("Zwierzę", "Kot")
    assert not typechecker.czy_głowa_podtypem("Zwierzę", "Futrzak")


def test_najmniejsza_unia_pokrywa_członków():
    _moduł_kraty()
    assert typechecker.najmniejsza_unia({"Kot", "Pies"}) == "Zwierzę"
    assert typechecker.najmniejsza_unia({"Kot", "Zwierzę"}) == "Zwierzę"


def test_najmniejsza_unia_brak_pokrycia():
    _moduł_kraty()
    assert typechecker.najmniejsza_unia({"Pies", "Chomik"}) is None
    assert typechecker.najmniejsza_unia({"Kot", "Liczba"}) is None


def test_najmniejsza_unia_remis_to_błąd():
    _moduł_kraty()
    with pytest.raises(TypeCheckError, match="więcej niż jedna minimalna"):
        typechecker.najmniejsza_unia({"Kot"})


# =====================================================================
# Biunifikacja (jednostkowo)
# =====================================================================

def test_ogranicz_konkrety_ta_sama_głowa():
    _moduł_kraty()
    ogranicz(Konkret("Liczba"), Konkret("Liczba"))  # nie rzuca


def test_ogranicz_członek_do_unii():
    _moduł_kraty()
    ogranicz(Konkret("Kot"), Konkret("Zwierzę"))  # nie rzuca


def test_ogranicz_unia_do_członka_rzuca():
    _moduł_kraty()
    with pytest.raises(TypeCheckError,
                       match="nie mieści się w slocie.*zawęź dopasowaniem"):
        ogranicz(Konkret("Zwierzę"), Konkret("Kot"))


def test_ogranicz_obce_głowy_rzuca():
    _moduł_kraty()
    with pytest.raises(TypeCheckError, match="nie można zunifikować"):
        ogranicz(Konkret("Liczba"), Konkret("Znak"))


def test_zmienna_akumuluje_granice_i_przechodniość():
    _moduł_kraty()
    v1, v2 = new_type(), new_type()
    ogranicz(v1, v2)
    ogranicz(Konkret("Liczba"), v1)   # dolna v1 płynie do v2
    ogranicz(v2, Konkret("Liczba"))   # nie rzuca
    with pytest.raises(TypeCheckError):
        ogranicz(v2, Konkret("Znak"))


def test_przechodniość_wykrywa_konflikt_przez_krawędź():
    _moduł_kraty()
    v1, v2 = new_type(), new_type()
    ogranicz(v1, v2)
    ogranicz(v2, Konkret("Znak"))
    with pytest.raises(TypeCheckError):
        ogranicz(Konkret("Liczba"), v1)


def test_zachłanny_join_dolnych_z_unią_przechodzi():
    _moduł_kraty()
    v = new_type()
    ogranicz(Konkret("Kot"), v)
    ogranicz(Konkret("Pies"), v)      # Kot ⊔ Pies = Zwierzę — łączliwe
    assert ty(v) == "Zwierzę"


def test_zachłanny_join_dolnych_bez_unii_rzuca():
    _moduł_kraty()
    v = new_type()
    ogranicz(Konkret("Pies"), v)
    with pytest.raises(TypeCheckError, match="nie można zunifikować"):
        ogranicz(Konkret("Chomik"), v)


def test_kolejność_granic_nie_zmienia_wyniku():
    """Ta sama para faktów w obu kolejnościach daje ten sam typ."""
    _moduł_kraty()
    a, b = new_type(), new_type()
    ogranicz(Konkret("Kot"), a)
    ogranicz(a, Konkret("Zwierzę"))
    ogranicz(b, Konkret("Zwierzę"))
    ogranicz(Konkret("Kot"), b)
    assert ty(a) == ty(b) == "Kot"


def test_inwariancja_argumentów_konstruktora():
    _moduł_kraty()
    v = new_type()
    ogranicz(Konkret("Pudło", (Konkret("Liczba"),)), Konkret("Pudło", (v,)))
    assert ty(v) == "Liczba"
    with pytest.raises(TypeCheckError):
        ogranicz(Konkret("Pudło", (Konkret("Znak"),)),
                 Konkret("Pudło", (v,)))


def test_strzałka_kontrawariantna_w_argumentach():
    _moduł_kraty()
    # (Zwierzę)→Liczba przyjmuje więcej — pasuje do slotu (Kot)→Liczba.
    ogranicz(Konkret(ARROW, (Konkret("Zwierzę"), Konkret("Liczba"))),
             Konkret(ARROW, (Konkret("Kot"), Konkret("Liczba"))))
    with pytest.raises(TypeCheckError):
        ogranicz(Konkret(ARROW, (Konkret("Kot"), Konkret("Liczba"))),
                 Konkret(ARROW, (Konkret("Zwierzę"), Konkret("Liczba"))))


def test_strzałka_kowariantna_w_wyniku():
    _moduł_kraty()
    ogranicz(Konkret(ARROW, (Konkret("Kot"),)),
             Konkret(ARROW, (Konkret("Zwierzę"),)))
    with pytest.raises(TypeCheckError):
        ogranicz(Konkret(ARROW, (Konkret("Zwierzę"),)),
                 Konkret(ARROW, (Konkret("Kot"),)))


def test_strzałka_zła_arność_rzuca():
    _moduł_kraty()
    with pytest.raises(TypeCheckError, match="liczba argumentów"):
        ogranicz(Konkret(ARROW, (Konkret("Liczba"), Konkret("Liczba"))),
                 Konkret(ARROW, (Konkret("Liczba"),)))


def test_biunifikacja_terminuje_na_cyklu():
    _moduł_kraty()
    v = new_type()
    rekurencyjny = Konkret("Pudło", (v,))
    ogranicz(rekurencyjny, v)
    ogranicz(v, rekurencyjny)  # nie zapętla się (pamięć par)


def test_konflikt_niesie_poszlaki_z_granic():
    _moduł_kraty()
    v = new_type()
    typechecker._set_note("pierwsza poszlaka")
    ogranicz(Konkret("Pies"), v)
    typechecker._set_note("druga poszlaka")
    with pytest.raises(TypeCheckError, match="pierwsza poszlaka"):
        ogranicz(Konkret("Chomik"), v)


# =====================================================================
# Materializacja (jednostkowo)
# =====================================================================

def test_materializacja_pojedynczej_dolnej():
    _moduł_kraty()
    v = new_type()
    ogranicz(Konkret("Kot"), v)
    assert ty(v) == "Kot"


def test_materializacja_default_z_górnych_singleton():
    _moduł_kraty()
    v = new_type()
    ogranicz(v, Konkret("Liczba"))
    assert ty(v) == "Liczba"


def test_materializacja_default_z_górnych_dokładna_unia():
    _moduł_kraty()
    v = new_type()
    ogranicz(v, Konkret("Zwierzę"))
    ogranicz(v, Konkret("Kot"))
    ogranicz(v, Konkret("Pies"))
    assert ty(v) == "Zwierzę"


def test_materializacja_wolnej_zmiennej_to_pytajnik():
    _moduł_kraty()
    assert ty(new_type()) == "?"


# =====================================================================
# Integracja: literały i przypisania
# =====================================================================

@pytest.mark.integration
def test_literały_typują_się(parse):
    src = (
        "aby działać:\n"
        "    liczba to pięć\n"
        "    litera to 'a'\n"
        "    flaga to prawda\n"
    )
    typechecker.resolve_module(parse(src))
    types = _var_types()
    assert types["liczba"] == "Liczba"
    assert types["litera"] == "Znak"
    assert types["flaga"] == "Przełącznik"


@pytest.mark.integration
def test_literał_tekstowy_bez_aliasu_rzuca(parse):
    src = (
        "aby działać:\n"
        "    napis to \"abc\"\n"
    )
    with pytest.raises(TypeCheckError, match="wymaga aliasu typu 'Tekst'"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_konflikt_przypisań_rzuca_z_poszlakami(parse):
    src = (
        "aby działać:\n"
        "    rzecz to jeden\n"
        "    rzecz to 'z'\n"
    )
    with pytest.raises(TypeCheckError) as ei:
        typechecker.resolve_module(parse(src))
    msg = str(ei.value)
    assert "nie można zunifikować" in msg
    assert "linia 2" in msg
    assert "przypisanie do 'rzecz'" in msg


@pytest.mark.integration
def test_przypisania_wariantów_akumulują_do_unii(parse):
    src = (
        "definicja Kota:\n    imię (Znak)\n"
        "\n"
        "definicja Psa:\n    kość (Znak)\n"
        "\n"
        "Zwierzę to Kot albo Pies\n"
        "\n"
        "aby działać:\n"
        "    pupil to Kot o imieniu 'M'\n"
        "    pupil to Pies o kości 's'\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["pupil"] == "Zwierzę"


@pytest.mark.integration
def test_adnotowana_deklaracja_przybija_typ(parse):
    src = (
        "aby działać:\n"
        "    wynik (Liczba) to pięć\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["wynik"] == "Liczba"


@pytest.mark.integration
def test_adnotowana_deklaracja_odrzuca_konflikt(parse):
    src = (
        "aby działać:\n"
        "    wynik (Znak) to pięć\n"
    )
    with pytest.raises(TypeCheckError):
        typechecker.resolve_module(parse(src))


# =====================================================================
# Integracja: struktury i kolejność pól
# =====================================================================

_ROZKAZY = (
    "definicja Kroku:\n"
    "    znak (Znak)\n"
    "\n"
    "definicja Cyklu:\n"
    "    numer (Liczba)\n"
    "\n"
    "Rozkaz to Krok albo Cykl\n"
    "\n"
    "definicja Ogniwa z elementem:\n"
    "    głowa (element)\n"
    "    ogon (Lista)\n"
    "\n"
    "Lista to Ogniwo albo Nic\n"
    "\n"
    "Program to Lista o elemencie Rozkaz\n"
    "\n"
)


@pytest.mark.integration
def test_konstrukcja_nadaje_typ_struktury(parse):
    src = (
        "definicja Kota:\n    imię (Znak)\n"
        "\n"
        "aby działać:\n"
        "    kot to Kot o imieniu 'M'\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["kot"] == "Kot"


@pytest.mark.integration
def test_zły_typ_pola_rzuca(parse):
    src = (
        "definicja Kota:\n    imię (Znak)\n"
        "\n"
        "aby działać:\n"
        "    kot to Kot o imieniu pięć\n"
    )
    with pytest.raises(TypeCheckError):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_element_generycznej_struktury_wnioskowany(parse):
    src = _ROZKAZY + (
        "aby działać:\n"
        "    lista to Ogniwo o głowie pięć o ogonie Nic\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["lista"] == "Ogniwo[Liczba]"


@pytest.mark.integration
def test_kolejność_pól_konstrukcji_bez_znaczenia(parse):
    """Flagowy test rdzenia: wariant w slocie-elemencie przed unią i po
    niej — oba szyki dają ten sam typ (stary solver betonował element)."""
    base = _ROZKAZY + (
        "aby brać program (Program) -> Liczba:\n"
        "    zwróć zero\n"
        "\n"
        "aby działać:\n"
        "    próżnia (Program) to Nic\n"
    )
    głowa_najpierw = base + (
        "    a to bierz (Ogniwo o głowie (Krok o znaku 'k') o ogonie próżni)\n"
    )
    ogon_najpierw = base + (
        "    a to bierz (Ogniwo o ogonie próżni o głowie (Krok o znaku 'k'))\n"
    )
    typechecker.resolve_module(parse(głowa_najpierw))
    _reset()
    typechecker.resolve_module(parse(ogon_najpierw))


def _reset():
    typechecker.last_type = 0
    typechecker.fun_decls = []
    typechecker.fun_scopes = []
    typechecker.module = None
    typechecker._pary.clear()
    typechecker._pary_żywe.clear()


@pytest.mark.integration
def test_jednorodność_listy_odrzuca_mieszankę(parse):
    src = _ROZKAZY + (
        "aby działać:\n"
        "    lista to Ogniwo o głowie pięć o ogonie "
        "(Ogniwo o głowie 'a' o ogonie Nic)\n"
    )
    with pytest.raises(TypeCheckError) as ei:
        typechecker.resolve_module(parse(src))
    msg = str(ei.value)
    assert "niejawny argument 'element'" in msg
    assert "z definicji 'Ogniwo'" in msg


@pytest.mark.integration
def test_kontenery_inwariantne_względem_unii(parse):
    """Lista o elemencie Krok ≠ Lista o elemencie Rozkaz."""
    src = _ROZKAZY + (
        "Marsz to Lista o elemencie Krok\n"
        "\n"
        "aby brać program (Program) -> Liczba:\n"
        "    zwróć zero\n"
        "\n"
        "aby dawać -> Marsz:\n"
        "    zwróć Ogniwo o głowie (Krok o znaku 'k') o ogonie Nic\n"
        "\n"
        "aby działać:\n"
        "    wynik to bierz (dawaj)\n"
    )
    with pytest.raises(TypeCheckError):
        typechecker.resolve_module(parse(src))


# =====================================================================
# Integracja: unie i dopasowanie `jest:`
# =====================================================================

_ZWIERZĘTA = (
    "definicja Kota:\n    imię (Znak)\n"
    "\n"
    "definicja Psa:\n    kość (Znak)\n"
    "\n"
    "Zwierzę to Kot albo Pies\n"
    "\n"
)


@pytest.mark.integration
def test_pełne_dopasowanie_wiąże_pola(parse):
    src = _ZWIERZĘTA + (
        "aby działać:\n"
        "    pupil (Zwierzę) to Kot o imieniu 'M'\n"
        "    pupil jest:\n"
        "        Kotem z imieniem:\n"
        "            litera to imię\n"
        "        Psem z kością:\n"
        "            litera to kość\n"
    )
    typechecker.resolve_module(parse(src))
    types = _var_types()
    assert types["imieniem"] == "Znak"
    assert types["litera"] == "Znak"


@pytest.mark.integration
def test_dopasowanie_brakująca_gałąź_rzuca(parse):
    src = _ZWIERZĘTA + (
        "aby działać:\n"
        "    pupil (Zwierzę) to Kot o imieniu 'M'\n"
        "    pupil jest:\n"
        "        Kotem:\n"
        "            x to jeden\n"
    )
    with pytest.raises(TypeCheckError, match="brakuje gałęzi: Pies"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_dopasowanie_gałąź_spoza_unii_rzuca(parse):
    src = _ZWIERZĘTA + (
        "definicja Chomika:\n    futro (Znak)\n"
        "\n"
        "aby działać:\n"
        "    pupil (Zwierzę) to Kot o imieniu 'M'\n"
        "    pupil jest:\n"
        "        Kotem:\n"
        "            x to jeden\n"
        "        Psem:\n"
        "            x to dwa\n"
        "        Chomikiem:\n"
        "            x to trzy\n"
    )
    with pytest.raises(TypeCheckError, match="spoza unii: Chomik"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_dopasowanie_powtórzona_gałąź_rzuca(parse):
    src = _ZWIERZĘTA + (
        "aby działać:\n"
        "    pupil (Zwierzę) to Kot o imieniu 'M'\n"
        "    pupil jest:\n"
        "        Kotem:\n"
        "            x to jeden\n"
        "        Kotem:\n"
        "            x to dwa\n"
        "        Psem:\n"
        "            x to trzy\n"
    )
    with pytest.raises(TypeCheckError, match="powtórzona gałąź"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_dopasowanie_wnioskuje_unię_wolnego_parametru(parse):
    src = _ZWIERZĘTA + (
        "aby badać pupila:\n"
        "    pupil jest:\n"
        "        Kotem z imieniem:\n"
        "            zwróć imię\n"
        "        Psem z kością:\n"
        "            zwróć kość\n"
        "\n"
        "aby działać:\n"
        "    litera to badaj Kot o imieniu 'M'\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["litera"] == "Znak"


@pytest.mark.integration
def test_dopasowanie_zachowuje_wąski_typ_podmiotu(parse):
    """Dopasowanie na konkretnym wariancie nie wymazuje faktu, że
    zmienna to Kot (górna granica ≤ unia to dozwolenie, nie fakt)."""
    src = _ZWIERZĘTA + (
        "aby działać:\n"
        "    kot to Kot o imieniu 'M'\n"
        "    kot jest:\n"
        "        Kotem:\n"
        "            x to jeden\n"
        "        Psem:\n"
        "            x to dwa\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["kot"] == "Kot"


@pytest.mark.integration
def test_częściowe_dopasowanie_z_inaczej(parse):
    src = _ZWIERZĘTA + (
        "aby działać:\n"
        "    pupil (Zwierzę) to Kot o imieniu 'M'\n"
        "    pupil jest:\n"
        "        Kotem:\n"
        "            x to jeden\n"
        "        inaczej:\n"
        "            x to dwa\n"
    )
    typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_zapis_do_podmiotu_idzie_na_zewnątrz(parse):
    """Idiom kursora: zapis w gałęzi poszerza zmienną ZEWNĘTRZNĄ do unii,
    a cień zawężenia w gałęzi pozostaje wąski."""
    src = _ZWIERZĘTA + (
        "aby działać:\n"
        "    pupil to Kot o imieniu 'M'\n"
        "    pupil jest:\n"
        "        Kotem:\n"
        "            pupil to Pies o kości 's'\n"
        "        Psem:\n"
        "            x to jeden\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["pupil"] == "Zwierzę"


# =====================================================================
# Integracja: łańcuchy dopełniaczowe
# =====================================================================

@pytest.mark.integration
def test_łańcuch_czyta_typ_pola(parse):
    src = _ZWIERZĘTA + (
        "aby działać:\n"
        "    kot to Kot o imieniu 'M'\n"
        "    litera to imię kota\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["litera"] == "Znak"


@pytest.mark.integration
def test_łańcuch_przez_unię_podpowiada_zawężenie(parse):
    src = _ZWIERZĘTA + (
        "aby działać:\n"
        "    pupil (Zwierzę) to Kot o imieniu 'M'\n"
        "    litera to imię pupila\n"
    )
    with pytest.raises(
        TypeCheckError,
        match=r"(?s)pole 'imię' nie jest wspólne wariantom unii "
              r"'Zwierzę \(Kot albo Pies\)'.*brakuje go w: Pies.*zawęź "
              r"dopasowaniem `jest:`",
    ):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_łańcuch_bez_kandydatów_wylicza_struktury(parse):
    src = _ZWIERZĘTA + (
        "aby działać:\n"
        "    pies to Pies o kości 'k'\n"
        "    x to imię kości psa\n"
    )
    # Dzielenie łańcucha rozwiązuje `kości psa` (Znak) i dopiero na tym
    # wyniku odmawia pola `imię` — błąd wskazuje konkretny typ podstawy.
    with pytest.raises(
        TypeCheckError,
        match=r"pole 'imię'.*nie występuje w typie \['Znak'\]",
    ):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_zapis_przez_łańcuch_sprawdza_typ(parse):
    src = _ZWIERZĘTA + (
        "aby działać:\n"
        "    kot to Kot o imieniu 'M'\n"
        "    imię kota to pięć\n"
    )
    with pytest.raises(TypeCheckError):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_górna_granica_filtruje_kandydatów_łańcucha(parse):
    """Pin porządkoniezależności: użycie w slocie unijnym daje ≤ Unia,
    a późniejszy łańcuch zawęża kandydatów przez to dozwolenie —
    obie kolejności linijek się typują."""
    base = (
        "definicja Drzewa dla rzeczy:\n"
        "    wartość (rzecz)\n"
        "    lewy_syn (Drzewo dla rzeczy)\n"
        "\n"
        "definicja Węzła z elementem:\n"
        "    wartość (element)\n"
        "    lewy_syn (Gałąź)\n"
        "\n"
        "Gałąź to Węzeł albo Nic\n"
        "\n"
        "aby zmierzyć gałąź (Gałąź) -> Liczba:\n"
        "    zwróć zero\n"
        "\n"
    )
    kolejność_a = base + (
        "aby testować drzewo:\n"
        "    głębia to zmierz drzewo\n"
        "    filar to lewy_syn drzewa\n"
    )
    kolejność_b = base + (
        "aby testować drzewo:\n"
        "    filar to lewy_syn drzewa\n"
        "    głębia to zmierz drzewo\n"
    )
    typechecker.resolve_module(parse(kolejność_a))
    _reset()
    typechecker.resolve_module(parse(kolejność_b))


# =====================================================================
# Integracja: aliasy i aplikacja nazwana
# =====================================================================

@pytest.mark.integration
def test_alias_do_builtina_przezroczysty(parse):
    src = (
        "Numer to Liczba\n"
        "\n"
        "aby działać:\n"
        "    wynik (Numer) to jeden\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["wynik"] == "Liczba"


@pytest.mark.integration
def test_łańcuch_aliasów_rozwija_się(parse):
    src = (
        "Numer to Liczba\n"
        "Cyfra to Numer\n"
        "\n"
        "aby działać:\n"
        "    wynik (Cyfra) to jeden\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["wynik"] == "Liczba"


@pytest.mark.integration
def test_cykl_aliasów_rzuca(parse):
    src = (
        "Numer to Cyfra\n"
        "Cyfra to Numer\n"
        "\n"
        "aby działać:\n"
        "    zwróć jeden\n"
    )
    with pytest.raises(TypeCheckError, match="cykl aliasów"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_alias_nieznanego_typu_rzuca(parse):
    src = (
        "Numer to Widmo\n"
        "\n"
        "aby działać:\n"
        "    zwróć jeden\n"
    )
    with pytest.raises(TypeCheckError, match="nieznany typ 'Widmo'"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_alias_wiąże_element_unii(parse):
    src = _ROZKAZY + (
        "aby brać program (Program) -> Liczba:\n"
        "    zwróć zero\n"
        "\n"
        "aby działać:\n"
        "    n to bierz (Ogniwo o głowie pięć o ogonie Nic)\n"
    )
    with pytest.raises(TypeCheckError):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_aplikacja_nazwana_w_adnotacji_unii(parse):
    """`-> Rezultat o elemencie Tekst` w sygnaturze externa — wiązanie
    `z wartością` w dopasowaniu ma typ Tekst (lista znaków)."""
    src = _PRZYGRYWKA + (
        "aby działać:\n"
        "    wynik to czytaj_plik ze \"dane\"\n"
        "    wynik jest:\n"
        "        Sukcesem z wartością:\n"
        "            treść to wartość\n"
        "        Błędem z opisem:\n"
        "            treść to opis\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["wartością"].startswith("Lista")


@pytest.mark.integration
def test_aplikacja_nazwana_nieznany_parametr_rzuca(parse):
    src = _PRZYGRYWKA + (
        "można wróżyć -> Rezultat o pierwiastku Liczba\n"
        "\n"
        "aby działać:\n"
        "    zwróć jeden\n"
    )
    with pytest.raises(TypeCheckError,
                       match="nie ma parametru 'pierwiastek'"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_pozycyjna_aplikacja_na_unii_rzuca(parse):
    src = _ROZKAZY + (
        "aby brać rzeczy (Lista z (Liczba)) -> Liczba:\n"
        "    zwróć zero\n"
    )
    with pytest.raises(TypeCheckError,
                       match="typ wariantowy 'Lista' nie przyjmuje"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_wspólny_parametr_w_aplikacji_nazwanej(parse):
    """Mała litera w aplikacji nazwanej = współdzielony parametr
    sygnatury: element wyniku równy elementowi listy."""
    src = _ROZKAZY + (
        "definicja Sukcesu z elementem:\n    wartość (element)\n"
        "\n"
        "definicja Błędu:\n    numer (Liczba)\n"
        "\n"
        "Rezultat to Sukces albo Błąd\n"
        "\n"
        "można wybierać z listy (Lista o elemencie rzecz) "
        "-> Rezultat o elemencie rzecz\n"
        "\n"
        "aby działać:\n"
        "    wynik to wybieraj z (Ogniwo o głowie pięć o ogonie Nic)\n"
        "    wynik jest:\n"
        "        Sukcesem z wartością:\n"
        "            liczba to wartość plus jeden\n"
        "        Błędem:\n"
        "            liczba to zero\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["wartością"] == "Liczba"


# =====================================================================
# Integracja: funkcje — polimorfizm, rekursja (SCC), externy
# =====================================================================

@pytest.mark.integration
def test_polimorficzne_wywołania_nie_interferują(parse):
    src = (
        "aby przetwarzać dla x:\n"
        "    zwróć x\n"
        "\n"
        "aby działać:\n"
        "    liczba to przetwarzać dla jeden\n"
        "    litera to przetwarzać dla 'z'\n"
    )
    typechecker.resolve_module(parse(src))
    types = _var_types()
    assert types["liczba"] == "Liczba"
    assert types["litera"] == "Znak"


@pytest.mark.integration
def test_typ_zwracany_płynie_przez_wywołanie(parse):
    src = (
        "aby liczyć dla x (Liczba) -> Liczba:\n"
        "    zwróć pięć\n"
        "\n"
        "aby działać:\n"
        "    wynik to licz dla jeden\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["wynik"] == "Liczba"


@pytest.mark.integration
def test_referencja_w_przód_bez_fixpointu(parse):
    src = (
        "aby przygotować dla x:\n"
        "    zwróć generować dla x\n"
        "\n"
        "aby generować dla y:\n"
        "    zwróć pięć\n"
        "\n"
        "aby działać:\n"
        "    a to przygotuj dla jeden\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["a"] == "Liczba"


@pytest.mark.integration
def test_rekursja_wzajemna_w_scc(parse):
    src = (
        "aby maleć liczbę (Liczba) -> Przełącznik:\n"
        "    jeśli liczba równa zero:\n"
        "        zwróć prawda\n"
        "    zwróć rosnąć (liczba minus jeden)\n"
        "\n"
        "aby rosnąć liczbę (Liczba) -> Przełącznik:\n"
        "    jeśli liczba równa zero:\n"
        "        zwróć fałsz\n"
        "    zwróć maleć (liczba minus jeden)\n"
        "\n"
        "aby działać:\n"
        "    wynik to maleć pięć\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["wynik"] == "Przełącznik"


@pytest.mark.integration
def test_rekursja_bezpośrednia(parse):
    src = (
        "aby liczyć x:\n"
        "    jeśli x równe zero:\n"
        "        zwróć zero\n"
        "    zwróć licz (x minus jeden)\n"
        "\n"
        "aby działać:\n"
        "    wynik to licz pięć\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["wynik"] == "Liczba"


@pytest.mark.integration
def test_extern_sygnatura_ogranicza_wołającego(parse):
    src = (
        "można policzyć x (Znak) -> Liczba\n"
        "\n"
        "aby działać:\n"
        "    wynik to policz pięć\n"
    )
    with pytest.raises(TypeCheckError):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_extern_nieznana_głowa_współdzielona_w_sygnaturze(parse):
    src = (
        "można leżeć na polanie (Miejsce) w lesie (Miejsce) "
        "przy jeziorze (Liczba) -> Liczba\n"
        "\n"
        "aby działać:\n"
        "    n to leż na pięć w 'l' przy siedem\n"
    )
    with pytest.raises(TypeCheckError):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_extern_wielokrotne_wywołania_nie_gubią_granic(parse):
    """Regresja: reużycie id() po odśmieceniu tymczasowych Konkretów
    gubiło ograniczenia przy kolejnych wywołaniach tego samego externa."""
    src = (
        "można podzielić pierwszą_liczbę (Liczba) przez drugą_liczbę "
        "(Liczba) -> Liczba\n"
        "\n"
        "można wypisać coś (Cokolwiek) -> Nic\n"
        "\n"
        "aby działać:\n"
        "    wypisz (podziel siedem przez dwa)\n"
        "    wypisz (podziel dziesięć przez pięć)\n"
        "    a to podziel sto przez dwa\n"
        "    b to podziel sto przez (podziel dziesięć przez pięć)\n"
    )
    typechecker.resolve_module(parse(src))
    types = _var_types()
    assert types["a"] == "Liczba"
    assert types["b"] == "Liczba"


# =====================================================================
# Integracja: wskazać bez adnotacji (flagowy test rdzenia)
# =====================================================================

@pytest.mark.integration
def test_ekstrakcja_elementu_generycznej_listy_bez_adnotacji(parse):
    """Element wyniku (Sukces o wartości głowa) płynie z elementu listy
    argumentu jedną ścieżką granic — bez żadnej adnotacji wiążącej.
    Stary solver gubił tę równość (poszlaki ≤ zamiast =)."""
    src = _PRZYGRYWKA + (
        "aby działać:\n"
        "    liczby to Ogniwo o głowie jeden o ogonie Nic\n"
        "    trafienie to wskaż jeden na liczbach\n"
        "    trafienie jest:\n"
        "        Sukcesem z wartością:\n"
        "            wypisz wartość\n"
        "        Błędem z opisem:\n"
        "            wypisz opis\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["wartością"] == "Liczba"


# =====================================================================
# Integracja: try-calle i zastosowania
# =====================================================================

_REZULTAT = (
    "definicja Sukcesu z elementem:\n    wartość (element)\n"
    "\n"
    "definicja Błędu:\n    numer (Liczba)\n"
    "\n"
    "Rezultat to Sukces albo Błąd\n"
    "\n"
)


@pytest.mark.integration
def test_try_call_odpakowuje_i_rozszerza_zwrot(parse):
    src = _REZULTAT + (
        "aby wybrać pozycję (Liczba):\n"
        "    jeśli pozycja równa zero:\n"
        "        zwróć Sukces o wartości pięć\n"
        "    zwróć Błąd o numerze jeden\n"
        "\n"
        "aby przetwarzać pozycję (Liczba):\n"
        "    liczba to wybrałbyś pozycję?\n"
        "    zwróć Sukces o wartości (liczba plus jeden)\n"
        "\n"
        "aby działać:\n"
        "    wynik to przetwarzaj zero\n"
        "    wynik jest:\n"
        "        Sukcesem z wartością:\n"
        "            n to wartość\n"
        "        Błędem:\n"
        "            n to zero\n"
    )
    typechecker.resolve_module(parse(src))
    types = _var_types()
    assert types["liczba"] == "Liczba"
    assert types["wynik"].startswith("Rezultat")


@pytest.mark.integration
def test_try_call_bez_deklaracji_rezultatu_rzuca(parse):
    src = (
        "aby brać x:\n"
        "    zwróć pięć\n"
        "\n"
        "aby działać:\n"
        "    y to brałbyś jeden?\n"
    )
    with pytest.raises(TypeCheckError,
                       match="Rezultat to Sukces albo Błąd"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_zastosowanie_typuje_wynik(parse):
    src = (
        "aby podwajać liczbę (Liczba) -> Liczba:\n"
        "    zwróć liczba razy dwa\n"
        "\n"
        "aby działać:\n"
        "    wynik to zastosuj podwajanie z pięć\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["wynik"] == "Liczba"


@pytest.mark.integration
def test_zastosowanie_zła_arność_rzuca(parse):
    src = (
        "aby podwajać liczbę (Liczba) -> Liczba:\n"
        "    zwróć liczba razy dwa\n"
        "\n"
        "aby działać:\n"
        "    wynik to zastosuj podwajanie z pięć z sześć\n"
    )
    with pytest.raises(TypeCheckError, match="argument"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_referencja_gerundialna_daje_strzałkę(parse):
    src = (
        "aby podwajać liczbę (Liczba) -> Liczba:\n"
        "    zwróć liczba razy dwa\n"
        "\n"
        "aby brać operację z liczbą (Liczba) -> Liczba:\n"
        "    zwróć zastosuj operację z liczbą\n"
        "\n"
        "aby działać:\n"
        "    wynik to bierz podwajanie z pięć\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["wynik"] == "Liczba"


# =====================================================================
# Bejcowanie (`zwiąż`)
# =====================================================================

_DODAWANIE = (
    "aby dodać liczbę (Liczba) do innej_liczby (Liczba) -> Liczba:\n"
    "    zwróć liczba plus inna_liczba\n"
    "\n"
)


@pytest.mark.integration
def test_zwiąż_typuje_strzałkę_pozostałych(parse):
    src = _DODAWANIE + (
        "aby działać:\n"
        "    domknięcie to zwiąż dodanie z dwa\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["domknięcie"] == "→[Liczba, Liczba]"


@pytest.mark.integration
def test_zwiąż_potem_zastosuj_typuje_wynik(parse):
    src = _DODAWANIE + (
        "aby działać:\n"
        "    domknięcie to zwiąż dodanie z dwa\n"
        "    wynik to zastosuj domknięcie z trzy\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["wynik"] == "Liczba"


@pytest.mark.integration
def test_zwiąż_wszystkie_argumenty_daje_gruszkę(parse):
    """Związanie pełnej arności → strzałka zeroargumentowa (thunk)."""
    src = _DODAWANIE + (
        "aby działać:\n"
        "    domknięcie to zwiąż dodanie z dwa z trzy\n"
        "    wynik to zastosuj domknięcie\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["domknięcie"] == "→[Liczba]"
    assert _var_types()["wynik"] == "Liczba"


@pytest.mark.integration
def test_zwiąż_argument_złego_typu_rzuca(parse):
    src = _DODAWANIE + (
        "aby działać:\n"
        "    domknięcie to zwiąż dodanie z prawda\n"
    )
    with pytest.raises(TypeCheckError):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_zwiąż_nadwiązanie_rzuca(parse):
    src = _DODAWANIE + (
        "aby działać:\n"
        "    domknięcie to zwiąż dodanie z jeden z dwa z trzy\n"
    )
    with pytest.raises(TypeCheckError, match="przyjmuje 2"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_zwiąż_nie_funkcja_rzuca(parse):
    src = (
        "aby działać:\n"
        "    pięść to pięć\n"
        "    domknięcie to zwiąż pięścią z dwa\n"
    )
    with pytest.raises(TypeCheckError, match="wartości funkcyjnej"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_zwiąż_nieustalony_parametr_rzuca(parse):
    """Wiązanie na generycznym parametrze (nieznana strzałka) — jawny
    błąd zamiast polimorfizmu wierszowego."""
    src = (
        "aby wiązać operację:\n"
        "    zwróć zwiąż operację z jeden\n"
    )
    with pytest.raises(TypeCheckError, match="znanej strzałce"):
        typechecker.resolve_module(parse(src))


# =====================================================================
# Gettery pól wspólnych unii — odczyt i zapis przez unię bez zawężania
# =====================================================================

_ROZGRYWKA = (
    "definicja Pola:\n"
    "    kolumna (Liczba)\n"
    "    wiersz (Liczba)\n"
    "\n"
    "definicja Pełzania:\n"
    "    owoc (Pole)\n"
    "    kierunek (Pole)\n"
    "\n"
    "definicja Porażki:\n"
    "    owoc (Pole)\n"
    "    powód (Znak)\n"
    "\n"
    "Rozgrywka to Pełzanie albo Porażka\n"
    "\n"
    "aby rozstrzygać od flagi:\n"
    "    jeśli flaga:\n"
    "        zwróć Pełzanie o owocu (Pole o kolumnie jeden o wierszu dwa)"
    " o kierunku (Pole o kolumnie zero o wierszu zero)\n"
    "    zwróć Porażka o owocu (Pole o kolumnie trzy o wierszu cztery)"
    " o powodzie 'x'\n"
    "\n"
)


@pytest.mark.integration
def test_unia_pole_wspólne_przez_fakt_unię(parse):
    """Wartość z funkcji zwracającej unię — pole wspólne czyta się
    bez zawężania."""
    src = _ROZGRYWKA + (
        "aby działać:\n"
        "    stan to rozstrzygaj od prawdy\n"
        "    miejsce to owoc stanu\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["stan"] == "Rozgrywka"
    assert _var_types()["miejsce"] == "Pole"


@pytest.mark.integration
def test_unia_pole_wspólne_dwa_fakty_warianty(parse):
    """Zmienna przepisana dwoma wariantami — fakty joinują się do unii,
    kandydat-unia wygrywa w _zawęź_alternatywy."""
    src = _ROZGRYWKA + (
        "aby działać:\n"
        "    stan to Pełzanie o owocu (Pole o kolumnie jeden o wierszu"
        " dwa) o kierunku (Pole o kolumnie zero o wierszu zero)\n"
        "    stan to Porażka o owocu (Pole o kolumnie trzy o wierszu"
        " cztery) o powodzie 'y'\n"
        "    miejsce to owoc stanu\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["stan"] == "Rozgrywka"
    assert _var_types()["miejsce"] == "Pole"


@pytest.mark.integration
def test_unia_pole_wspólne_adnotowany_parametr(parse):
    """Górna granica (adnotacja) o głowie-kandydacie rozstrzyga odczyt
    przez unię — jedyny poprawny dla każdego mieszkańca."""
    src = _ROZGRYWKA + (
        "aby wskazać_cel rozgrywki (Rozgrywka) -> Pole:\n"
        "    zwróć owoc rozgrywki\n"
        "\n"
        "aby działać:\n"
        "    miejsce to wskaż_cel (rozstrzygaj od fałszu)\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["miejsce"] == "Pole"


@pytest.mark.integration
def test_unia_pole_wspólne_zgadywanie_z_odczytu(parse):
    """Nieadnotowany parametr: sam odczyt pola otwiera dysjunkcję
    {struktury, unia}; każde wywołanie rozstrzyga ją po swojemu."""
    src = _ROZGRYWKA + (
        "aby zerkać na rzecz:\n"
        "    zwróć owoc rzeczy\n"
        "\n"
        "aby działać:\n"
        "    a to zerkaj na (Pełzanie o owocu (Pole o kolumnie jeden"
        " o wierszu dwa) o kierunku (Pole o kolumnie zero o wierszu"
        " zero))\n"
        "    b to zerkaj na (Porażka o owocu (Pole o kolumnie trzy"
        " o wierszu cztery) o powodzie 'x')\n"
        "    c to zerkaj na (rozstrzygaj od prawdy)\n"
    )
    typechecker.resolve_module(parse(src))
    # lenient: sygnaturowy parametr `rzecz` helpera zostaje polimorficzną
    # dysjunkcją — o rozstrzygnięciach mówią wywołania w `działać`
    typy = _var_types(lenient=True)
    assert typy["a"] == "Pole"
    assert typy["b"] == "Pole"
    assert typy["c"] == "Pole"


@pytest.mark.integration
def test_unia_fakt_struktury_wybiera_strukturę(parse):
    """Najmniejszy zgodny kandydat: fakt-struktura materializuje
    strukturę, nie unię — mimo że unia też jest kandydatem."""
    src = _ROZGRYWKA + (
        "aby działać:\n"
        "    ruch to Pełzanie o owocu (Pole o kolumnie jeden o wierszu"
        " dwa) o kierunku (Pole o kolumnie zero o wierszu zero)\n"
        "    miejsce to owoc ruchu\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["ruch"] == "Pełzanie"
    assert _var_types()["miejsce"] == "Pole"


@pytest.mark.integration
def test_unia_pole_wspólne_hierarchia_zagnieżdżona(parse):
    """Pole wspólne wszystkim LIŚCIOM przechodnim — czyta się przez
    szczyt hierarchii."""
    src = (
        "definicja Kota:\n"
        "    znak (Znak)\n"
        "\n"
        "definicja Jamnika:\n"
        "    znak (Znak)\n"
        "\n"
        "definicja Pudla:\n"
        "    znak (Znak)\n"
        "\n"
        "Pies to Jamnik albo Pudel\n"
        "\n"
        "Zwierzę to Kot albo Pies\n"
        "\n"
        "aby działać:\n"
        "    okaz (Zwierzę) to Kot o znaku 'a'\n"
        "    cecha to znak okazu\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["cecha"] == "Znak"


@pytest.mark.integration
def test_unia_pole_wspólne_łańcuch_głęboki(parse):
    """Łańcuch przez unię i dalej w głąb struktury."""
    src = _ROZGRYWKA + (
        "aby działać:\n"
        "    stan to rozstrzygaj od prawdy\n"
        "    numer to kolumna owocu stanu\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["numer"] == "Liczba"


@pytest.mark.integration
def test_unia_pole_wspólne_w_polu_struktury(parse):
    """Zejście łańcucha trafia w unię W ŚRODKU łańcucha (pole struktury
    typu unijnego) — odczyt pola wspólnego działa i tam."""
    src = _ROZGRYWKA + (
        "definicja Pudełka:\n"
        "    zawartość (Rozgrywka)\n"
        "\n"
        "aby działać:\n"
        "    pudło to Pudełko o zawartości (rozstrzygaj od prawdy)\n"
        "    miejsce to owoc zawartości pudła\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["miejsce"] == "Pole"


_POJEMNIKI_WSPÓLNE = (
    "definicja Ogniwa z elementem:\n"
    "    głowa (element)\n"
    "    ogon (Lista)\n"
    "\n"
    "Lista to Ogniwo albo Nic\n"
    "\n"
    "definicja Kubła z elementem:\n"
    "    zapas (Lista o elemencie element)\n"
    "\n"
    "definicja Worka z elementem:\n"
    "    zapas (Lista o elemencie element)\n"
    "\n"
    "Pojemnik to Kubeł albo Worek\n"
    "\n"
)


@pytest.mark.integration
def test_unia_współdzielony_parametr_przepływa(parse):
    """Parametry o tej samej nazwie to JEDEN slot unii — element pola
    wspólnego przepływa z konstrukcji do odczytu przez unię."""
    src = _POJEMNIKI_WSPÓLNE + (
        "aby działać:\n"
        "    schowek to Kubeł o zapasie (Ogniwo o głowie pięć o ogonie"
        " Nic)\n"
        "    schowek to Worek o zapasie (Ogniwo o głowie sześć o ogonie"
        " Nic)\n"
        "    zbiór to zapas schowka\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["schowek"] == "Pojemnik[Liczba]"
    assert _var_types()["zbiór"] == "Lista[Liczba]"


@pytest.mark.integration
def test_unia_zapis_pola_przez_unię(parse):
    """Zapis pola wspólnego przez unię — płytki i przez głęboki
    łańcuch."""
    src = _ROZGRYWKA + (
        "aby działać:\n"
        "    stan to rozstrzygaj od prawdy\n"
        "    owoc stanu to Pole o kolumnie osiem o wierszu osiem\n"
        "    kolumna owocu stanu to dziewięć\n"
    )
    typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_unia_zapis_złego_typu_rzuca(parse):
    src = _ROZGRYWKA + (
        "aby działać:\n"
        "    stan to rozstrzygaj od prawdy\n"
        "    owoc stanu to pięć\n"
    )
    with pytest.raises(TypeCheckError):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_unia_pole_niewspólne_wymaga_zawężenia(parse):
    """Pole obecne tylko w części wariantów — czytelna odmowa
    z listą braków."""
    src = _ROZGRYWKA + (
        "aby działać:\n"
        "    stan to rozstrzygaj od prawdy\n"
        "    dokąd to kierunek stanu\n"
    )
    with pytest.raises(
        TypeCheckError,
        match=r"(?s)pole 'kierunek' nie jest wspólne wariantom unii "
              r"'Rozgrywka \(Pełzanie albo Porażka\)'.*mają je: "
              r"Pełzanie.*brakuje go w: Porażka.*zawęź dopasowaniem "
              r"`jest:`",
    ):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_unia_pole_wspólne_z_nazwy_różne_typy(parse):
    src = (
        "definicja Kubła:\n"
        "    waga (Liczba)\n"
        "\n"
        "definicja Worka:\n"
        "    waga (Znak)\n"
        "\n"
        "Pojemnik to Kubeł albo Worek\n"
        "\n"
        "aby wybierać od flagi:\n"
        "    jeśli flaga:\n"
        "        zwróć Kubeł o wadze pięć\n"
        "    zwróć Worek o wadze 'w'\n"
        "\n"
        "aby działać:\n"
        "    rupieć to wybieraj od prawdy\n"
        "    ciężar to waga rupiecia\n"
    )
    with pytest.raises(
        TypeCheckError,
        match=r"(?s)pole 'waga' jest wspólne wariantom unii "
              r"'Pojemnik \(Kubeł albo Worek\)' z nazwy, ale nie "
              r"z typu.*Kubeł ma 'Liczba'.*Worek ma 'Znak'.*"
              r"identycznego typu",
    ):
        typechecker.resolve_module(parse(src))


_POJEMNIKI_ROZJECHANE = (
    "definicja Ogniwa z elementem:\n"
    "    głowa (element)\n"
    "    ogon (Lista)\n"
    "\n"
    "Lista to Ogniwo albo Nic\n"
    "\n"
    "definicja Kubła z gratem:\n"
    "    zapas (Lista o elemencie grat)\n"
    "\n"
    "%s"
    "\n"
    "Pojemnik to Kubeł albo Worek\n"
    "\n"
    "aby wybierać od flagi:\n"
    "    jeśli flaga:\n"
    "        zwróć Kubeł o zapasie (Ogniwo o głowie pięć o ogonie Nic)\n"
    "    zwróć Worek o zapasie (Ogniwo o głowie sześć o ogonie Nic)\n"
    "\n"
    "aby działać:\n"
    "    rupieć to wybieraj od prawdy\n"
    "    zbiór to zapas rupiecia\n"
)


@pytest.mark.integration
def test_unia_parametr_niewspółdzielony_diagnoza(parse):
    """Pole wspólne z nazwy, ale parametry nazwane różnie to osobne
    sloty unii — komunikat nazywa oba z rodowodem."""
    src = _POJEMNIKI_ROZJECHANE % (
        "definicja Worka ze sztuką:\n"
        "    zapas (Lista o elemencie sztuka)\n"
    )
    with pytest.raises(TypeCheckError) as ei:
        typechecker.resolve_module(parse(src))
    tekst = str(ei.value)
    assert "pole 'zapas' jest wspólne wariantom unii" in tekst
    assert "parametr nie jest współdzielony" in tekst
    assert "'grat' (z definicji 'Kubeł')" in tekst
    assert "'sztuka' (z definicji 'Worek')" in tekst
    assert "po NAZWIE parametru" in tekst


@pytest.mark.integration
def test_pole_luźne_zakazane_w_wariancie_unii(parse):
    """Wariant z polem luźnym nie przechodzi walidacji — zakaz pól
    luźnych uprzedza dawny scenariusz „slot kontra wolny"."""
    src = _POJEMNIKI_ROZJECHANE % (
        "definicja Worka:\n"
        "    zapas (Lista)\n"
    )
    with pytest.raises(
        TypeCheckError,
        match=r"(?s)pole 'zapas' struktury 'Worek' nie wiąże parametru "
              r"'element' typu 'Lista'.*pola luźne są zakazane",
    ):
        typechecker.resolve_module(parse(src))


# Aplikacja nazwana na STRUKTURZE wiąże argumenty granicami na świeżych
# zmiennych (nie wprost, jak unia) — porównanie typów pola musi patrzeć
# przez te granice (`_sedno_pola`).

_PARA = (
    "definicja Pary z klucza na wartość:\n"
    "    znamię (klucz)\n"
    "    ładunek (wartość)\n"
    "\n"
)


def _pojemnik_przez_parę(kubeł_para, worek_para, worek_binder="z gratem",
                         worek_znamię="siedem"):
    return _PARA + (
        f"definicja Kubła ze sztuką:\n"
        f"    spis (Para {kubeł_para})\n"
        f"\n"
        f"definicja Worka {worek_binder}:\n"
        f"    spis (Para {worek_para})\n"
        f"\n"
        f"Pojemnik to Kubeł albo Worek\n"
        f"\n"
        f"aby wybierać od flagi:\n"
        f"    jeśli flaga:\n"
        f"        zwróć Kubeł o spisie (Para o znamieniu pięć o ładunku"
        f" sześć)\n"
        f"    zwróć Worek o spisie (Para o znamieniu {worek_znamię}"
        f" o ładunku osiem)\n"
        f"\n"
        f"aby działać:\n"
        f"    rupieć to wybieraj od prawdy\n"
        f"    wykaz to spis rupiecia\n"
    )


@pytest.mark.integration
def test_unia_aplikacja_na_strukturze_zgodne_przypięcia(parse):
    """Ten sam konkret i ten sam slot (po nazwie) w obu wariantach —
    pole wspólne mimo wiązań przez granice."""
    src = _pojemnik_przez_parę(
        "o kluczu Liczba o wartości sztuka",
        "o kluczu Liczba o wartości sztuka",
        worek_binder="ze sztuką",
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["wykaz"].startswith("Para")


@pytest.mark.integration
def test_unia_aplikacja_na_strukturze_różne_przypięcia_rzuca(parse):
    """`Para o kluczu Liczba` kontra `Para o kluczu Znak` — różnica
    siedzi w granicach świeżych zmiennych, nie w argumentach wprost;
    bez patrzenia przez granice checker twierdziłby Liczba przy
    wartości Znak (statyczne kłamstwo)."""
    src = _pojemnik_przez_parę(
        "o kluczu Liczba o wartości sztuka",
        "o kluczu Znak o wartości grat",
        worek_znamię="'z'",
    )
    with pytest.raises(
        TypeCheckError,
        match=r"(?s)pole 'spis' jest wspólne wariantom unii "
              r"'Pojemnik \(Kubeł albo Worek\)' z nazwy, ale nie "
              r"z typu.*Para\[Liczba, \?\].*Para\[Znak, \?\]",
    ):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_unia_aplikacja_na_strukturze_różne_sloty_rzuca(parse):
    """Konkrety zgodne, ale parametry wartości nazwane różnie — slot
    unii osiągany przez granice też podlega współdzieleniu."""
    src = _pojemnik_przez_parę(
        "o kluczu Liczba o wartości sztuka",
        "o kluczu Liczba o wartości grat",
    )
    with pytest.raises(TypeCheckError) as ei:
        typechecker.resolve_module(parse(src))
    tekst = str(ei.value)
    assert "parametr nie jest współdzielony" in tekst
    assert "'sztuka' (z definicji 'Kubeł')" in tekst
    assert "'grat' (z definicji 'Worek')" in tekst


@pytest.mark.integration
def test_unia_dwuparametrowe_pole_pierwsza_różnica_wygrywa(parse):
    """Pole typu unijnego o DWÓCH parametrach, różne na obu pozycjach
    (strukturalnie i slotowo) — komunikat opisuje pierwszą różnicę
    w porządku argumentów (strukturalną), z pełnymi typami obu stron."""
    src = (
        "definicja Orła z klucza na wartość:\n"
        "    czub (klucz)\n"
        "    ogonek (wartość)\n"
        "\n"
        "definicja Reszki z klucza na wartość:\n"
        "    czub (klucz)\n"
        "    ogonek (wartość)\n"
        "\n"
        "Dwojak to Orzeł albo Reszka\n"
        "\n"
        "definicja Kubła ze sztuką:\n"
        "    spis (Dwojak o kluczu Liczba o wartości sztuka)\n"
        "\n"
        "definicja Worka z gratem:\n"
        "    spis (Dwojak o kluczu Znak o wartości grat)\n"
        "\n"
        "Pojemnik to Kubeł albo Worek\n"
        "\n"
        "aby wybierać od flagi:\n"
        "    jeśli flaga:\n"
        "        zwróć Kubeł o spisie (Orzeł o czubie pięć o ogonku"
        " sześć)\n"
        "    zwróć Worek o spisie (Orzeł o czubie 'z' o ogonku siedem)\n"
        "\n"
        "aby działać:\n"
        "    rupieć to wybieraj od prawdy\n"
        "    wykaz to spis rupiecia\n"
    )
    with pytest.raises(
        TypeCheckError,
        match=r"(?s)pole 'spis' jest wspólne wariantom unii "
              r"'Pojemnik \(Kubeł albo Worek\)' z nazwy, ale nie "
              r"z typu.*Dwojak\[Liczba, \?\].*Dwojak\[Znak, \?\]",
    ):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_pole_luźne_zakazane(parse):
    """ZAKAZ PÓL LUŹNYCH: pole typu generycznego bez związania
    parametru odpada w walidacji z receptą naprawy."""
    src = (
        "definicja Ogniwa z elementem:\n"
        "    głowa (element)\n"
        "    ogon (Lista)\n"
        "\n"
        "Lista to Ogniwo albo Nic\n"
        "\n"
        "definicja Kubła:\n"
        "    zapas (Lista)\n"
        "\n"
        "aby działać:\n"
        "    zwróć Nic\n"
    )
    with pytest.raises(
        TypeCheckError,
        match=r"(?s)pole 'zapas' struktury 'Kubeł' nie wiąże parametru "
              r"'element' typu 'Lista'.*w pełni związany.*aplikacją "
              r"nazwaną.*zadeklaruj w nagłówku parametr.*zakazane",
    ):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_pole_luźne_zakaz_częściowa_aplikacja(parse):
    """Aplikacja częściowa na strukturze (drugi parametr niezwiązany)
    to też pole luźne."""
    src = _PARA + (
        "definicja Kubła:\n"
        "    spis (Para o kluczu Liczba)\n"
        "\n"
        "aby działać:\n"
        "    zwróć Nic\n"
    )
    with pytest.raises(
        TypeCheckError,
        match=r"(?s)pole 'spis' struktury 'Kubeł' nie wiąże parametru "
              r"'wartość' typu 'Para'",
    ):
        typechecker.resolve_module(parse(src))


# =====================================================================
# Natychmiastowość joinów (dawne dziury z bad/)
# =====================================================================

_OGNIWA = (
    "definicja Ogniwa z elementem:\n"
    "    głowa (element)\n"
    "    ogon (Lista)\n"
    "\n"
    "Lista to Ogniwo albo Nic\n"
    "\n"
    "można wypisać coś (Cokolwiek) -> Nic\n"
    "\n"
)


@pytest.mark.integration
def test_join_tej_samej_głowy_unifikuje_argumenty_natychmiast(parse):
    """Dwa fakty Ogniwo[Liczba]/Ogniwo[Znak] na jednej zmiennej —
    konflikt w linii sprawcy, nie przy późniejszym odczycie (dawniej:
    ciche przejście, a z odczytem RecursionError)."""
    src = _OGNIWA + (
        "aby działać:\n"
        "    zbiór to Ogniwo o głowie pięć o ogonie Nic\n"
        "    zbiór to Ogniwo o głowie 'a' o ogonie Nic\n"
        "    wypisz zbiór\n"
    )
    with pytest.raises(
        TypeCheckError,
        match=r"(?s)niejawny argument 'element' typu 'Ogniwo'.*"
              r"nie można zunifikować",
    ):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_join_z_odczytem_pola_czysty_błąd(parse):
    """Wariant z odczytem pola — dawniej nieskończona rekursja
    diagnostyki (raise→render→raise), teraz czysty komunikat."""
    src = _OGNIWA + (
        "aby działać:\n"
        "    zbiór to Ogniwo o głowie pięć o ogonie Nic\n"
        "    zbiór to Ogniwo o głowie 'a' o ogonie Nic\n"
        "    wypisz głowa zbioru\n"
    )
    with pytest.raises(TypeCheckError, match="nie można zunifikować"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_join_z_adnotacją_czysty_błąd(parse):
    """Konflikt elementów pod adnotowaną deklaracją `(Lista)` — czysty
    błąd zamiast rekursji diagnostyki."""
    src = _OGNIWA + (
        "aby działać:\n"
        "    zbiór (Lista) to Ogniwo o głowie pięć o ogonie Nic\n"
        "    zbiór to Ogniwo o głowie 'a' o ogonie Nic\n"
        "    wypisz zbiór\n"
    )
    with pytest.raises(TypeCheckError, match="nie można zunifikować"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_strzałka_i_konkret_konflikt_natychmiast(parse):
    """Wartość funkcyjna i zwykła nie łączą się — błąd w linii
    przypisania, nie dopiero przy `zastosuj`/arytmetyce."""
    src = _OGNIWA + (
        "aby dodać liczbę (Liczba) do innej_liczby (Liczba) -> Liczba:\n"
        "    zwróć liczba plus inna_liczba\n"
        "\n"
        "aby działać:\n"
        "    f to zwiąż dodanie z dwa\n"
        "    f to pięć\n"
        "    wypisz f\n"
    )
    with pytest.raises(
        TypeCheckError,
        match=r"(?s)wartość funkcyjna i zwykła wartość nie łączą się",
    ):
        typechecker.resolve_module(parse(src))


_MAGAZYNY = (
    "definicja Ogniwa z elementem:\n"
    "    głowa (element)\n"
    "    ogon (Lista)\n"
    "\n"
    "Lista to Ogniwo albo Nic\n"
    "\n"
    "można wypisać coś (Cokolwiek) -> Nic\n"
    "\n"
    "definicja Kubła z elementem:\n"
    "    zapas (Lista o elemencie element)\n"
    "\n"
    "definicja Worka z elementem:\n"
    "    zapas (Lista o elemencie element)\n"
    "\n"
    "aby dodać liczbę (Liczba) do innej_liczby (Liczba) -> Liczba:\n"
    "    zwróć liczba plus inna_liczba\n"
    "\n"
    "aby zajrzeć do rzeczy:\n"
    "    zwróć zapas rzeczy\n"
    "\n"
    "aby zmierzyć listę (Lista) -> Liczba:\n"
    "    lista jest:\n"
    "        Ogniwem z ogonem:\n"
    "            zwróć jeden plus zmierz ogon\n"
    "        Niczym:\n"
    "            zwróć zero\n"
    "\n"
    "aby złożyć listę (Lista) z operacją z akumulatorem:\n"
    "    lista jest:\n"
    "        Ogniwem z głową z ogonem:\n"
    "            reszta to złóż ogon z operacją z akumulatorem\n"
    "            zwróć zastosuj operację z głową z resztą\n"
    "        Niczym:\n"
    "            zwróć akumulator\n"
    "\n"
    "aby działać:\n"
    "    k to Kubeł o zapasie (Ogniwo o głowie pięć o ogonie Nic)\n"
    "    w to Worek o zapasie (Ogniwo o głowie 'a' o ogonie Nic)\n"
    "    siatka to zajrzyj do k\n"
    "    sakwa to zajrzyj do w\n"
    "    wypisz złóż siatkę z dodaniem z zero\n"
)


@pytest.mark.integration
def test_wynik_łańcucha_sprzężony_z_kandydatem(parse):
    """Wynik łańcucha o wielu kandydatach niesie argumenty ZWYCIĘZCY
    per wywołanie: fold liczb po kuble liczb przechodzi, a zmierzenie
    sakwy znaków też — każda instancja rozstrzyga po swojemu."""
    src = _MAGAZYNY.replace(
        "    wypisz złóż siatkę z dodaniem z zero\n",
        "    wypisz złóż siatkę z dodaniem z zero\n"
        "    wypisz zmierz sakwę\n",
    )
    typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_wynik_łańcucha_kontaminacja_odrzucona(parse):
    """DAWNA DZIURA: fold dodawania po sakwie ZNAKÓW przechodził
    typechecker (wynik łańcucha gubił argumenty) i wybuchał w runtime —
    teraz czysty błąd typów."""
    src = _MAGAZYNY + "    wypisz złóż sakwę z dodaniem z zero\n"
    with pytest.raises(
        TypeCheckError,
        match="nie można zunifikować Znak z Liczba"
              "|nie można zunifikować Liczba z Znak",
    ):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_pola_tej_samej_lemmy_niejednoznaczny_odczyt(parse):
    """DAWNY BŁĄD SEMANTYKI: `formy papieru` czytało pole `forma`
    (dopasowanie po samej lemmie) — teraz głośna niejednoznaczność."""
    src = (
        "można wypisać coś (Cokolwiek) -> Nic\n"
        "\n"
        "definicja Ankiety:\n"
        "    forma (Liczba)\n"
        "    formy (Znak)\n"
        "\n"
        "aby działać:\n"
        "    papier to Ankieta o formie pięć o formach 'f'\n"
        "    wypisz formy papieru\n"
    )
    with pytest.raises(
        TypeCheckError,
        match=r"(?s)jest niejednoznaczny — pasuje do pól:.*'forma'"
              r".*nazwij pola rozróżnialnie",
    ):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_pole_związane_wszystkie_formy_legalne(parse):
    """Wiązania, które POZOSTAJĄ legalne: konkret w aplikacji nazwanej,
    parametr struktury wprost, przechwyt po nazwie, alias."""
    src = (
        "definicja Ogniwa z elementem:\n"
        "    głowa (element)\n"
        "    ogon (Lista)\n"
        "\n"
        "Lista to Ogniwo albo Nic\n"
        "\n"
        "Tekst to Lista o elemencie Znak\n"
        "\n"
        "definicja Kubła z elementem:\n"
        "    zapas (Lista)\n"
        "    metka (Tekst)\n"
        "    rozmiar (Liczba)\n"
        "\n"
        "definicja Worka:\n"
        "    zapas (Lista o elemencie Liczba)\n"
        "\n"
        "aby działać:\n"
        "    zwróć Nic\n"
    )
    typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_zwiąż_domknięcie_przez_slot_funkcyjny(parse):
    """Domknięcie przekazane jako argument aplikuje się w ciele odbiorcy."""
    src = _DODAWANIE + (
        "aby brać operację z liczbą (Liczba) -> Liczba:\n"
        "    zwróć zastosuj operację z liczbą\n"
        "\n"
        "aby działać:\n"
        "    domknięcie to zwiąż dodanie z dwa\n"
        "    wynik to bierz domknięcie z pięć\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["wynik"] == "Liczba"


# =====================================================================
# Integracja: totalność zwrotów i grounding
# =====================================================================

@pytest.mark.integration
def test_nietotalny_zwrot_dounifikowuje_nic(parse):
    src = (
        "aby badać flagę:\n"
        "    jeśli flaga:\n"
        "        zwróć 'z'\n"
    )
    with pytest.raises(TypeCheckError):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_adnotowany_zwrot_bez_zwróć_rzuca(parse):
    src = (
        "aby testować_nic -> Znak:\n"
        "    wynik to pięć\n"
    )
    with pytest.raises(TypeCheckError):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_grounding_wolnej_zmiennej_rzuca_ze_śladem(parse):
    src = (
        "można zapisać dane (Liczba) -> Zapis\n"
        "\n"
        "aby działać:\n"
        "    wynik to zapisz pięć\n"
    )
    with pytest.raises(
        TypeCheckError,
        match=r"nie można wywnioskować konkretnego typu zmiennej "
              r"'wynik'.*pochodzi z externa 'zapisz'",
    ):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_wolne_argumenty_unii_uchodzą_groundingowi(parse):
    """Nikt nie obserwuje elementu pustej listy — runtime go nie
    potrzebuje, grounding przepuszcza."""
    src = _ROZKAZY + (
        "aby działać:\n"
        "    pusta (Lista) to Nic\n"
    )
    typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_grounding_wewnątrz_funkcji_pomocniczych_nie_obowiązuje(parse):
    src = (
        "aby przetwarzać dla x:\n"
        "    zwróć x\n"
        "\n"
        "aby działać:\n"
        "    zwróć jeden\n"
    )
    typechecker.resolve_module(parse(src))  # wolny x poza działać — OK


# =====================================================================
# Integracja: pętla `dla` — głośna odmowa
# =====================================================================

@pytest.mark.integration
def test_pętla_dla_odmawia_głośno(parse):
    src = (
        "definicja Kosza:\n    rzecz (Liczba)\n"
        "\n"
        "aby działać:\n"
        "    kosz to Kosz o rzeczy pięć\n"
        "    dla sztuki w koszu:\n"
        "        x to jeden\n"
    )
    with pytest.raises(TypeCheckError, match="protokół iteracji"):
        typechecker.resolve_module(parse(src))


# =====================================================================
# Hierarchia unii (unie jako warianty unii)
# =====================================================================

def _moduł_hierarchii():
    typechecker.module = ast.Module(body=[
        ast.StructDef(name=("Kot",), fields=[], params=[]),
        ast.StructDef(name=("Labrador",), fields=[], params=[]),
        ast.StructDef(name=("Chihuahua",), fields=[], params=[]),
        ast.UnionDef(name=("Pies",),
                     members=[("Labrador",), ("Chihuahua",)]),
        ast.UnionDef(name=("Zwierzę",), members=[("Kot",), ("Pies",)]),
    ])


def test_podtypowanie_przechodnie_przez_poziomy():
    _moduł_hierarchii()
    assert typechecker.czy_głowa_podtypem("Labrador", "Pies")
    assert typechecker.czy_głowa_podtypem("Pies", "Zwierzę")
    assert typechecker.czy_głowa_podtypem("Labrador", "Zwierzę")
    assert not typechecker.czy_głowa_podtypem("Zwierzę", "Pies")
    assert not typechecker.czy_głowa_podtypem("Kot", "Pies")


def test_członkowie_przechodni_to_liście():
    _moduł_hierarchii()
    assert typechecker.członkowie_przechodni("Zwierzę") == {
        "Kot", "Labrador", "Chihuahua"}
    assert typechecker.członkowie_przechodni("Pies") == {
        "Labrador", "Chihuahua"}


def test_najmniejsza_unia_wybiera_poziom():
    _moduł_hierarchii()
    assert typechecker.najmniejsza_unia(
        {"Labrador", "Chihuahua"}) == "Pies"
    assert typechecker.najmniejsza_unia({"Labrador", "Kot"}) == "Zwierzę"
    assert typechecker.najmniejsza_unia({"Pies", "Kot"}) == "Zwierzę"


def test_ogranicz_liść_do_unii_babki():
    _moduł_hierarchii()
    ogranicz(Konkret("Labrador"), Konkret("Zwierzę"))  # nie rzuca
    ogranicz(Konkret("Pies"), Konkret("Zwierzę"))      # nie rzuca
    v = new_type()
    ogranicz(Konkret("Labrador"), v)
    ogranicz(Konkret("Kot"), v)
    assert ty(v) == "Zwierzę"


_HIERARCHIA = (
    "definicja Kota:\n    imię (Znak)\n"
    "\n"
    "definicja Jamnika:\n    kość (Znak)\n"
    "\n"
    "definicja Pudla:\n    fryzura (Znak)\n"
    "\n"
    "Pies to Jamnik albo Pudel\n"
    "\n"
    "Zwierzę to Kot albo Pies\n"
    "\n"
)


@pytest.mark.integration
def test_dopasowanie_gałęzią_unią(parse):
    """Gałąź `Psem:` pokrywa oba liście pod-unii — dopasowanie
    {Kot, Pies} na Zwierzęciu jest wyczerpujące."""
    src = _HIERARCHIA + (
        "aby opisać zwierzę (Zwierzę) -> Znak:\n"
        "    zwierzę jest:\n"
        "        Kotem z imieniem:\n"
        "            zwróć imię\n"
        "        Psem:\n"
        "            zwróć 'p'\n"
        "\n"
        "aby działać:\n"
        "    litera to opisz Jamnik o kości 'j'\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["litera"] == "Znak"


@pytest.mark.integration
def test_dopasowanie_liśćmi_przez_poziomy(parse):
    """Wyczerpująco także mieszanką poziomów: {Kot, Jamnik, Pudel}."""
    src = _HIERARCHIA + (
        "aby opisać zwierzę (Zwierzę) -> Znak:\n"
        "    zwierzę jest:\n"
        "        Kotem z imieniem:\n"
        "            zwróć imię\n"
        "        Jamnikiem z kością:\n"
        "            zwróć kość\n"
        "        Pudlem z fryzurą:\n"
        "            zwróć fryzura\n"
    )
    typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_nakładające_się_gałęzie_rzucają(parse):
    src = _HIERARCHIA + (
        "aby opisać zwierzę (Zwierzę) -> Znak:\n"
        "    zwierzę jest:\n"
        "        Kotem z imieniem:\n"
        "            zwróć imię\n"
        "        Psem:\n"
        "            zwróć 'p'\n"
        "        Jamnikiem:\n"
        "            zwróć 'j'\n"
    )
    with pytest.raises(TypeCheckError,
                       match="nakładające się gałęzie"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_join_wybiera_najciaśniejszy_poziom(parse):
    src = _HIERARCHIA + (
        "aby działać:\n"
        "    pupil to Jamnik o kości 'a'\n"
        "    pupil to Pudel o fryzurze 'b'\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["pupil"] == "Pies"


@pytest.mark.integration
def test_liść_przechodzi_do_slotu_babki(parse):
    src = _HIERARCHIA + (
        "aby przyjąć zwierzę (Zwierzę) -> Liczba:\n"
        "    zwróć zero\n"
        "\n"
        "aby działać:\n"
        "    n to przyjmij Jamnik o kości 'x'\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["n"] == "Liczba"


# =====================================================================
# Punkt wejścia z argumentami — `aby działać dla argumentów:`
# =====================================================================

@pytest.mark.integration
def test_działać_z_parametrem_dostaje_listę_tekstów(parse):
    src = _PRZYGRYWKA + (
        "aby działać dla argumentów:\n"
        "    rozmiar to zmierz argumenty\n"
    )
    typechecker.resolve_module(parse(src))
    types = _var_types()
    assert types["argumentów"] == "Lista[Lista[Znak]]"   # Lista[Tekst]
    assert types["rozmiar"] == "Liczba"


@pytest.mark.integration
def test_działać_z_dwoma_parametrami_rzuca(parse):
    src = _PRZYGRYWKA + (
        "aby działać dla argumentów z liczbą (Liczba):\n"
        "    zwróć jeden\n"
    )
    with pytest.raises(TypeCheckError,
                       match="najwyżej JEDEN parametr"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_działać_z_parametrem_bez_przygrywki_rzuca(parse):
    src = (
        "aby działać dla argumentów:\n"
        "    zwróć jeden\n"
    )
    with pytest.raises(TypeCheckError,
                       match="uwzględnij przygrywka.ć"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_działać_z_parametrem_odrzuca_złe_użycie(parse):
    """Argument programu to Tekst — dodanie go do Liczby pęka."""
    src = _PRZYGRYWKA + (
        "aby działać dla argumentów:\n"
        "    argumenty są:\n"
        "        Ogniwem z głową:\n"
        "            suma to głowa plus jeden\n"
        "        Niczym:\n"
        "            zwróć Nic\n"
    )
    with pytest.raises(TypeCheckError):
        typechecker.resolve_module(parse(src))
