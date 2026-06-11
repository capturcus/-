import ast_nodes as ast


_CASE_ORDER = ["nom", "gen", "dat", "acc", "inst", "loc", "voc"]


def _format_case(case):
    if not case:
        return None
    cs = sorted(case, key=_CASE_ORDER.index)
    if len(cs) == 1:
        return cs[0]
    return ",".join(cs)


def pretty(node):
    print(_label(node))
    _print_children(node, "")


def _print_children(node, prefix):
    groups = _groups(node)
    if groups is not None:
        for i, (label, items) in enumerate(groups):
            is_last = i == len(groups) - 1
            branch = "└── " if is_last else "├── "
            ext = "    " if is_last else "│   "
            print(prefix + branch + label + ":")
            for j, child in enumerate(items):
                is_last_child = j == len(items) - 1
                inner_branch = "└── " if is_last_child else "├── "
                inner_ext = "    " if is_last_child else "│   "
                print(prefix + ext + inner_branch + _label(child))
                _print_children(child, prefix + ext + inner_ext)
        return
    children = _children(node)
    for i, child in enumerate(children):
        is_last = i == len(children) - 1
        branch = "└── " if is_last else "├── "
        ext = "    " if is_last else "│   "
        print(prefix + branch + _label(child))
        _print_children(child, prefix + ext)


def _groups(node):
    if isinstance(node, ast.Phrase) and node.resolved is not None:
        return _groups(node.resolved)
    if isinstance(node, ast.FunctionCall):
        if node.params:
            return [("params", node.params)]
        return None
    if isinstance(node, ast.TryCall):
        return _groups(node.call)
    if isinstance(node, ast.FunctionDef):
        groups = []
        if node.params:
            groups.append(("params", node.params))
        groups.append(("body", node.body))
        return groups
    if isinstance(node, ast.ExternFunctionDef):
        if node.params:
            return [("params", node.params)]
        return None
    if isinstance(node, ast.StructDef):
        return [("fields", node.fields)]
    if isinstance(node, ast.Match):
        return [("subject", [node.subject]), ("branches", node.branches)]
    if isinstance(node, ast.MatchBranch):
        return [("body", node.body)]
    if isinstance(node, ast.StructCreation):
        if node.args:
            return [("args", node.args)]
        return None
    if isinstance(node, ast.If):
        groups = [("cond", [node.cond]), ("then", node.then_body)]
        if node.else_body:
            groups.append(("else", node.else_body))
        return groups
    if isinstance(node, ast.While):
        return [("cond", [node.cond]), ("body", node.body)]
    if isinstance(node, ast.For):
        return [
            ("var", [node.var]),
            ("collection", [node.collection]),
            ("body", node.body),
        ]
    return None


def _fmt_tref(tref):
    """Wyrażenie typu jako string: głowa + ([prep] arg)* (rekurencyjnie)."""
    if tref is None:
        return "?"
    s = "_".join(tref.head)
    for a in tref.args:
        prep = ("_".join(a.prep) + " ") if a.prep else ""
        s += f" {prep}{_fmt_tref(a.type)}"
    return s


