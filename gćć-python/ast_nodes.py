from dataclasses import dataclass, field
from itertools import product
from typing import NamedTuple

from morph_anal import canonical, VERB_POS


_ADJ_LIKE = ("adj", "pact", "ppas")


class Variant(NamedTuple):
    """Spójna interpretacja identyfikatora: lemma + case + liczba + rodzaj + reszta.

    `lemmas` to krotka lemm per segment. `case` to frozenset przypadków
    spójnych dla wszystkich segmentów. `number` (sg/pl) i `gender` (m/f/n)
    pochodzą z subst-głowy (lub adj-głowy w pure-adj variants). Mogą być
    None tylko dla atomów / passthroughów single-letter. `rest_length` to
    liczba passthrough-segmentów po subst-głowie. `had_subst` flaga
    czy wariant ma subst-głowę — używana do preferowania subst-readings
    nad adj przy walidacji LHS/field (zmienne są zwykle rzeczownikami).
    `specialized` flaga czy któraś z analiz źródłowych miała SGJP qualifier
    (np. `ryb.`, `przest.`, `pot.`) — przy ambiguity preferujemy odczyty
    mainstream (specialized=False).
    """
    lemmas: tuple
    case: frozenset
    number: str
    gender: str
    rest_length: int
    had_subst: bool = True
    specialized: bool = False


@dataclass
class Module:
    body: list


def enumerate_canonical_lemmas(surface, analyses):
    """Wszystkie kanoniczne interpretacje lemma — kartezjański produkt
    per-segment opcji. Używane gdy identyfikator nie ma wariantów (atomy,
    verb-only function names) oraz przez FunctionIdentifier.

    Zwraca list[tuple[str, ...]]. Atom (single-letter, no analyses) → [(seg,)].
    Multi-pos segment → wszystkie lemmy z poolu (adj-priority jeśli adj-like
    readings istnieją, inaczej wszystkie analizy). Per-segment caps z surface
    aplikowane do lemmy (capital surface → capitalized lemma)."""
    def _cap(lemma, seg):
        if seg and seg[0].isupper() and lemma:
            return lemma[:1].upper() + lemma[1:]
        return lemma
    per_seg = []
    for seg, anas in zip(surface, analyses):
        if not anas or len(seg) == 1:
            per_seg.append((seg,))
            continue
        adj_like = [a for a in anas if a.pos in _ADJ_LIKE]
        pool = adj_like if adj_like else list(anas)
        lemmas = tuple({_cap(a.lemma, seg) for a in pool})
        per_seg.append(lemmas)
    return [tuple(combo) for combo in product(*per_seg)]


@dataclass(frozen=True)
class Identifier:
    """Identyfikator nie-funkcyjny.

    Pełna informacja jest w `variants` — krotka `Variant` (lemmas, case,
    number, gender, rest_length). Każdy wariant to spójna interpretacja
    (adj-czytanie vs subst-czytanie per segment, splittowanie per (lemma,
    number, gender)). Widoki pochodne:
    - `lemmas_set`: frozenset wszystkich możliwych lemma-tuple'i (variants
      lub fallback do enumerate_canonical_lemmas dla atomów).
    - `scope_keys`: frozenset pełnych kluczy (lemmas, number, gender) —
      używany przez scope zmiennych i field_names. Atomy mają klucz
      (lemma, None, None).
    - `case`: union case wszystkich wariantów. None gdy variants=().
    """
    surface: tuple
    analyses: tuple = ()  # tuple[tuple[MorphAnalysis, ...], ...]
    variants: tuple = ()  # tuple[Variant, ...]
    line: int = None  # 1-based linia w źródle, None gdy syntetyczna konstrukcja

    @property
    def lemmas_set(self):
        if self.variants:
            return frozenset(v.lemmas for v in self.variants)
        return frozenset(enumerate_canonical_lemmas(self.surface, self.analyses))

    @property
    def scope_keys(self):
        if self.variants:
            return frozenset(
                (v.lemmas, v.number, v.gender) for v in self.variants
            )
        return frozenset(
            (l, None, None)
            for l in enumerate_canonical_lemmas(self.surface, self.analyses)
        )

    @property
    def case(self):
        if not self.variants:
            return None
        return frozenset().union(*(v.case for v in self.variants))


