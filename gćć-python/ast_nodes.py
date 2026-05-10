from dataclasses import dataclass, field

from morph_anal import canonical, VERB_POS, VerbForm


_ADJ_LIKE = ("adj", "pact", "ppas")


@dataclass
class Module:
    body: list
    phrases: list


def _canonical_segments(surface, analyses):
    """Canonical-style lematy gdy identyfikator nie ma wariantów (verb-only
    nazwa funkcji albo atom)."""
    out = []
    for seg, anas in zip(surface, analyses):
        if not anas or len(seg) == 1:
            out.append(seg)
            continue
        adj_like = [a for a in anas if a.pos in _ADJ_LIKE]
        pool = adj_like if adj_like else list(anas)
        chosen = next((a for a in pool if a.lemma == seg), pool[0])
        out.append(chosen.lemma)
    return tuple(out)


@dataclass(frozen=True)
class Identifier:
    """Identyfikator nie-funkcyjny.

    Pełna informacja jest w `variants` — każdy wariant to spójna
    interpretacja `(lemmas_tuple, case_frozenset)` (adj-czytanie vs
    subst-czytanie per segment). Atrybuty `segments` i `case` to widoki
    pochodne na variants:
    - `segments`: lemmas wariantu z największym case-set (najmniej
      zawężona interpretacja). Gdy variants=() (verbal-only lub atom)
      fallback do canonical-style lemm z analiz.
    - `case`: union case wszystkich wariantów. None gdy variants=().
    """
    surface: tuple
    analyses: tuple = ()  # tuple[tuple[MorphAnalysis, ...], ...]
    variants: tuple = ()  # tuple[ tuple[lemmas_tuple, case_frozenset], ... ]

    @property
    def segments(self):
        if self.variants:
            best = max(self.variants, key=lambda v: len(v[1]))
            return best[0]
        return _canonical_segments(self.surface, self.analyses)

    @property
    def case(self):
        if not self.variants:
            return None
        return frozenset().union(*(case for _, case in self.variants))


class IdentifierError(SyntaxError):
    pass


class FunctionIdentifierError(IdentifierError):
    pass


def _validate_function_name(surface, analyses):
    """Zwraca (verb_index, verb_form) lub rzuca FunctionIdentifierError.

    Gdy w tym samym segmencie jest kilka verb-readings (np. impt różnych
    czasowników), bierze pierwszy. To zachowuje obecną semantykę: w
    praktyce takie kolizje są rzadkie, a wcześniejsza heurystyka i tak
    fall-backowała do `verb_anas[0]` gdy `segments[i]` było non-verbal.
    """
    if not analyses:
        raise FunctionIdentifierError(
            f"identyfikator funkcji '{'_'.join(surface)}' "
            f"nie ma danych morfologicznych"
        )
    for i, anas in enumerate(analyses):
        seg = surface[i]
        if not anas or len(seg) == 1:
            continue
        verb_anas = [a for a in anas if a.pos in VERB_POS]
        if not verb_anas:
            continue
        chosen = next(
            (a for a in verb_anas if a.lemma == seg),
            verb_anas[0],
        )
        return i, chosen.verb_form
    raise FunctionIdentifierError(
        f"nazwa funkcji '{'_'.join(surface)}' nie zawiera czasownika; "
        f"wymagany jest co najmniej jeden segment czasownikowy "
        f"(fin, impt, inf, imps, praet, pcon, winien, będzie, fut, cond)"
    )


@dataclass(frozen=True)
class FunctionIdentifier:
    segments: tuple
    surface: tuple
    verb_index: int
    verb_form: VerbForm

    @classmethod
    def from_head(cls, head):
        verb_index, verb_form = _validate_function_name(
            head.surface, head.analyses
        )
        return cls(
            segments=_canonical_segments(head.surface, head.analyses),
            surface=head.surface,
            verb_index=verb_index,
            verb_form=verb_form,
        )

    @classmethod
    def from_token(cls, tok):
        """Buduje FunctionIdentifier bezpośrednio z tokenu morfologicznego.
        Używane przez parse_func_def — definicja funkcji jest jednoznaczna,
        więc nie potrzeba etapu HeadIdentifier."""
        _, surface, analyses = tok
        segments = canonical(tok)
        analyses_t = tuple(tuple(a) for a in analyses)
        verb_index, verb_form = _validate_function_name(surface, analyses_t)
        return cls(
            segments=segments,
            surface=surface,
            verb_index=verb_index,
            verb_form=verb_form,
        )


@dataclass
class FunctionDef:
    name: "FunctionIdentifier"
    params: list
    body: list
    return_type: tuple = None


@dataclass
class Param:
    prep: tuple
    name: Identifier
    case: frozenset
    type: tuple = None


@dataclass
class StructDef:
    name: tuple
    fields: list


@dataclass
class Field:
    name: Identifier
    type: tuple


@dataclass
class Phrase:
    tokens: list  # surowe tokeny (po preprocess) zebrane przez parser.collect_phrase
    resolved: object = None  # wypełniane przez expression.resolve_module


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
class Break:
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


class ResolveError(Exception):
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
class StructArg:
    field_name: tuple
    value: object


@dataclass
class StructCtx:
    type_name: tuple
    assigned: set = field(default_factory=set)
