# #694: credit costs no paid plan loses money on


Every price sits above its vendor or compute cost at the worst-case revenue per credit: Enterprise annual ($998 for 2,500 credits a month), about $0.032 per credit after Stripe's fees. Vendor costs come from research done 2026-11-01.

| Action | Now | Was |
|---|---|---|
| Song / iterative edit / mashup | 1 / 1 / 2 (unchanged) | |
| Short sound | **1** | 0.5 |
| Mastering, Bakuage (default, everyone) | **2** | 5 |
| Mastering, LANDR (admins only) | **130** | 2 |
| Mastering, Dolby (admins only) | **11** | 3 |
| Video, per minute of song, rounded up | **156** at 720p / **375** at 1080p / **1,350** at 4K | 5–10 flat |
| Voice training | **LoRA 75**, or **LoKr 5** (new `method=lokr`) | 10 |
| Cover art (#693) | 3 | 0 |

- **Mastering:** a non-admin asking for LANDR or Dolby gets a 403 before any charge. Their job is pinned to `allowed_services: ["bakuage"]`, so the fallback chain can't run it on a dearer service either. The web picker shows Bakuage only, and admins also see LANDR and Dolby at their prices.
- **LoKr:** this trains through ACE-Step's `/v1/training/start_lokr` and loads the exported `lokr_weights.safetensors`.
- **Video:** the web's estimate mirrors the per-minute formula.

## Evidence

```bash
uv run pytest tests/test_credits_api.py tests/test_mastering_service.py -q --no-cov -k "Cost or cost or bakuage" 2>&1 | tail -1
```

```output
18 passed, 29 deselected, 2 warnings in 1.48s
```

```bash
uv run pytest -m integration tests/test_mastering_api.py tests/test_mastering_batch_api.py tests/test_mastering_tasks.py -q --no-cov -k "admin or pinned or bakuage or default" 2>&1 | tail -1
```

```output
9 passed, 63 deselected, 2 warnings in 3.93s
```

```bash
uv run pytest -m integration tests/test_voice_models_api.py -q --no-cov -k "lokr or method" 2>&1 | tail -1
```

```output
2 passed, 53 deselected, 2 warnings in 3.24s
```

```bash
cd web && npx vitest run components/mastering/mastering-config.test.tsx lib/video.test.ts 2>&1 | grep -E "Tests "
```

```output
      Tests  43 passed (43)
```
