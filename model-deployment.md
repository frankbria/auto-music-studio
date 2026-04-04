# ACE-Step-1.5 — Model Deployment Guide
**Version:** 1.0 Draft (April 2026)
**Model:** ACE-Step-1.5 (fork: github.com/frankbria/ACE-Step-1.5)
**Scope:** Local and remote GPU deployment strategies for the AI music generation engine

---

## Table of Contents

1. [Deployment Overview](#1-deployment-overview)
2. [Local Deployment](#2-local-deployment)
3. [Remote Deployment — RunPod](#3-remote-deployment--runpod)
4. [Hybrid Architecture](#4-hybrid-architecture)
5. [Docker Image & Container Setup](#5-docker-image--container-setup)
6. [API Gateway & Routing](#6-api-gateway--routing)
7. [Security](#7-security)
8. [Cost Analysis](#8-cost-analysis)
9. [Operational Runbook](#9-operational-runbook)

---

## 1. Deployment Overview

### 1.1 Two Compute Targets

The platform supports running the ACE-Step-1.5 model on two targets, selectable per-request or by configuration:

| Target | When to Use | Latency | Cost |
|---|---|---|---|
| **Local GPU** | Day-to-day creation, quick iterations, privacy-sensitive work | Lowest (no network) | Free (hardware already owned) |
| **Remote GPU (RunPod)** | XL model at full precision, batch generation, local GPU busy, mobile/travel access | +1–5s network overhead | Pay-per-second |

### 1.2 Design Principles
- **Transparent switching:** The platform API proxies requests to whichever backend is active. The web app and VST3 plugin don't need to know where the model is running.
- **No re-uploading:** Model weights are stored persistently on both local disk and RunPod Network Volumes. Upload once, use indefinitely.
- **Scale to zero:** Remote GPU costs $0 when idle. No need to manually tear down.
- **Fallback:** If the remote endpoint is unavailable, fall back to local. If local GPU is unavailable (e.g., accessing from mobile), route to remote.

---

## 2. Local Deployment

### 2.1 Hardware Profile
| Component | Specification |
|---|---|
| **GPU** | 16GB VRAM (e.g., RTX 4070 Ti Super, RTX 4080, RTX A4000) |
| **RAM** | 32GB+ recommended |
| **Storage** | ~15GB for model weights + dependencies |
| **OS** | Linux (WSL2), macOS (Apple Silicon via MLX), Windows |

### 2.2 Model Compatibility with 16GB VRAM

| Model Variant | VRAM (bf16) | VRAM (INT8) | Fits 16GB? | Notes |
|---|---|---|---|---|
| **Turbo (2B DiT)** | ~4.7GB | ~2.4GB | Yes | Fast iteration, 8 inference steps |
| **Base (2B DiT)** | ~4.7GB | ~2.4GB | Yes | Standard quality, 32-64 steps |
| **SFT (2B DiT)** | ~4.7GB | ~2.4GB | Yes | Best instruction following |
| **XL-Turbo (4B DiT)** | ~9GB | ~5GB | Yes | Fast high-quality |
| **XL-Base (4B DiT)** | ~9GB | ~5GB | Yes | High quality |
| **XL-SFT (4B DiT)** | ~9GB | ~5GB | Yes | Best quality + instruction following |
| **XL-SFT (4B DiT, bf16, no quant)** | ~20GB | N/A | No — use remote | Full precision requires 20GB+ |

**Summary:** 16GB VRAM handles all quantized variants comfortably. Only full-precision XL without quantization requires a remote GPU.

### 2.3 Installation

```bash
# Clone the fork
git clone https://github.com/frankbria/ACE-Step-1.5.git
cd ACE-Step-1.5

# Create virtual environment
uv venv
source .venv/bin/activate

# Install dependencies (NVIDIA CUDA example)
uv sync
pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126

# Model weights download on first run (auto-cached to ~/.cache/huggingface/)
```

### 2.4 Running the Local API Server

```bash
# Start the REST API server
uv run acestep-api

# Server listens on http://localhost:8001
# Optional: set API key for security
export ACESTEP_API_KEY=108030f6e31f4e8694b2d8d534854137
```

### 2.5 Multi-Model Configuration

Load multiple variants simultaneously for different quality tiers:

```bash
export ACESTEP_CONFIG_PATH=configs/turbo.yaml       # Fast preview
export ACESTEP_CONFIG_PATH2=configs/xl-sft.yaml      # High quality
uv run acestep-api
```

Select per-request via the `model` parameter in the API call.

### 2.6 Local Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `http://localhost:8001/release_task` | POST | Submit generation job |
| `http://localhost:8001/query_result` | POST | Check job status (batch) |
| `http://localhost:8001/v1/stats` | GET | Server load and timing |
| `http://localhost:8001/synth?wav=1` | GET | Render audio codes to WAV |

---

## 3. Remote Deployment — RunPod

### 3.1 Why RunPod
- GPU rental with per-second billing
- Network Volumes for persistent model storage (upload weights once)
- Serverless endpoints that scale to zero (no idle cost)
- Python SDK for programmatic management
- Free egress (no download fees)
- HTTPS endpoints out of the box

### 3.2 Deployment Options

#### Option A: Serverless Endpoint (Recommended)

Best for production use. Auto-scales, zero idle cost, managed infrastructure.

**How it works:**
1. Build a Docker image with ACE-Step-1.5 + a RunPod handler function.
2. Deploy as a serverless endpoint on RunPod.
3. RunPod provides an HTTPS URL: `https://api.runpod.ai/v2/{endpoint_id}/run`
4. Workers spin up on first request, scale to zero after idle timeout.
5. Model weights loaded from a Network Volume (not baked into the Docker image).

**Lifecycle:**
```
User sends request
    → RunPod spins up a worker (cold start: 5-15s first time, <200ms with FlashBoot)
    → Worker loads model from Network Volume
    → Processes request, returns audio
    → After idle period (configurable), worker scales down
    → $0 cost when idle
```

**Worker types:**
| Type | Behavior | Best For |
|---|---|---|
| **Flex Worker** | Scales to zero. Small cold start. Pay only when active. | Low/medium traffic, cost-sensitive |
| **Active Worker** | Always warm (no cold start). Bills 24/7 at ~20-30% discount. | High-traffic production |

**Recommendation:** Start with 1 Flex Worker. Add Active Workers if cold starts become a UX issue.

#### Option B: GPU Pod (On-Demand VM)

Best for development, experimentation, and long interactive sessions.

**How it works:**
1. Create a pod from a custom template with ACE-Step-1.5.
2. Mount a Network Volume with model weights.
3. SSH in or access via web terminal.
4. Run `uv run acestep-api` manually or via startup script.
5. Access API via RunPod's HTTP proxy: `https://{pod_id}-8001.proxy.runpod.net`
6. Stop the pod when done (storage persists, compute stops billing).
7. Resume later — weights are still on the Network Volume.

**Lifecycle:**
```
Create pod (once) → Start → Use → Stop ($0 compute, storage billed) → Resume → Use → Stop
                                                                        ↑ Weights persist
```

**Automation via API:**
```python
import runpod
runpod.api_key = "your_runpod_api_key"

# Start pod when user logs in
runpod.resume_pod("pod_id")

# Stop pod when user logs out
runpod.stop_pod("pod_id")
```

### 3.3 Network Volume Setup

**One-time setup — model weights persist indefinitely.**

```bash
# 1. Create a Network Volume in RunPod dashboard (or via API)
#    Region: US-TX-3 (or wherever you want pods)
#    Size: 30GB (model weights + cache + workspace)
#    Cost: ~$2.10/month

# 2. Create a temporary pod with the volume mounted
#    Mount path: /workspace/models

# 3. SSH into the pod and download weights
ssh root@pod-ip
cd /workspace/models
git clone https://github.com/frankbria/ACE-Step-1.5.git
cd ACE-Step-1.5
uv venv && uv sync
# Download model weights (auto-fetched from HuggingFace on first run)
uv run python -c "from acestep import load_model; load_model('turbo')"
uv run python -c "from acestep import load_model; load_model('xl-sft')"

# 4. Stop the temporary pod. Weights stay on the volume.
# 5. All future pods/serverless workers mount this same volume.
```

**Storage costs:**
| Volume Size | Monthly Cost | What It Holds |
|---|---|---|
| 15GB | ~$1.05 | One model variant + code |
| 30GB | ~$2.10 | All model variants + code + cache |
| 50GB | ~$3.50 | Everything + generated audio buffer |

### 3.4 Serverless Handler Implementation

```python
# handler.py — RunPod serverless handler for ACE-Step-1.5
import runpod
import requests
import subprocess
import time
import os

# Start the ACE-Step API server as a subprocess
api_process = None

def start_api_server():
    """Start the ACE-Step-1.5 REST API server."""
    global api_process
    if api_process is None or api_process.poll() is not None:
        env = os.environ.copy()
        env["ACESTEP_API_KEY"] = os.getenv("ACESTEP_API_KEY", "")
        api_process = subprocess.Popen(
            ["uv", "run", "acestep-api"],
            cwd="/workspace/models/ACE-Step-1.5",
            env=env
        )
        # Wait for server to be ready
        for _ in range(30):
            try:
                r = requests.get("http://localhost:8001/v1/stats", timeout=2)
                if r.status_code == 200:
                    return True
            except:
                time.sleep(1)
    return False

def handler(event):
    """Handle incoming generation requests."""
    start_api_server()

    input_data = event["input"]

    # Forward to ACE-Step API
    response = requests.post(
        "http://localhost:8001/release_task",
        json=input_data,
        timeout=300
    )

    if response.status_code == 200:
        result = response.json()
        # Poll for completion
        task_id = result.get("task_id")
        while True:
            status = requests.post(
                "http://localhost:8001/query_result",
                json={"task_ids": [task_id]}
            ).json()
            if status.get("completed"):
                return status
            time.sleep(1)
    else:
        return {"error": response.text}

runpod.serverless.start({"handler": handler})
```

### 3.5 GPU Tier Recommendations

| GPU | VRAM | Price/hr (Secure) | Price/hr (Community) | Best For |
|---|---|---|---|---|
| **RTX 3090** | 24GB | ~$0.43 | ~$0.22 | Budget option, slower |
| **RTX 4090** | 24GB | ~$0.44 | ~$0.34 | **Best value** — fast + affordable |
| **A100 40GB** | 40GB | ~$1.19 | ~$0.89 | Batch processing, multiple concurrent jobs |
| **A100 80GB** | 80GB | ~$1.64 | ~$1.19 | Overkill for single ACE-Step instance |

**Recommendation:** RTX 4090 for Serverless (best price/performance). RTX 3090 for development pods (cheapest).

### 3.6 RunPod API Access

**SDK Installation:**
```bash
pip install runpod
```

**Environment Variable:**
```bash
# Add to .env
RUNPOD_API_KEY=your_runpod_api_key
```

**Programmatic Pod Management:**
```python
import runpod
runpod.api_key = os.getenv("RUNPOD_API_KEY")

# List pods
pods = runpod.get_pods()

# Create a pod
pod = runpod.create_pod(
    name="ace-step-dev",
    image_name="frankbria/ace-step:latest",
    gpu_type_id="NVIDIA GeForce RTX 4090",
    volume_in_gb=0,  # Using network volume instead
    network_volume_id="vol_abc123",
    ports="8001/http",
    env={"ACESTEP_API_KEY": os.getenv("ACEMUSIC_API_KEY")}
)

# Stop (preserves volume, stops compute billing)
runpod.stop_pod(pod["id"])

# Resume (restarts with same volume)
runpod.resume_pod(pod["id"])

# Terminate (fully deletes pod, volume persists separately)
runpod.terminate_pod(pod["id"])
```

**Serverless Endpoint Management:**
```python
# Deploy endpoint
endpoint = runpod.create_endpoint(
    name="ace-step-prod",
    template_id="tmpl_abc123",
    gpu_ids=["NVIDIA GeForce RTX 4090"],
    network_volume_id="vol_abc123",
    workers_min=0,      # Scale to zero
    workers_max=3,       # Max concurrent workers
    idle_timeout=60,     # Seconds before scaling down
    flash_boot=True      # Fast cold starts
)

# Call endpoint
result = runpod.run(
    endpoint["id"],
    input={
        "prompt": "upbeat pop song with piano",
        "lyrics": "[Verse]\nHello world...",
        "inference_steps": 8,
        "model": "turbo"
    }
)
```

---

## 4. Hybrid Architecture

### 4.1 Routing Logic

The platform API layer routes generation requests based on availability and user preference:

```
Request arrives at Platform API
    │
    ├─ Is local GPU available and user prefers local?
    │   └─ YES → Forward to http://localhost:8001
    │
    ├─ Is local GPU busy or unavailable?
    │   └─ YES → Forward to RunPod serverless endpoint
    │
    ├─ Does the request require XL model at full precision?
    │   └─ YES → Forward to RunPod (needs 20GB+ VRAM)
    │
    └─ User explicitly selected "Remote GPU"?
        └─ YES → Forward to RunPod
```

### 4.2 Configuration

```bash
# .env additions for hybrid mode
ACEMUSIC_API_KEY=108030f6e31f4e8694b2d8d534854137
ACEMUSIC_BASE_URL=https://api.acemusic.ai

# Local ACE-Step server
ACESTEP_LOCAL_URL=http://localhost:8001
ACESTEP_LOCAL_ENABLED=true

# RunPod remote
RUNPOD_API_KEY=your_runpod_api_key
RUNPOD_ENDPOINT_ID=your_endpoint_id
RUNPOD_ENDPOINT_URL=https://api.runpod.ai/v2/{endpoint_id}/run
RUNPOD_ENABLED=true

# Routing preference: local_first | remote_first | remote_only | local_only
COMPUTE_PREFERENCE=local_first
```

### 4.3 Platform API Proxy

The platform's FastAPI backend acts as a unified gateway:

```
┌─────────────────────────────────────────────────┐
│              Platform API (FastAPI)              │
│                                                   │
│  POST /api/generate                              │
│    ├─ Validates request                          │
│    ├─ Checks compute routing preference          │
│    ├─ Forwards to local or RunPod                │
│    ├─ Streams progress updates to client         │
│    └─ Stores result in workspace                 │
│                                                   │
│  GET /api/compute/status                         │
│    ├─ Local GPU: available/busy/offline           │
│    └─ RunPod: active workers / scaling status    │
└─────────────────────────────────────────────────┘
         │                       │
         ▼                       ▼
   ┌───────────┐        ┌──────────────────┐
   │  Local     │        │  RunPod          │
   │  ACE-Step  │        │  Serverless      │
   │  :8001     │        │  Endpoint        │
   └───────────┘        └──────────────────┘
```

### 4.4 VST3 Plugin Routing

The VST3 plugin connects to the Platform API, not directly to ACE-Step:

```
VST3 Plugin → http://localhost:3000/api/generate → Platform API → Local or RunPod
```

This means the plugin doesn't need to know about RunPod. The Platform API handles routing transparently.

---

## 5. Docker Image & Container Setup

### 5.1 Dockerfile

```dockerfile
FROM pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install uv

# Clone ACE-Step (or copy from build context)
RUN git clone https://github.com/frankbria/ACE-Step-1.5.git /app/ACE-Step-1.5

WORKDIR /app/ACE-Step-1.5

# Install Python dependencies
RUN uv venv && uv sync

# For serverless: install runpod SDK
RUN pip install runpod requests

# Copy handler for serverless mode
COPY handler.py /app/handler.py

# Expose API port
EXPOSE 8001

# Default: start API server directly (for pods)
# For serverless: override CMD to run handler.py
CMD ["uv", "run", "acestep-api"]
```

### 5.2 Build & Push

```bash
# Build the image
docker build -t frankbria/ace-step:latest .

# Push to Docker Hub (RunPod pulls from here)
docker push frankbria/ace-step:latest
```

### 5.3 RunPod Template

Create a template in the RunPod dashboard:
- **Image:** `frankbria/ace-step:latest`
- **Expose ports:** `8001/http`
- **Volume mount:** `/workspace/models` (Network Volume)
- **Environment variables:** `ACESTEP_API_KEY`, `HF_HOME=/workspace/models/.cache`
- **Start command (pod):** `uv run acestep-api`
- **Start command (serverless):** `python /app/handler.py`

---

## 6. API Gateway & Routing

### 6.1 Unified API Contract

Regardless of where the model runs, the Platform API exposes a single interface:

```
POST /api/generate
Content-Type: application/json
Authorization: Bearer {user_token}

{
  "prompt": "upbeat indie rock with jangly guitars",
  "lyrics": "[Verse]\nWalking down the street...",
  "vocal_language": "en",
  "instrumental": false,
  "model": "turbo",
  "inference_steps": 8,
  "duration": 120,
  "bpm": 128,
  "key": "C major",
  "seed": -1,
  "compute_target": "auto"    // "auto" | "local" | "remote"
}
```

**Response (async):**
```json
{
  "job_id": "job_abc123",
  "status": "queued",
  "compute_target": "local",
  "estimated_time_seconds": 12
}
```

**Polling:**
```
GET /api/generate/{job_id}/status

{
  "job_id": "job_abc123",
  "status": "completed",
  "clips": [
    {"id": "clip_1", "url": "/api/clips/clip_1/audio", "format": "wav", "duration": 120.5},
    {"id": "clip_2", "url": "/api/clips/clip_2/audio", "format": "wav", "duration": 119.8}
  ]
}
```

### 6.2 Health Check Endpoints

```
GET /api/compute/status

{
  "local": {
    "available": true,
    "gpu": "NVIDIA RTX 4070 Ti Super",
    "vram_total_gb": 16,
    "vram_used_gb": 4.7,
    "active_jobs": 1,
    "models_loaded": ["turbo", "xl-sft"]
  },
  "remote": {
    "available": true,
    "provider": "runpod",
    "endpoint_id": "ep_abc123",
    "active_workers": 0,
    "max_workers": 3,
    "status": "idle"
  },
  "routing": "local_first"
}
```

---

## 7. Security

### 7.1 API Key Management

| Key | Storage | Purpose |
|---|---|---|
| `ACEMUSIC_API_KEY` | `.env` (local) | Authenticates requests to the ACE-Step API server |
| `RUNPOD_API_KEY` | `.env` (local) | Authenticates with RunPod management API |
| `ACESTEP_API_KEY` | RunPod env var | Secures the remote ACE-Step server |

### 7.2 Network Security
- **Local:** ACE-Step server binds to `localhost` only (not `0.0.0.0`). Only the Platform API can reach it.
- **Remote (Serverless):** RunPod endpoints are authenticated via RunPod API key in the request header. Not publicly accessible without the key.
- **Remote (Pod):** RunPod proxy URLs are ephemeral and authenticated. For additional security, the ACE-Step API key is required.
- **Platform API:** User authentication (OAuth/JWT) is enforced at the Platform API layer before any request reaches the model.

### 7.3 Secrets Never in Docker Images
- Model API keys are passed as environment variables at runtime, never baked into Docker images.
- RunPod API key is stored only in the platform's `.env` file, never committed to git.

---

## 8. Cost Analysis

### 8.1 Local-Only Cost
| Item | Cost |
|---|---|
| GPU compute | $0 (hardware already owned) |
| Electricity | ~$0.05–0.10/hr under load (varies by region) |
| **Total per song** | **~$0.01** (electricity only) |

### 8.2 RunPod Serverless Cost (RTX 4090)

| Scenario | Compute Time | Cost |
|---|---|---|
| **1 song (Turbo, 8 steps)** | ~5s | ~$0.001 |
| **1 song (Standard, 32 steps)** | ~30s | ~$0.004 |
| **1 song (XL-SFT, 64 steps)** | ~60s | ~$0.007 |
| **10 songs/day (mixed)** | ~5 min | ~$0.04 |
| **100 songs/day (mixed)** | ~50 min | ~$0.37 |
| **Network Volume (30GB)** | Always-on | ~$2.10/month |
| **Idle time** | — | **$0** |

### 8.3 RunPod Pod Cost (RTX 4090, On-Demand)

| Scenario | Duration | Cost |
|---|---|---|
| **2-hour session** | 2 hrs | ~$0.88 |
| **8-hour workday** | 8 hrs | ~$3.52 |
| **Pod stopped overnight** | Storage only | ~$0.07/day |
| **Monthly (4 hrs/day, 20 days)** | 80 hrs | ~$35.20 + $2.10 storage |

### 8.4 Cost Comparison Summary

| Usage Pattern | Local | Serverless | Pod |
|---|---|---|---|
| **Light (10 songs/day)** | ~$0.10/day | ~$0.04/day + $0.07 storage | ~$1.76/day (2hr session) |
| **Medium (50 songs/day)** | ~$0.50/day | ~$0.18/day + $0.07 storage | ~$3.52/day (4hr session) |
| **Heavy (200 songs/day)** | ~$2.00/day | ~$0.74/day + $0.07 storage | ~$7.04/day (8hr session) |

**Conclusion:** Local is cheapest. Serverless is ideal for overflow/remote access. Pods are best for long interactive sessions or development.

---

## 9. Operational Runbook

### 9.1 First-Time Setup

```bash
# 1. Local setup
git clone https://github.com/frankbria/ACE-Step-1.5.git
cd ACE-Step-1.5
uv venv && uv sync
uv run acestep-api  # Downloads weights on first run

# 2. RunPod setup
pip install runpod
# Create Network Volume via dashboard (region: US-TX-3, 30GB)
# Create pod, mount volume, download weights (see §3.3)
# Build & push Docker image (see §5)
# Deploy serverless endpoint or create pod template
```

### 9.2 Daily Workflow

```bash
# Start local server
cd ~/ACE-Step-1.5
export ACESTEP_API_KEY=$(grep ACEMUSIC_API_KEY ~/projects/auto-music-studio/.env | cut -d= -f2)
uv run acestep-api

# Start platform
cd ~/projects/auto-music-studio
# Platform auto-detects local server and configures routing
```

### 9.3 Switching to Remote

```bash
# Option 1: Set preference in .env
COMPUTE_PREFERENCE=remote_first

# Option 2: Per-request via API
curl -X POST http://localhost:3000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "epic orchestral", "compute_target": "remote"}'
```

### 9.4 Monitoring

```bash
# Local server stats
curl http://localhost:8001/v1/stats

# RunPod endpoint status
python3 -c "
import runpod
runpod.api_key = 'your_key'
print(runpod.get_endpoint('ep_abc123'))
"
```

### 9.5 Troubleshooting

| Symptom | Check | Fix |
|---|---|---|
| Local server not responding | `curl localhost:8001/v1/stats` | Restart `uv run acestep-api` |
| VRAM out of memory | `nvidia-smi` | Switch to Turbo model or remote |
| RunPod cold start too slow | Check FlashBoot setting | Enable FlashBoot, or add 1 Active Worker |
| RunPod endpoint 403 | API key in request header | Verify `RUNPOD_API_KEY` in `.env` |
| Generated audio is empty | Check inference steps | Increase steps (min 8 for Turbo, 32 for Standard) |

---

*End of deployment guide.*
