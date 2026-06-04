import contextlib, io, re
import lexer, morph_anal, preprocess, parser as parser_mod, expression, typechecker as tc
db, preps = morph_anal.load("../sgjp.tab")
def run(label, src):
    tc.last_type = 0; tc.fun_decls = []; tc.module = None
    try:
        morphs = preprocess.preprocess(morph_anal.analyze(lexer.lex(src), db))
        module = parser_mod.parse(morphs, preps)
        expression.resolve_module(module, preps)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            tc.resolve_module(module)
        out=[]
        for line in buf.getvalue().splitlines():
            m = re.match(r"Identifier\(surface=(\([^)]*\)).*?\)\s+(\S+)\s*$", line)
            if m: out.append(f"{m.group(1)}->{m.group(2)}")
        print(f"[OK] {label}: " + "; ".join(out))
    except Exception as e:
        print(f"[ERR] {label}: {type(e).__name__}: {e}")

run("bare cmp", "aby f:\n    koszt większe od budżet\n")
run("bare arith", "aby f:\n    lewy plus prawy\n")
run("cmp assigned", "aby f:\n    czy to koszt większe od budżet\n")
