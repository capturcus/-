"""Konstrukcja `Identifier` z tokenu morfologicznego.

Identyfikator multi-segment ma postać `[adj/pact/ppas]+ [subst]? [reszta]`.
Każdy segment z adj-readings I subst-readings może być interpretowany na dwa
sposoby — adj-czytanie kontynuuje prefix przymiotnikowy, subst-czytanie
zamyka prefix jako głowa rzeczownikowa.

`_enumerate_variants` produkuje WSZYSTKIE spójne interpretacje (każda z
parą lemma + case). Dispatcher kontekstowy w `expression.py` wybiera ten
wariant, który domyka lokalny konstrukt (struct arg, chain step, fcall slot).

Brak wariantów ≠ błąd identyfikatora — może oznaczać identyfikator funkcji
(verbal segment bez noun-like) lub atom bez form (single letter, single seg
bez analiz). Multi-seg z brakiem valid prefiksu jest błędem syntaktycznym.
"""

import lexer
from morph_anal import canonical, VERB_POS
from ast_nodes import (
    Identifier, IdentifierError, Variant, InterpreterError, ResolveError,
)


_NOUN_LIKE = {"subst", "adj", "pact", "ppas"}
_ADJ_LIKE = ("adj", "pact", "ppas")


def is_prep(token, preps):
    if token is None or token[0] is not lexer.Token.WORD:
        return False
    canon = canonical(token)
    return len(canon) == 1 and canon[0] in preps


def make_identifier(tok):
    _, surface, analyses = tok[0], tok[1], tok[2]
    line = getattr(tok, "line", None)
    analyses_t = tuple(tuple(a) for a in analyses)
    try:
        variants = _enumerate_variants(surface, analyses_t)
    except IdentifierError as e:
        if e.line is None:
            e.line = line
        raise
    return Identifier(
        surface=surface,
        analyses=analyses_t,
        variants=variants,
        line=line,
    )


