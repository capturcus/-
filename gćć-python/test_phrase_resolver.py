import os

import pytest

import lexer
import morph_anal
import parser as parser_mod
import phrase_resolver

SGJP_PATH = os.path.join(os.path.dirname(__file__), "..", "sgjp.tab")


# ---------- fixtures ----------

@pytest.fixture(scope="session")
def _loaded():
    return morph_anal.load(SGJP_PATH)


@pytest.fixture(scope="session")
def _db(_loaded):
    return _loaded[0]


@pytest.fixture(scope="session")
def _preps(_loaded):
    return _loaded[1]


# Wspólny zestaw struktur dla większości testów. Pola, które wykorzystujemy:
#   Komentarz: identyfikator, autor, post, treść
#   Użytkownik: identyfikator, nazwa, imię
#   Post: identyfikator, autor, treść, liczba_polubień
#   Sesja: flaga_aktywności, użytkownik
STRUCTS = (
    "definicja Komentarza:\n"
    "    identyfikator (Tekst)\n"
    "    autor (Użytkownik)\n"
    "    post (Post)\n"
    "    treść (Tekst)\n"
    "\n"
    "definicja Użytkownika:\n"
    "    identyfikator (Tekst)\n"
    "    nazwa (Tekst)\n"
    "    imię (Tekst)\n"
    "\n"
    "definicja Postu:\n"
    "    identyfikator (Tekst)\n"
    "    autor (Użytkownik)\n"
    "    treść (Tekst)\n"
    "    liczba_polubień (Liczba)\n"
    "\n"
    "definicja Sesji:\n"
    "    flaga_aktywności (Przełącznik)\n"
    "    użytkownik (Użytkownik)\n"
    "\n"
)


# Funkcje wymagane przez resolver (każde wywołanie musi mieć definicję).
# `pisać`/`zapisać` MUSZĄ mieć dokładnie tyle paramów, ile dany test podaje
# w call site (signature-aware fn-call walidates arity). Universal sig się
# nie sprawdza — zamiast tego każdy test wstawia inline def przez `_pisać_sig`
# / `_zapisać_sig` pasującą do swojego wywołania. FUNCTIONS prelude trzyma
# tylko fns o stałej arity, używane spójnie w testach.
FUNCTIONS = (
    "aby pracować:\n"
    "    zwrócić\n"
    "\n"
    "aby wziąć_z_bazy z bazy:\n"
    "    zwrócić\n"
    "\n"
    "aby wziąć_nazwę_z_bazy o identyfikatorze:\n"
    "    zwrócić\n"
    "\n"
    "aby wziąć_użytkownika_z_bazy o identyfikatorze:\n"
    "    zwrócić\n"
    "\n"
    "aby stworzyć_post z treścią dla użytkownika:\n"
    "    zwrócić\n"
    "\n"
    "aby polubić post (Post):\n"
    "    zwrócić\n"
    "\n"
    "aby abdykować:\n"
    "    zwrócić\n"
    "\n"
    "aby przestać_obserwować użytkownika:\n"
    "    zwrócić\n"
    "\n"
)


def _pisać_sig(*params):
    """Inline def `aby pisać <params>:` — testy używają per-arity."""
    suffix = " " + " ".join(params) if params else ""
    return f"aby pisać{suffix}:\n    zwrócić\n\n"


def _zapisać_sig(*params):
    suffix = " " + " ".join(params) if params else ""
    return f"aby zapisać{suffix}:\n    zwrócić\n\n"


@pytest.fixture
def resolve(_db, _preps):
    """Parsuje i resolwuje moduł. Każdy test dostaje świeży fields=[]."""

    def _resolve(body, with_structs=True, with_functions=True):
        phrase_resolver.fields = []
        text = ""
        if with_structs:
            text += STRUCTS
        if with_functions:
            text += FUNCTIONS
        text += body
        ast = parser_mod.parse(morph_anal.analyze(lexer.lex(text), _db), _preps)
        phrase_resolver.resolve_module(ast)
        return ast

    return _resolve


# ---------- helpers ----------

def _func_def(ast, name=("działać",)):
    """Domyślnie zwraca FunctionDef o nazwie `działać` (typowy wrapper testu).
    FUNCTIONS prelude wprowadza wiele FunctionDefów do modułu, więc nie można
    polegać na 'pierwszym napotkanym' — bierzemy konkretny."""
    for node in ast.body:
        if isinstance(node, parser_mod.FunctionDef):
            if node.name.segments == name:
                return node
    raise AssertionError(f"nie znaleziono FunctionDef o nazwie {name}")


def _walk_phrases(node, out):
    if isinstance(node, parser_mod.Phrase):
        out.append(node)
        for w in node.words:
            if not isinstance(w.value, parser_mod.Identifier):
                _walk_phrases(w.value, out)
        return
    if isinstance(node, parser_mod.Module):
        for s in node.body:
            _walk_phrases(s, out)
        return
    if isinstance(node, parser_mod.FunctionDef):
        for s in node.body:
            _walk_phrases(s, out)
        return
    if isinstance(node, parser_mod.Assignment):
        _walk_phrases(node.target, out)
        _walk_phrases(node.value, out)
        return
    if isinstance(node, parser_mod.If):
        _walk_phrases(node.cond, out)
        for s in node.then_body:
            _walk_phrases(s, out)
        for s in node.else_body:
            _walk_phrases(s, out)
        return
    if isinstance(node, parser_mod.While):
        _walk_phrases(node.cond, out)
        for s in node.body:
            _walk_phrases(s, out)
        return
    if isinstance(node, parser_mod.Return):
        if node.value is not None:
            _walk_phrases(node.value, out)
        return
    if isinstance(node, (parser_mod.BinOp, parser_mod.And, parser_mod.Or)):
        _walk_phrases(node.left, out)
        _walk_phrases(node.right, out)
        return
    if isinstance(node, (parser_mod.UnaryOp, parser_mod.Not)):
        _walk_phrases(node.operand, out)
        return


def _first_phrase(ast):
    out = []
    _walk_phrases(ast, out)
    return out[0]


def _chain_segments(chain_or_phrase):
    if isinstance(chain_or_phrase, parser_mod.Phrase):
        gc = chain_or_phrase.resolved_phrase
    else:
        gc = chain_or_phrase
    assert isinstance(gc, phrase_resolver.GetterChain), \
        f"oczekiwano GetterChain, było {type(gc).__name__}"
    return [w.value.segments for w in gc.chain]


def _is_call(phrase, name_segments, *, n_params=None):
    fc = phrase.resolved_phrase
    assert isinstance(fc, phrase_resolver.FunctionCall), \
        f"oczekiwano FunctionCall, było {type(fc).__name__}"
    assert fc.name.segments == name_segments, \
        f"name {fc.name.segments} != {name_segments}"
    if n_params is not None:
        assert len(fc.params) == n_params, \
            f"len(params) = {len(fc.params)}, oczekiwano {n_params}"
    return fc


