# Custom voice models (Stage 25)

Train a voice from your own recordings and use it in generation.

## Training a voice

`POST /api/v1/voice-models/train` — multipart: 2–10 reference recordings, a name, and an
optional description.

| Check | Rule |
| --- | --- |
| File count | 2–10 |
| Format | anything `soundfile` decodes (WAV, FLAC, OGG) |
| Sample rate | ≥ 16 kHz |
| Duration | ≥ 1 s per reference |
| Level | not silent |
| Consistency | no obvious odd-one-out (see the caveat below) |

**Every rejection names the file**, because "invalid file" is useless when ten were
uploaded: `thin.wav: sample rate is 8000 Hz, below the 16000 Hz minimum.`

**Validation runs before the charge.** A rejected upload costs nothing. Training costs
**10 credits**, deducted only once every check that can reject the request has passed, and
**refunded on any failure** — using the amount actually charged, so a later price change
cannot alter what you get back.

### The consistency check is not speaker verification

It compares spectral centroids. That catches the mistake that actually happens — a drum
loop or a backing track mixed in among the vocal takes — and it will **not** distinguish
two different people with similar timbre. The threshold is deliberately loose: a false
reject costs you a usable model, which is worse than training on one slightly odd take.

Doing this properly needs speaker embeddings, which is its own piece of work.

## How training actually runs

The worker drives ACE-Step's LoRA endpoints:

```
POST /v1/dataset/scan               → find the references
PUT  /v1/dataset/sample/{i}         → label each one
POST /v1/dataset/preprocess_async   → build tensors
POST /v1/training/start             → fine-tune
GET  /v1/training/status            → poll
POST /v1/training/export            → export the adapter
```

Four things about that sequence are worth knowing, because none is guessable and each was
wrong in the first implementation:

1. **Scan and label are not optional.** Preprocessing works on the server's *current*
   dataset and silently skips unlabelled samples — calling it directly returns
   `No labeled samples to preprocess` and produces nothing.
2. **Training status is a boolean.** `/v1/training/status` reports `is_training` with a
   human `status` string ("Idle"), not `completed`/`failed`. `is_training` reads false
   both *before* a run starts and after it ends, so the poller has a start grace period —
   without it, a run that never began reports success and keeps the credits.
3. **Export writes a directory.** The loadable PEFT adapter is the `adapter/` child of the
   export path; pointing `/v1/lora/load` at the root is rejected.
4. **Paths must resolve under ACE-Step's working directory** — see
   `acestep/training/path_safety.py`. The training endpoints take *paths, not uploads*, so
   **the platform and ACE-Step must share a filesystem.** A split deployment needs a
   shared volume; there is no upload endpoint to fall back on.

## Verified end to end

A real 3-reference run against a local ACE-Step 1.5:

```
preprocess   3/3 samples → tensors on disk
training     11,010,048 parameters, loss 1.647
export       43 MB adapter
load back    {"lora_loaded": true, "active_adapter": "adapter"}
```

The exported adapter loads back into the model, which is the difference between "the job
completed" and "the voice is usable" — a distinction the code makes too: a model is only
`is_usable` when it is `ready` **and** holds weights.
