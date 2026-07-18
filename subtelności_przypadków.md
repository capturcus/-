# Subtelności nośników przypadka — odkrycia z implementacji

Zjawiska odkryte podczas wdrażania zasady „każdy argument niesie
przypadek" (słowa `wynik` i `literał`) oraz ujednolicenia rozstrzygania
(zawężenie po scope + krok imienny + koniec pozycyjności poza
bliźniakami; 2026-07-18). Każdy przykład był uruchomiony na
interpreterze — wyjścia i komunikaty są autentyczne.

---

## 0. Model rozstrzygania (wspólny dla rozkaźnika i `wynik`)

1. **Zawężenie po scope** — słowo argumentu czyta się tylko odczytami
   istniejących zmiennych.
2. **Krok imienny** — argument będący dosłownie nazwą parametru wiąże
   jego slot (gdy gramatyka pozwala).
3. **Eliminacja po (przyimku, przypadku)** — reszta zajmuje sloty
   jednoznaczne.
4. Pozycyjnie tylko **bliźniaki** (ta sama para przyimek+przypadek po
   zawężeniu rządem przyimka); inaczej głośny remis.

---

## 1. Scope i krok imienny kontra remis nominalizacyjny

Pod `wynik` dopełnienie bliższe przesuwa się do dopełniacza, więc przy
dwóch gołych slotach dopełniacz czyta się na oba sposoby. O tym, czy to
remis, decyduje SCOPE i nazwy parametrów:

```
aby uczyć dziecko muzyki:
    zwróć dziecko

aby działać:
    dziecko to "Jaś"
    muzyka to "gama"
    wypisz wynik uczenia dziecka muzyki      # → Jaś  (rozstrzygnięte!)
```

Słowo `muzyki` przy jedynej zmiennej `muzyka` to jej dopełniacz
(odczyt mnogi nie istnieje w scope), a `dziecka`/`muzyki` są dosłownie
nazwami parametrów `uczyć` — krok imienny wiąże sloty jednoznacznie.

Gdy zmienne NIE są nazwami parametrów, dwuznaczność nominalizacji jest
realna i głośna:

```
    uczeń to "Jaś"
    gama to "gama"
    wypisz wynik uczenia ucznia gamy         # ← remis
```

```
BłądRezolucji: niejednoznaczny argument 'ucznia' w wywołaniu 'uczenia' — pasuje do
RÓŻNYCH slotów: `dziecko` (biernik|mianownik|wołacz), `muzyki`
(biernik|dopełniacz|mianownik|wołacz) (pod nominalizacją dopełniacz czyta się też jako
przesunięte dopełnienie bliższe (goły slot biernikowy)); pozycyjnie rozstrzygają się
wyłącznie sloty nierozróżnialne
rozstrzygnij:
  • nazwij zmienną tak jak parametr slotu — słowo będące nazwą parametru wiąże jego slot
  • wyabstrahuj wywołanie do zmiennej rozkaźnikiem i przekaż zmienną
  • albo daj parametrom 'uczenia' rozróżnialne przyimki/przypadki w sygnaturze
```

W wypisanych slotach widać, że slot `muzyki` zawiera biernik
i mianownik, choć w sygnaturze stoi jako dopełniacz — „muzyki" to
morfologicznie także mianownik/biernik liczby mnogiej (kolizja
gen-lp = nom-lm po stronie *sygnatury*). Dlatego forma biernikowa nie
rozstrzyga po przypadku i recept trzeba szukać w nazwach, rozkaźniku
przez zmienną albo w przyimku w sygnaturze (wszystkie zweryfikowane:
`aby uczyć dziecko do muzyki` → `wynik uczenia dziecka do muzyki` → Jaś).

**Remis wariantowy**: gdy w scope są `muzyka` I `muzyki`, słowo
`muzyki` czyta się jako dwie różne zmienne — wybór zmiennej to wybór
wartości, więc błąd jest natychmiastowy:

```
    muzyka to "gama"
    muzyki to "pasaż"
    wypisz wynik uczenia dziecka muzyki      # ← remis wariantowy
```

