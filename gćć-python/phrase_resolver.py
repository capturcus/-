import parser
from dataclasses import dataclass

fields = []


class ResolveError(Exception):
    pass


@dataclass
class FunctionCall:
    name: parser.Identifier
    params: list


@dataclass
class GetterChain:
    chain: list


class PhraseResolver:
    def __init__(self, words, fields):
        self.words = words
        self.pos = 0
        self.fields = {f.name.segments for f in fields}

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
        return word.value.segments in self.fields

    def _is_gen_no_prep(self, word):
        if word is None or not isinstance(word.value, parser.Identifier):
            return False
        if word.value.case is None or "gen" not in word.value.case:
            return False
        return word.prep is None

    def _can_start_chain(self, head_word):
        return self._is_field(head_word) and self._is_gen_no_prep(self.peek())

    def parse_phrase(self):
        head = self.advance()
        if self._can_start_chain(head):
            chain = self.parse_getter_chain(head)
            if self.peek() is None:
                return chain
        if self._is_field(head) and self.peek() is not None:
            raise ResolveError(
                f"identyfikator '{'_'.join(head.value.surface)}' jest polem — "
                f"nie może wystąpić w roli nazwy funkcji"
            )
        return self.parse_function_call(head)

    def parse_function_call(self, head):
        params = []
        while self.peek() is not None:
            params.append(self.parse_arg())
        return FunctionCall(name=head.value, params=params)

    def parse_arg(self):
        word = self.advance()
        if self._can_start_chain(word):
            return self.parse_getter_chain(word)
        return word

    def parse_getter_chain(self, head_word):
        chain = [head_word, self.advance()]
        while self._is_gen_no_prep(self.peek()) and self._is_field(chain[-1]):
            chain.append(self.advance())
        return GetterChain(chain=chain)


def resolve_phrase(p):
    global fields
    p.resolved_phrase = PhraseResolver(p.words, fields).parse_phrase()


def resolve_module(m):
    global fields
    fields = []
    function_names = set()
    for i in m.body:
        if isinstance(i, parser.StructDef):
            for f in i.fields:
                fields.append(f)
        elif isinstance(i, parser.FunctionDef):
            function_names.add(i.name)
    field_names = {f.name.segments for f in fields}
    overlap = field_names & function_names
    if overlap:
        names = ", ".join("_".join(n) for n in sorted(overlap))
        raise ResolveError(
            f"konflikt nazw: identyfikator nie może być jednocześnie polem i funkcją: {names}"
        )
    for p in m.phrases:
        resolve_phrase(p)
