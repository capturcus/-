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
    for w in p.words:
        if not isinstance(w.value, parser.Identifier):
            resolve_expr(w.value)
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



def resolve_expr(e):
    if isinstance(e, parser.Phrase):
        resolve_phrase(e)
    elif isinstance(e, parser.BinOp):
        resolve_expr(e.left)
        resolve_expr(e.right)
    elif isinstance(e, parser.UnaryOp):
        resolve_expr(e.operand)
    elif isinstance(e, parser.Not):
        resolve_expr(e.operand)
    elif isinstance(e, (parser.And, parser.Or)):
        resolve_expr(e.left)
        resolve_expr(e.right)


def resolve_assignment(a):
    resolve_expr(a.target)
    resolve_expr(a.value)


def resolve_if(node):
    resolve_expr(node.cond)
    for s in node.then_body:
        resolve_stmt(s)
    for s in node.else_body:
        resolve_stmt(s)


def resolve_while(node):
    resolve_expr(node.cond)
    for s in node.body:
        resolve_stmt(s)


def resolve_return(r):
    resolve_expr(r.value)


def resolve_stmt(s):
    if isinstance(s, parser.Assignment):
        resolve_assignment(s)
    elif isinstance(s, parser.If):
        resolve_if(s)
    elif isinstance(s, parser.While):
        resolve_while(s)
    elif isinstance(s, parser.Return):
        resolve_return(s)
    elif isinstance(s, parser.Break):
        pass
    else:
        resolve_expr(s)


def resolve_func_def(fd):
    for s in fd.body:
        resolve_stmt(s)


def resolve_module(m):
    global fields
    fields = []
    for i in m.body:
        if isinstance(i, parser.StructDef):
            for f in i.fields:
                fields.append(f)
    for i in m.body:
        if isinstance(i, parser.FunctionDef):
            resolve_func_def(i)
