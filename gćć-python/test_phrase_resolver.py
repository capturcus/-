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


@pytest.fixture
def resolve(_db, _preps):
    """Parsuje i resolwuje moduł. Każdy test dostaje świeży fields=[]."""

    def _resolve(body, with_structs=True):
        phrase_resolver.fields = []
        text = (STRUCTS if with_structs else "") + body
        ast = parser_mod.parse(morph_anal.analyze(lexer.lex(text), _db), _preps)
        phrase_resolver.resolve_module(ast)
        return ast

    return _resolve


# ---------- helpers ----------

def _func_def(ast, name=None):
    for node in ast.body:
        if isinstance(node, parser_mod.FunctionDef):
            if name is None or node.name == name:
                return node
    raise AssertionError("nie znaleziono FunctionDef")


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
        gc = chain_or_phrase.func_call
    else:
        gc = chain_or_phrase
    assert isinstance(gc, phrase_resolver.GetterChain), \
        f"oczekiwano GetterChain, było {type(gc).__name__}"
    return [w.value.segments for w in gc.chain]


def _is_call(phrase, name_segments, *, n_params=None):
    fc = phrase.func_call
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
    # `siema` — sam head, brak argumentów
    ast = resolve("aby f:\n    siema\n")
    p = _first_phrase(ast)
    fc = _is_call(p, ("siema",), n_params=0)
    assert fc.params == []


def test_call_with_one_non_gen_arg(resolve):
    # `pisz tekstem` — tekstem ma case={inst}, brak chaina
    ast = resolve("aby f:\n    pisz tekstem\n")
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=1)
    assert isinstance(fc.params[0], parser_mod.Word)
    assert fc.params[0].value.segments == ("tekst",)


def test_call_with_prep_args(resolve):
    # `zapisz w bazie nowego` — prep=w, prep=None ale `nowy` to nie field
    # field-check robi się dla poprzedniego słowa, nie chaina, tutaj nie ma popredniego field
    ast = resolve("aby f:\n    zapisz w bazie nowego\n")
    p = _first_phrase(ast)
    fc = _is_call(p, ("zapisać",), n_params=2)
    assert fc.params[0].prep == ("w",)
    # `nowego` ma gen, ale poprzednie słowo (`baza`) nie jest fieldem → arg pozycyjny
    assert isinstance(fc.params[1], parser_mod.Word)
    assert fc.params[1].value.segments == ("nowy",)


def test_genitive_arg_when_prev_word_is_not_a_field(resolve):
    # `pisz autora` — `pisz` (head) nie jest fieldem → autora staje się zwykłym argumentem
    ast = resolve("aby f:\n    pisz autora\n")
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=1)
    assert isinstance(fc.params[0], parser_mod.Word)
    assert fc.params[0].value.segments == ("autor",)


def test_genitive_with_preposition_does_not_start_chain(resolve):
    # `pisz nazwa od użytkownika` — `od użytkownika` ma prep, więc nie startuje chaina
    ast = resolve("aby f:\n    pisz nazwa od użytkownika\n")
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
    ast = resolve("aby f:\n    nazwa użytkownika\n")
    p = _first_phrase(ast)
    assert _chain_segments(p) == [("nazwa",), ("użytkownik",)]


def test_bare_chain_length_three(resolve):
    # `imię autora komentarza`
    ast = resolve("aby f:\n    imię autora komentarza\n")
    p = _first_phrase(ast)
    assert _chain_segments(p) == [("imię",), ("autor",), ("komentarz",)]


def test_bare_chain_length_four(resolve):
    # `imię autora postu komentarza` — czteroogniwowy łańcuch
    ast = resolve("aby f:\n    imię autora postu komentarza\n")
    p = _first_phrase(ast)
    assert _chain_segments(p) == [
        ("imię",), ("autor",), ("post",), ("komentarz",),
    ]


