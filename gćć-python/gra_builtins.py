"""Builtiny graficzne (pygame) — tryb natychmiastowy: program otwiera
okno, rysuje kształty w pętli `dopóki pokaż_klatkę:` i odpytuje wejście.
Sygnatury `można` i typy (Barwa, Wydarzenie) deklaruje `biblioteki/gra.ć`.

pygame importowany LENIWIE, przy pierwszym wywołaniu builtinu graficznego
— interpreter (i wszystkie programy bez gra.ć) działa bez zainstalowanego
pygame. Ten moduł na poziomie importu nie dotyka ani pygame, ani atrybutów
executora (import cykliczny executor↔gra_builtins jest bezpieczny, bo
wszystkie odwołania są w ciałach funkcji, wykonywanych w runtime).

`pokaż_klatkę` robi całą obsługę klatki naraz: flip, tick(60), pompowanie
kolejki zdarzeń do bufora (dla `pobierz_wydarzenia`) i auto-czyszczenie
ekranu pod następną klatkę. Zamknięcie okna krzyżykiem daje `fałsz`, więc
szkielet gry `dopóki pokaż_klatkę:` nigdy nie zawiesza okna.
"""

import ast_nodes as ast

_pygame = None      # moduł pygame po leniwym imporcie
_ekran = None       # Surface głównego okna (None = okno nieotwarte)
_zegar = None       # pygame.time.Clock
_zamknięte = False  # okno zamknięte krzyżykiem — rysowanie staje się no-opem
_wydarzenia = []    # bufor zdarzeń Ć (RuntimeValue) z ostatniej klatki
_duszki = {}        # cache: ścieżka → Surface
_czcionki = {}      # cache: rozmiar → Font

# 30 zamiast typowych 60 — tree-walker nie wyrabia dużych budżetów
# na klatkę, a przy 30 animacja wciąż wygląda płynnie.
KLATKI_NA_SEKUNDĘ = 30

# Polskie nazwy klawiszy → nazwy SDL; pozostałe nazwy (litery, cyfry)
# przechodzą bez tłumaczenia. Odwrotna mapa tłumaczy zdarzenia.
_KLAWISZE = {
    "lewo": "left", "prawo": "right", "góra": "up", "dół": "down",
    "spacja": "space", "enter": "return", "wyjście": "escape",
}
_KLAWISZE_ODWROTNE = {v: k for k, v in _KLAWISZE.items()}

# Nazwy barw dla `dobierz_barwę` (rzeczowniki, jak pola Barwy).
_BARWY = {
    "czerń": (0, 0, 0), "biel": (255, 255, 255), "szarość": (128, 128, 128),
    "czerwień": (255, 0, 0), "zieleń": (0, 170, 0), "błękit": (40, 120, 255),
    "żółć": (255, 210, 0), "pomarańcz": (255, 140, 0),
    "fiolet": (150, 60, 220), "róż": (255, 105, 180), "brąz": (140, 90, 40),
}


def _wymagaj_pygame():
    global _pygame
    if _pygame is None:
        import os
        # Banner powitalny pygame szedłby na stdout programu Ć.
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        try:
            import pygame
        except ImportError:
            # pygame-ce, nie pygame: klasyczny pakiet nie publikuje wheeli
            # dla świeżych Pythonów i buduje się ze źródeł bez SDL_ttf
            # oraz SDL_image (brak napisów i duszków PNG).
            raise RuntimeError(
                "builtiny graficzne wymagają biblioteki pygame — "
                "zainstaluj: pip3 install pygame-ce")
        _pygame = pygame
    return _pygame


def _wymagaj_okna():
    pg = _wymagaj_pygame()
    if _ekran is None:
        raise RuntimeError(
            "brak otwartego okna — najpierw wywołaj 'otwórz_okno "
            "o szerokości ... o wysokości ... z tytułem ...'")
    return pg


# ---------- mostek wartości Ć ↔ Python ----------

def _atom(lemma):
    """Klucz pola w formie atomowej — `scope_key_matches` dopasuje go
    do każdego odczytu po samej lemmie (jak w `_sukces`/`_błąd`)."""
    return ((lemma,), None, None)


def _nic():
    return executor.RuntimeValue(value=None, type="Nic")


def _pole_struktury(rv, lemma):
    for klucz, wartość in rv.value.items():
        if ast.scope_key_matches(_atom(lemma), klucz):
            return wartość
    raise RuntimeError(f"struktura '{rv.type}' nie ma pola '{lemma}'")


