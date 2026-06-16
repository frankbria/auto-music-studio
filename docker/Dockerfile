# ACE-Step-1.5 worker image (US-11.3).
#
# Runs in two modes from a single image:
#   - Pod / standalone API server (default): serves the ACE-Step REST API on :8001.
#   - RunPod serverless worker: override the CMD to `python /app/handler.py`.
#
# Model weights are NOT baked in — they load at runtime from a RunPod Network Volume
# mounted at /workspace/models (see model-deployment.md §3.3, §5.3). Keeping weights
# out of the image holds it under the 10GB target and lets every worker share one
# volume.
FROM pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime

WORKDIR /app

# System dependencies: git to clone the model repo at build time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# uv drives ACE-Step's Python environment (matches local deployment in §2.3).
RUN pip install --no-cache-dir uv

# Clone the ACE-Step-1.5 fork and install its dependencies. The code lives in the
# image; only the weights come from the Network Volume.
RUN git clone https://github.com/frankbria/ACE-Step-1.5.git /app/ACE-Step-1.5

WORKDIR /app/ACE-Step-1.5
RUN uv venv && uv sync

# Serverless extras: the RunPod SDK plus httpx for the handler's API proxy (httpx is
# the HTTP client used throughout the platform; the handler reuses it here).
RUN pip install --no-cache-dir runpod httpx

# Serverless handler (bridges RunPod events to the local ACE-Step API).
COPY handler.py /app/handler.py

EXPOSE 8001

# Default: run the API server directly (used by pods and by the serverless handler,
# which spawns it as a subprocess).
#
# Serverless mode: override this CMD with `python /app/handler.py` (set as the
# endpoint/template start command — see model-deployment.md §5.3).
CMD ["uv", "run", "acestep-api"]