def scope_key_matches(a, b):
    """Czy dwa scope-keys (lemmas, number, gender) wskazują tę samą zmienną.

    Kanoniczny predykat dopasowania zmiennych — używany przez resolver
    (`expression._Scope.has_var`) oraz typechecker (`typechecker.Scope`).
    Atom-compat: klucz z (number=None, gender=None) matchuje po samej lemmie
    (atomy / single-letter nie niosą liczby ani rodzaju)."""
    if a == b:
        return True
    (la, na, ga), (lb, nb, gb) = a, b
    if na is None and ga is None and la == lb:
        return True
    if nb is None and gb is None and la == lb:
        return True
    return False


class InterpreterError(SyntaxError):
    """Bazowa klasa błędów interpretera. Niesie `line` (1-based numer linii
    w pliku źródłowym) oraz `extra_context` (opcjonalny block tekstu z
    structural-context, np. 'w deklaracji struktury Foo (linia N)').

    `SyntaxError` jako baza zapewnia że `pytest.raises(SyntaxError, ...)`
    nadal łapie błędy migrowane z plain SyntaxError."""
    def __init__(self, message, *, line=None, extra_context=None):
        super().__init__(message)
        self.line = line
        self.extra_context = extra_context


class IdentifierError(InterpreterError):
    pass


class FunctionIdentifierError(IdentifierError):
    pass


def _validate_function_name(surface, analyses):
    """Waliduje że identyfikator funkcji ma ≥1 segment czasownikowy.
    Rzuca FunctionIdentifierError gdy: brak analiz, lub żaden segment
    nie zawiera reading z `VERB_POS`."""
    if not analyses:
        raise FunctionIdentifierError(
            f"identyfikator funkcji '{'_'.join(surface)}' "
            f"nie ma danych morfologicznych"
        )
    for i, anas in enumerate(analyses):
        seg = surface[i]
        if not anas or len(seg) == 1:
            continue
        if any(a.pos in VERB_POS for a in anas):
            return
    raise FunctionIdentifierError(
        f"nazwa funkcji '{'_'.join(surface)}' nie zawiera czasownika; "
        f"wymagany jest co najmniej jeden segment czasownikowy "
        f"(fin, impt, inf, imps, praet, pcon, winien, będzie, fut, cond)"
    )


@dataclass(frozen=True)
class FunctionIdentifier:
    lemmas_set: frozenset  # frozenset[tuple[str, ...]] — wszystkie kanoniczne interpretacje
    surface: tuple
    line: int = None

    @classmethod
    def from_head(cls, head):
        try:
            _validate_function_name(head.surface, head.analyses)
        except FunctionIdentifierError as e:
            if e.line is None:
                e.line = head.line
            raise
        lemmas = frozenset(enumerate_canonical_lemmas(head.surface, head.analyses))
        return cls(
            lemmas_set=lemmas,
            surface=head.surface,
            line=head.line,
        )

    @classmethod
    def from_token(cls, tok):
        """Buduje FunctionIdentifier bezpośrednio z tokenu morfologicznego.
        Używane przez parse_func_def — definicja funkcji jest jednoznaczna
        strukturalnie (zaczyna się od 'aby'), ale jej name może mieć wiele
        kanonicznych interpretacji lemma (np. multi-pos segmenty)."""
        _, surface, analyses = tok[0], tok[1], tok[2]
        line = getattr(tok, "line", None)
        analyses_t = tuple(tuple(a) for a in analyses)
        try:
            _validate_function_name(surface, analyses_t)
        except FunctionIdentifierError as e:
            if e.line is None:
                e.line = line
            raise
        lemmas = frozenset(enumerate_canonical_lemmas(surface, analyses_t))
        return cls(
            lemmas_set=lemmas,
            surface=surface,
            line=line,
        )


@dataclass
class TypeRef:
    """Wyrażenie typu (potencjalnie parametryzowane).

    `head` — krotka lemm konstruktora (np. ("mapa",)); ta sama postać, którą
    czyta typechecker. `args` — lista `TypeArg` w kolejności źródłowej (puste
    dla typów nieparametryzowanych). Argumenty są NIEZWIĄZANE z parametrami
    struktury — wiązanie (po prep/case) jest odroczone do fazy typecheckera."""
    head: tuple
    args: list = field(default_factory=list)
    line: int = None