# ============================================================
#  Brak getter chaina — zwykłe FunctionCall
# ============================================================

def test_single_word_phrase_is_empty_call(resolve):
    # `pracuj` — sam head (impt:sg:sec:imperf), brak argumentów
    ast = resolve("aby działać:\n    pracuj\n")
    p = _first_phrase(ast)
    fc = _is_call(p, ("pracować",), n_params=0)
    assert fc.params == []


def test_call_with_one_non_gen_arg(resolve):
    # `pisz tekstem` — tekstem ma case={inst}, brak chaina
    ast = resolve(_pisać_sig("b") + "aby działać:\n    pisz tekstem\n")
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=1)
    assert isinstance(fc.params[0], parser_mod.Word)
    assert fc.params[0].value.segments == ("tekst",)


def test_call_with_prep_args(resolve):
    # `zapisz w bazie nowego` — `nowy` to nie field; sig: `aby zapisać x w y:`
    # → slot 0 (no-prep) ← `nowego`, slot 1 (w) ← `w bazie`.
    ast = resolve(
        _zapisać_sig("b", "w", "c") + "aby działać:\n    zapisz w bazie nowego\n"
    )
    p = _first_phrase(ast)
    fc = _is_call(p, ("zapisać",), n_params=2)
    # Slot 0: no-prep, `nowego`.
    assert isinstance(fc.params[0], parser_mod.Word)
    assert fc.params[0].prep is None
    assert fc.params[0].value.segments == ("nowy",)
    # Slot 1: prep=w, `bazie`.
    assert isinstance(fc.params[1], parser_mod.Word)
    assert fc.params[1].prep == ("w",)
    assert fc.params[1].value.segments == ("baza",)


def test_genitive_arg_when_prev_word_is_not_a_field(resolve):
    # `pisz autora` — `pisz` (head) nie jest fieldem → autora staje się zwykłym argumentem
    ast = resolve(_pisać_sig("b") + "aby działać:\n    pisz autora\n")
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=1)
    assert isinstance(fc.params[0], parser_mod.Word)
    assert fc.params[0].value.segments == ("autor",)


def test_genitive_with_preposition_does_not_start_chain(resolve):
    # `pisz nazwa od użytkownika` — `od użytkownika` ma prep, więc nie startuje chaina
    ast = resolve(
        _pisać_sig("b", "od", "c") + "aby działać:\n    pisz nazwa od użytkownika\n"
    )
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=2)
    assert all(isinstance(par, parser_mod.Word) for par in fc.params)
    assert fc.params[0].value.segments == ("nazwa",)
    assert fc.params[1].prep == ("od",)
    assert fc.params[1].value.segments == ("użytkownik",)


# ============================================================
#  Sam getter chain (cała fraza zwija się do GetterChain)
# ============================================================

def test_bare_chain_length_two(resolve):
    # `nazwa użytkownika` — head jest fieldem, użytkownika gen → cała fraza to GetterChain
    ast = resolve("aby działać:\n    nazwa użytkownika\n")
    p = _first_phrase(ast)
    assert _chain_segments(p) == [("nazwa",), ("użytkownik",)]


def test_bare_chain_length_three(resolve):
    # `imię autora komentarza`
    ast = resolve("aby działać:\n    imię autora komentarza\n")
    p = _first_phrase(ast)
    assert _chain_segments(p) == [("imię",), ("autor",), ("komentarz",)]


def test_bare_chain_length_four(resolve):
    # `imię autora postu komentarza` — czteroogniwowy łańcuch
    ast = resolve("aby działać:\n    imię autora postu komentarza\n")
    p = _first_phrase(ast)
    assert _chain_segments(p) == [
        ("imię",), ("autor",), ("post",), ("komentarz",),
    ]


def test_bare_chain_length_five(resolve):
    # Pięcioogniwowy łańcuch. Każde ogniwo nie-bazowe musi być fieldem:
    #   imię (Użytkownik) → autor (Post/Komentarz) → post (Komentarz) → użytkownik (Sesja) → sesja (baza).
    ast = resolve("aby działać:\n    imię autora postu użytkownika sesji\n")
    p = _first_phrase(ast)
    assert _chain_segments(p) == [
        ("imię",), ("autor",), ("post",), ("użytkownik",), ("sesja",),
    ]


def test_chain_stops_when_intermediate_would_not_be_a_field_is_error(resolve):
    # `imię autora postu komentarza użytkownika` — head=imię (field), chain
    # zatrzymuje się na `komentarza` (komentarz nie jest fieldem), `użytkownika`
    # zostaje. Head musiałby pełnić rolę nazwy funkcji → ResolveError.
    with pytest.raises(phrase_resolver.ResolveError):
        resolve("aby działać:\n    imię autora postu komentarza użytkownika\n")


def test_chain_does_not_extend_past_non_field_base(resolve):
    # `pisz autora obiektu komentarza` — chain startuje przy `autora`/`obiektu`
    # (`autor` jest fieldem), ale `obiekt` nie jest fieldem, więc rozszerzenie
    # o `komentarza` jest odrzucone — `komentarza` ląduje jako osobny arg.
    ast = resolve(
        _pisać_sig("b", "c") + "aby działać:\n    pisz autora obiektu komentarza\n"
    )
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=2)
    assert isinstance(fc.params[0], phrase_resolver.GetterChain)
    assert _chain_segments(fc.params[0]) == [("autor",), ("obiekt",)]
    assert isinstance(fc.params[1], parser_mod.Word)
    assert fc.params[1].value.segments == ("komentarz",)


def test_rejected_extension_with_field_head_is_error(resolve):
    # `imię autora postu komentarza użytkownika sesji` — head=imię (field),
    # pierwszy chain zatrzymuje się na komentarzu, użytkownika sesji pozostają.
    # Head musiałby pełnić rolę nazwy funkcji → ResolveError.
    with pytest.raises(phrase_resolver.ResolveError):
        resolve("aby działać:\n    imię autora postu komentarza użytkownika sesji\n")


def test_chain_link_check_per_step_with_field_head_is_error(resolve):
    # `imię obserwatora obserwacji` — head=imię (field), chain zatrzymuje się
    # na obserwatorze (obserwator nie jest fieldem), obserwacja pozostaje.
    # Head musiałby pełnić rolę nazwy funkcji → ResolveError.
    with pytest.raises(phrase_resolver.ResolveError):
        resolve("aby działać:\n    imię obserwatora obserwacji\n")