def _label(node):
    if isinstance(node, ast.Module):
        return "Module"
    if isinstance(node, ast.FunctionDef):
        s = f"FunctionDef {'_'.join(node.name.surface)}"
        if node.return_type is not None:
            s += f" -> {_fmt_tref(node.return_type)}"
        return s
    if isinstance(node, ast.ExternFunctionDef):
        s = f"ExternFunctionDef {'_'.join(node.name.surface)}"
        if node.return_type is not None:
            s += f" -> {_fmt_tref(node.return_type)}"
        return s
    if isinstance(node, ast.StructDef):
        return f"StructDef {'_'.join(node.name)}"
    if isinstance(node, ast.UnionDef):
        members = " albo ".join("_".join(m) for m in node.members)
        return f"UnionDef {'_'.join(node.name)} = {members}"
    if isinstance(node, ast.Match):
        return "Match"
    if isinstance(node, ast.MatchBranch):
        s = f"MatchBranch {'_'.join(node.type_name)}"
        for f in node.fields:
            s += f" z {'_'.join(f.surface)}"
        return s
    if isinstance(node, ast.Field):
        return f"Field {'_'.join(node.name.surface)} : {_fmt_tref(node.type)}"
    if isinstance(node, ast.Param):
        parts = ["Param"]
        if node.prep:
            parts.append("_".join(node.prep))
        parts.append("_".join(node.name.surface))
        if node.case:
            parts.append(f"({_format_case(node.case)})")
        if node.type is not None:
            parts.append(f": {_fmt_tref(node.type)}")
        return " ".join(parts)
    if isinstance(node, ast.Phrase):
        if node.resolved is not None:
            return _label(node.resolved)
        return "Phrase"
    if isinstance(node, ast.FunctionCall):
        return f"FunctionCall {'_'.join(node.name.surface)}"
    if isinstance(node, ast.TryCall):
        return f"TryCall {'_'.join(node.call.name.surface)}"
    if isinstance(node, ast.GetterChain):
        return "GetterChain"
    if isinstance(node, ast.StructCreation):
        return f"StructCreation {'_'.join(node.type_name)}"
    if isinstance(node, ast.Typed):
        return f"Typed : {_fmt_tref(node.type)}"
    if isinstance(node, ast.StructArg):
        suffix = " (shorthand)" if node.value is None else ""
        # field_name to teraz pełen klucz (lemmas, number, gender);
        # dla wydruku użyj samej lemma-tuple.
        lemmas = node.field_name[0] if isinstance(node.field_name[0], tuple) else node.field_name
        return f"StructArg {'_'.join(lemmas)}{suffix}"
    if isinstance(node, ast.Identifier):
        return f"Reference {'_'.join(node.surface)}"
    if isinstance(node, ast.Word):
        parts = ["Word"]
        if node.prep:
            parts.append("_".join(node.prep))
        if isinstance(node.value, ast.Identifier):
            parts.append("_".join(node.value.surface))
        if node.case:
            parts.append(f"({_format_case(node.case)})")
        return " ".join(parts)
    if isinstance(node, ast.Assignment):
        return "Assignment"
    if isinstance(node, ast.IntLit):
        return f"IntLit {node.value}"
    if isinstance(node, ast.StrLit):
        return f"StrLit {node.value!r}"
    if isinstance(node, ast.BoolLit):
        return f"BoolLit {'prawda' if node.value else 'fałsz'}"
    if isinstance(node, ast.BinOp):
        return f"BinOp {node.op}"
    if isinstance(node, ast.UnaryOp):
        return f"UnaryOp {node.op}"
    if isinstance(node, ast.If):
        return "If"
    if isinstance(node, ast.While):
        return "While"
    if isinstance(node, ast.For):
        return "For"
    if isinstance(node, ast.Break):
        return "Break"
    if isinstance(node, ast.Return):
        return "Return"
    if isinstance(node, ast.Not):
        return "Not"
    if isinstance(node, ast.And):
        return "And"
    if isinstance(node, ast.Or):
        return "Or"
    return repr(node)


def _children(node):
    if isinstance(node, ast.Module):
        return node.body
    if isinstance(node, ast.Phrase):
        if node.resolved is not None:
            return _children(node.resolved)
        return []
    if isinstance(node, ast.FunctionCall):
        return []
    if isinstance(node, ast.GetterChain):
        return node.chain
    if isinstance(node, ast.StructCreation):
        return []
    if isinstance(node, ast.Typed):
        return [node.expr]
    if isinstance(node, ast.StructArg):
        return [] if node.value is None else [node.value]
    if isinstance(node, ast.Identifier):
        return []
    if isinstance(node, ast.Word):
        if isinstance(node.value, ast.Identifier):
            return []
        return [node.value]
    if isinstance(node, ast.Assignment):
        return [node.target, node.value]
    if isinstance(node, ast.BinOp):
        return [node.left, node.right]
    if isinstance(node, ast.UnaryOp):
        return [node.operand]
    if isinstance(node, ast.Return):
        return [] if node.value is None else [node.value]
    if isinstance(node, ast.Not):
        return [node.operand]
    if isinstance(node, (ast.And, ast.Or)):
        return [node.left, node.right]
    return []
