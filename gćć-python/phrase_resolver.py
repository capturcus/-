import parser
from dataclasses import dataclass, field
from itertools import product

fields = []


class ResolveError(Exception):
    pass


@dataclass
class FunctionCall:
    name: parser.FunctionIdentifier
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


_ADJ_LIKE_POS = ("adj", "pact", "ppas")


def _adj_cases_from_analyses(analyses):
    if not analyses:
        return frozenset()
    out = frozenset()
    for ana in analyses[0]:
        if ana.pos in _ADJ_LIKE_POS and ana.case:
            out |= ana.case
    return out


class PhraseResolver:
    def __init__(self, words, fields, fields_by_type, types):
        self.words = words
        self.pos = 0
        self.field_names = {f.name.segments for f in fields}
        self.fields_by_type = fields_by_type
        self.types = types
        self.struct_stack = []

    def peek(self, offset=0):
        i = self.pos + offset
        return self.words[i] if i < len(self.words) else None

    def advance(self):
        w = self.peek()
        self.pos += 1
        return w

    def _is_field(self, word):
        if word is None or not isinstance(word.value, parser.Identifier):
            return False
        return word.value.segments in self.field_names

    def _is_gen_no_prep(self, word):
        if word is None or not isinstance(word.value, parser.Identifier):
            return False
        if word.value.case is None or "gen" not in word.value.case:
            return False
        return word.prep is None

    def _can_start_chain(self, head_word):
        return self._is_field(head_word) and self._is_gen_no_prep(self.peek())

    def _starts_struct_creation(self, word):
        if word.prep is not None:
            return False
        if not isinstance(word.value, parser.Identifier):
            return False
        if word.value.segments != ("nowy",):
            return False
        nxt = self.peek()
        if nxt is None or nxt.prep is not None:
            return False
        if not isinstance(nxt.value, parser.Identifier):
            return False
        if nxt.value.segments not in self.types:
            return False
        return self._cases_overlap(word, nxt)

    def _starts_sub_function_call(self, word):
        if word.prep is not None:
            return False
        if not isinstance(word.value, parser.Identifier):
            return False
        try:
            parser.FunctionIdentifier.from_head(word.value)
            return True
        except parser.FunctionIdentifierError:
            return False

    def _cases_overlap(self, nowy_word, type_word):
        nowy_cases = _adj_cases_from_analyses(nowy_word.value.analyses)
        type_cases = type_word.value.case
        if not nowy_cases or not type_cases:
            return True
        return bool(nowy_cases & type_cases)

    def _at_struct_arg_boundary(self):
        if not self.struct_stack:
            return False
        p = self.peek()
        if not self._is_z_inst(p):
            return False
        return any(
            self._field_name_match(p.value, self.fields_by_type[ctx.type_name])
            is not None
            for ctx in self.struct_stack
        )

    def _at_phrase_end(self):
        return self.peek() is None or self._at_struct_arg_boundary()

    def _struct_arg_field_for(self, ctx):
        p = self.peek()
        if not self._is_z_inst(p):
            return None
        matched = self._field_name_match(
            p.value, self.fields_by_type[ctx.type_name]
        )
        if matched is None or matched in ctx.assigned:
            return None
        return matched

    @staticmethod
    def _is_z_inst(p):
        if p is None or p.prep != ("z",):
            return False
        if not isinstance(p.value, parser.Identifier):
            return False
        return p.value.case is not None and "inst" in p.value.case

    @staticmethod
    def _field_name_match(identifier, field_set):
        """Identifier może mieć segments wybierające jedną z wielu możliwych lemm
        (canonical preferuje pierwszą analyzę). Tu sprawdzamy WSZYSTKIE kombinacje
        lemm i zwracamy tę, która pasuje do field_set — albo None."""
        if identifier.segments in field_set:
            return identifier.segments
        if not identifier.analyses:
            return None
        options = [
            sorted({a.lemma for a in seg_anas}) if seg_anas else [identifier.segments[i]]
            for i, seg_anas in enumerate(identifier.analyses)
        ]
        for combo in product(*options):
            if combo in field_set:
                return combo
        return None

    def _bare_head(self, head):
        try:
            name = parser.FunctionIdentifier.from_head(head.value)
            return FunctionCall(name=name, params=[])
        except parser.FunctionIdentifierError:
            return head.value

    def parse_phrase(self):
        p = self.peek()
        if not isinstance(p.value, parser.Identifier):
            return self.advance()
        head = self.advance()
        if self._starts_struct_creation(head):
            return self.parse_struct_creation(head)
        if self._can_start_chain(head):
            chain = self.parse_getter_chain(head)
            if self._at_phrase_end():
                return chain
        if self._is_field(head) and not self._at_phrase_end():
            raise ResolveError(
                f"identyfikator '{'_'.join(head.value.surface)}' jest polem — "
                f"nie może wystąpić w roli nazwy funkcji"
            )
        if self._at_phrase_end():
            return self._bare_head(head)
        return self.parse_function_call(head)

    def parse_function_call(self, head):
        params = []
        while not self._at_phrase_end():
            params.append(self.parse_arg())
        try:
            name = parser.FunctionIdentifier.from_head(head.value)
        except parser.FunctionIdentifierError:
            if not params:
                return head.value
            raise
        return FunctionCall(name=name, params=params)

    def parse_arg(self):
        word = self.advance()
        if self._can_start_chain(word):
            return self.parse_getter_chain(word)
        if self._starts_struct_creation(word):
            return self.parse_struct_creation(word)
        if self._starts_sub_function_call(word):
            return self.parse_function_call(word)
        return word

    def parse_getter_chain(self, head_word):
        chain = [head_word, self.advance()]
        while self._is_gen_no_prep(self.peek()) and self._is_field(chain[-1]):
            chain.append(self.advance())
        return GetterChain(chain=chain)

    def parse_struct_creation(self, nowy_word):
        type_word = self.advance()
        type_name = type_word.value.segments
        ctx = StructCtx(type_name=type_name)
        self.struct_stack.append(ctx)
        args = []
        while True:
            field_name = self._struct_arg_field_for(ctx)
            if field_name is None:
                break
            self.advance()
            ctx.assigned.add(field_name)
            if self._at_phrase_end():
                args.append(StructArg(field_name=field_name, value=None))
            else:
                args.append(StructArg(
                    field_name=field_name,
                    value=self.parse_phrase(),
                ))
        self.struct_stack.pop()
        return StructCreation(type_name=type_name, args=args)


def resolve_phrase(p, fields_by_type, types):
    global fields
    resolver = PhraseResolver(p.words, fields, fields_by_type, types)
    p.resolved_phrase = resolver.parse_phrase()
    if resolver.peek() is not None:
        raise ResolveError(
            f"po sparsowaniu frazy pozostały niesparsowane tokeny "
            f"(pierwszy: {resolver.peek()})"
        )


def resolve_module(m):
    global fields
    fields = []
    fields_by_type = {}
    types = set()
    function_names = set()
    for i in m.body:
        if isinstance(i, parser.StructDef):
            types.add(i.name)
            fbt = fields_by_type.setdefault(i.name, set())
            for f in i.fields:
                fields.append(f)
                fbt.add(f.name.segments)
        elif isinstance(i, parser.FunctionDef):
            function_names.add(i.name.segments)
    field_names = {f.name.segments for f in fields}
    overlap = field_names & function_names
    if overlap:
        names = ", ".join("_".join(n) for n in sorted(overlap))
        raise ResolveError(
            f"konflikt nazw: identyfikator nie może być jednocześnie polem i funkcją: {names}"
        )
    for p in m.phrases:
        resolve_phrase(p, fields_by_type, types)
