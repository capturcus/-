# Komunikaty błędów po migracji na MLsub — przegląd i propozycje

Nowy solver przechowuje przy każdej zmiennej PEŁNY zbiór granic
z prowieniencją: `dolne = [(typ, nota)]` (co wpłynęło i skąd),
`górne = [(typ, nota)]` (czego się wymaga i skąd), `alternatywy`
(dysjunkcje kandydatów). To znacznie więcej, niż komunikaty dziś
pokazują. Format: **sytuacja** → *obecny komunikat* → **proponowany**.

## 0. Infrastruktura (odblokowuje resztę — zrobić najpierw)

0a. **Etykiety zmiennych.** Zmienne w komunikatach to dziś `t7`.
    Solver zna kontekst powstania każdej: deklaracja zmiennej
    użytkownika (scope.declare), slot parametru (budowa sygnatury),
    pole struktury (elaborate w konstrukcji), element listy
    (instancja struktury), wynik wywołania. Dodać `Zmienna.etykieta`
    ustawianą w tych miejscach: „zmienna 'rzecz' (działać)",
    „parametr 'liczbę' funkcji 'dodać'", „pole 'imię' struktury 'Kot'",
    „element 'Ogniwo'", „wynik wywołania 'zapisz' (linia 4)".
    Wszędzie w komunikatach renderować etykietę zamiast tN.

0b. **Nota przekazywana jawnie.** `_current_note` to global ustawiany
    przez resolve_* — po zagnieżdżonych rozstrzygnięciach bywa
    nieświeży (nota z wnętrza wyrażenia przykleja się do granicy
    zewnętrznej). Przekazywać notę parametrem `ogranicz(pod, nad,
    nota=)`; global zostaje fallbackiem.

0c. **Ścieżka przepływu.** `_przepchnij` dekoruje konflikt jedną
    granicą pośredniczącą („przez granicę: …"). Akumulować CAŁĄ
    ścieżkę krawędzi od źródła do pękającego slotu:
    „droga wartości: Liczba (linia 2: przypisanie do 'rzecz')
    → 'rzecz' → argument 1 wywołania 'f' (linia 7)
    → parametr 'x' funkcji 'f' → zwrot z 'f' (linia 3)".

0d. **Poszlakownik — pełny zrzut ograniczeń zmiennej.** Jedna funkcja
    renderująca używana przez WSZYSTKIE błędy unifikacji i groundingu:

        zmienna 'rzecz' (działać):
          wpływa do niej:
            • Liczba — linia 2: przypisanie do 'rzecz'
            • Znak   — linia 3: przypisanie do 'rzecz'   ← nowa, sprzeczna
          wymaga się od niej:
            • (Cokolwiek) — linia 4: argument 1 wywołania 'wypisz'

    To realizuje postulat: programista widzi WSZYSTKIE poszlaki
    i sam wskazuje, która jest błędna. Limit rozsądku: pełna lista
    do ~12 pozycji, potem „… i N dalszych (najstarsze pominięte)".

## 1. Błędy unifikacji (biunifikacja)

1a. **Konflikt głów konkretów** →
    *nie można zunifikować Liczba z Znak — zdecyduj, która poszlaka…*
    (poszlaki tylko, gdy konflikt wykrył zachłanny join na zmiennej;
    z `_ogranicz_konkrety` komunikat bywa GOŁY, bo Konkrety nie noszą
    not) → **zawsze dołączać poszlakownik zmiennych, przez które
    konflikt przepłynął (0c/0d), plus zdania „czego oczekiwano/co
    otrzymano": „slot 'imię' struktury 'Kot' oczekuje Znak (deklaracja:
    linia 2), otrzymał Liczba (linia 7: pole 'imię' konstrukcji)"**.

1b. **Join dolnych nie istnieje** →
    *nie można zunifikować Pies z Chomik…* → **nazwać problem wprost:
    „wartości typu Pies (linia 2) i Chomik (linia 5) trafiają do tej
    samej zmiennej 'pupil', a żadna zadeklarowana unia ich nie łączy.
    Unie zawierające Psa: Zwierzę (Kot albo Pies); zawierające
    Chomika: Futrzak (Kot albo Chomik). Jeśli to zamierzone,
    zadeklaruj unię: `Pupil to Pies albo Chomik`"** — sugestia
    deklaracji + istniejące prawie-pasujące unie z ich składem.