def test_bare_chain_collapse_predicate_uses_identity(resolve):
    # Zwijanie do GetterChain uruchamia się tylko gdy chain[0] is words[0].
    # `pisz nazwa użytkownika` — chain[0] to nazwa (words[1]), NIE pisz (words[0])
    ast = resolve(_pisać_sig("b") + "aby działać:\n    pisz nazwa użytkownika\n")
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=1)
    assert isinstance(fc.params[0], phrase_resolver.GetterChain)
    assert _chain_segments(fc.params[0]) == [("nazwa",), ("użytkownik",)]


# ============================================================
#  Pozycja getter chaina w obrębie wywołania funkcji
# ============================================================

def test_chain_at_end_of_call(resolve):
    # `pisz imię autora komentarza` → FunctionCall(pisz, [chain])
    ast = resolve(_pisać_sig("b") + "aby działać:\n    pisz imię autora komentarza\n")
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=1)
    assert _chain_segments(fc.params[0]) == [
        ("imię",), ("autor",), ("komentarz",),
    ]


def test_field_head_with_chain_and_more_args_is_error(resolve):
    # `imię autora komentarza po spacjach` — head=imię (field), chain consumes 3 słów,
    # `po spacjach` zostaje. Head musiałby pełnić rolę nazwy funkcji → ResolveError.
    with pytest.raises(phrase_resolver.ResolveError):
        resolve("aby działać:\n    imię autora komentarza po spacjach\n")

def test_chain_in_the_middle(resolve):
    # `pisz nazwa użytkownika tekstem` — chain między argumentami
    ast = resolve(
        _pisać_sig("b", "c") + "aby działać:\n    pisz nazwa użytkownika tekstem\n"
    )
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=2)
    assert isinstance(fc.params[0], phrase_resolver.GetterChain)
    assert _chain_segments(fc.params[0]) == [("nazwa",), ("użytkownik",)]
    assert isinstance(fc.params[1], parser_mod.Word)
    assert fc.params[1].value.segments == ("tekst",)


def test_arg_then_chain_at_end(resolve):
    # `pisz tekstem nazwa użytkownika` — najpierw arg, potem chain
    ast = resolve(
        _pisać_sig("b", "c") + "aby działać:\n    pisz tekstem nazwa użytkownika\n"
    )
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=2)
    assert isinstance(fc.params[0], parser_mod.Word)
    assert fc.params[0].value.segments == ("tekst",)
    assert isinstance(fc.params[1], phrase_resolver.GetterChain)
    assert _chain_segments(fc.params[1]) == [("nazwa",), ("użytkownik",)]


def test_chain_followed_by_prep_arg(resolve):
    # `pisz nazwa użytkownika z bazy` — chain kończy się gdy następne słowo ma prep
    ast = resolve(
        _pisać_sig("b", "z", "c") + "aby działać:\n    pisz nazwa użytkownika z bazy\n"
    )
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=2)
    assert isinstance(fc.params[0], phrase_resolver.GetterChain)
    assert _chain_segments(fc.params[0]) == [("nazwa",), ("użytkownik",)]
    assert isinstance(fc.params[1], parser_mod.Word)
    assert fc.params[1].prep == ("z",)


# ============================================================
#  Wiele getter chainów w obrębie jednej frazy
# ============================================================

def test_two_chains_back_to_back(resolve):
    # `pisz imię autora komentarza nazwa użytkownika` — dwa łańcuchy stykające się
    ast = resolve(
        _pisać_sig("b", "c")
        + "aby działać:\n    pisz imię autora komentarza nazwa użytkownika\n"
    )
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=2)
    assert _chain_segments(fc.params[0]) == [
        ("imię",), ("autor",), ("komentarz",),
    ]
    assert _chain_segments(fc.params[1]) == [("nazwa",), ("użytkownik",)]


def test_two_chains_with_arg_between(resolve):
    # `pisz nazwa użytkownika tekstem imię autora komentarza`
    ast = resolve(
        _pisać_sig("b", "c", "d")
        + "aby działać:\n    pisz nazwa użytkownika tekstem imię autora komentarza\n"
    )
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=3)
    assert _chain_segments(fc.params[0]) == [("nazwa",), ("użytkownik",)]
    assert isinstance(fc.params[1], parser_mod.Word)
    assert fc.params[1].value.segments == ("tekst",)
    assert _chain_segments(fc.params[2]) == [
        ("imię",), ("autor",), ("komentarz",),
    ]


def test_three_chains_in_one_phrase(resolve):
    # `pisz nazwa użytkownika imię autora komentarza identyfikator postu`
    ast = resolve(
        _pisać_sig("b", "c", "d")
        + "aby działać:\n"
        + "    pisz nazwa użytkownika imię autora komentarza identyfikator postu\n"
    )
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=3)
    assert _chain_segments(fc.params[0]) == [("nazwa",), ("użytkownik",)]
    assert _chain_segments(fc.params[1]) == [
        ("imię",), ("autor",), ("komentarz",),
    ]
    assert _chain_segments(fc.params[2]) == [
        ("identyfikator",), ("post",),
    ]


# ============================================================
#  Rekurencyjne resolvowanie (chain wewnątrz expressionu/podfrazy)
# ============================================================

def test_chain_in_assignment_target(resolve):
    # `imię autora komentarza to "Anna"` — LHS to Phrase, której resolved_phrase to GetterChain
    ast = resolve('aby działać:\n    imię autora komentarza to "Anna"\n')
    a = _func_def(ast).body[0]
    assert isinstance(a, parser_mod.Assignment)
    assert isinstance(a.target, parser_mod.Phrase)
    assert _chain_segments(a.target) == [
        ("imię",), ("autor",), ("komentarz",),
    ]
    assert isinstance(a.value, parser_mod.StrLit)


def test_chain_in_assignment_rhs(resolve):
    # `wynik to imię autora komentarza` — RHS to Phrase z bare GetterChain
    ast = resolve("aby działać:\n    wynik to imię autora komentarza\n")
    a = _func_def(ast).body[0]
    assert isinstance(a, parser_mod.Assignment)
    assert isinstance(a.value, parser_mod.Phrase)
    assert _chain_segments(a.value) == [
        ("imię",), ("autor",), ("komentarz",),
    ]


def test_chain_inside_return(resolve):
    ast = resolve("aby działać:\n    zwróć imię autora komentarza\n")
    r = _func_def(ast).body[0]
    assert isinstance(r, parser_mod.Return)
    assert isinstance(r.value, parser_mod.Phrase)
    assert _chain_segments(r.value) == [
        ("imię",), ("autor",), ("komentarz",),
    ]


