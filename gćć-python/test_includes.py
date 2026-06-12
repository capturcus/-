"""Testy passu 0 — scalanie plików dyrektywą `uwzględnij` (includes.py).

Pass jest czysto tekstowy (bez SGJP), więc testy jednostkowe chodzą na
plikach tymczasowych. Na końcu dwa testy integracyjne: scalony program
przechodzi pełny pipeline, a deduplikacja diamentu faktycznie ratuje
przed błędem zduplikowanych deklaracji.
"""

import os
import unicodedata

import pytest

import includes
import lexer
import morph_anal
import preprocess
import parser as parser_mod
import expression
from ast_nodes import InterpreterError


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ---------- parse_directive ----------

def test_directive_parsing():
    assert includes.parse_directive("uwzględnij pojemniki.ć") == "pojemniki.ć"
    assert includes.parse_directive("uwzględnij  biblioteki/napisy.ć  ") == "biblioteki/napisy.ć"
    assert includes.parse_directive("  uwzględnij pojemniki.ć") is None  # nie od kolumny 0
    assert includes.parse_directive("uwzględnijmy pojemniki.ć") is None  # to nie dyrektywa
    assert includes.parse_directive("uwzględnij") is None                # brak ścieżki
    assert includes.parse_directive("x to uwzględnij") is None


def test_directive_parsing_nfd_source():
    """Treść pliku w NFD (zdarza się po niektórych edytorach/wklejkach)."""
    nfd = unicodedata.normalize("NFD", "uwzględnij pojemniki.ć")
    assert includes.parse_directive(nfd) == "pojemniki.ć"


# ---------- scalanie ----------

def test_simple_include_inlines_content(tmp_path):
    _write(f"{tmp_path}/biblioteka.ć", "aby pomagać komuś:\n    zwróć coś\n")
    _write(f"{tmp_path}/główny.ć",
           "uwzględnij biblioteka.ć\n\naby działać:\n    zwróć\n")
    merged = includes.resolve(f"{tmp_path}/główny.ć").text
    assert "aby pomagać komuś:" in merged
    assert "uwzględnij" not in merged
    # zawartość wchodzi w miejscu dyrektywy — przed resztą programu
    assert merged.index("pomagać") < merged.index("działać")


def test_nested_includes(tmp_path):
    _write(f"{tmp_path}/c.ć", "# poziom C\n")
    _write(f"{tmp_path}/b.ć", "uwzględnij c.ć\n# poziom B\n")
    _write(f"{tmp_path}/a.ć", "uwzględnij b.ć\n# poziom A\n")
    merged = includes.resolve(f"{tmp_path}/a.ć").text
    assert merged.index("poziom C") < merged.index("poziom B") < merged.index("poziom A")


def test_diamond_includes_once(tmp_path):
    """a→b→d oraz a→c→d: deklaracje z d dokładnie raz."""
    _write(f"{tmp_path}/d.ć", "# wspólna baza\n")
    _write(f"{tmp_path}/b.ć", "uwzględnij d.ć\n# b\n")
    _write(f"{tmp_path}/c.ć", "uwzględnij d.ć\n# c\n")
    _write(f"{tmp_path}/a.ć", "uwzględnij b.ć\nuwzględnij c.ć\n")
    merged = includes.resolve(f"{tmp_path}/a.ć").text
    assert merged.count("wspólna baza") == 1
    assert "# b" in merged and "# c" in merged


def test_direct_duplicate_include(tmp_path):
    _write(f"{tmp_path}/d.ć", "# baza\n")
    _write(f"{tmp_path}/a.ć", "uwzględnij d.ć\nuwzględnij d.ć\n")
    assert includes.resolve(f"{tmp_path}/a.ć").text.count("# baza") == 1


def test_cycle_terminates(tmp_path):
    _write(f"{tmp_path}/a.ć", "uwzględnij b.ć\n# treść a\n")
    _write(f"{tmp_path}/b.ć", "uwzględnij a.ć\n# treść b\n")
    merged = includes.resolve(f"{tmp_path}/a.ć").text
    assert merged.count("treść a") == 1
    assert merged.count("treść b") == 1


