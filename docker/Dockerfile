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

# Serverless extras: the RunPod SDK, httpx for the handler's API proxy (httpx is the
# HTTP client used throughout the platform), and boto3 so the handler can upload
# generated clips to S3 and return presigned URLs the platform can fetch (US-11.x).
RUN pip install --no-cache-dir runpod httpx boto3

# Serverless handler (bridges RunPod events to the local ACE-Step API).
COPY handler.py /app/handler.py

# Load model weights from the Network Volume cache, never from the image (§5.3). The
# RunPod template may override this; the handler also defaults to it.
ENV HF_HOME=/workspace/models/.cache

EXPOSE 8001

# Default: run the API server directly (used by pods and by the serverless handler,
# which spawns it as a subprocess).
#
# Serverless mode: override this CMD with `python /app/handler.py` (set as the
# endpoint/template start command — see model-deployment.md §5.3).
CMD ["uv", "run", "acestep-api"]
