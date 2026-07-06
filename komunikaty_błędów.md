# Komunikaty błędów do dodania — gładszy DX

Zebrane z realnych potknięć (sesja lipiec 2026: AVL, wyrażenia.ć, katalog bad/).
Format: **sytuacja** → *obecny komunikat* → **proponowany**.
Wzorce do naśladowania (już dobre): odmowa `dla` (mówi *dlaczego* i *co zamiast*),
kompletność konstrukcji (lista braków), „zawęź dopasowaniem `jest:`".

## Zasada ogólna (infrastruktura, nie kosmetyka)

1. **Każdy `TypeCheckError` niesie `plik:linia`.** Dziś większość błędów unifikacji
   nie ma lokalizacji — trzeba przewlec `line` przez resolve_* do unify (choćby
   jako kontekst „podczas typowania linii N"). do tego przy każdym błędzie unifikacji
   (nie można zunifikować A z B) interpreter powinien wypisywać wszystke miejsca, w których 
   było wnioskowane cokolwiek na temat A i B, tak żeby programista mógł zdecydować, która z tych poszlak jest błędna
2. **Każdy błąd runtime niesie Ć-owy stos**: lematy funkcji + linie instrukcji
   zamiast surowego traceback Pythona. Executor zna `function_lemmas` na każdej
   ramce — wystarczy je zbierać przy propagacji wyjątku.

## Parser / resolver

3. **Kolizja „nawias po wyrażeniu = adnotacja"** (quirk 16) — gdy parser typów
   padnie w nawiasie, którego zawartość zaczyna się od znanej głowy struktury:
   → *oczekiwano WORD, otrzymano TEXT 'Mruczek'*
   → **„nawias po wyrażeniu to adnotacja typu; jeśli to miała być konstrukcja
   struktury jako argument, poprzedź nawias przyimkiem (`z (Kot …)`) albo
   użyj zmiennej pośredniej"**.
4. **Aspekt czasownika** (oceń/oceniaj, spróbuj/próbuj) — gdy „niezadeklarowana
   zmienna" jest formą rozkazującą czasownika, którego DRUGI aspekt jest
   zadeklarowaną funkcją:
   → *'oceń' nie jest zadeklarowaną zmienną…*
   → **„'oceń' to rozkaźnik od 'ocenić'; zadeklarowana jest funkcja 'oceniać'
   — jej rozkaźnik to 'oceniaj' (albo zmień deklarację na 'ocenić')"**.
5. **Pułapka liczebnikowa** (szereg, ile) —
   → *liczebnik 'szereg' nie jest rozpoznawany przez słowniki*
   → **„'szereg' ma w SGJP odczyt liczebnikowy i nie może być nazwą — wybierz
   inną (np. 'spis', 'wykaz')"**.
6. **Słowo spoza SGJP** (arność) — dziś objawia się kryptycznie w środku
   konstruktora (*oczekiwano RPAREN, otrzymano WORD 'o'*):
   → **„słowo 'arność' nie występuje w SGJP — nazwy w Ć muszą się odmieniać;
   sprawdź `redis-cli EXISTS sgjp:f:SŁOWO` i wybierz odmienialny synonim"**
   (wykrycie: passthrough-lemat w pozycji pola/parametru).
7. **Sztywne dopasowanie przypadków argumentów** —
   → *argument funkcji 'X' nie pasuje do żadnego wolnego parametru w trybie pozycyjnym*
   → **dopisać tabelkę: „sloty: `z formą` (narzędnik), `do mapy` (dopełniacz);
   otrzymano: 'forma' (mianownik) — inflektuj argument albo weź go w nawias
   (argument w nawiasie jest bezprzypadkowy)"**.
8. **Kolizja wiązania pola z parametrem** (quirk 10) — gdy wiązanie `z wartością`
   przesłania parametr o tej samej lemmie: **ostrzeżenie** „wiązanie 'wartość'
   przesłania parametr 'wartość' — w tej gałęzi czytasz pole, nie parametr".

## Typechecker

9. **Chain przez wartość typu unii** (Problem A) —
   → *cannot unify Zwierzę with Kot*
   → **„pole 'imię' czytane z wartości typu unii 'Zwierzę' (może być Niczym)
   — zawęź dopasowaniem `jest:`; pole ma wariant Kot"** + linia.
10. **Niejawne argumenty unii** — jeśli to nie alias to użytkownik ich nie napisał, więc błąd
    musi je nazwać z rodowodem:
    → *cannot unify Ogon[Liczba] with Ogon[Tekst]* (hipotetycznie)
    → **„element listy 'Ogon' to już Liczba (parametr 'element' z definicji
    Węzła, ustalony w linii N), a tu płynie Tekst (linia M)"**.
14. **Grounding** — obecne „dodaj adnotację typu" bywa niewykonalne; dopisać
    ŹRÓDŁO: **„typ zmiennej 'x' nieustalony: pochodzi z externa 'zapisać'
    (czysta świeżość) i nigdzie nie jest obserwowany — użyj wartości
    strukturalnie albo dodaj adnotację"**.
15. jeśli struktura nie ma podanych wszystkich pól, wykryć i dopowiedzieć:
    → *tworzenie struktury 'Lista' wymaga wszystkich pól — brakuje: następnik*
    → być może to już jest, nie wiem
16. **Goły `raise` w resolve_getter_chain** (linia ~924) — dziś potrafi dać
    `RuntimeError: No active exception to reraise`; zamienić na TypeCheckError
    z liniami i listą kandydatów.

## Runtime (executor)

18. **Pole nie znalezione** —
    → *pole nie znalezione frozenset({(('imię',), 'sg', 'n')})*
    → **„odczyt pola 'imię' z wartości 'Nic' (linia N, w funkcji
    'przedstawić') — wartość nie jest wariantem posiadającym to pole"**.
20. **Głębokość rekursji** — łapać RecursionError:
    **„przekroczono głębokość rekursji (~1000 ramek) w 'liczyć' — czy rekursja
    ma przypadek bazowy? (limit interpretera, nie języka)"**. w kodzie gdzieś już jest wyspecyfikowany limit rekursji, więc użyj po prostu tego samego.
