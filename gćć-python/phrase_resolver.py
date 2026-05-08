import parser
from dataclasses import dataclass

fields = []

@dataclass
class FunctionCall:
    name: parser.Identifier
    params: list

@dataclass
class GetterChain:
    chain: list

def is_a_field(word):
    global fields
    if not isinstance(word, parser.Identifier):
        return False
    return word.segments in [x.name.segments for x in fields]

def resolve_phrase(p):
    # todo: check first word grammar
    ret = FunctionCall(name=p.words[0].value, params=[])
    chain_started = False
    gen_chain = []
    for i in range(1, len(p.words)):
        word = p.words[i]
        # Słowo wchodzi do chaina (rozpoczyna lub rozszerza), gdy ono samo jest
        # w dopełniaczu bez przyimka ORAZ poprzednie słowo — które właśnie staje
        # się ogniwem-fieldem — jest fieldem. Drugi warunek egzekwujemy na każdym
        # przejściu: w `imię autora komentarza` zarówno `imię` (chain[0]), jak i
        # `autor` (chain[1]) muszą być fieldami; tylko ostatni element to baza.
        is_chain_link = (
            isinstance(word.value, parser.Identifier)
            and word.value.case is not None
            and "gen" in word.value.case
            and word.prep is None
        )
        if is_chain_link and is_a_field(p.words[i-1].value):
            if chain_started:
                gen_chain.append(word)
            else:
                if ret.params:
                    ret.params.pop()
                gen_chain = [p.words[i-1], word]
                chain_started = True
        else:
            if chain_started:
                ret.params.append(GetterChain(chain=gen_chain))
                chain_started = False
            ret.params.append(word)
    if chain_started:
        ret.params.append(GetterChain(chain=gen_chain))
    if (
        len(ret.params) == 1
        and isinstance(ret.params[0], GetterChain)
        and ret.params[0].chain[0] is p.words[0]
    ):
        p.func_call = ret.params[0]
    else:
        p.func_call = ret
    print(p.func_call)


def resolve_module(m):
    global fields
    fields = []
    for i in m.body:
        if isinstance(i, parser.StructDef):
            for f in i.fields:
                fields.append(f)
    for p in m.phrases:
        resolve_phrase(p)