def test_paths_relative_to_including_file(tmp_path):
    """b.ć w podkatalogu uwzględnia c.ć ze SWOJEGO katalogu."""
    _write(f"{tmp_path}/pod/c.ć", "# sąsiad b\n")
    _write(f"{tmp_path}/pod/b.ć", "uwzględnij c.ć\n")
    _write(f"{tmp_path}/a.ć", "uwzględnij pod/b.ć\n")
    assert "# sąsiad b" in includes.resolve(f"{tmp_path}/a.ć").text


def test_dedup_across_nfc_nfd_paths(tmp_path):
    """Ten sam plik raz przez ścieżkę NFC, raz NFD — jeden wpis."""
    name_nfc = "wspólna.ć"
    name_nfd = unicodedata.normalize("NFD", name_nfc)
    _write(f"{tmp_path}/{name_nfc}", "# jedna baza\n")
    _write(f"{tmp_path}/a.ć",
           f"uwzględnij {name_nfc}\nuwzględnij {name_nfd}\n")
    assert includes.resolve(f"{tmp_path}/a.ć").text.count("# jedna baza") == 1


def test_missing_include_raises_with_location(tmp_path):
    _write(f"{tmp_path}/a.ć", "# coś\nuwzględnij nie_ma.ć\n")
    with pytest.raises(InterpreterError) as ei:
        includes.resolve(f"{tmp_path}/a.ć")
    msg = str(ei.value)
    assert "nie_ma.ć" in msg
    assert "linia 2" in msg


def test_stdin_variant_resolves_from_cwd(tmp_path, monkeypatch):
    _write(f"{tmp_path}/baza.ć", "# z bieżącego katalogu\n")
    monkeypatch.chdir(tmp_path)
    merged = includes.resolve_stdin("uwzględnij baza.ć\n# main\n").text
    assert "# z bieżącego katalogu" in merged


# ---------- integracja: scalony program przechodzi pipeline ----------

# SGJP (db) i preps pochodzą ze współdzielonej fixturki w conftest.py.

def _pipeline(text, preps, db):
    morphs = preprocess.preprocess(morph_anal.analyze(lexer.lex(text), db))
    module = parser_mod.parse(morphs, preps)
    expression.resolve_module(module, preps)
    return module


_POJEMNIKI = (
    "definicja Węzła z elementem:\n"
    "    głowa (element)\n"
    "    ogon (Lista)\n"
    "\n"
    "definicja PustejListy:\n"
    "    znacznik (Liczba)\n"
    "\n"
    "Lista to Węzeł albo PustaLista\n"
    "\n"
    "aby doczepiać element do listy:\n"
    "    zwróć Węzeł o głowie element o ogonie lista\n"
)


@pytest.mark.integration
def test_merged_program_passes_pipeline(tmp_path, db, preps):
    _write(f"{tmp_path}/pojemniki.ć", _POJEMNIKI)
    _write(f"{tmp_path}/główny.ć", (
        "uwzględnij pojemniki.ć\n"
        "\n"
        "aby działać:\n"
        "    lista to doczepiaj jeden do (PustaLista o znaczniku zero)\n"
    ))
    module = _pipeline(includes.resolve(f"{tmp_path}/główny.ć").text, preps, db)
    names = ["_".join(getattr(d, "name").surface)
             for d in module.body if hasattr(d, "name")
             and hasattr(getattr(d, "name"), "surface")]
    assert "doczepiać" in names and "działać" in names


@pytest.mark.integration
def test_diamond_dedup_avoids_duplicate_declarations(tmp_path, db, preps):
    """Bez deduplikacji `Węzeł` z pojemników wszedłby dwa razy i resolver
    zgłosiłby duplikat deklaracji."""
    _write(f"{tmp_path}/pojemniki.ć", _POJEMNIKI)
    _write(f"{tmp_path}/napisy.ć",
           "uwzględnij pojemniki.ć\n"
           "można skleić tekst (Tekst) z drugim (Tekst) -> Tekst\n")
    _write(f"{tmp_path}/kolejki.ć",
           "uwzględnij pojemniki.ć\n"
           "aby opróżniać listę:\n"
           "    zwróć PustaLista o znaczniku zero\n")
    _write(f"{tmp_path}/główny.ć", (
        "uwzględnij napisy.ć\n"
        "uwzględnij kolejki.ć\n"
        "\n"
        "aby działać:\n"
        "    pusta to opróżniaj (Węzeł o głowie jeden o ogonie (PustaLista o znaczniku zero))\n"
    ))
    _pipeline(includes.resolve(f"{tmp_path}/główny.ć").text, preps, db)  # nie rzuca


