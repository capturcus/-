"""Testy warstwy morfologicznej — archaizmy (kwalifikatory daw./arch.).

Hasła archaiczne SGJP są domyślnie pomijane (kolidują z żywą polszczyzną —
sztandarowy przykład: dawny rzeczownik „pusta" przechwytujący deklaracje
zmiennych przymiotnikowych, dawny przyimek „miasto"); `--archaizmy`
przywraca je na żądanie. Testy poziomu `load()` chodzą na mini-słowniku
z tmp_path — bez pełnego SGJP."""

import pytest

import morph_anal


@pytest.mark.parametrize("kwalifikatory,archaiczne", [
    ("daw.", True),
    ("arch.", True),
    ("daw.,rzad.", True),
    ("rzad.,daw.", True),
    ("daw.|pot.", True),
    ("daw._dziś_gwar.", True),
    ('arch._(tylko_po_"ku")', True),
    ("archit.", False),   # dziedzinowy, NIE archaizm
    ("przest.", False),   # przestarzałe ≠ dawne — zostaje
    ("pot.", False),
    ("", False),
])
def test_archaiczne_kwalifikatory(kwalifikatory, archaiczne):
    assert morph_anal._archaiczne(kwalifikatory) is archaiczne


_MINI_TAB = (
    "pusta\tpusta\tsubst:sg:nom:f\tnazwa_pospolita\tdaw.\n"
    "pusta\tpusty\tadj:sg:nom.voc:f:pos\tprzymiotnik\t\n"
    "pustej\tpusty\tadj:sg:gen.dat.loc:f:pos\tprzymiotnik\t\n"
    "miasto\tmiasto:P\tprep:gen\tprzyimek\tdaw.\n"
    "miasto\tmiasto\tsubst:sg:nom.acc.voc:n2\tnazwa_pospolita\t\n"
    "dżdżem\tdeszcz\tsubst:sg:inst:m3\tnazwa_pospolita\tdaw.\n"
    "dla\tdla\tprep:gen\tprzyimek\t\n"
)


@pytest.fixture()
def mini_tab(tmp_path):
    path = tmp_path / "mini.tab"
    path.write_text(_MINI_TAB, encoding="utf-8")
    return str(path)


def test_load_pomija_archaizmy(mini_tab):
    """Domyślnie linie daw./arch. nie wchodzą ani do analiz, ani do
    przyimków — „pusta" zostaje przymiotnikiem, „miasto" rzeczownikiem,
    forma wyłącznie archaiczna („dżdżem") znika w całości."""
    db, preps = morph_anal.load(mini_tab)
    assert {a.lemma for a in db["pusta"]} == {"pusty"}
    assert "dżdżem" not in db
    assert "miasto" not in preps
    assert preps == {"dla": {"gen"}}


def test_load_z_archaizmami_zachowuje_wszystko(mini_tab):
    """`archaizmy=True` (tryb --archaizmy oraz migracja do Redisa)
    zachowuje pełny słownik."""
    db, preps = morph_anal.load(mini_tab, archaizmy=True)
    assert {a.lemma for a in db["pusta"]} == {"pusty", "pusta"}
    assert db["dżdżem"][0].lemma == "deszcz"
    assert preps == {"dla": {"gen"}, "miasto": {"gen"}}
