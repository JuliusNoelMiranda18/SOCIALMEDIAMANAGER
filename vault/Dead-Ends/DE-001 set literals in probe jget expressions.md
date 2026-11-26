# DE-001 set literals in probe jget expressions

**Stage:** 5 · **Area:** [[Publishing Service]] (probes) · [[Webhook]]

## What we tried
In `probe1_idempotency.sh`: `check "…" "$(echo "$R" | jget "{e['status'] for e in d['entries']} <= {'publishing','published'}")" True`.

## Why it was wrong
macOS `/bin/bash` 3.2 brace-expands `{'publishing','published'}` inside a double-quoted string nested in `"$(…)"`. jget ran as several python calls: two tracebacks (`'<=' not supported between instances of 'set' and 'str'`) and one stray `True`, so the check printed a **false PASS**. zsh does not do this, so it only shows under `bash`.

## Do this instead
No `{a,b}` literals (set or dict with a comma) in jget expressions; use tuples/lists: `all(e['status'] in ('publishing', 'published') for e in d['entries'])`. A comprehension without a comma (`{e['status'] for …}`) is safe.

## Don't retry unless
The probes run on bash ≥ 4 everywhere (they do not: macOS host bash is 3.2).