def test_chain_inside_if_cond(resolve):
    src = (
        "aby działać:\n"
        "    jeśli flaga_aktywności sesji:\n"
        "        x to 1\n"
    )
    ast = resolve(src)
    if_node = _func_def(ast).body[0]
    assert isinstance(if_node.cond, parser_mod.Phrase)
    assert _chain_segments(if_node.cond) == [
        ("flaga", "aktywność"), ("sesja",),
    ]


def test_chain_inside_while_cond_and_body(resolve):
    src = (
        "aby działać:\n"
        "    dopóki flaga_aktywności sesji:\n"
        "        nazwa użytkownika to \"x\"\n"
    )
    ast = resolve(src)
    w = _func_def(ast).body[0]
    assert isinstance(w, parser_mod.While)
    assert _chain_segments(w.cond) == [
        ("flaga", "aktywność"), ("sesja",),
    ]
    a = w.body[0]
    assert _chain_segments(a.target) == [("nazwa",), ("użytkownik",)]


def test_chain_inside_binop_left(resolve):
    # `liczba_polubień postu + 1`
    ast = resolve("aby działać:\n    x to liczba_polubień postu + 1\n")
    a = _func_def(ast).body[0]
    expr = a.value
    assert isinstance(expr, parser_mod.BinOp) and expr.op == "+"
    assert _chain_segments(expr.left) == [
        ("liczba", "polubić"), ("post",),
    ]


def test_chain_inside_binop_both_sides(resolve):
    # `liczba_polubień postu = liczba_polubień komentarza`
    ast = resolve(
        "aby działać:\n"
        "    jeśli liczba_polubień postu = identyfikator komentarza:\n"
        "        x to 1\n"
    )
    if_node = _func_def(ast).body[0]
    cmp_ = if_node.cond
    assert isinstance(cmp_, parser_mod.BinOp) and cmp_.op == "="
    assert _chain_segments(cmp_.left) == [
        ("liczba", "polubić"), ("post",),
    ]
    assert _chain_segments(cmp_.right) == [
        ("identyfikator",), ("komentarz",),
    ]


def test_chain_inside_not(resolve):
    ast = resolve(
        "aby działać:\n"
        "    jeśli nie flaga_aktywności sesji:\n"
        "        x to 1\n"
    )
    if_node = _func_def(ast).body[0]
    assert isinstance(if_node.cond, parser_mod.Not)
    assert _chain_segments(if_node.cond.operand) == [
        ("flaga", "aktywność"), ("sesja",),
    ]


def test_chain_inside_and_or(resolve):
    # `flaga_aktywności sesji i nazwa użytkownika = "x"`
    ast = resolve(
        "aby działać:\n"
        "    jeśli flaga_aktywności sesji i nazwa użytkownika = \"x\":\n"
        "        a to 1\n"
    )
    if_node = _func_def(ast).body[0]
    assert isinstance(if_node.cond, parser_mod.And)
    assert _chain_segments(if_node.cond.left) == [
        ("flaga", "aktywność"), ("sesja",),
    ]
    cmp_ = if_node.cond.right
    assert isinstance(cmp_, parser_mod.BinOp) and cmp_.op == "="
    assert _chain_segments(cmp_.left) == [("nazwa",), ("użytkownik",)]


def test_chain_inside_unary_minus(resolve):
    # `-liczba_polubień postu`
    ast = resolve("aby działać:\n    x to -liczba_polubień postu\n")
    a = _func_def(ast).body[0]
    assert isinstance(a.value, parser_mod.UnaryOp) and a.value.op == "-"
    assert _chain_segments(a.value.operand) == [
        ("liczba", "polubić"), ("post",),
    ]


def test_chain_inside_parens(resolve):
    # `pisz (imię autora komentarza)` — wewnętrzna fraza zwija się do GetterChain
    ast = resolve(
        _pisać_sig("b") + "aby działać:\n    pisz (imię autora komentarza)\n"
    )
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=1)
    inner_word = fc.params[0]
    assert isinstance(inner_word, parser_mod.Word)
    assert isinstance(inner_word.value, parser_mod.Phrase)
    assert _chain_segments(inner_word.value) == [
        ("imię",), ("autor",), ("komentarz",),
    ]


def test_chain_in_outer_phrase_arg_position_with_inner_resolved_chain(resolve):
    # `pisz tekstem (nazwa użytkownika)` — wewnętrzna fraza GetterChain, zewnętrzna FunctionCall
    ast = resolve(
        _pisać_sig("b", "c")
        + "aby działać:\n    pisz tekstem (nazwa użytkownika)\n"
    )
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=2)
    assert isinstance(fc.params[0], parser_mod.Word)
    assert fc.params[0].value.segments == ("tekst",)
    inner_word = fc.params[1]
    assert isinstance(inner_word.value, parser_mod.Phrase)
    assert _chain_segments(inner_word.value) == [("nazwa",), ("użytkownik",)]


# ============================================================
#  Nazwa funkcji jako field (uprawniony zbieg okoliczności)
# ============================================================

def test_head_word_that_is_also_a_field(resolve):
    # `nazwa użytkownika` — head `nazwa` jest fieldem (Użytkownika)
    # zwija się do GetterChain
    ast = resolve("aby działać:\n    nazwa użytkownika\n")
    p = _first_phrase(ast)
    assert _chain_segments(p) == [("nazwa",), ("użytkownik",)]


def test_field_head_with_extra_literal_arg_is_error(resolve):
    # `nazwa użytkownika "x"` — head=nazwa (field), chain=[nazwa, użytkownik],
    # `"x"` zostaje. Head musiałby pełnić rolę nazwy funkcji → ResolveError.
    with pytest.raises(phrase_resolver.ResolveError):
        resolve('aby działać:\n    nazwa użytkownika "x"\n')


# ============================================================
#  Identyfikator z prefiksem przyimkowym
# ============================================================

def test_prep_identifier_can_be_field_check_target(resolve):
    # `pisz dla użytkownika sesji` — words[1]=dla użytkownika (prep), words[2]=sesji (gen)
    # is_a_field(użytkownik) → True → chain=[dla użytkownika, sesji]
    # Chain[0] ma prep="dla". Cały chain jest jednym argumentem fukcji `pisz`.
    ast = resolve(
        _pisać_sig("dla", "b") + "aby działać:\n    pisz dla użytkownika sesji\n"
    )
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=1)
    chain = fc.params[0]
    assert isinstance(chain, phrase_resolver.GetterChain)
    assert _chain_segments(chain) == [("użytkownik",), ("sesja",)]
    # Prep "dla" pozostaje na pierwszym ogniwie chaina
    assert chain.chain[0].prep == ("dla",)


# ============================================================
#  Chain zaczynający się od argumentu wcześniejszego w params
# ============================================================

