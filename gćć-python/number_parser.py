"""Parser liczebników słownych: `sto dwadzieścia trzy` → 123.

Liczbą jest słowo, które ma w SGJP analizę z `pos == "num"` LUB którego lemma
(na dowolnej analizie) należy do znanych słowników liczebnikowych. Whitelist
lemmowa jest konieczna, bo część form fleksyjnych nie ma w SGJP tagu num:
gen pl magnitud (`tysięcy/milionów/...`) jest tagowane wyłącznie jako subst,
odmiany `zera/zeru/zerem` tylko jako subst, a `jednego/jedną/jednym` tylko
jako adj — wszystkie muszą dawać wartość liczbową.
"""

import lexer
from morph_anal import canonical


UNITS = {
    "zero": 0, "jeden": 1, "dwa": 2, "trzy": 3, "cztery": 4,
    "pięć": 5, "sześć": 6, "siedem": 7, "osiem": 8, "dziewięć": 9,
    "dziesięć": 10, "jedenaście": 11, "dwanaście": 12, "trzynaście": 13,
    "czternaście": 14, "piętnaście": 15, "szesnaście": 16,
    "siedemnaście": 17, "osiemnaście": 18, "dziewiętnaście": 19,
}

TENS = {
    "dwadzieścia": 20, "trzydzieści": 30, "czterdzieści": 40,
    "pięćdziesiąt": 50, "sześćdziesiąt": 60, "siedemdziesiąt": 70,
    "osiemdziesiąt": 80, "dziewięćdziesiąt": 90,
}

HUNDREDS = {
    "sto": 100, "dwieście": 200, "trzysta": 300, "czterysta": 400,
    "pięćset": 500, "sześćset": 600, "siedemset": 700,
    "osiemset": 800, "dziewięćset": 900,
}

MAGNITUDES = {
    "tysiąc": 10**3, "milion": 10**6, "miliard": 10**9,
    "bilion": 10**12, "trylion": 10**18,
}

MAGNITUDE_LEMMAS = frozenset(MAGNITUDES.keys())
_ALL_LEMMAS = (
    frozenset(UNITS) | frozenset(TENS) | frozenset(HUNDREDS) | MAGNITUDE_LEMMAS
)


from ast_nodes import InterpreterError


class NumberParseError(InterpreterError):
    pass


def _num_lemma(token):
    """Zwraca lemmę liczbową dla tokenu lub None gdy nie jest liczebnikiem.

    Iteruje po wszystkich analizach SGJP. Preferuje analizy z `pos == "num"`
    których lemma trafia w słowniki (priorytet 1), żeby ominąć fakt, że SGJP
    czasem ma lemmy w formie potocznej np. `tysiące:tysiące:num` zamiast
    kanonicznego `tysiąc`. W drugiej kolejności sprawdza whitelistę lemmową
    na DOWOLNEJ analizie — to ratuje formy bez tagu num: `tysięcy/milionów`
    (gen pl tagowane wyłącznie jako subst), `zera/zeru` (subst) oraz
    `jednego/jedną` (adj).
    """
    kind, surface, analyses = token
    if kind is not lexer.Token.WORD:
        return None
    if len(surface) != 1:
        return None
    seg_anas = analyses[0]
    # 1) num-analiza z lemmą znaną słownikom
    for ana in seg_anas:
        if ana.pos == "num" and ana.lemma in _ALL_LEMMAS:
            return ana.lemma
    # 2) whitelist lemmowa po dowolnej analizie (subst/adj odmiany liczebników)
    for ana in seg_anas:
        if ana.lemma in _ALL_LEMMAS:
            return ana.lemma
    # 3) dowolna num-analiza (zachowamy oryginalną lemmę dla diagnostyki)
    for ana in seg_anas:
        if ana.pos == "num":
            return ana.lemma
    return None


def is_number_word(token):
    return _num_lemma(token) is not None


def parse_number_words(tokens):
    """Sumuje listę tokenów-liczebników do jednej wartości int.

    Algorytm grupowy: kumuluje jednostki/dziesiątki/setki w `current`,
    przy magnitudzie domyka grupę przez `total += max(current,1) * mag`.
    Końcowy `current` to "ogon" mniejszy od najmniejszej napotkanej magnitudy.
    """
    if not tokens:
        raise NumberParseError("pusta sekwencja liczebnikowa")
    total = 0
    current = 0
    for tok in tokens:
        line = getattr(tok, "line", None)
        lemma = _num_lemma(tok)
        if lemma is None:
            raise NumberParseError(
                f"token {tok!r} nie jest liczebnikiem",
                line=line,
            )
        if lemma in UNITS:
            current += UNITS[lemma]
        elif lemma in TENS:
            current += TENS[lemma]
        elif lemma in HUNDREDS:
            current += HUNDREDS[lemma]
        elif lemma in MAGNITUDES:
            total += max(current, 1) * MAGNITUDES[lemma]
            current = 0
        else:
            # Pułapka liczebnikowa: słowo z num-odczytem w SGJP (szereg,
            # ile, …) użyte jako nazwa — scalanie sekwencji liczebnikowych
            # połknęło je zanim parser zobaczył identyfikator.
            raise NumberParseError(
                f"'{lemma}' ma w SGJP odczyt liczebnikowy i nie może być "
                f"nazwą — wybierz inną (np. 'spis', 'wykaz')",
                line=line,
            )
    return total + current
