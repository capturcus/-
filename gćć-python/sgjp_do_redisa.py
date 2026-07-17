#!/usr/bin/env python3
"""Jednorazowa (i idempotentna) migracja SGJP do lokalnego Redisa.

Zapisuje GOTOWE analizy morfologiczne (po passie re-lematyzacji imiesłowów
i gerundiów do form cytowanych z `morph_anal.load`) pod kluczami
`sgjp:f:<forma>`, przyimki pod `sgjp:preps`, a na końcu metadane pod
`sgjp:meta`. Dzięki temu `gćć.py --redis` lematyzuje bez ładowania bazy.

Idempotencja i wykrywanie zmian: `sgjp:meta` niesie odcisk źródła
(wersja schematu + rozmiar + mtime pliku sgjp.tab). Zgodny odcisk →
„aktualne, nic do zrobienia"; inny odcisk (nowe wydanie SGJP) → pełna
ponowna migracja (z wyczyszczeniem starych kluczy, żeby nie zostały
formy usunięte ze źródła). `--wymuś` wymusza migrację mimo zgodności.
"""

import argparse
import json
import sys
import time

import argparse_po_polsku
import morph_anal
from morph_anal import REDIS_PREFIX, analysis_to_jsonable, source_fingerprint

argparse_po_polsku.spolszcz()

BATCH = 10_000
PROGRESS_EVERY = 500_000


def _clear_prefix(client):
    """Usuwa wszystkie klucze `sgjp:*` (SCAN + UNLINK w paczkach) — stare
    formy nie mogą przeżyć wymiany źródła."""
    removed = 0
    cursor = 0
    while True:
        cursor, keys = client.scan(cursor=cursor, match=f"{REDIS_PREFIX}*",
                                   count=BATCH)
        if keys:
            client.unlink(*keys)
            removed += len(keys)
        if cursor == 0:
            return removed


def migrate(sgjp_path, url, force=False, quiet=False):
    """Zwraca True, gdy migracja się wykonała; False, gdy była zbędna
    (odcisk źródła zgodny z `sgjp:meta`). Importowalne — testy migrują
    subset do osobnego logicznego DB."""
    import redis

    def say(msg):
        if not quiet:
            print(msg, file=sys.stderr)

    client = redis.Redis.from_url(url)
    client.ping()

    fingerprint = source_fingerprint(sgjp_path)
    meta_raw = client.get(f"{REDIS_PREFIX}meta")
    if meta_raw is not None and not force:
        meta = json.loads(meta_raw)
        if all(meta.get(k) == v for k, v in fingerprint.items()):
            say(f"Redis aktualny ({meta.get('formy')} form, "
                f"źródło niezmienione) — nic do zrobienia.")
            return False
        say("Odcisk źródła się zmienił — migruję ponownie.")

    policy = client.config_get("maxmemory-policy").get("maxmemory-policy")
    if policy not in (b"noeviction", "noeviction"):
        say(f"OSTRZEŻENIE: maxmemory-policy={policy!r} — Redis może po cichu "
            f"usuwać klucze SGJP; zalecane 'noeviction'.")

    db, preps = morph_anal.load(sgjp_path)

    t0 = time.time()
    say("Czyszczę stare klucze sgjp:* ...")
    removed = _clear_prefix(client)
    say(f"Usunięto {removed} kluczy.")

    say(f"Zapisuję {len(db)} form ...")
    pipe = client.pipeline(transaction=False)
    written = 0
    for form, analyses in db.items():
        payload = json.dumps([analysis_to_jsonable(a) for a in analyses],
                             ensure_ascii=False, separators=(",", ":"))
        pipe.set(f"{REDIS_PREFIX}f:{form}", payload)
        written += 1
        if written % BATCH == 0:
            pipe.execute()
        if written % PROGRESS_EVERY == 0:
            say(f"  {written}/{len(db)} ...")
    pipe.execute()

    client.set(f"{REDIS_PREFIX}preps", json.dumps(
        {lemma: sorted(cases) for lemma, cases in preps.items()},
        ensure_ascii=False))
    # Meta NA KOŃCU — częściowa migracja zostaje wykrywalna (brak mety).
    meta = dict(fingerprint)
    meta["formy"] = len(db)
    meta["źródło"] = sgjp_path
    client.set(f"{REDIS_PREFIX}meta", json.dumps(meta, ensure_ascii=False))
    client.save()

    info = client.info("memory")
    say(f"Zmigrowano {written} form w {time.time() - t0:.0f} s; "
        f"pamięć Redisa: {info.get('used_memory_human')}.")
    return True


def main():
    argp = argparse.ArgumentParser(description=__doc__)
    argp.add_argument("--sgjp", default="../sgjp.tab")
    argp.add_argument("--url", default="redis://localhost:6379/0")
    argp.add_argument("--wymuś", action="store_true", dest="force",
                      help="migruj nawet przy zgodnym odcisku źródła")
    args = argp.parse_args()
    migrate(args.sgjp, args.url, force=args.force)


if __name__ == "__main__":
    main()
