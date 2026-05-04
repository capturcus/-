import parser


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
        params = ", ".join(".".join(p) for p in node.params)
        return f"FunctionDef {'_'.join(node.name)}({params})"
    if isinstance(node, parser.Assignment):
        return f"Assignment ← {'.'.join(node.target)}"
    if isinstance(node, parser.IntLit):
        return f"IntLit {node.value}"
    if isinstance(node, parser.StrLit):
        return f"StrLit {node.value!r}"
    if isinstance(node, parser.Var):
        return f"Var {'_'.join(node.name)}"
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
    return repr(node)


def _children(node):
    if isinstance(node, parser.Module):
        return node.body
    if isinstance(node, parser.FunctionDef):
        return node.body
    if isinstance(node, parser.Assignment):
        return [node.value]
    if isinstance(node, parser.BinOp):
        return [node.left, node.right]
    if isinstance(node, parser.UnaryOp):
        return [node.operand]
    return []