def test_bare_chain_length_five(resolve):
    # Pięcioogniwowy łańcuch. Każde ogniwo nie-bazowe musi być fieldem:
    #   imię (Użytkownik) → autor (Post/Komentarz) → post (Komentarz) → użytkownik (Sesja) → sesja (baza).
    ast = resolve("aby f:\n    imię autora postu użytkownika sesji\n")
    p = _first_phrase(ast)
    assert _chain_segments(p) == [
        ("imię",), ("autor",), ("post",), ("użytkownik",), ("sesja",),
    ]


def test_chain_stops_when_intermediate_would_not_be_a_field(resolve):
    # `imię autora postu komentarza użytkownika` — `komentarz` nie jest fieldem
    # żadnego structu. Chain nie może się rozszerzyć obejmując `użytkownika`,
    # bo wtedy `komentarz` stałby się intermediate (a nie bazą), co wymaga
    # bycia fieldem. Zatem chain kończy się na `komentarza` (jako bazie),
    # a `użytkownika` zostaje osobnym, pozycyjnym argumentem.
    ast = resolve("aby f:\n    imię autora postu komentarza użytkownika\n")
    p = _first_phrase(ast)
    fc = _is_call(p, ("imię",), n_params=2)
    assert isinstance(fc.params[0], phrase_resolver.GetterChain)
    assert _chain_segments(fc.params[0]) == [
        ("imię",), ("autor",), ("post",), ("komentarz",),
    ]
    assert isinstance(fc.params[1], parser_mod.Word)
    assert fc.params[1].value.segments == ("użytkownik",)


def test_chain_does_not_extend_past_non_field_base(resolve):
    # `pisz autora obiektu komentarza` — chain startuje przy `autora`/`obiektu`
    # (`autor` jest fieldem), ale `obiekt` nie jest fieldem, więc rozszerzenie
    # o `komentarza` jest odrzucone — `komentarza` ląduje jako osobny arg.
    ast = resolve("aby f:\n    pisz autora obiektu komentarza\n")
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=2)
    assert isinstance(fc.params[0], phrase_resolver.GetterChain)
    assert _chain_segments(fc.params[0]) == [("autor",), ("obiekt",)]
    assert isinstance(fc.params[1], parser_mod.Word)
    assert fc.params[1].value.segments == ("komentarz",)


def test_rejected_extension_can_seed_new_chain(resolve):
    # `imię autora postu komentarza użytkownika sesji` —
    # pierwszy chain kończy się na `komentarza` (bo `komentarz` nie jest fieldem).
    # Ale dalej `użytkownik` jest fieldem (Sesji), więc startuje DRUGI chain
    # `użytkownika sesji`.
    ast = resolve("aby f:\n    imię autora postu komentarza użytkownika sesji\n")
    p = _first_phrase(ast)
    fc = _is_call(p, ("imię",), n_params=2)
    assert isinstance(fc.params[0], phrase_resolver.GetterChain)
    assert _chain_segments(fc.params[0]) == [
        ("imię",), ("autor",), ("post",), ("komentarz",),
    ]
    assert isinstance(fc.params[1], phrase_resolver.GetterChain)
    assert _chain_segments(fc.params[1]) == [("użytkownik",), ("sesja",)]