def _enumerate_variants(surface, analyses):
    """Wszystkie spójne interpretacje identyfikatora.

    Zwraca tuple[Variant, ...]. Wariant niesie (lemmas, case, number,
    gender, rest_length); number/gender pochodzą z subst-głowy (lub
    z adj-głowy w pure-adj variants). Adj-prefiks musi zgadzać się
    z subst-głową w (number, gender) — to zapewnia constraint w backtracku.
    Splittowanie per (lemma, number, gender) sprawia że "kotka" produkuje
    osobne warianty `(kotek, sg, m)` i `(kotka, sg, f)` zamiast jednego
    lemma-only wariantu.

    `rest_length` = liczba passthrough-segmentów po subst-głowie
    (0 dla `[adj+][subst]`, 0 dla pure-adj bez subst, ≥1 gdy po subst
    są jeszcze segmenty doklejane jako reszta).
    Pusta krotka → identyfikator funkcji (verbal-only segment) lub atom
    bez form (single-seg opaque). Multi-seg z brakiem valid prefiksu →
    raise IdentifierError.
    """
    n_segs = len(surface)
    # Step 1: verb-only segment ⇒ identyfikator funkcji, brak wariantów.
    for seg, anas in zip(surface, analyses):
        if not anas or len(seg) == 1:
            continue
        poses = {a.pos for a in anas}
        if poses & VERB_POS and not (poses & _NOUN_LIKE):
            return ()

    # Step 2: per-seg readings — pogrupowane po (lemma, number, gender).
    # Splittowanie po genderach z frozensetu analizy: tag `subst:pl:nom:m1.m2.m3`
    # daje 3 osobne grupy z różnym gender (po normalizacji m1/m2/m3→m
    # zwykle ≤1). Dzięki temu `kotka` (subst:sg:gen:m2 oraz subst:sg:nom:f)
    # rodzi dwie różne grupy (`(kotek, sg, m)` i `(kotka, sg, f)`).
    seg_data = []
    for seg, anas in zip(surface, analyses):
        if len(seg) == 1 or not anas:
            seg_data.append({"opaque": True, "lemma": seg})
            continue
        # Grupa (lemma, num, g) → {cases, specialized}. `specialized` jest
        # True dopóki KAŻDA analiza w grupie ma niepusty SGJP qualifier
        # (`ryb.`, `przest.`, `pot.` itp). Gdy choć jedna jest unqualified
        # (mainstream), grupa staje się mainstream.
        adj_groups = {}
        subst_groups = {}
        for a in anas:
            if not a.case:
                continue
            if a.pos in _ADJ_LIKE:
                target = adj_groups
            elif a.pos == "subst":
                target = subst_groups
            else:
                continue
            is_specialized = bool(a.qualifier)
            genders = a.gender if a.gender else frozenset({None})
            for g in genders:
                key = (a.lemma, a.number, g)
                prev_cases, prev_spec = target.get(key, (frozenset(), True))
                target[key] = (prev_cases | a.case, prev_spec and is_specialized)
        adj_choices = list(adj_groups.items())   # [((lemma, num, g), (cases, spec)), ...]
        subst_choices = list(subst_groups.items())
        # Lemma fallback dla „reszty" (segmenty po subst-głowie) — canonical-style.
        # seg.lower() chroni przed pułapką homograficzną: dla capital surface
        # bez .lower() fallback do pool[0] może wybrać niewłaściwy lemmat
        # (np. "por" zamiast "pora", "marek" zamiast "marka").
        rest_pool = [a for a in anas if a.pos in _ADJ_LIKE] or list(anas)
        rest_lemma = next(
            (a.lemma for a in rest_pool if a.lemma == seg.lower()),
            rest_pool[0].lemma if rest_pool else seg,
        )
        seg_data.append({
            "opaque": False,
            "adj_choices": adj_choices,
            "subst_choices": subst_choices,
            "rest_lemma": rest_lemma,
        })

    # Step 3: backtrack.
    variants = []

    def _cap(lemma, seg):
        if seg and seg[0].isupper() and lemma:
            return lemma[:1].upper() + lemma[1:]
        return lemma

    def _cap_tuple(lemmas):
        return tuple(_cap(l, surface[i]) for i, l in enumerate(lemmas))

    def backtrack(seg_i, lemmas, cases, number, gender, had_subst, subst_at, specialized):
        # number/gender pochodzą z subst-głowy (lub adj-głowy w pure-adj
        # variants). Adj-prefiks NIE narzuca kongruencji — case intersection
        # i tak filtruje większość niespójności, a strict agreement zepsułaby
        # warianty typu `części_mowy` z adj-prefiksem `częsty` (m) + subst
        # `mowa` (f), które dispatcher musi widzieć żeby później rzucić.
        # `specialized` jest True gdy wszystkie wybrane grupy miały SGJP
        # qualifier — to flaguje wariant jako niemainstream (deprio przy
        # ambiguity, ale wciąż produkowany dla downstream resolution).
        if had_subst:
            # Reszta segmentów: passthrough z canonical-style lemma; case bez zmian.
            # number/gender dziedziczone z subst-głowy.
            rest_lemmas = list(lemmas)
            for j in range(seg_i, n_segs):
                d = seg_data[j]
                rest_lemmas.append(d["lemma"] if d["opaque"] else d["rest_lemma"])
            rest_length = n_segs - subst_at - 1
            variants.append(Variant(
                _cap_tuple(rest_lemmas), cases, number, gender, rest_length,
                had_subst=True, specialized=specialized,
            ))
            return
        if seg_i == n_segs:
            # Doszliśmy do końca prefiksu bez subst-głowy. Akceptujemy gdy
            # cases niepuste — to single-seg adj/pact/ppas alone (np.
            # "obserwującego") albo multi-seg z adj-only (rzadkie ale OK).
            # number/gender w tym przypadku z ostatniego adj-segmentu.
            if cases is not None:
                variants.append(Variant(
                    _cap_tuple(lemmas), cases, number, gender, 0,
                    had_subst=False, specialized=specialized,
                ))
            return
        d = seg_data[seg_i]
        if d["opaque"]:
            # Opaque (single-letter lub bez analiz): passthrough, bez wpływu
            # na case/number/gender/specialized.
            backtrack(seg_i + 1, lemmas + [d["lemma"]], cases, number, gender, had_subst, subst_at, specialized)
            return
        # Wariant: adj-czytanie (kontynuuje prefix). Gałąź per (lemma, num, g).
        # Number/gender adj-segmentu propagowane do następnego segmentu — w
        # pure-adj variants posłużą jako finalna kategoria.
        for (adj_lemma, adj_num, adj_g), (adj_cases, adj_spec) in d["adj_choices"]:
            new_cases = adj_cases if cases is None else (cases & adj_cases)
            if new_cases:
                backtrack(
                    seg_i + 1, lemmas + [adj_lemma], new_cases,
                    adj_num, adj_g, had_subst, subst_at,
                    specialized or adj_spec,
                )
        # Wariant: subst-czytanie (zamyka prefix jako głowa). Gałąź per (lemma, num, g).
        # Subst-głowa narzuca finalne (number, gender) wariantu — adj-prefiks
        # już nie ma wpływu (jego (num, g) zostają nadpisane).
        for (subst_lemma, subst_num, subst_g), (subst_cases, subst_spec) in d["subst_choices"]:
            new_cases = subst_cases if cases is None else (cases & subst_cases)
            if new_cases:
                backtrack(
                    seg_i + 1, lemmas + [subst_lemma], new_cases,
                    subst_num, subst_g, had_subst=True, subst_at=seg_i,
                    specialized=specialized or subst_spec,
                )

    backtrack(0, [], None, None, None, False, None, False)

    if not variants:
        # Brak żadnej spójnej interpretacji.
        if n_segs == 1:
            # Single-seg atom — np. interj "och", qub bez noun-like form.
            # Zwracamy () — Identifier.case=None, segments=canonical (jak dotychczas).
            return ()
        # Multi-seg bez valid prefiksu — błąd syntaktyczny.
        raise IdentifierError(_ident_err(
            surface,
            f"pierwszy segment '{surface[0]}' nie jest ani przymiotnikiem, "
            f"ani rzeczownikiem, ani identyfikatorem funkcji",
        ))
    return tuple(variants)


