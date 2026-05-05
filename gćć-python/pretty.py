import parser


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
    if isinstance(node, parser.FunctionDef):
        groups = []
        if node.params:
            groups.append(("params", node.params))
        groups.append(("body", node.body))
        return groups
    if isinstance(node, parser.StructDef):
        return [("fields", node.fields)]
    if isinstance(node, parser.If):
        groups = [("cond", [node.cond]), ("then", node.then_body)]
        if node.else_body:
            groups.append(("else", node.else_body))
        return groups
    if isinstance(node, parser.While):
        return [("cond", [node.cond]), ("body", node.body)]
    return None


def _label(node):
    if isinstance(node, parser.Module):
        return "Module"
    if isinstance(node, parser.FunctionDef):
        s = f"FunctionDef {'_'.join(node.name)}"
        if node.return_type:
            s += f" -> {'_'.join(node.return_type)}"
        return s
    if isinstance(node, parser.StructDef):
        return f"StructDef {'_'.join(node.name)}"
    if isinstance(node, parser.Field):
        return f"Field {'_'.join(node.name.segments)} : {'_'.join(node.type)}"
    if isinstance(node, parser.Param):
        parts = ["Param"]
        if node.prep:
            parts.append("_".join(node.prep))
        parts.append("_".join(node.name.segments))
        if node.case:
            parts.append(f"({_format_case(node.case)})")
        if node.type:
            parts.append(f": {'_'.join(node.type)}")
        return " ".join(parts)
    if isinstance(node, parser.Phrase):
        return "Phrase"
    if isinstance(node, parser.Word):
        parts = ["Word"]
        if node.prep:
            parts.append("_".join(node.prep))
        if isinstance(node.value, parser.Identifier):
            parts.append("_".join(node.value.segments))
        if node.case:
            parts.append(f"({_format_case(node.case)})")
        return " ".join(parts)
    if isinstance(node, parser.Assignment):
        return "Assignment"
    if isinstance(node, parser.IntLit):
        return f"IntLit {node.value}"
    if isinstance(node, parser.StrLit):
        return f"StrLit {node.value!r}"
    if isinstance(node, parser.BinOp):
        return f"BinOp {node.op}"
    if isinstance(node, parser.UnaryOp):
        return f"UnaryOp {node.op}"
    if isinstance(node, parser.If):
        return "If"
    if isinstance(node, parser.While):
        return "While"
    if isinstance(node, parser.Break):
        return "Break"
    if isinstance(node, parser.Return):
        return "Return"
    if isinstance(node, parser.Not):
        return "Not"
    if isinstance(node, parser.And):
        return "And"
    if isinstance(node, parser.Or):
        return "Or"
    return repr(node)


def _children(node):
    if isinstance(node, parser.Module):
        return node.body
    if isinstance(node, parser.Phrase):
        return node.words
    if isinstance(node, parser.Word):
        if isinstance(node.value, parser.Identifier):
            return []
        return [node.value]
    if isinstance(node, parser.Assignment):
        return [node.target, node.value]
    if isinstance(node, parser.BinOp):
        return [node.left, node.right]
    if isinstance(node, parser.UnaryOp):
        return [node.operand]
    if isinstance(node, parser.Return):
        return [] if node.value is None else [node.value]
    if isinstance(node, parser.Not):
        return [node.operand]
    if isinstance(node, (parser.And, parser.Or)):
        return [node.left, node.right]
    return []