def test_chain_link_check_per_step_at_three_link_chain(resolve):
    # Eksplicytnie: w 3-ogniwowym chainie `imię autora komentarza` sprawdzamy,
    # że NIE TYLKO `imię` ale TAKŻE `autor` musi być fieldem dla rozszerzenia.
    # `imię obserwatora obserwacji` — `obserwator` nie jest fieldem (jest tylko
    # w tej testowej STRUCTS jako pole Obserwacji? Nie — w naszych STRUCTS go nie ma).
    # Chain: i=1 obserwatora gen, is_a_field(imię)? Yes (Użytkownik.imię).
    #   pop (empty), chain=[imię, obserwatora]. started.
    # i=2 obserwacji gen, is_a_field(obserwator)? No. Reject. Close chain.
    #   Append obserwacji.
    # → FunctionCall(imię, [GetterChain([imię, obserwatora]), obserwacji_word])
    # — chain[0] is words[0], ale len(params)==2 → nie zwija się do bare.
    ast = resolve("aby f:\n    imię obserwatora obserwacji\n")
    p = _first_phrase(ast)
    fc = _is_call(p, ("imię",), n_params=2)
    assert isinstance(fc.params[0], phrase_resolver.GetterChain)
    assert _chain_segments(fc.params[0]) == [("imię",), ("obserwator",)]
    assert isinstance(fc.params[1], parser_mod.Word)
    assert fc.params[1].value.segments == ("obserwacja",)


def test_bare_chain_collapse_predicate_uses_identity(resolve):
    # Zwijanie do GetterChain uruchamia się tylko gdy chain[0] is words[0].
    # `pisz nazwa użytkownika` — chain[0] to nazwa (words[1]), NIE pisz (words[0])
    ast = resolve("aby f:\n    pisz nazwa użytkownika\n")
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=1)
    assert isinstance(fc.params[0], phrase_resolver.GetterChain)
    assert _chain_segments(fc.params[0]) == [("nazwa",), ("użytkownik",)]


# ============================================================
#  Pozycja getter chaina w obrębie wywołania funkcji
# ============================================================

def test_chain_at_end_of_call(resolve):
    # `pisz imię autora komentarza` → FunctionCall(pisz, [chain])
    ast = resolve("aby f:\n    pisz imię autora komentarza\n")
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=1)
    assert _chain_segments(fc.params[0]) == [
        ("imię",), ("autor",), ("komentarz",),
    ]


def test_chain_at_start_then_more_args(resolve):
    # `imię autora komentarza po spacjach` — chain na początku, prep arg na końcu
    ast = resolve("aby f:\n    imię autora komentarza po spacjach\n")
    p = _first_phrase(ast)
    # Head to `imię` → FunctionCall(imię, [chain, po_spacjach])
    fc = _is_call(p, ("imię",), n_params=2)
    assert isinstance(fc.params[0], phrase_resolver.GetterChain)
    assert _chain_segments(fc.params[0]) == [
        ("imię",), ("autor",), ("komentarz",),
    ]
    assert isinstance(fc.params[1], parser_mod.Word)
    assert fc.params[1].prep == ("po",)
    assert fc.params[1].value.segments == ("spacja",)


def test_chain_in_the_middle(resolve):
    # `pisz nazwa użytkownika tekstem` — chain między argumentami
    ast = resolve("aby f:\n    pisz nazwa użytkownika tekstem\n")
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=2)
    assert isinstance(fc.params[0], phrase_resolver.GetterChain)
    assert _chain_segments(fc.params[0]) == [("nazwa",), ("użytkownik",)]
    assert isinstance(fc.params[1], parser_mod.Word)
    assert fc.params[1].value.segments == ("tekst",)


def test_arg_then_chain_at_end(resolve):
    # `pisz tekstem nazwa użytkownika` — najpierw arg, potem chain
    ast = resolve("aby f:\n    pisz tekstem nazwa użytkownika\n")
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=2)
    assert isinstance(fc.params[0], parser_mod.Word)
    assert fc.params[0].value.segments == ("tekst",)
    assert isinstance(fc.params[1], phrase_resolver.GetterChain)
    assert _chain_segments(fc.params[1]) == [("nazwa",), ("użytkownik",)]


def test_chain_followed_by_prep_arg(resolve):
    # `pisz nazwa użytkownika z bazy` — chain kończy się gdy następne słowo ma prep
    ast = resolve("aby f:\n    pisz nazwa użytkownika z bazy\n")
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
    ast = resolve("aby f:\n    pisz imię autora komentarza nazwa użytkownika\n")
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=2)
    assert _chain_segments(fc.params[0]) == [
        ("imię",), ("autor",), ("komentarz",),
    ]
    assert _chain_segments(fc.params[1]) == [("nazwa",), ("użytkownik",)]


