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

def is_a_field(word: parser.Identifier):
    global fields
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
        if not isinstance(p.words[i].value, parser.Identifier):
            ret.params.append(p.words[i])
            if chain_started:
                # collapse chain
                ret.params.append(GetterChain(chain=gen_chain))
                chain_started = False
            continue
        word = p.words[i]
        if word.value.case is not None and "gen" in word.value.case and word.prep is None:
            if chain_started:
                gen_chain.append(word)
                continue
            else:
                if is_a_field(p.words[i-1].value):
                    if len(ret.params) > 0:
                        ret.params.pop()
                    gen_chain = [p.words[i-1], p.words[i]]
                    chain_started = True
        else:
            if chain_started:
                # collapse chain
                ret.params.append(GetterChain(chain=gen_chain))
                chain_started = False
            ret.params.append(word)
    if chain_started:
        ret.params.append(GetterChain(chain=gen_chain))
    p.func_call = ret
    print(ret)



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
    for i in m.body:
        if isinstance(i, parser.StructDef):
            for f in i.fields:
                fields.append(f)
    for i in m.body:
        if isinstance(i, parser.FunctionDef):
            resolve_func_def(i)
