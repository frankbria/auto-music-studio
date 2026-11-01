# #587: a moderation action landing mid-decision is not overridden

`decide()` used to read the decision in force, check the appeal wasn't superseded, and only then write the appeal's status. A removal landing between the read and the write passed the check. The appeal was stamped `reversed` (or `info_requested`), and the creator was told so, while the clip stayed down.

Now the appeal is claimed with its conditional status write. The clip is then restored only if `moderation_reviewed_at` is unchanged since the read; for `request_info` it's re-checked. If a newer action landed, the appeal is rolled back to how it was and the admin gets the superseded 409. No notice is written.

## Evidence

The integration test lands a real `moderation.act_on_clip(..., "remove", ...)` between the in-force read and the write, through a seam on `_appealable_action`:


```bash
uv run pytest -m integration tests/test_clip_appeals_api.py -k mid_decision -q --no-cov 2>&1 | tail -1
```

```output
2 passed, 57 deselected, 1 warning in 4.89s
```