# ---------- mapa pochodzenia linii ----------

def test_origin_maps_merged_lines_to_source_files(tmp_path):
    _write(f"{tmp_path}/lib.ć", "# lib 1\n# lib 2\n# lib 3\n")
    _write(f"{tmp_path}/główny.ć",
           "# main 1\nuwzględnij lib.ć\n# main 3\n# main 4\n")
    sc = includes.resolve(f"{tmp_path}/główny.ć")
    lines = sc.text.splitlines()
    # scalony: main1, lib1, lib2, lib3, main3, main4
    assert lines[0] == "# main 1" and sc.origin(1) == (f"{tmp_path}/główny.ć", 1)
    assert lines[1] == "# lib 1" and sc.origin(2) == (f"{tmp_path}/lib.ć", 1)
    assert lines[3] == "# lib 3" and sc.origin(4) == (f"{tmp_path}/lib.ć", 3)
    # linia główna PO dyrektywie: scalony nr 5, oryginalny nr 3
    assert lines[4] == "# main 3" and sc.origin(5) == (f"{tmp_path}/główny.ć", 3)
    assert sc.origin(None) is None
    assert sc.origin(99) is None


def test_origin_for_nested_include(tmp_path):
    _write(f"{tmp_path}/pod/c.ć", "# w c\n")
    _write(f"{tmp_path}/pod/b.ć", "uwzględnij c.ć\n# w b\n")
    _write(f"{tmp_path}/a.ć", "uwzględnij pod/b.ć\n# w a\n")
    sc = includes.resolve(f"{tmp_path}/a.ć")
    by_text = {line: sc.origin(i + 1) for i, line in enumerate(sc.text.splitlines())}
    assert by_text["# w c"] == (f"{tmp_path}/pod/c.ć", 1)
    assert by_text["# w b"] == (f"{tmp_path}/pod/b.ć", 2)
    assert by_text["# w a"] == (f"{tmp_path}/a.ć", 2)


def test_translate_rewrites_embedded_line_refs(tmp_path):
    _write(f"{tmp_path}/lib.ć", "# lib 1\n# lib 2\n")
    _write(f"{tmp_path}/główny.ć", "uwzględnij lib.ć\n# main 2\n")
    sc = includes.resolve(f"{tmp_path}/główny.ć")
    główny = f"{tmp_path}/główny.ć"
    # scalona linia 3 = główny.ć:2 (ten sam plik → bez dopisku)
    assert sc.translate("konflikt w linii 3", główny) == "konflikt w linii 2"
    # scalona linia 1 = lib.ć:1 (inny plik → dopisek)
    assert sc.translate("(linia 1)", główny) == f"(linia 1 w {tmp_path}/lib.ć)"
    # bez wzorca / poza zakresem — nietknięte
    assert sc.translate("zwykły tekst", główny) == "zwykły tekst"
    assert sc.translate("linia 999", główny) == "linia 999"


def test_print_error_reports_original_file_and_line(tmp_path, capsys):
    """End-to-end przez gćć._print_error: błąd w linii scalonej wskazuje
    oryginalny plik i numer."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("gcc_cli", "gćć.py")
    gcc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gcc)

    _write(f"{tmp_path}/lib.ć", "# lib 1\n# lib 2\n# lib 3\n")
    _write(f"{tmp_path}/główny.ć", "uwzględnij lib.ć\n# main 2\nzepsuta linia\n")
    sc = includes.resolve(f"{tmp_path}/główny.ć")
    # scalony: lib1, lib2, lib3, "# main 2", "zepsuta linia"
    # → "zepsuta linia" to scalona 5, oryginalna główny.ć:3
    err = InterpreterError("coś poszło źle (linia 2)", line=5)
    gcc._print_error(f"{tmp_path}/główny.ć", sc.text, err, sc)
    stderr = capsys.readouterr().err
    assert f"{tmp_path}/główny.ć:3:" in stderr          # nagłówek: oryginalna linia
    assert f"linia 2 w {tmp_path}/lib.ć" in stderr      # embedded ref: inny plik
    assert "zepsuta linia" in stderr                    # snippet: właściwa treść
    assert "|   3 |" in stderr                          # ramka: oryginalny numer