def test_chain_pops_correct_param_when_starting_after_other_args(resolve):
    # `pisz tekstem mocnym nazwa użytkownika`
    # Resolver ma popnąć tylko `nazwa` z params, NIE wcześniejszych argów.
    ast = resolve(
        _pisać_sig("b", "c", "d")
        + "aby działać:\n    pisz tekstem mocnym nazwa użytkownika\n"
    )
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=3)
    assert isinstance(fc.params[0], parser_mod.Word) and fc.params[0].value.segments == ("tekst",)
    assert isinstance(fc.params[1], parser_mod.Word) and fc.params[1].value.segments == ("mocny",)
    assert isinstance(fc.params[2], phrase_resolver.GetterChain)
    assert _chain_segments(fc.params[2]) == [("nazwa",), ("użytkownik",)]


# ============================================================
#  Integracja: realny fragment z instagram.ć
# ============================================================

def test_realistic_phrase_from_instagram_sample(resolve):
    # Wzorowane na: `liczba_polubień postu to liczba_polubień postu + 1`
    # `with_functions=False` — chcemy, żeby `polubić` w module pochodził tylko
    # z poniższego inline definition (FUNCTIONS prelude też definiuje polubić,
    # co nadpisałoby ciało).
    src = (
        "aby polubić post (Post):\n"
        "    liczba_polubień postu to liczba_polubień postu + 1\n"
    )
    ast = resolve(src, with_functions=False)
    a = _func_def(ast, name=("polubić",)).body[0]
    assert isinstance(a, parser_mod.Assignment)
    # LHS: bare GetterChain (chain[0] is words[0])
    assert _chain_segments(a.target) == [
        ("liczba", "polubić"), ("post",),
    ]
    # RHS: BinOp(GetterChain, IntLit(1))
    assert isinstance(a.value, parser_mod.BinOp)
    assert _chain_segments(a.value.left) == [
        ("liczba", "polubić"), ("post",),
    ]
    assert isinstance(a.value.right, parser_mod.IntLit) and a.value.right.value == 1


def test_realistic_phrase_with_inner_chain_param(resolve):
    # `stwórz_post z treścią dla użytkownika sesji` — z instagram.ć
    src = (
        "aby działać sesji (Sesja) z treścią (Tekst):\n"
        "    nowy to stwórz_post z treścią dla użytkownika sesji\n"
    )
    ast = resolve(src)
    a = _func_def(ast).body[0]
    assert isinstance(a, parser_mod.Assignment)
    fc = a.value.resolved_phrase
    assert isinstance(fc, phrase_resolver.FunctionCall)
    assert fc.name.segments == ("stworzyć", "post")
    # `z treścią` to zwykły arg z prep
    # `dla użytkownika sesji` zwija się do GetterChain z prep "dla" na chain[0]
    assert isinstance(fc.params[0], parser_mod.Word)
    assert fc.params[0].prep == ("z",)
    assert isinstance(fc.params[1], phrase_resolver.GetterChain)
    assert _chain_segments(fc.params[1]) == [("użytkownik",), ("sesja",)]
    assert fc.params[1].chain[0].prep == ("dla",)


# ============================================================
#  TESTY OBNAŻAJĄCE BUGI
#
#  Każdy test poniżej z prefiksem `test_BUG_` demonstruje konkretny defekt
#  w bieżącej implementacji phrase_resolver.py. Test FAILUJE w obecnym stanie.
# ============================================================

def test_BUG_chain_followed_by_string_literal_keeps_source_order(resolve):
    """BUG #1: chain w params, po którym następuje literał — paramy są w odwrotnej kolejności.

    W resolve_phrase, gdy bieżące słowo NIE jest Identifierem a chain_started=True:
        ret.params.append(p.words[i])             # ← appendowany NAJPIERW non-Identifier
        if chain_started:
            ret.params.append(GetterChain(...))   # ← dopiero potem chain
    Powinno być odwrotnie: najpierw zwinąć chain, potem dopisać literał.
    """
    ast = resolve(
        _pisać_sig("b", "c")
        + 'aby działać:\n    pisz nazwa użytkownika "etykieta"\n'
    )
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=2)
    assert isinstance(fc.params[0], phrase_resolver.GetterChain), (
        f"params[0] powinien być GetterChain (chain pojawia się w źródle przed \"etykieta\"), "
        f"był {type(fc.params[0]).__name__}"
    )
    assert isinstance(fc.params[1], parser_mod.Word)
    assert isinstance(fc.params[1].value, parser_mod.StrLit)


def test_BUG_chain_followed_by_int_literal_keeps_source_order(resolve):
    """Wariant Buga #1 z literałem liczbowym."""
    ast = resolve(
        _pisać_sig("b", "c") + "aby działać:\n    pisz nazwa użytkownika 42\n"
    )
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=2)
    assert isinstance(fc.params[0], phrase_resolver.GetterChain), (
        f"params[0] powinien być chainem, był {type(fc.params[0]).__name__}"
    )
    assert isinstance(fc.params[1].value, parser_mod.IntLit)


def test_BUG_chain_followed_by_paren_phrase_keeps_source_order(resolve):
    """Wariant Buga #1 z subfrazą w nawiasach."""
    ast = resolve(
        _pisać_sig("b", "c") + "aby działać:\n    pisz nazwa użytkownika (1 + 2)\n"
    )
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=2)
    assert isinstance(fc.params[0], phrase_resolver.GetterChain), (
        f"params[0] powinien być chainem, był {type(fc.params[0]).__name__}"
    )


def test_BUG_is_a_field_crashes_on_string_literal_predecessor(resolve):
    """BUG #2: is_a_field crashuje, gdy poprzednie słowo nie jest Identifierem.

    Gdy spotykamy słowo w gen z prep=None i chain_started=False, resolver wywołuje
    is_a_field(p.words[i-1].value) bez sprawdzenia, czy value to Identifier.
    Dla StrLit (czy IntLit) brak atrybutu .segments → AttributeError.
    """
    # Sama próba resolvowania powinna nie crashować.
    ast = resolve(_pisać_sig("b", "c") + 'aby działać:\n    pisz "x" autora\n')
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=2)
    # `autora` powinno być zwykłym argumentem (StrLit nie jest fieldem)
    assert isinstance(fc.params[1], parser_mod.Word)
    assert fc.params[1].value.segments == ("autor",)


def test_BUG_is_a_field_crashes_on_int_literal_predecessor(resolve):
    """Wariant Buga #2 — IntLit zamiast StrLit."""
    ast = resolve(_pisać_sig("b", "c") + "aby działać:\n    pisz 42 autora\n")
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=2)
    assert isinstance(fc.params[1], parser_mod.Word)
    assert fc.params[1].value.segments == ("autor",)