def _barwa_na_rgb(rv):
    """Struktura Barwa (czerwień/zieleń/błękit) → krotka RGB z obcięciem
    do zakresu 0–255."""
    return tuple(
        max(0, min(255, _pole_struktury(rv, skł).value))
        for skł in ("czerwień", "zieleń", "błękit")
    )


def _barwa(rgb):
    czerwień, zieleń, błękit = rgb
    return executor.RuntimeValue(value={
        _atom("czerwień"): executor.RuntimeValue(value=czerwień, type="Liczba"),
        _atom("zieleń"): executor.RuntimeValue(value=zieleń, type="Liczba"),
        _atom("błękit"): executor.RuntimeValue(value=błękit, type="Liczba"),
    }, type="Barwa")


def _liczba(n):
    return executor.RuntimeValue(value=n, type="Liczba")


def _lista_z(wartości):
    """Lista Ć z pythonowej listy RuntimeValue — łańcuch Ogniw po kluczach
    z przygrywki (gra.ć włącza przygrywkę, więc `tekst_lista` jest ustawione)."""
    if executor.tekst_lista is None:
        raise RuntimeError("budowa listy wymaga przygrywki (uwzględnij gra.ć)")
    ogniwo, klucz_głowy, klucz_ogona = executor.tekst_lista
    wynik = _nic()
    for w in reversed(wartości):
        wynik = executor.RuntimeValue(
            value={klucz_głowy: w, klucz_ogona: wynik}, type=ogniwo)
    return wynik


# ---------- zdarzenia jako struktury Ć ----------

def _naciśnięcie(nazwa_sdl):
    nazwa = _KLAWISZE_ODWROTNE.get(nazwa_sdl, nazwa_sdl)
    return executor.RuntimeValue(value={
        _atom("klawisz"): executor._lista_znaków(nazwa),
    }, type="Naciśnięcie")


def _kliknięcie(pozycja, przycisk):
    return executor.RuntimeValue(value={
        _atom("poziom"): _liczba(pozycja[0]),
        _atom("pion"): _liczba(pozycja[1]),
        _atom("przycisk"): _liczba(przycisk),
    }, type="Kliknięcie")


def _ruch(pozycja):
    return executor.RuntimeValue(value={
        _atom("poziom"): _liczba(pozycja[0]),
        _atom("pion"): _liczba(pozycja[1]),
    }, type="Ruch")


# ---------- builtiny ----------

def _otwórz_okno(args):
    global _ekran, _zegar, _zamknięte
    pg = _wymagaj_pygame()
    szerokość, wysokość = args[0].value, args[1].value
    tytuł = executor._tekst_do_pythona(args[2]) or ""
    pg.display.init()
    pg.font.init()
    _ekran = pg.display.set_mode((szerokość, wysokość))
    pg.display.set_caption(tytuł)
    _zegar = pg.time.Clock()
    _zamknięte = False
    _ekran.fill((0, 0, 0))
    return _nic()


def _pokaż_klatkę(args):
    global _zamknięte
    pg = _wymagaj_okna()
    if _zamknięte:
        return executor.RuntimeValue(value=False, type="Przełącznik")
    pg.display.flip()
    _zegar.tick(KLATKI_NA_SEKUNDĘ)
    _wydarzenia.clear()
    for zdarzenie in pg.event.get():
        if zdarzenie.type == pg.QUIT:
            _zamknięte = True
        elif zdarzenie.type == pg.KEYDOWN:
            _wydarzenia.append(_naciśnięcie(pg.key.name(zdarzenie.key)))
        elif zdarzenie.type == pg.MOUSEBUTTONDOWN:
            _wydarzenia.append(_kliknięcie(zdarzenie.pos, zdarzenie.button))
        elif zdarzenie.type == pg.MOUSEMOTION:
            _wydarzenia.append(_ruch(zdarzenie.pos))
    if _zamknięte:
        pg.display.quit()
        return executor.RuntimeValue(value=False, type="Przełącznik")
    _ekran.fill((0, 0, 0))  # czysta powierzchnia pod następną klatkę
    return executor.RuntimeValue(value=True, type="Przełącznik")


def _rysuj(args, rysunek):
    """Wspólna otoczka rysowania: wymaga okna, a po zamknięciu okna jest
    no-opem (program może jeszcze wykonać instrukcje po ostatniej klatce)."""
    _wymagaj_okna()
    if not _zamknięte:
        rysunek()
    return _nic()


