"""Testy komunikatów błędów (komunikaty_błędów.md) — gładszy DX.

Każdy nowy komunikat ma tu test integracyjny przez pełny pipeline
(lex → morph → parse → resolve → typecheck [→ execute]). SGJP z sesyjnej
fixtury w conftest.py.
"""

import pytest

import lexer
import morph_anal
import preprocess
import parser as parser_mod
import expression
import ast_nodes as ast
import typechecker
import executor


@pytest.fixture(autouse=True)
def _reset_typechecker():
    typechecker.last_type = 0
    typechecker.fun_decls = []
    typechecker.fun_scopes = []
    typechecker.module = None
    yield
    typechecker.last_type = 0
    typechecker.fun_decls = []
    typechecker.fun_scopes = []
    typechecker.module = None


@pytest.fixture
def parse(db, preps):
    def _parse(text):
        morphs = preprocess.preprocess(morph_anal.analyze(lexer.lex(text), db))
        module = parser_mod.parse(morphs, preps)
        expression.resolve_module(module, preps)
        return module
    return _parse


@pytest.fixture
def run(parse):
    """Pełny pipeline z wykonaniem — do testów błędów runtime."""
    def _run(text):
        module = parse(text)
        typechecker.resolve_module(module)
        executor.execute(module)
    return _run


# =====================================================================
# Pkt 1 — każdy TypeCheckError z linią; poszlaki przy błędzie unifikacji
# =====================================================================