```
BłądRezolucji: niejednoznaczny argument 'muzyki' w wywołaniu 'uczenia' — słowo czyta
się jako różne zmienne:
  • zmienna 'muzyka (pl, f)' (biernik|mianownik|wołacz)
  • zmienna 'muzyka (sg, f)' (dopełniacz)
rozstrzygnij: zmień nazwę jednej ze zmiennych — kolizja odmian (dopełniacz lp =
mianownik lm) jest nieusuwalna z polszczyzny
```

---

## 2. Sloty-bliźniaki liczone po przypadku EFEKTYWNYM (∩ rząd przyimka)

Fallback pozycyjny jest legalny tylko między slotami nierozróżnialnymi.
Nierozróżnialność trzeba liczyć po przypadku efektywnym = przypadek
slotu ∩ rząd przyimka, nie po surowych zbiorach morfologicznych:

```
aby rysować od lewej od góry:
    wypisz lewa
    wypisz góra

aby działać:
    rysuj od dziesięciu od dwudziestu        # → 10, 20 (pozycyjnie, legalnie)
```

| slot        | surowe przypadki formy   | ∩ rząd „od" (gen) |
|-------------|--------------------------|--------------------|
| `od lewej`  | dat, gen, loc            | **{gen}**          |
| `od góry`   | acc, gen, nom, voc       | **{gen}**          |

Po surowych zbiorach sloty „różnią się" i dwa bezprzypadkowe liczebniki
dostawałyby fałszywy remis — tak wybuchła `grafika.ć` w trakcie
implementacji. Przyimek „od" rządzi wyłącznie dopełniaczem, więc
gramatycznie oba sloty są nieodróżnialne — o kolejności słusznie
decyduje pozycja, jak w naturalnej polszczyźnie. Implementacja:
`_eff_slot` w `expression._match_args_to_slots`.

---

## 3. Eliminacja i krok imienny często czynią `literał` zbędnym

Goły literał kandyduje do wielu slotów, ale inne argumenty go
rozstrzygają:

```
aby zawieźć pasażera transportem do celu: …

zawieź "samochód" psa do domu            # → pies / samochód / dom (bez literału!)
```

„psa" pasuje wyłącznie do `pasażera`, „do domu" pinuje `do celu` —
literałowi zostaje jeden slot. Podobnie krok imienny: w `wybierz
prawda kota psa` argumenty `kota`/`psa` są nazwami parametrów, więc
wiążą swoje sloty, a `prawda` dostaje ostatni wolny.

`literał` jest potrzebny dopiero, gdy nic nie rozstrzyga — zmienne nie
są nazwami parametrów i same są wieloznaczne:

```
aby wybrać flagę kota psa:
    jeśli flaga:
        zwróć kot
    zwróć pies

aby działać:
    zwierzak to Kot o imieniu "Mruczek"
    przybłęda to Pies o kości "szynka"
    pupil to wybierz prawda zwierzaka przybłędy     # ← błąd
```

```
BłądRezolucji: goły literał '(wyrażenie)' w wywołaniu 'wybierz' pasuje do RÓŻNYCH
slotów: `flagę` (biernik), `kota` (biernik|dopełniacz|mianownik), `psa`
(biernik|dopełniacz) — literał jest nieodmienny, więc o slocie nie rozstrzyga przypadek
nadaj mu przypadek odmienionym słowem 'literał':
  • 'literał …' → slot `flagę`
  • 'literał / literału …' → slot `kota`
  • 'literał / literału …' → slot `psa`
```

Uwaga: w TEJ sygnaturze wszystkie trzy gołe sloty dzielą biernik, więc
`literał prawda` (biernik) nadal pasuje do trzech różnych slotów —
kolejny głośny remis wskaże uczciwą receptę: nazwij zmienne jak
parametry (`kot`/`pies` — krok imienny zwiąże sloty) albo daj
parametrom rozróżnialne przyimki. `literał` rozstrzyga wtedy, gdy
formy przypadków faktycznie rozdzielają sloty, np. biernik vs
narzędnik w `zawieź literałem "samochód" psa do domu`.