def test_BUG_is_a_field_crashes_on_paren_phrase_predecessor(resolve):
    """Wariant Buga #2 — sub-Phrase w nawiasach."""
    ast = resolve(_pisać_sig("b", "c") + "aby działać:\n    pisz (1 + 2) autora\n")
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=2)
    assert isinstance(fc.params[1], parser_mod.Word)
    assert fc.params[1].value.segments == ("autor",)


def test_BUG_resolve_module_does_not_leak_fields_across_calls(_db, _preps):
    """BUG #3: phrase_resolver.fields nie jest resetowane przy starcie resolve_module.

    Pola wszystkich poprzednich modułów akumulują się w globalnej liście.
    Drugi moduł (bez własnych structów) nie powinien widzieć pól pierwszego.
    """
    # Świeży stan
    phrase_resolver.fields = []

    # Moduł 1 — pełen structów
    text1 = STRUCTS + "aby działać:\n    nazwa użytkownika\n"
    ast1 = parser_mod.parse(morph_anal.analyze(lexer.lex(text1), _db), _preps)
    phrase_resolver.resolve_module(ast1)
    fields_after_module_1 = list(phrase_resolver.fields)
    assert len(fields_after_module_1) > 0  # załadowane z STRUCTS

    # Moduł 2 — bez structów. resolve_module powinien zacząć ze świeżą listą fields.
    # `pisać` wymaga definicji (signature-aware fn-call) — dorzucamy stub.
    # W module 2 brak structów → "nazwa" nie jest fieldem → chain się nie tworzy.
    # Call `pisz nazwa użytkownika` ma więc 2 osobne argi (Word, Word).
    text2 = (
        "aby pisać b c:\n"
        "    zwrócić\n"
        "\n"
        "aby testować:\n"
        "    pisz nazwa użytkownika\n"
    )
    ast2 = parser_mod.parse(morph_anal.analyze(lexer.lex(text2), _db), _preps)
    phrase_resolver.resolve_module(ast2)

    # Tu OCZEKUJEMY: fields zresetowane dla nowego modułu.
    # Bug: fields wciąż zawiera pola modułu 1.
    fields_after_module_2 = phrase_resolver.fields
    assert len(fields_after_module_2) == 0, (
        f"po resolve_module nowego modułu (bez structów) "
        f"fields powinno mieć 0 elementów, ma {len(fields_after_module_2)} — "
        f"stan przeciekł z poprzedniego modułu"
    )

    # Skutek funkcjonalny: w module 2 `nazwa użytkownika` nie powinno być GetterChainem
    # (bo `nazwa` nie jest fieldem nigdzie w module 2), tylko zwykłym FunctionCallem.
    out = []
    _walk_phrases(ast2, out)
    p2 = out[0]
    fc = p2.resolved_phrase
    assert isinstance(fc, phrase_resolver.FunctionCall)
    assert all(isinstance(par, parser_mod.Word) for par in fc.params), (
        f"bez structów `nazwa użytkownika` powinno być [Word, Word], jest "
        f"{[type(p).__name__ for p in fc.params]}"
    )


# ============================================================
#  FunctionIdentifier — walidacja czasownika i forma fleksyjna
# ============================================================

def test_func_call_zero_verbs_rejected(resolve):
    # `pies` (subst) z parametrem `kota` (subst) — fraza z parametrami,
    # ale w head nie ma czasownika. Single-word non-verb wpadłby na bare
    # reference; tu z parametrami MUSI być FunctionCall, więc rzuca.
    with pytest.raises(parser_mod.FunctionIdentifierError):
        resolve("aby działać:\n    pies kota\n")


def test_func_call_opaque_name_rejected(resolve):
    # `fibonacci` nie ma analiz w SGJP → brak czasownika → odrzucone
    # (z parametrem `xyz`, żeby wymusić ścieżkę FunctionCall a nie bare ref)
    with pytest.raises(parser_mod.FunctionIdentifierError):
        resolve("aby działać:\n    fibonacci xyz\n")


def test_function_identifier_carries_verb_form(resolve):
    # `pisz` to impt:sg:sec:imperf
    ast = resolve(_pisać_sig() + "aby działać:\n    pisz\n")
    fc = _first_phrase(ast).resolved_phrase
    assert isinstance(fc, phrase_resolver.FunctionCall)
    assert isinstance(fc.name, parser_mod.FunctionIdentifier)
    assert fc.name.verb_index == 0
    assert fc.name.verb_form.pos == "impt"
    assert fc.name.verb_form.mood == "rozkazujący"
    assert fc.name.verb_form.aspect == "imperf"
    assert fc.name.verb_form.number == "sg"
    assert fc.name.verb_form.person == "sec"


def test_function_identifier_inf_has_no_mood(resolve):
    # `polubić` to inf:perf — bezokolicznik nie jest trybem
    ast = resolve("aby działać:\n    polubić post\n")
    fc = _first_phrase(ast).resolved_phrase
    assert fc.name.verb_form.pos == "inf"
    assert fc.name.verb_form.mood is None
    assert fc.name.verb_form.aspect == "perf"
    assert fc.name.verb_form.number is None


def test_function_identifier_cond_mood(resolve):
    # `abdykowałby` to cond:sg:m1.m2.m3:ter:imperf.perf
    ast = resolve("aby działać:\n    abdykowałby\n")
    fc = _first_phrase(ast).resolved_phrase
    assert fc.name.verb_form.pos == "cond"
    assert fc.name.verb_form.mood == "przypuszczający"
    assert fc.name.verb_form.person == "ter"


def test_function_identifier_picks_first_verb_in_compound(resolve):
    # `przestań_obserwować`: `przestań` (impt) jest pierwszym czasownikiem,
    # więc on determinuje verb_form całego identyfikatora.
    ast = resolve("aby działać:\n    przestań_obserwować użytkownika\n")
    fc = _first_phrase(ast).resolved_phrase
    assert isinstance(fc, phrase_resolver.FunctionCall)
    assert fc.name.verb_index == 0
    assert fc.name.verb_form.pos == "impt"
    assert fc.name.verb_form.mood == "rozkazujący"


def test_bare_non_verb_reference_is_not_function_call(resolve):
    # `wynik` to LHS przypisania — pojedyncze niewerbowe słowo.
    # Resolved_phrase nie jest FunctionCall (bo brak czasownika),
    # tylko gołym Identifier.
    ast = resolve("aby działać:\n    wynik to 42\n")
    a = _func_def(ast).body[0]
    assert isinstance(a, parser_mod.Assignment)
    target = a.target.resolved_phrase
    assert isinstance(target, parser_mod.Identifier)
    assert target.segments == ("wynik",)


# ============================================================
#  StructCreation
# ============================================================

