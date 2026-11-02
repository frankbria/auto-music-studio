# #693: cover art on a current OpenAI image model, charged credits


OpenAI retired `dall-e-3`, the default model in `image_client.py`, from its API on 2026-05-12, and `gpt-image-1` on 2026-10-23, so cover-art generation was failing. It now uses `gpt-image-2.5-flare` at medium quality and asks for all 4 options in one request (`n=4`). It no longer sends `response_format`, which GPT image models reject with a 400.

Generation was also free, though it calls a paid API. `POST /clips/{id}/artwork/generate` now charges **3 credits** through `charge_and_create`, after the prompt is screened, so a blocked prompt charges nothing. A failed job is refunded like any other.

## Evidence

```bash
uv run pytest tests/test_image_client.py -q --no-cov 2>&1 | tail -1
```

```output
6 passed in 0.03s
```

```bash
uv run pytest -m integration tests/test_artwork_api.py tests/test_artwork_service.py -q --no-cov 2>&1 | tail -1
```

```output
20 passed, 7 deselected, 2 warnings in 5.16s
```
