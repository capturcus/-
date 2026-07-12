# Testy skradzione z suit innych kompilatorów

Scenariusze zachowań systemu typów zaczerpnięte z testów OCamla
(`typing-poly`, `typing-rectypes`, `typing-misc` — m.in. occur check,
monomorfizm parametrów, generalizacja po SCC, currying), Flow
(`refinements`, `recursive_defs`, `match_exhaustive`,
`object_widening`, havoc po wywołaniu), Crystala (semantic: `if`,
`union`, `is_a`, `generic_class`, `closure`, rekurencyjne struktury)
i TypeScriptu (narrowing, excess property check, strictFunctionTypes —
wariancja strzałek w obu kierunkach, strictNullChecks), przepisane na
**oryginalne programy w Ć** — kradzione są pomysły na scenariusze,
nie kod.

Uruchamianie i konwencje plików (`.wynik`, `.błąd`, …): wspólny runner
w katalogu głównym repozytorium — `python3 uruchom_testy.py
test_skradzion` (opis: `-h`).

Znaleziska tej suity (dziura #14 — gaszenie cienia zawężenia, #15 —
`_brak_pola`) są opisane i odhaczone w `nieścisłości_typów.md`.