1c. **Remis minimalnych unii** →
    *głowy [...] pokrywa więcej niż jedna minimalna unia: U1, U2* →
    **dodać skład obu unii i linie granic, które wymusiły join:
    „Kot (linia 3) ⊔ Pies (linia 6) pokrywają i Domownik (Kot albo
    Pies), i Ulubieńcy (Kot albo Pies) — adnotacja `(Domownik)` przy
    deklaracji zmiennej rozstrzygnie"**.

1d. **Unia w slocie wariantu** →
    *nie można zunifikować Zwierzę z Kot* → **„wartość typu unii
    'Zwierzę' (może być Psem) nie mieści się w slocie oczekującym
    dokładnie Kota — zawęź dopasowaniem `jest:` przed przekazaniem";
    wskazać, skąd slot (parametr/pole, linia deklaracji), skąd unia
    (nota granicy)**.

1e. **Niejawny argument (jednorodność list)** →
    *niejawny argument 'element' typu 'Ogniwo' (parametr z definicji
    'Ogniwo') nie zgadza się…* → **dodać oba miejsca ustalenia:
    „element ustalony jako Liczba w linii 5 (pole 'głowa'), a w linii
    6 płynie Znak (pole 'głowa' wewnętrznego ogniwa) — listy w Ć są
    jednorodne"** (noty z granic argów są w grafie — wystarczy je
    wyrenderować).

1f. **Strzałki** →
    *niezgodna liczba argumentów funkcji: (…)→… vs (…)→…* →
    **„wartość funkcyjna przyjmuje 1 argument ((Liczba) → Liczba,
    z referencji 'podwajanie', linia 2), a zastosowanie podaje 2
    (linia 9)"; dla konfliktu kontrawariancji: „funkcja wymaga
    argumentu Zwierzę, a zastosowanie dostarcza tylko gwarancję
    Kota…" — kierunek kontrawariancji wyjaśniony słowami**.

## 2. Grounding (punkt wejścia `działać`)

2a. **Wolna zmienna** →
    *nie można wywnioskować konkretnego typu zmiennej 'x' (linia N);
    pozostało t3; [ślad] — użyj wartości strukturalnie albo dodaj
    adnotację* → **klasyfikować przyczynę po kształcie grafu:**
    - zero granic → „'x' nigdzie nie otrzymuje wartości ani nie jest
      używana — martwa zmienna?";
    - tylko górne, wielogłowe → „'x' znana wyłącznie z wymagań:
      ≤ Domownik (linia 4), ≤ Futrzak (linia 6); domyślkowanie
      niejednoznaczne — adnotacja rozstrzygnie";
    - ekstern → jak dziś („pochodzi z externa 'zapisz', czysta
      świeżość") + „obserwuj wynik: dopasuj `jest:`, przekaż do
      funkcji o jawnym typie albo adnotuj";
    - wolny element kontenera obserwowany przez wiązanie → wskazać
      wiązanie i listę, z której pochodzi.
    **Zawsze: poszlakownik (0d) zamiast surowego `pozostało t3`.**

2b. **Nierozstrzygnięta dysjunkcja** →
    *typ pasuje do wielu możliwości: Rezultat, Wynik — dodaj adnotację*
    → **dodać pochodzenie i różnicę: „możliwości zebrane w dopasowaniu
    z 'inaczej:' (linia 8): Rezultat (Sukces albo Błąd) i Wynik
    (Sukces albo Porażka) — rozstrzygnie gałąź z wariantem
    występującym tylko w jednej unii (Błąd/Porażka), użycie w slocie
    o znanym typie albo adnotacja"** (wymaga not przy alternatywach:
    zapisywać (kandydat, nota-powstania) — dziś alternatywy not nie
    niosą).

## 3. Dopasowanie `jest:`

3a. *brakuje gałęzi: Pies* → **dodać, skąd wiadomo, że podmiot to
    unia: „podmiot 'pupil' jest Zwierzęciem (adnotacja: linia 2) —
    unia ma warianty Kot, Pies; brakuje gałęzi: Pies (albo dodaj
    `inaczej:`)"**.

3b. *gałęzie … nie odpowiadają członkom żadnego typu wariantowego* →
    **wylistować prawie-trafienia: dla każdej unii o niepustym
    przecięciu z gałęziami — czego brakuje/co jest nadmiarowe:
    „najbliżej: Zwierzę (brakuje: Pies), Futrzak (nadmiarowe:
    Pies)"**.

3c. *pasuje do wielu typów wariantowych: …* → **jak 2b: wskazać
    warianty-dyskryminatory, których dodanie/usunięcie rozstrzyga**.

3d. **Wiązanie pola nieistniejącego w wariancie** →
    *'x' nie jest polem struktury 'Kot' (linia N)* → **dodać listę
    pól wariantu z typami: „Kot ma pola: imię (Znak)" + did-you-mean
    po lemmie przy literówce**.

