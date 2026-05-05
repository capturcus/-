import parser


def resolve_phrase(p):
    print(p)
    for w in p.words:
        if not isinstance(w.value, tuple):
            resolve_expr(w.value)


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
    for i in m.body:
        if isinstance(i, parser.FunctionDef):
            resolve_func_def(i)