def _ident_err(surface, reason):
    return (
        f"Niepoprawny identyfikator '{'_'.join(surface)}': {reason}. "
        f"Oczekiwana forma: [przymiotnik...] [rzeczownik] [reszta], "
        f"gdzie przymiotniki i rzeczownik zgadzają się w przypadku."
    )


# ---------- rozstrzyganie kanonicznego wariantu (wspólne dla zmiennych / pól / typów) ----------

_CASE_NAMES_LOC = {
    "nom": "mianowniku",
    "gen": "dopełniaczu",
    "dat": "celowniku",
    "acc": "bierniku",
    "inst": "narzędniku",
    "loc": "miejscowniku",
    "voc": "wołaczu",
}


def _prefer_subst(variants):
    """Jeśli istnieje wariant z subst-głową, odrzuć pure-adj variants.

    Pure-adj readings (np. `częsty` dla surface `części`) to typowo
    fałszywi przyjaciele — w Polskim nazwy zmiennych/pól/typów to rzeczowniki,
    nie przymiotniki. Pure-adj pozostają wybierane TYLKO gdy nie ma żadnego
    subst-readingu (np. `obserwującego` jest tylko ppas, brak subst)."""
    subst_variants = [v for v in variants if v.had_subst]
    return subst_variants if subst_variants else variants


def _prefer_mainstream(variants):
    """Preferuj warianty mainstream (specialized=False) nad qualified.

    SGJP oznacza specjalistyczne/regionalne/przestarzałe znaczenia
    qualifierami (np. `wiersza` "ryb."). Fallback do specialized tylko gdy
    nie ma żadnego mainstream-readingu."""
    mainstream = [v for v in variants if not v.specialized]
    return mainstream if mainstream else variants


def _canonical_priority(key):
    """Priorytet wyboru kanonicznego klucza spośród same-lemma wariantów:
    sg m > sg f > sg n > pl m > pl f > pl n (sg m to typowa lemma-citation)."""
    lemmas, number, gender = key
    return (
        number != "sg",
        gender != "m",
        gender != "f",
        gender != "n",
        number or "",
        gender or "",
        lemmas,
    )


def _collapse_same_lemma(keys):
    """Jeśli wszystkie klucze (lemmas, num, gender) mają tę samą lemmę,
    zwróć jeden kanoniczny (preferuje sg m). Inaczej zwróć oryginalne keys.

    Pure-adj surface jak `zebrane` produkuje wiele nom wariantów
    `(zebrany, *, *)` (po splitcie gender-frozensetu) — to ta sama "rzecz"
    (nominalizacja). Subst-only ambiguity (`kotki`: kotek vs kotka) NIE jest
    collapsed — różne lematy oznaczają różne rzeczy."""
    if len(keys) <= 1:
        return keys
    lemmas = {k[0] for k in keys}
    if len(lemmas) == 1:
        return {min(keys, key=_canonical_priority)}
    return keys