## 4. Łańcuchy dopełniaczowe

4a. *pole 'imię' czytane z wartości typu unii 'Zwierzę' (może być
    Niczym) — zawęź…* → **dodać, SKĄD unia (nota granicy, która
    poszerzyła bazę): „'pupil' stał się Zwierzęciem przez zapis
    w linii 21 (gałąź Kotem)"; wymienić pola dostępne bez zawężenia
    (wspólne wszystkim wariantom, jeśli są)**.

4b. *żadna struktura nie ma pola 'X'* → **did-you-mean po lemmach
    (odległość edycyjna na powierzchniach pól wszystkich struktur):
    „czy chodziło o 'imię' (Kot) albo 'ramię' (Robot)?"**.

4c. *pole 'X' mają struktury: A, B, ale żadna nie domyka dalszej
    części łańcucha* → **pokazać, gdzie domykanie pęka per kandydat:
    „A: pole 'x' jest Liczbą, a łańcuch czyta z niego 'y';
    B: brak pola 'y' w strukturze C"**.

4d. *pole 'X' nie występuje w typie [...] podstawy łańcucha* →
    **poszlakownik bazy (skąd wiemy, że baza jest tego typu) + lista
    pól rzeczywistego typu bazy**.

## 5. Wywołania i sygnatury

5a. *wywołanie niezadeklarowanej funkcji 'x'* → **did-you-mean po
    kluczach zadeklarowanych funkcji: wspólny lemat innego aspektu
    (jest już hint aspektowy w resolverze — użyć tej samej maszynerii
    w typecheckerze), bliskość lematów, liczba segmentów**.

5b. **Konflikt argumentu wywołania** (dziś generyczny 1a) →
    **„argument 2 wywołania 'dodaj' (linia 7): funkcja oczekuje
    Liczba (parametr 'do sumy', deklaracja linia 1), otrzymała Znak
    — droga wartości: …(0c)"**.

5c. **Konflikt zwrotów** → **„funkcja 'badać' zwraca Znak (linia 3)
    i Nic (ścieżka bez `zwróć` — funkcja częściowa), a Znak∪Nic nie
    łączy żadna unia — dodaj `zwróć` na końcu albo zadeklaruj unię"**
    — niejawny zwrot Nic musi być NAZWANY w poszlace (dziś nota
    „niejawny zwrot Nic z 'badać'" istnieje — dodać podpowiedź).

## 6. Aliasy i aplikacja nazwana

6a. *nieznany typ 'Widmo' w deklaracji aliasu* → **+ did-you-mean po
    zadeklarowanych typach**.

6b. *typ wariantowy 'U' nie ma parametru 'p' — parametry: …* →
    **dodać definicje źródłowe parametrów: „parametry: element
    (z definicji Ogniwa)"** — `_param_pedigree` już to umie.

6c. *typ wariantowy 'Lista' nie przyjmuje argumentów typu* (pozycyjna)
    → **dopowiedzieć formę poprawną: „aplikacja na unii wyłącznie
    nazwana: `Lista o elemencie Liczba`"**.

## 7. Higiena istniejących komunikatów

7a. Dekorator *„(podczas typowania linii N, w funkcji 'F')"* — zostaje;
    ujednolicić: NIE doklejać, gdy komunikat już niesie tę samą linię.

7b. `_msg_konflikt` obcina poszlaki do 8 — po wdrożeniu 0d limit
    wspólny i jawny („… i N dalszych").

7c. Materializacja w komunikatach: renderować granice jak
    w test_typechecker._render (argumenty zmaterializowane:
    `Ogniwo[Liczba]`, nie `Ogniwo[t5]`); dla zmiennej częściowo
    znanej: „co najmniej Zwierzę (≥ Kot: linia 2; ≥ Pies: linia 5)".

7d. Wypis alternatyw zawsze posortowany; unie zawsze ze składem
    („Zwierzę (Kot albo Pies)") przy pierwszym wystąpieniu w treści.

## Kolejność wdrożenia

1. 0a+0b (etykiety, jawna nota) — czysta infrastruktura;
2. 0d poszlakownik + podpięcie do 1a/1b/2a (największy zysk DX,
   w tym postulat „wylistuj wszystkie poszlaki");
3. 0c ścieżka przepływu; 4. sekcje 2b/3/4 (dysjunkcje z notami,
   prawie-trafienia, did-you-mean); 5. reszta drobiazgów (5-7).
Każdy krok: aktualizacja test_diagnostyka.py + nowe testy formatów.