def _is_struct_creation(node, type_name):
    sc = node.resolved_phrase if isinstance(node, parser_mod.Phrase) else node
    assert isinstance(sc, phrase_resolver.StructCreation), \
        f"oczekiwano StructCreation, było {type(sc).__name__}"
    assert sc.type_name == type_name, \
        f"type_name {sc.type_name} != {type_name}"
    return sc


def test_struct_creation_top_level_in_assignment(resolve):
    # `nowy Użytkownik o nazwie "Anna"` jako RHS — explicit value przez `o + loc`.
    ast = resolve('aby działać:\n    wynik to nowy Użytkownik o nazwie "Anna"\n')
    a = _func_def(ast).body[0]
    assert isinstance(a, parser_mod.Assignment)
    sc = _is_struct_creation(a.value, ("użytkownik",))
    assert len(sc.args) == 1
    arg = sc.args[0]
    assert arg.field_name == ("nazwa",)
    assert isinstance(arg.value, parser_mod.Word)
    assert isinstance(arg.value.value, parser_mod.StrLit)
    assert arg.value.value.value == "Anna"


def test_struct_creation_shorthand_two_fields(resolve):
    # `nowy Użytkownik z nazwą z identyfikatorem` — oba shorthandy (None value)
    ast = resolve("aby działać:\n    nowy Użytkownik z nazwą z identyfikatorem\n")
    p = _first_phrase(ast)
    sc = _is_struct_creation(p, ("użytkownik",))
    assert len(sc.args) == 2
    assert sc.args[0].field_name == ("nazwa",) and sc.args[0].value is None
    assert sc.args[1].field_name == ("identyfikator",) and sc.args[1].value is None


def test_struct_creation_nested(resolve):
    # `nowy Komentarz o autorze nowy Użytkownik o nazwie "P"` — zagnieżdżony
    # struct z explicit fields.
    ast = resolve(
        'aby działać:\n'
        '    wynik to nowy Komentarz o autorze nowy Użytkownik o nazwie "P"\n'
    )
    a = _func_def(ast).body[0]
    sc = _is_struct_creation(a.value, ("komentarz",))
    assert len(sc.args) == 1
    autor_arg = sc.args[0]
    assert autor_arg.field_name == ("autor",)
    inner = autor_arg.value
    assert isinstance(inner, phrase_resolver.StructCreation)
    assert inner.type_name == ("użytkownik",)
    assert len(inner.args) == 1
    assert inner.args[0].field_name == ("nazwa",)
    assert inner.args[0].value.value.value == "P"


def test_struct_creation_as_function_call_arg(resolve):
    # `zapisz nowego Komentarza o treści "x"` — struct_creation w roli arga function_call
    ast = resolve(
        _zapisać_sig("b")
        + 'aby działać:\n    zapisz nowego Komentarza o treści "x"\n'
    )
    p = _first_phrase(ast)
    fc = p.resolved_phrase
    assert isinstance(fc, phrase_resolver.FunctionCall)
    assert fc.name.segments == ("zapisać",)
    assert len(fc.params) == 1
    sc = fc.params[0]
    assert isinstance(sc, phrase_resolver.StructCreation)
    assert sc.type_name == ("komentarz",)
    assert len(sc.args) == 1
    assert sc.args[0].field_name == ("treść",)


def test_struct_creation_with_function_call_value(resolve):
    # `nowy Użytkownik o nazwie weź_nazwę_z_bazy o identyfikatorze` — sub-function-call
    # jako wartość. `weź_nazwę_z_bazy` ma w sygnaturze `o identyfikatorze`, więc
    # absorbuje token mimo, że `identyfikator` jest też polem `Użytkownik`.
    ast = resolve(
        'aby działać:\n'
        '    nowy Użytkownik o nazwie weź_nazwę_z_bazy o identyfikatorze\n'
    )
    p = _first_phrase(ast)
    sc = _is_struct_creation(p, ("użytkownik",))
    assert len(sc.args) == 1
    arg = sc.args[0]
    assert arg.field_name == ("nazwa",)
    inner_fc = arg.value
    assert isinstance(inner_fc, phrase_resolver.FunctionCall)
    assert inner_fc.name.segments == ("wziąć", "nazwa", "z", "baza")
    assert len(inner_fc.params) == 1
    param = inner_fc.params[0]
    assert isinstance(param, parser_mod.Word)
    assert param.prep == ("o",)
    assert param.value.segments == ("identyfikator",)


def test_struct_creation_duplicate_field_propagates_up(resolve):
    # Innermost (Użytkownik) ma identyfikator; outer (Komentarz) też.
    # Pierwsze "o identyfikatorze 1" → Użytkownik. Drugie "o identyfikatorze 2" →
    # Użytkownik już ma → zamknij Użytkownik, propaguj do Komentarza.
    ast = resolve(
        'aby działać:\n'
        '    wynik to nowy Komentarz o autorze nowy Użytkownik '
        'o identyfikatorze 1 o identyfikatorze 2\n'
    )
    a = _func_def(ast).body[0]
    sc = _is_struct_creation(a.value, ("komentarz",))
    assert len(sc.args) == 2
    autor_arg = sc.args[0]
    assert autor_arg.field_name == ("autor",)
    inner = autor_arg.value
    assert isinstance(inner, phrase_resolver.StructCreation)
    assert inner.type_name == ("użytkownik",)
    assert len(inner.args) == 1
    assert inner.args[0].field_name == ("identyfikator",)
    assert inner.args[0].value.value.value == 1
    outer_ident = sc.args[1]
    assert outer_ident.field_name == ("identyfikator",)
    assert outer_ident.value.value.value == 2


def test_struct_creation_inner_fn_swallows_non_field_z_arg(resolve):
    # `nowy Komentarz o autorze weź_z_bazy z bazy o treści "x"`
    # `weź_z_bazy` ma w sygnaturze `z bazy` → absorbuje. `o treści` to pole
    # `Komentarza` i nie pasuje do żadnego slotu `weź_z_bazy` → sub-call kończy się,
    # token wpada do otaczającego struktu jako struct_arg.
    ast = resolve(
        'aby działać:\n'
        '    nowy Komentarz o autorze weź_z_bazy z bazy o treści "x"\n'
    )
    p = _first_phrase(ast)
    sc = _is_struct_creation(p, ("komentarz",))
    assert len(sc.args) == 2
    autor = sc.args[0]
    assert autor.field_name == ("autor",)
    inner_fc = autor.value
    assert isinstance(inner_fc, phrase_resolver.FunctionCall)
    assert inner_fc.name.segments == ("wziąć", "z", "baza")
    assert len(inner_fc.params) == 1
    assert inner_fc.params[0].prep == ("z",)
    assert inner_fc.params[0].value.segments == ("baza",)
    treść = sc.args[1]
    assert treść.field_name == ("treść",)
    assert isinstance(treść.value, parser_mod.Word)
    assert treść.value.value.value == "x"


