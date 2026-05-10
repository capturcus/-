from dataclasses import dataclass, field

from morph_anal import canonical, VERB_POS, VerbForm


@dataclass
class Module:
    body: list
    phrases: list


@dataclass(frozen=True)
class Identifier:
    segments: tuple
    surface: tuple
    case: frozenset = None
    analyses: tuple = ()  # tuple[tuple[MorphAnalysis, ...], ...]


class IdentifierError(SyntaxError):
    pass


class FunctionIdentifierError(IdentifierError):
    pass


def _validate_function_name(surface, segments, analyses):
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
            (a for a in verb_anas if a.lemma == segments[i]),
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
            head.surface, head.segments, head.analyses
        )
        return cls(
            segments=head.segments,
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
        verb_index, verb_form = _validate_function_name(
            surface, segments, analyses_t
        )
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