def _narysuj_koło(args):
    def rysunek():
        lewa, góra, promień = (a.value for a in args[:3])
        _pygame.draw.circle(
            _ekran, _barwa_na_rgb(args[3]), (lewa, góra), promień)
    return _rysuj(args, rysunek)


def _narysuj_prostokąt(args):
    def rysunek():
        lewa, góra, szerokość, wysokość = (a.value for a in args[:4])
        _pygame.draw.rect(
            _ekran, _barwa_na_rgb(args[4]),
            _pygame.Rect(lewa, góra, szerokość, wysokość))
    return _rysuj(args, rysunek)


def _narysuj_napis(args):
    def rysunek():
        treść = executor._tekst_do_pythona(args[0]) or ""
        lewa, góra, rozmiar = (a.value for a in args[1:4])
        if rozmiar not in _czcionki:
            _czcionki[rozmiar] = _pygame.font.SysFont(None, rozmiar)
        obraz = _czcionki[rozmiar].render(treść, True, _barwa_na_rgb(args[4]))
        _ekran.blit(obraz, (lewa, góra))
    return _rysuj(args, rysunek)


def _narysuj_duszka(args):
    def rysunek():
        ścieżka = executor._tekst_do_pythona(args[0])
        lewa, góra = args[1].value, args[2].value
        if ścieżka not in _duszki:
            try:
                _duszki[ścieżka] = _pygame.image.load(ścieżka).convert_alpha()
            except (OSError, _pygame.error) as e:
                raise RuntimeError(
                    f"nie można wczytać duszka '{ścieżka}': {e}")
        _ekran.blit(_duszki[ścieżka], (lewa, góra))
    return _rysuj(args, rysunek)


def _dobierz_barwę(args):
    """Barwa po polskiej nazwie albo w zapisie \"#RRGGBB\" — czysty Python,
    działa bez pygame (i bez okna)."""
    nazwa = executor._tekst_do_pythona(args[0]) or ""
    if nazwa in _BARWY:
        return _barwa(_BARWY[nazwa])
    if nazwa.startswith("#") and len(nazwa) == 7:
        try:
            return _barwa(tuple(int(nazwa[i:i + 2], 16) for i in (1, 3, 5)))
        except ValueError:
            pass
    raise RuntimeError(
        f"nieznana barwa '{nazwa}' — dostępne: "
        f"{', '.join(sorted(_BARWY))} albo zapis \"#RRGGBB\"")


def _zbadaj_klawisz(args):
    pg = _wymagaj_okna()
    nazwa = executor._tekst_do_pythona(args[0]) or ""
    try:
        kod = pg.key.key_code(_KLAWISZE.get(nazwa, nazwa))
    except ValueError:
        polskie = ", ".join(sorted(_KLAWISZE))
        raise RuntimeError(
            f"nieznany klawisz '{nazwa}' — użyj nazwy polskiej ({polskie}), "
            f"litery, cyfry albo nazwy SDL")
    if _zamknięte:
        return executor.RuntimeValue(value=False, type="Przełącznik")
    return executor.RuntimeValue(
        value=bool(pg.key.get_pressed()[kod]), type="Przełącznik")


def _pobierz_wydarzenia(args):
    _wymagaj_okna()
    return _lista_z(list(_wydarzenia))


BUILTIN_FUNCTIONS = [
    ([("otworzyć", "okno")], _otwórz_okno),
    ([("pokazać", "klatka")], _pokaż_klatkę),
    ([("narysować", "koło")], _narysuj_koło),
    ([("narysować", "prostokąt")], _narysuj_prostokąt),
    ([("narysować", "napis")], _narysuj_napis),
    ([("narysować", "duszek")], _narysuj_duszka),
    ([("dobrać", "barwa")], _dobierz_barwę),
    ([("zbadać", "klawisz")], _zbadaj_klawisz),
    ([("pobrać", "wydarzenie")], _pobierz_wydarzenia),
]

# Import na KOŃCU modułu: funkcje wyżej sięgają do `executor.…` dopiero
# w runtime, a dzięki tej pozycji import działa w obu kierunkach cyklu
# executor↔gra_builtins (executor widzi już zdefiniowane BUILTIN_FUNCTIONS,
# gdy sam jest importowany jako pierwszy przez ten moduł).
import executor