def test_struct_creation_with_chain_value(resolve):
    # `nowy Komentarz o autorze autora postu` — chain jako wartość pola
    ast = resolve('aby działać:\n    nowy Komentarz o autorze autora postu\n')
    p = _first_phrase(ast)
    sc = _is_struct_creation(p, ("komentarz",))
    assert len(sc.args) == 1
    arg = sc.args[0]
    assert arg.field_name == ("autor",)
    chain = arg.value
    assert isinstance(chain, phrase_resolver.GetterChain)
    assert [w.value.segments for w in chain.chain] == [("autor",), ("post",)]


def test_struct_creation_accusative_animate(resolve):
    # `zapisz nowego Komentarza o treści "x"` — biernik żywotnopodobny
    ast = resolve(
        _zapisać_sig("b")
        + 'aby działać:\n    zapisz nowego Komentarza o treści "x"\n'
    )
    p = _first_phrase(ast)
    fc = p.resolved_phrase
    assert isinstance(fc, phrase_resolver.FunctionCall)
    sc = fc.params[0]
    assert isinstance(sc, phrase_resolver.StructCreation)
    assert sc.type_name == ("komentarz",)


def test_struct_creation_accusative_inanimate(resolve):
    # `zapisz nowy Komentarz o treści "x"` — biernik nieżywotny (= mianownik)
    ast = resolve(
        _zapisać_sig("b")
        + 'aby działać:\n    zapisz nowy Komentarz o treści "x"\n'
    )
    p = _first_phrase(ast)
    fc = p.resolved_phrase
    assert isinstance(fc, phrase_resolver.FunctionCall)
    sc = fc.params[0]
    assert isinstance(sc, phrase_resolver.StructCreation)
    assert sc.type_name == ("komentarz",)


# ---------- Negatywne ----------

def test_struct_creation_no_type_after_nowy(resolve):
    # `nowy o imieniu "Piotr"` — `o imieniu` ma prep, nie jest type_word.
    # Nie wchodzi w struct_creation, fall-through do function_call, `nowy` to adj
    # bez czasownika → FunctionIdentifierError.
    with pytest.raises(parser_mod.FunctionIdentifierError):
        resolve('aby działać:\n    nowy o imieniu "Piotr"\n')


def test_struct_creation_unknown_type(resolve):
    # `Pies` nie jest typem w module — nie wchodzi w struct_creation,
    # fall-through, `nowy` adj bez czasownika → FunctionIdentifierError.
    with pytest.raises(parser_mod.FunctionIdentifierError):
        resolve('aby działać:\n    nowy Pies o imieniu "Reks"\n')


def test_struct_creation_field_not_of_struct(resolve):
    # `o bazie` — baza nie jest fieldem Komentarza, struct_creation się kończy
    # po `nowy Komentarz`, dalsze tokeny nie skonsumowane → ResolveError.
    with pytest.raises(phrase_resolver.ResolveError):
        resolve('aby działać:\n    nowy Komentarz o bazie "x"\n')


def test_struct_creation_case_mismatch(resolve):
    # `nowy Użytkownikowi` — adj nominatyw + subst datyw, brak overlapu cases.
    # _starts_struct_creation False → fall-through → function_call → nowy nie verb.
    with pytest.raises(parser_mod.FunctionIdentifierError):
        resolve('aby działać:\n    nowy Użytkownikowi\n')


# ---------- Nowe testy: o + loc, signature-aware function call ----------

def test_struct_creation_explicit_without_value_raises(resolve):
    # `o imieniu` to explicit struct arg — wymaga wartości po nim. Brak → ResolveError.
    with pytest.raises(phrase_resolver.ResolveError):
        resolve('aby działać:\n    nowy Użytkownik o imieniu\n')


def test_struct_creation_mixed_explicit_and_shorthand(resolve):
    # `o imieniu "M"` to explicit, `z identyfikatorem` to shorthand — w jednym strukcie.
    ast = resolve('aby działać:\n    nowy Użytkownik o imieniu "M" z identyfikatorem\n')
    p = _first_phrase(ast)
    sc = _is_struct_creation(p, ("użytkownik",))
    assert len(sc.args) == 2
    assert sc.args[0].field_name == ("imię",)
    assert isinstance(sc.args[0].value, parser_mod.Word)
    assert isinstance(sc.args[0].value.value, parser_mod.StrLit)
    assert sc.args[0].value.value.value == "M"
    assert sc.args[1].field_name == ("identyfikator",)
    assert sc.args[1].value is None  # shorthand


def test_function_call_signature_absorbs_o_loc_field(resolve):
    # Funkcja `weź_nazwę_z_bazy` ma w sygnaturze `o identyfikatorze`. Choć
    # `identyfikator` jest też polem `Użytkownik`, fn ma priorytet — absorbuje.
    ast = resolve(
        'aby działać:\n'
        '    nowy Użytkownik o nazwie weź_nazwę_z_bazy o identyfikatorze\n'
    )
    p = _first_phrase(ast)
    sc = _is_struct_creation(p, ("użytkownik",))
    assert len(sc.args) == 1
    arg = sc.args[0]
    assert arg.field_name == ("nazwa",)
    inner_fc = arg.value
    assert isinstance(inner_fc, phrase_resolver.FunctionCall)
    assert inner_fc.name.segments == ("wziąć", "nazwa", "z", "baza")
    assert len(inner_fc.params) == 1
    assert inner_fc.params[0].prep == ("o",)
    assert inner_fc.params[0].value.segments == ("identyfikator",)


def test_function_call_signature_does_not_absorb_mismatched_prep(resolve):
    # Lokalna fn `przefiltrować` ma w sygnaturze `dla identyfikatora` (prep=dla).
    # Wywołanie chce dać jej `o identyfikatorze` (prep=o) — brak matchu po prep,
    # i case'y też się nie zgadzają (loc vs gen). Pozycyjny fallback nie pomoże,
    # bo argument nie pasuje do żadnego wolnego slotu. Strict validation: error.
    src = (
        "aby przefiltrować dla identyfikatora:\n"
        "    zwrócić\n"
        "\n"
        "aby działać:\n"
        '    nowy Użytkownik o nazwie przefiltruj o identyfikatorze "x"\n'
    )
    with pytest.raises(phrase_resolver.ResolveError):
        resolve(src, with_functions=False)


def test_unknown_function_raises(resolve):
    # `wziąć_z_chmurki` nie jest zdefiniowana → ResolveError.
    with pytest.raises(phrase_resolver.ResolveError):
        resolve('aby działać:\n    wziąć_z_chmurki o identyfikatorze\n')