def _format_scope_key(key):
    """Czytelny opis klucza (lemmas, number, gender) do komunikatów błędów."""
    lemmas, number, gender = key
    name = "_".join(lemmas)
    parts = [p for p in (number, gender) if p is not None]
    return f"{name} ({', '.join(parts)})" if parts else name


def canonical_identity(ident, *, required_case, label,
                       error_cls=ResolveError, missing_hint=""):
    """Jeden kanoniczny klucz (lemmas, number, gender) z wariantów identyfikatora.

    Wspólny pipeline dla zmiennych, pól i typów: głowa-rzeczownik (rdzeń
    `[przymiotnik*] rzeczownik`) musi być w `required_case`, reszta jest
    passthrough w dowolnym przypadku; przy niejednoznaczności wygrywa rozkład
    z najkrótszą resztą (`rest_length`).

      1. warianty z `required_case in v.case`; pusto → error (brak formy),
      2. _prefer_subst, 3. _prefer_mainstream,
      4. min(rest_length), zostaw remisy,
      5. _collapse_same_lemma nad {(lemmas, number, gender)},
      6. >1 → error (niejednoznaczne); inaczej jedyny klucz.

    `required_case=None` → tryb bezprzypadkowy: nie filtruj po przypadku, użyj
    wszystkich wariantów (argumenty typów parametryzowanych identyfikujemy po
    lemmie, niezależnie od przypadku — `z elementem`, `na wartość`, `dla rzeczy`).

    `label` + `required_case` parametryzują polski komunikat; `error_cls`
    pozwala typom rzucać InterpreterError (faza parse), a zmiennym/polom
    ResolveError (faza resolve). `missing_hint` to opcjonalny suffix komunikatu
    o braku przypadku. Zakłada niepustą `ident.variants` (caller obsługuje atom)."""
    case_name = _CASE_NAMES_LOC.get(required_case, required_case)
    surface = "_".join(ident.surface)
    if required_case is None:
        matching = list(ident.variants)
    else:
        matching = [v for v in ident.variants if required_case in v.case]
    if not matching:
        raise error_cls(
            f"{label} '{surface}' musi być w {case_name}{missing_hint}",
            line=ident.line,
        )
    matching = _prefer_subst(matching)
    matching = _prefer_mainstream(matching)
    min_rest = min(v.rest_length for v in matching)
    keys = _collapse_same_lemma({
        (v.lemmas, v.number, v.gender)
        for v in matching if v.rest_length == min_rest
    })
    if len(keys) > 1:
        opts = ", ".join(sorted(_format_scope_key(k) for k in keys))
        raise error_cls(
            f"{label} '{surface}' jest niejednoznaczna w {case_name} — "
            f"pasuje do wielu opcji: {opts}",
            line=ident.line,
        )
    return next(iter(keys))


def canonical_type(token, *, required_case, label="nazwa typu"):
    """Tożsamość typu (krotka lemm) z tokenu — ta sama logika co dla zmiennych.

    Buduje warianty (`make_identifier`), rozstrzyga `canonical_identity`
    (głowa-rzeczownik w `required_case`, reszta passthrough, min-rest tie-break)
    i rzutuje klucz do samej krotki lemm — liczba/rodzaj nie różnicują typów,
    a deklaracja (gen) i referencja (nom) tego samego typu dają tę samą lemmę.

    Brak wariantów: czysty atom bez analiz (obcy/single-letter token) →
    zachowaj surface; inaczej (czasownik / kształt funkcji, np. `JedzieSamochodem`)
    → błąd, bo nazwa typu musi mieć głowę nominalną."""
    ident = make_identifier(token)
    if ident.variants:
        key = canonical_identity(
            ident, required_case=required_case, label=label,
            error_cls=InterpreterError,
        )
        return key[0]
    if all(not a for a in ident.analyses):
        return tuple(ident.surface)  # obcy/single-letter atom — zachowaj surface
    case_name = _CASE_NAMES_LOC.get(required_case, required_case)
    raise InterpreterError(
        f"{label} '{'_'.join(ident.surface)}' musi zaczynać się rzeczownikiem "
        f"lub przymiotnikiem (w {case_name}); '{ident.surface[0]}' wygląda jak "
        f"identyfikator funkcji",
        line=ident.line,
    )
