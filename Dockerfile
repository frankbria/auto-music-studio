# Platform API image (#429): FastAPI + the in-process job processor.
#
# Single container by design — the job processor runs inside the API's lifespan, and
# splitting it into its own scalable service makes #427 (stale-requeue racing a long video
# render) live. Revisit once #427 is closed; see docs/deployment.md.
#
# Two stages so the build toolchain and the uv cache stay out of the runtime layer. The
# ACE-Step worker image (docker/Dockerfile) is a different thing entirely — CUDA base,
# clones an external repo — and shares nothing with this.

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9.30 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies before source: this layer is the expensive one and only the lockfile
# should be able to invalidate it.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --extra api --extra s3

COPY src ./src
# --no-editable: an editable install points at /app/src, which would make the runtime
# stage depend on source that its own COPY happens to place identically. Install the
# package properly instead.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --extra api --extra s3


FROM python:3.12-slim AS runtime

# ffmpeg is a hard runtime requirement, not a convenience: free-tier video watermarking
# (#401), flac/mp3 conversion, batch transcode and Studio mixdowns all shell out to it.
# CI installs it (ci.yml) and production ran on trust — baking it in is the whole point.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 acemusic

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Absolute, and mounted as volumes in compose. Both of these default to CWD-relative
    # paths (`./acemusic-voice-training`, `Path.cwd()/"storage"`), which in a container
    # means "wherever the process happened to start, inside the writable layer, gone on
    # restart". Set here rather than by changing the defaults: voice_training_root is
    # deliberately relative so the API and ACE-Step share a filesystem, and the value is
    # sent verbatim to ACE-Step.
    ACEMUSIC_API_VOICE_TRAINING_ROOT=/data/voice-training \
    ACEMUSIC_STORAGE_LOCAL_ROOT=/data/storage

WORKDIR /app

COPY --from=builder --chown=acemusic:acemusic /app/.venv /app/.venv

RUN mkdir -p /data/storage /data/voice-training && chown -R acemusic:acemusic /data

USER acemusic

EXPOSE 8000

# Liveness only — /api/v1/health deliberately does not touch MongoDB. The API already
# fails fast on an unreachable database at startup, so a container that answers here is
# one that got past that.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/v1/health || exit 1

# No console script exists for the server (pyproject only ships the `acemusic` CLI), so
# the ASGI target is named directly. No --reload: that is a development flag.
CMD ["uvicorn", "acemusic.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