@pytest.mark.integration
def test_unify_error_carries_line_context(parse):
    """Konflikt typów w ciele funkcji niesie linię i nazwę funkcji."""
    src = (
        "aby działać:\n"
        "    rzecz to jeden\n"
        "    rzecz to 'z'\n"
    )
    with pytest.raises(typechecker.TypeCheckError, match=r"lini\w+ 3"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_unify_error_lists_clues_about_both_sides(parse):
    """Błąd unifikacji wypisuje poszlaki: miejsca, w których wnioskowano
    o obu stronach konfliktu — z liniami."""
    src = (
        "aby działać:\n"
        "    rzecz to jeden\n"
        "    rzecz to 'z'\n"
    )
    with pytest.raises(typechecker.TypeCheckError) as ei:
        typechecker.resolve_module(parse(src))
    msg = str(ei.value)
    assert "nie można zunifikować" in msg
    assert "zmienna 'rzecz'" in msg          # etykieta zamiast tN
    assert "wpływa do niej" in msg           # poszlakownik: pełne granice
    assert "linia 2" in msg                  # pierwsze przypisanie (Liczba)
    assert "przypisanie do 'rzecz'" in msg
    assert "← sprzeczna" in msg              # nadchodząca granica oznaczona
    assert "zadeklaruj unię" in msg          # sugestia naprawy


# =====================================================================
# Pkt 2 + 20 — Ć-owy stos wywołań; przekroczenie głębokości rekursji
# =====================================================================

_REKURSJA_BEZ_DNA = (
    "aby liczyć x:\n"
    "    jeśli x równe zero:\n"
    "        zwróć zero\n"
    "    zwróć licz x\n"
    "\n"
    "aby działać:\n"
    "    wynik to licz jeden\n"
)


@pytest.mark.integration
def test_recursion_error_names_function_and_hints_base_case(run):
    with pytest.raises(
        executor.CRuntimeError,
        match=r"przekroczono głębokość rekursji .*w 'liczyć'.*"
              r"przypadek bazowy.*limit interpretera",
    ):
        run(_REKURSJA_BEZ_DNA)


@pytest.mark.integration
def test_runtime_error_carries_c_stack(run):
    """CRuntimeError niesie stos: ramki z lematami funkcji i liniami
    instrukcji — od 'działać' po najgłębsze 'liczyć' (linia 4: zwrot)."""
    with pytest.raises(executor.CRuntimeError) as ei:
        run(_REKURSJA_BEZ_DNA)
    stack = ei.value.stack
    assert stack[0] == ("działać", 7)
    assert stack[-1][0] == "liczyć"
    # Ramki wołające stoją na linii 4 (`zwróć licz x`); najgłębsza mogła
    # pęknąć już przy warunku w linii 2.
    assert ("liczyć", 4) in stack
    assert len(stack) > 100  # faktyczna głębokość rekursji, nie atrapa


# =====================================================================
# Wbudowane dzielenie: dzielenie przez zero to czytelny błąd wykonania
# =====================================================================

_DZIELENIE_PRELUDE = (
    "można podzielić pierwszą_liczbę (Liczba) przez drugą_liczbę (Liczba)"
    " -> Liczba\n"
    "\n"
    "można wziąć_resztę_z_dzielenia pierwszej_liczby (Liczba) przez "
    "drugą_liczbę (Liczba) -> Liczba\n"
    "\n"
)


@pytest.mark.integration
def test_division_by_zero_reports_location(run):
    src = _DZIELENIE_PRELUDE + (
        "aby działać:\n"
        "    iloraz to podziel pięć przez zero\n"
    )
    with pytest.raises(
        executor.CRuntimeError,
        match=r"dzielenie przez zero \(linia 6, w funkcji 'działać'\)",
    ):
        run(src)


@pytest.mark.integration
def test_modulo_by_zero_reports_location(run):
    src = _DZIELENIE_PRELUDE + (
        "aby działać:\n"
        "    reszta to weź_resztę_z_dzielenia pięciu przez zero\n"
    )
    with pytest.raises(
        executor.CRuntimeError,
        match=r"reszta z dzielenia przez zero",
    ):
        run(src)


# =====================================================================
# Pkt 18 — odczyt/zapis pola z wartości bez tego pola
# =====================================================================

def test_field_read_from_nic_names_field_and_type():
    nic = executor.RuntimeValue(value=None, type="Nic")
    with pytest.raises(
        RuntimeError,
        match=r"odczyt pola 'imię' z wartości typu 'Nic' — wartość nie "
              r"jest wariantem posiadającym to pole",
    ):
        executor._field_value(nic, [(("imię",), "sg", "n")])


def test_field_write_to_nic_names_field_and_type():
    nic = executor.RuntimeValue(value=None, type="Nic")
    with pytest.raises(RuntimeError, match=r"zapis pola 'imię' z wartości"):
        executor._field_set(nic, [(("imię",), "sg", "n")],
                            executor.RuntimeValue(value=1, type="Liczba"))


# =====================================================================
# Pkt 9 — chain przez wartość typu unii: podpowiedź zawężenia
# =====================================================================

@pytest.mark.integration
def test_chain_on_union_value_suggests_narrowing(parse):
    src = (
        "definicja Kota:\n"
        "    imię (Znak)\n"
        "\n"
        "definicja Psa:\n"
        "    kość (Znak)\n"
        "\n"
        "Zwierzę to Kot albo Pies\n"
        "\n"
        "aby przyjąć zwierzę (Zwierzę) -> Liczba:\n"
        "    zwróć zero\n"
        "\n"
        "aby działać:\n"
        "    zwierzę (Zwierzę) to Kot o imieniu 'M'\n"
        "    ozdoba to imię zwierzęcia\n"
    )
    with pytest.raises(
        typechecker.TypeCheckError,
        match=r"(?s)pole 'imię' czytane z wartości typu unii "
              r"'Zwierzę \(Kot albo Pies\)'.*zawęź dopasowaniem "
              r"`jest:`.*pole ma wariant Kot.*wartość stała się unią",
    ):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_chain_on_union_with_nic_mentions_nic(parse):
    src = (
        "definicja Ogniwa z elementem:\n"
        "    głowa (element)\n"
        "    ogon (Lista)\n"
        "\n"
        "Lista to Ogniwo albo Nic\n"
        "\n"
        "aby brać listę (Lista):\n"
        "    zwróć głowa listy\n"
    )
    with pytest.raises(
        typechecker.TypeCheckError,
        match=r"(?s)pole 'głowa' czytane z wartości typu unii "
              r"'Lista \(Nic albo Ogniwo\)' \(może być Niczym\)",
    ):
        typechecker.resolve_module(parse(src))


# =====================================================================
# Pkt 16 — łańcuch bez kandydatów: TypeCheckError zamiast gołego raise
# =====================================================================

@pytest.mark.integration
def test_unresolvable_chain_lists_candidates(parse):
    """Chain 'imię kości psa' — pole 'imię' istnieje (Kot), ale kość jest
    Znakiem, więc żaden kandydat nie domyka łańcucha."""
    src = (
        "definicja Kota:\n"
        "    imię (Znak)\n"
        "\n"
        "definicja Psa:\n"
        "    kość (Znak)\n"
        "\n"
        "aby działać:\n"
        "    pies to Pies o kości 'k'\n"
        "    x to imię kości psa\n"
    )
    with pytest.raises(
        typechecker.TypeCheckError,
        match=r"nie można zresolvować łańcucha dopełniaczowego "
              r"'imię kości psa' \(linia 9\) — pole 'kości' mają struktury: "
              r"Pies, ale żadna nie domyka",
    ):
        typechecker.resolve_module(parse(src))


# =====================================================================
# Pkt 10 — niejawne argumenty unii: konflikt nazywa parametr z rodowodem
# =====================================================================

@pytest.mark.integration
def test_union_arg_conflict_names_parameter_with_pedigree(parse):
    src = (
        "definicja Ogniwa z elementem:\n"
        "    głowa (element)\n"
        "    ogon (Lista)\n"
        "\n"
        "Lista to Ogniwo albo Nic\n"
        "\n"
        "aby działać:\n"
        "    lista to Ogniwo o głowie pięć o ogonie "
        "(Ogniwo o głowie 'a' o ogonie Nic)\n"
    )
    with pytest.raises(typechecker.TypeCheckError) as ei:
        typechecker.resolve_module(parse(src))
    msg = str(ei.value)
    assert "niejawny argument 'element'" in msg
    assert "z definicji 'Ogniwo'" in msg
    assert "nie można zunifikować" in msg   # wewnętrzny konflikt z poszlakami


# =====================================================================
# Pkt 14 — grounding wskazuje źródło nieustalonego typu (ekstern)
# =====================================================================

@pytest.mark.integration
def test_grounding_error_names_extern_origin(parse):
    src = (
        "można zapisać dane (Liczba) -> Zapis\n"
        "\n"
        "aby działać:\n"
        "    wynik to zapisz pięć\n"
    )
    with pytest.raises(
        typechecker.TypeCheckError,
        match=r"(?s)nie można wywnioskować konkretnego typu zmiennej "
              r"'wynik'.*pochodzi z externa 'zapisz' \(czysta świeżość\).*"
              r"użyj wartości strukturalnie albo dodaj adnotację",
    ):
        typechecker.resolve_module(parse(src))


# =====================================================================
# Pkt 7 — tabelka slotów przy niedopasowaniu argumentów wywołania
# =====================================================================

@pytest.mark.integration
def test_arg_slot_mismatch_shows_slot_table(parse):
    src = (
        "aby dodać liczbę do sumy -> Liczba:\n"
        "    zwróć liczba plus suma\n"
        "\n"
        "aby działać:\n"
        "    kwota to pięć\n"
        "    wynik to dodaj pięć kwota\n"
    )
    with pytest.raises(ast.ResolveError) as ei:
        parse(src)
    msg = str(ei.value)
    assert "nie pasuje do żadnego wolnego parametru" in msg
    assert "sloty:" in msg
    assert "`liczbę` (biernik)" in msg
    assert "`do sumy` (" in msg
    assert "otrzymano: 'kwota' (mianownik" in msg
    assert "argument w nawiasie jest bezprzypadkowy" in msg


# =====================================================================
# Pkt 4 — rozkaźnik drugiego aspektu zadeklarowanej funkcji
# =====================================================================

@pytest.mark.integration
def test_undeclared_imperative_suggests_aspect_pair(parse):
    src = (
        "aby oceniać liczbę (Liczba) -> Liczba:\n"
        "    zwróć liczba\n"
        "\n"
        "aby działać:\n"
        "    wynik to oceń pięć\n"
    )
    with pytest.raises(ast.ResolveError) as ei:
        parse(src)
    msg = str(ei.value)
    assert "'oceń' to rozkaźnik od 'ocenić'" in msg
    assert "zadeklarowana jest funkcja 'oceniać'" in msg
    assert "jej rozkaźnik to 'oceniaj'" in msg
    assert "albo zmień deklarację na 'ocenić'" in msg


# =====================================================================
# Pkt 5 — pułapka liczebnikowa (nazwa z num-odczytem w SGJP)
# =====================================================================

@pytest.mark.integration
def test_numeral_word_as_name_names_the_trap(parse):
    src = (
        "aby działać:\n"
        "    szereg to pięć\n"
    )
    with pytest.raises(ast.InterpreterError) as ei:
        parse(src)
    msg = str(ei.value)
    assert "ma w SGJP odczyt liczebnikowy i nie może być nazwą" in msg
    assert "spis" in msg


# =====================================================================
# Pkt 6 — słowo spoza SGJP w pozycji pola/parametru
# =====================================================================

@pytest.mark.integration
def test_word_outside_sgjp_in_field_position(parse):
    src = (
        "definicja Rzeczy:\n"
        "    arność (Liczba)\n"
    )
    with pytest.raises(ast.InterpreterError) as ei:
        parse(src)
    msg = str(ei.value)
    assert "słowo 'arność' (pole struktury) nie występuje w SGJP" in msg
    assert "redis-cli EXISTS sgjp:f:arność" in msg
    assert "odmienialny synonim" in msg


@pytest.mark.integration
def test_word_outside_sgjp_in_param_position(parse):
    src = (
        "aby liczyć arność -> Liczba:\n"
        "    zwróć zero\n"
    )
    with pytest.raises(ast.InterpreterError) as ei:
        parse(src)
    assert "słowo 'arność' (parametr) nie występuje w SGJP" in str(ei.value)


# =====================================================================
# Pkt 3 — kolizja „nawias po wyrażeniu = adnotacja" (quirk 16)
# =====================================================================

@pytest.mark.integration
def test_paren_after_expression_annotation_collision_hint(parse):
    src = (
        "definicja Kota:\n"
        "    imię (Znak)\n"
        "\n"
        "aby działać:\n"
        "    kot to Kot o imieniu 'a'\n"
        "    inny to kot (Kot o imieniu 'b')\n"
    )
    with pytest.raises(ast.ResolveError) as ei:
        parse(src)
    msg = str(ei.value)
    assert "nawias po wyrażeniu to adnotacja typu" in msg
    assert "poprzedź nawias przyimkiem" in msg
    assert "zmiennej pośredniej" in msg


# =====================================================================
# Pkt 8 — ostrzeżenie: wiązanie pola przesłania parametr (quirk 10)
# =====================================================================

@pytest.mark.integration
def test_match_binding_shadowing_param_warns(parse, capsys):
    src = (
        "definicja Sukcesu z elementem:\n"
        "    wartość (element)\n"
        "\n"
        "definicja Błędu:\n"
        "    opis (Znak)\n"
        "\n"
        "Rezultat to Sukces albo Błąd\n"
        "\n"
        "aby badać rezultat (Rezultat) z wartością (Liczba) -> Liczba:\n"
        "    rezultat jest:\n"
        "        Sukcesem z wartością:\n"
        "            zwróć zero\n"
        "        Błędem:\n"
        "            zwróć wartość\n"
    )
    parse(src)
    err = capsys.readouterr().err
    assert "OSTRZEŻENIE (linia 11)" in err
    assert "wiązanie 'wartością' przesłania widoczną zmienną" in err
    assert "to pole, nie tamta zmienna" in err


@pytest.mark.integration
def test_incomplete_struct_lists_missing_fields(parse):
    """Pkt 15 — komunikat kompletności konstrukcji istnieje od dawna;
    ten test przybija treść: nazwa struktury + lista brakujących pól."""
    src = (
        "definicja Kota:\n"
        "    imię (Znak)\n"
        "    wiek (Liczba)\n"
        "\n"
        "aby działać:\n"
        "    kot to Kot o imieniu 'a'\n"
    )
    with pytest.raises(ast.ResolveError) as ei:
        parse(src)
    msg = str(ei.value)
    assert "tworzenie struktury 'Kot' wymaga wszystkich pól" in msg
    assert "brakuje:" in msg
    assert "wiek" in msg


@pytest.mark.integration
def test_match_binding_without_shadowing_is_silent(parse, capsys):
    src = (
        "definicja Sukcesu z elementem:\n"
        "    wartość (element)\n"
        "\n"
        "definicja Błędu:\n"
        "    opis (Znak)\n"
        "\n"
        "Rezultat to Sukces albo Błąd\n"
        "\n"
        "aby badać rezultat (Rezultat) -> Liczba:\n"
        "    rezultat jest:\n"
        "        Sukcesem z wartością:\n"
        "            zwróć wartość\n"
        "        Błędem:\n"
        "            zwróć zero\n"
    )
    parse(src)
    assert "OSTRZEŻENIE" not in capsys.readouterr().err


# =====================================================================
# MLsub — nowa diagnostyka (komunikaty_błędów.md po migracji)
# =====================================================================

@pytest.mark.integration
def test_kontrast_oczekiwane_otrzymane_w_argumencie(parse):
    src = (
        "aby brać x (Znak) -> Znak:\n"
        "    zwróć x\n"
        "\n"
        "aby działać:\n"
        "    y to bierz pięć\n"
    )
    with pytest.raises(
        typechecker.TypeCheckError,
        match=r"argument 1 wywołania 'bierz': oczekiwano Znak, "
              r"otrzymano Liczba",
    ):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_prawie_trafienia_unii_w_dopasowaniu(parse):
    src = (
        "definicja Kota:\n    imię (Znak)\n"
        "\n"
        "definicja Psa:\n    kość (Znak)\n"
        "\n"
        "definicja Chomika:\n    futro (Znak)\n"
        "\n"
        "Zwierzę to Kot albo Pies\n"
        "\n"
        "aby badać coś:\n"
        "    coś jest:\n"
        "        Kotem:\n"
        "            zwróć jeden\n"
        "        Chomikiem:\n"
        "            zwróć dwa\n"
    )
    with pytest.raises(
        typechecker.TypeCheckError,
        match=r"(?s)nie odpowiadają członkom.*najbliżej:.*"
              r"Zwierzę \(Kot albo Pies\) — brakuje: Pies; "
              r"nadmiarowe: Chomik",
    ):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_dyskryminatory_przy_nierozstrzygniętej_dysjunkcji(parse):
    src = (
        "definicja Sukcesu z elementem:\n    wartość (element)\n"
        "\n"
        "definicja Błędu:\n    numer (Liczba)\n"
        "\n"
        "definicja Porażki:\n    powód (Znak)\n"
        "\n"
        "Rezultat to Sukces albo Błąd\n"
        "Wynik to Sukces albo Porażka\n"
        "\n"
        "aby wytwarzać coś:\n"
        "    zwróć coś\n"
        "\n"
        "aby działać:\n"
        "    tajemnica to wytwarzaj pięć\n"
        "    tajemnica jest:\n"
        "        Sukcesem:\n"
        "            x to jeden\n"
        "        inaczej:\n"
        "            x to dwa\n"
    )
    with pytest.raises(
        typechecker.TypeCheckError,
        match=r"(?s)pasuje do wielu możliwości.*"
              r"możliwości zebrane: dopasowanie z 'inaczej:'.*"
              r"wariantu-dyskryminatora: Błąd \(tylko Rezultat\)",
    ):
        typechecker.resolve_module(parse(src))
