"""Współdzielone fixturki sesyjne dla całego zestawu testów.

SGJP (`sgjp.tab`, ~5M form) ładuje się ~8–13s. Wcześniej każdy moduł testowy
definiował własną `loaded`/`db`/`preps` — `scope="session"` deduplikuje tylko
w obrębie jednego modułu, więc SGJP ładował się raz NA MODUŁ (5×). Tutaj jedna
sesyjna fixturka współdzielona przez wszystkie moduły → SGJP ładuje się RAZ."""

import os

import pytest

import morph_anal
import typechecker

# Tryb deweloperski typecheckera: poszlaka zapisana pod notą ogólną
# (ścieżka bez własnego _set_note) = głośny AssertionError. Testy wymuszają
# kompletność not; zwykłe uruchomienia gćć.py degradują się do ogólnika.
typechecker._wymuś_noty = True

SGJP_PATH = os.path.join(os.path.dirname(__file__), "..", "sgjp.tab")


@pytest.fixture(scope="session")
def loaded():
    return morph_anal.load(SGJP_PATH)


@pytest.fixture(scope="session")
def db(loaded):
    return loaded[0]


@pytest.fixture(scope="session")
def preps(loaded):
    return loaded[1]
