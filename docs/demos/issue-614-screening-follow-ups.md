# #614: screening follow-ups


## Allow terms follow the letter rule

Under `fold_leetspeak`, a rule term with letters needs a letter in its match, so `to` never matches `70` (#561). Allow terms skipped that check, so an allow term `to` erased `70` from the text before rules ran, hiding a hit on it. They now share `_counts` with rule terms.

## The audit's `before` comes from the write

`PATCH /admin/screening-rules` logged a `before` read ahead of its atomic write, so a save landing in between went missing from the diff. `swap_rules` returns the pre-image from the same `find_one_and_update` (`ReturnDocument.BEFORE`) and derives the after from it.

## Confusables: closed with a decision

`_HOMOGLYPHS` stays at the Greek, Armenian, Cherokee and Latin small-capital entries. Folding another script needs a false-positive pass over it, and no evasion through other scripts has been seen. Reopen when one is.

## Evidence

Both tests were mutation-checked: reverting either fix turns its test red.

```bash
uv run pytest tests/test_screening_api.py -q --no-cov -k never_erases 2>&1 | tail -1
```

```output
1 passed, 307 deselected, 2 warnings in 1.04s
```

```bash
uv run pytest -m integration tests/test_screening_api.py -q --no-cov -k audit_before 2>&1 | tail -1
```

```output
1 passed, 307 deselected, 2 warnings in 2.84s
```