def test_two_chains_with_arg_between(resolve):
    # `pisz nazwa użytkownika tekstem imię autora komentarza`
    ast = resolve("aby f:\n    pisz nazwa użytkownika tekstem imię autora komentarza\n")
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
        "aby f:\n"
        "    pisz nazwa użytkownika imię autora komentarza identyfikator postu\n"
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
    # `imię autora komentarza to "Anna"` — LHS to Phrase, której func_call to GetterChain
    ast = resolve('aby f:\n    imię autora komentarza to "Anna"\n')
    a = _func_def(ast).body[0]
    assert isinstance(a, parser_mod.Assignment)
    assert isinstance(a.target, parser_mod.Phrase)
    assert _chain_segments(a.target) == [
        ("imię",), ("autor",), ("komentarz",),
    ]
    assert isinstance(a.value, parser_mod.StrLit)


def test_chain_in_assignment_rhs(resolve):
    # `wynik to imię autora komentarza` — RHS to Phrase z bare GetterChain
    ast = resolve("aby f:\n    wynik to imię autora komentarza\n")
    a = _func_def(ast).body[0]
    assert isinstance(a, parser_mod.Assignment)
    assert isinstance(a.value, parser_mod.Phrase)
    assert _chain_segments(a.value) == [
        ("imię",), ("autor",), ("komentarz",),
    ]


def test_chain_inside_return(resolve):
    ast = resolve("aby f:\n    zwróć imię autora komentarza\n")
    r = _func_def(ast).body[0]
    assert isinstance(r, parser_mod.Return)
    assert isinstance(r.value, parser_mod.Phrase)
    assert _chain_segments(r.value) == [
        ("imię",), ("autor",), ("komentarz",),
    ]


def test_chain_inside_if_cond(resolve):
    src = (
        "aby f:\n"
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
        "aby f:\n"
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
    ast = resolve("aby f:\n    x to liczba_polubień postu + 1\n")
    a = _func_def(ast).body[0]
    expr = a.value
    assert isinstance(expr, parser_mod.BinOp) and expr.op == "+"
    assert _chain_segments(expr.left) == [
        ("liczba", "polubić"), ("post",),
    ]


def test_chain_inside_binop_both_sides(resolve):
    # `liczba_polubień postu = liczba_polubień komentarza`
    ast = resolve(
        "aby f:\n"
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
        "aby f:\n"
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
        "aby f:\n"
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
    ast = resolve("aby f:\n    x to -liczba_polubień postu\n")
    a = _func_def(ast).body[0]
    assert isinstance(a.value, parser_mod.UnaryOp) and a.value.op == "-"
    assert _chain_segments(a.value.operand) == [
        ("liczba", "polubić"), ("post",),
    ]


def test_chain_inside_parens(resolve):
    # `pisz (imię autora komentarza)` — wewnętrzna fraza zwija się do GetterChain
    ast = resolve("aby f:\n    pisz (imię autora komentarza)\n")
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
    ast = resolve("aby f:\n    pisz tekstem (nazwa użytkownika)\n")
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
    ast = resolve("aby f:\n    nazwa użytkownika\n")
    p = _first_phrase(ast)
    assert _chain_segments(p) == [("nazwa",), ("użytkownik",)]


def test_head_word_field_with_extra_arg_does_not_collapse(resolve):
    # `nazwa użytkownika \"x\"` — head jest fieldem, ale fraza ma dodatkowy arg → FunctionCall
    ast = resolve('aby f:\n    nazwa użytkownika "x"\n')
    p = _first_phrase(ast)
    # Z powodu Buga A kolejność może być nieprawidłowa, ale całość nie zwija się do GetterChain.
    fc = p.func_call
    assert isinstance(fc, phrase_resolver.FunctionCall), \
        f"oczekiwano FunctionCall (jest dodatkowy arg), było {type(fc).__name__}"
    assert fc.name.segments == ("nazwa",)


# ============================================================
#  Identyfikator z prefiksem przyimkowym
# ============================================================

def test_prep_identifier_can_be_field_check_target(resolve):
    # `pisz dla użytkownika sesji` — words[1]=dla użytkownika (prep), words[2]=sesji (gen)
    # is_a_field(użytkownik) → True → chain=[dla użytkownika, sesji]
    # Chain[0] ma prep="dla". Cały chain jest jednym argumentem fukcji `pisz`.
    ast = resolve("aby f:\n    pisz dla użytkownika sesji\n")
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
    ast = resolve("aby f:\n    pisz tekstem mocnym nazwa użytkownika\n")
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
    src = (
        "aby polubić post (Post):\n"
        "    liczba_polubień postu to liczba_polubień postu + 1\n"
    )
    ast = resolve(src)
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
        "aby f sesji (Sesja) z treścią (Tekst):\n"
        "    nowy to stwórz_post z treścią dla użytkownika sesji\n"
    )
    ast = resolve(src)
    a = _func_def(ast).body[0]
    assert isinstance(a, parser_mod.Assignment)
    fc = a.value.func_call
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
    ast = resolve('aby f:\n    pisz nazwa użytkownika "etykieta"\n')
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
    ast = resolve("aby f:\n    pisz nazwa użytkownika 42\n")
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=2)
    assert isinstance(fc.params[0], phrase_resolver.GetterChain), (
        f"params[0] powinien być chainem, był {type(fc.params[0]).__name__}"
    )
    assert isinstance(fc.params[1].value, parser_mod.IntLit)


