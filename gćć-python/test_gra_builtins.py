"""Testy mostka wartości Ć↔Python w gra_builtins — bez otwierania okna.

Nie wymagają pygame: `dobierz_barwę`, budowa struktur zdarzeń i list są
czystym Pythonem, a ścieżka braku pygame jest symulowana przez zatrucie
sys.modules (import daje wtedy ImportError niezależnie od instalacji).
"""

import sys

import pytest

import executor
import gra_builtins as gb


@pytest.fixture(autouse=True)
def sztuczna_przygrywka(monkeypatch):
    """Klucze Ogniwa jak z przygrywki — wystarczą mostkowi list/tekstów."""
    monkeypatch.setattr(executor, "tekst_lista", (
        "Ogniwo", (("głowa",), None, None), (("ogon",), None, None)))


def _tekst(napis):
    return executor._lista_znaków(napis)


def _składowe_barwy(rv):
    assert rv.type == "Barwa"
    return tuple(gb._pole_struktury(rv, skł).value
                 for skł in ("czerwień", "zieleń", "błękit"))


# ---------- dobierz_barwę (czysty Python, bez pygame) ----------

def test_barwa_po_nazwie():
    rv = gb._dobierz_barwę([_tekst("zieleń")])
    assert _składowe_barwy(rv) == (0, 170, 0)


def test_barwa_hex():
    rv = gb._dobierz_barwę([_tekst("#204080")])
    assert _składowe_barwy(rv) == (32, 64, 128)


def test_barwa_nieznana():
    with pytest.raises(RuntimeError, match="nieznana barwa"):
        gb._dobierz_barwę([_tekst("seledyn")])


def test_barwa_zepsuty_hex():
    with pytest.raises(RuntimeError, match="nieznana barwa"):
        gb._dobierz_barwę([_tekst("#zzzzzz")])


# ---------- mostek struktur i list ----------

def test_barwa_na_rgb_obcina_zakres():
    rv = gb._barwa((300, -5, 128))
    assert gb._barwa_na_rgb(rv) == (255, 0, 128)


def test_naciśnięcie_tłumaczy_nazwę_sdl():
    rv = gb._naciśnięcie("left")
    assert rv.type == "Naciśnięcie"
    assert executor._tekst_do_pythona(
        gb._pole_struktury(rv, "klawisz")) == "lewo"


def test_kliknięcie_pola():
    rv = gb._kliknięcie((120, 45), 1)
    assert rv.type == "Kliknięcie"
    assert gb._pole_struktury(rv, "poziom").value == 120
    assert gb._pole_struktury(rv, "pion").value == 45
    assert gb._pole_struktury(rv, "przycisk").value == 1


def test_lista_z_pusta_to_nic():
    assert gb._lista_z([]).type == "Nic"


def test_lista_z_zachowuje_kolejność():
    rv = gb._lista_z([gb._liczba(1), gb._liczba(2)])
    assert rv.type == "Ogniwo"
    głowa = gb._pole_struktury(rv, "głowa")
    ogon = gb._pole_struktury(rv, "ogon")
    assert głowa.value == 1
    assert gb._pole_struktury(ogon, "głowa").value == 2
    assert gb._pole_struktury(ogon, "ogon").type == "Nic"


# ---------- brak pygame ----------

def test_bez_pygame_czytelny_błąd(monkeypatch):
    """Zatruty sys.modules symuluje brak pygame — builtin graficzny ma
    dawać instrukcję instalacji, a nie traceback importu."""
    monkeypatch.setattr(gb, "_pygame", None)
    monkeypatch.setitem(sys.modules, "pygame", None)
    with pytest.raises(RuntimeError, match="pip3 install pygame"):
        gb._wymagaj_pygame()


def test_bez_okna_czytelny_błąd(monkeypatch):
    monkeypatch.setattr(gb, "_ekran", None)
    with pytest.raises(RuntimeError, match="otwórz_okno"):
        gb._wymagaj_okna()