@dataclass
class TypeArg:
    """Jeden argument aplikacji typu: opcjonalny przyimek + (rekurencyjny) TypeRef.
    `case` — przypadek gramatyczny argumentu (jak `Param.case`), do dopasowania
    arg→param tym samym silnikiem (prep, case) co wywołania funkcji. None dla
    argumentów zagnieżdżonych w nawiasach (brak pojedynczego słowa rządzącego)."""
    prep: tuple
    type: "TypeRef"
    case: frozenset = None


@dataclass
class FunctionDef:
    name: "FunctionIdentifier"
    params: list
    body: list
    line: int = None
    return_type: object = None


@dataclass
class ExternFunctionDef:
    name: "FunctionIdentifier"
    params: list
    line: int = None
    return_type: object = None


@dataclass
class Param:
    prep: tuple
    name: Identifier
    case: frozenset
    type: object = None


@dataclass
class StructDef:
    name: tuple
    fields: list
    line: int = None
    params: list = field(default_factory=list)


@dataclass
class UnionDef:
    """Typ wariantowy: `Rezultat to Wynik albo Błąd`.

    `name`/`members` — krotki lemm (ta sama postać co `StructDef.name`).
    Warianty są BEZ parametrów typu — parametryzacja to sprawa konkretnych
    struktur (unia tylko grupuje głowy)."""
    name: tuple
    members: list  # list[tuple]
    line: int = None


@dataclass
class Match:
    """Konstrukt `X jest:` — dopasowanie wartości unii do wariantów."""
    subject: "Phrase"
    branches: list  # list[MatchBranch]
    line: int = None


@dataclass
class MatchBranch:
    """Gałąź `Wariantem z polem [z polem...]:` wewnątrz dopasowania `X jest:`.

    `type_name` — nazwa wariantu w narzędniku ("wynik jest (czym?) Błędem").
    `fields` — identyfikatory pól do związania (forma narzędnika po `z`);
    może być podzbiorem pól struktury. Pass 2 zawęża każdy do wariantu
    pasującego do zadeklarowanego pola."""
    type_name: tuple
    fields: list  # list[Identifier]
    body: list
    line: int = None


@dataclass
class Field:
    name: Identifier
    line: int = None
    type: object = None


@dataclass
class Phrase:
    tokens: list  # surowe tokeny (po preprocess) zebrane przez parser.collect_phrase
    resolved: object = None  # wypełniane przez expression.resolve_module
    line: int = None  # 1-based linia pierwszego tokenu (do error reporting)


@dataclass
class Word:
    prep: tuple
    value: object
    case: str


@dataclass
class Assignment:
    target: tuple
    value: object


@dataclass
class IntLit:
    value: int


@dataclass
class StrLit:
    value: str


@dataclass
class BoolLit:
    value: bool


@dataclass
class BinOp:
    op: str
    left: object
    right: object


@dataclass
class UnaryOp:
    op: str
    operand: object


@dataclass
class If:
    cond: object
    then_body: list
    else_body: list


@dataclass
class While:
    cond: object
    body: list


@dataclass
class For:
    var: Identifier
    collection: object
    body: list


@dataclass
class Break:
    pass


@dataclass
class Continue:
    pass


@dataclass
class Return:
    value: object = None


@dataclass
class Not:
    operand: object


@dataclass
class And:
    left: object
    right: object


@dataclass
class Or:
    left: object
    right: object


LOGICAL_OPS = {("nie",), ("i",), ("lub",)}


class ResolveError(InterpreterError):
    pass


@dataclass
class FunctionCall:
    name: FunctionIdentifier
    params: list


@dataclass
class GetterChain:
    chain: list


@dataclass
class StructCreation:
    type_name: tuple
    args: list


@dataclass
class TryCall:
    """Wywołanie z obsługą błędu: tryb przypuszczający + '?' po argumentach
    (`wybrałbyś zero z części?`). Semantyka jak `?` Rusta: wynik-Sukces
    odpakowany do wartości, Błąd propagowany returnem z funkcji otaczającej.
    Wymaga zadeklarowanej w module unii `Rezultat to Sukces albo Błąd`."""
    call: FunctionCall
    line: int = None


@dataclass
class Typed:
    expr: object
    line: int = None
    type: object = None


@dataclass
class StructArg:
    field_name: tuple
    value: object


@dataclass
class StructCtx:
    type_name: tuple
    assigned: set = field(default_factory=set)