def test_BUG_chain_followed_by_paren_phrase_keeps_source_order(resolve):
    """Wariant Buga #1 z subfrazą w nawiasach."""
    ast = resolve("aby f:\n    pisz nazwa użytkownika (1 + 2)\n")
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
    ast = resolve('aby f:\n    pisz "x" autora\n')
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=2)
    # `autora` powinno być zwykłym argumentem (StrLit nie jest fieldem)
    assert isinstance(fc.params[1], parser_mod.Word)
    assert fc.params[1].value.segments == ("autor",)


def test_BUG_is_a_field_crashes_on_int_literal_predecessor(resolve):
    """Wariant Buga #2 — IntLit zamiast StrLit."""
    ast = resolve("aby f:\n    pisz 42 autora\n")
    p = _first_phrase(ast)
    fc = _is_call(p, ("pisać",), n_params=2)
    assert isinstance(fc.params[1], parser_mod.Word)
    assert fc.params[1].value.segments == ("autor",)


def test_BUG_is_a_field_crashes_on_paren_phrase_predecessor(resolve):
    """Wariant Buga #2 — sub-Phrase w nawiasach."""
    ast = resolve("aby f:\n    pisz (1 + 2) autora\n")
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
    text1 = STRUCTS + "aby f:\n    nazwa użytkownika\n"
    ast1 = parser_mod.parse(morph_anal.analyze(lexer.lex(text1), _db), _preps)
    phrase_resolver.resolve_module(ast1)
    fields_after_module_1 = list(phrase_resolver.fields)
    assert len(fields_after_module_1) > 0  # załadowane z STRUCTS

    # Moduł 2 — bez structów. resolve_module powinien zacząć ze świeżą listą fields.
    text2 = "aby g:\n    pisz nazwa użytkownika\n"
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
    fc = p2.func_call
    assert isinstance(fc, phrase_resolver.FunctionCall)
    assert all(isinstance(par, parser_mod.Word) for par in fc.params), (
        f"bez structów `nazwa użytkownika` powinno być [Word, Word], jest "
        f"{[type(p).__name__ for p in fc.params]}"
    )
