## Layer 2: Platform API

*Goal: Wrap the CLI foundation in a FastAPI service with authentication, async job processing, compute routing, mastering, distribution, and export APIs. After this layer, the platform is fully operational via HTTP — any client (web, mobile, plugin) can consume it.*

---

### Stage 8: API Foundation

**Overview:** Stand up the FastAPI project with versioned routes, MongoDB persistence, OAuth2 authentication, user management, and file storage. This stage replaces the CLI's local SQLite with a shared database and adds multi-user support. Every subsequent API stage builds on these primitives.

---

#### US-8.1: FastAPI Project and Versioned Routes

**As a** developer, **I want** a properly structured FastAPI application with versioned routes and auto-generated docs, **so that** I have a stable API surface that clients can depend on from day one.

**Description:**
Bootstrap the `api/` directory inside the monorepo with a FastAPI app, versioned under `/api/v1/`. Include health check, CORS configuration for local and future web clients, and OpenAPI/Swagger docs at `/docs`.

**Functional Requirements:**
- FastAPI app with `/api/v1/` route prefix
- `GET /api/v1/health` returns server status, version, and uptime
- CORS middleware configured with allowed origins (localhost initially, configurable via env)
- OpenAPI docs available at `/docs` and `/redoc`
- Environment-based configuration using pydantic-settings (`.env` file)
- Uvicorn runner with reload for development

**Acceptance Criteria:**
- [ ] `uv run uvicorn acemusic.api.main:app --reload` starts without error
- [ ] `GET /api/v1/health` returns 200 with `{"status": "ok", "version": "..."}`
- [ ] `/docs` renders the Swagger UI with all registered endpoints
- [ ] CORS headers are present in responses for configured origins
- [ ] Requests to `/api/v2/` return 404 (no version leak)

---

#### US-8.2: MongoDB Connection and Core Collections

**As a** developer, **I want** MongoDB connected with schemas for songs, users, and workspaces, **so that** the API has a persistent, scalable data layer from the start.

**Description:**
Establish the MongoDB connection using Motor (async driver) with Beanie or raw Motor documents. Define the core collections that the platform needs: users, workspaces, clips, and jobs. Seed a default workspace on user creation.

**Functional Requirements:**
- Async MongoDB connection via Motor with connection pooling
- Collections: `users`, `workspaces`, `clips`, `jobs`
- Beanie ODM models (or Pydantic + Motor) for each collection with validation
- Database name and connection string configurable via environment variables
- Startup event verifies connectivity; fails fast if MongoDB is unreachable
- Indexes on: `clips.workspace_id`, `clips.user_id`, `clips.created_at`, `users.email`

**Acceptance Criteria:**
- [ ] Application connects to MongoDB on startup and logs success
- [ ] If MongoDB is down, the app exits with a clear error (not a silent hang)
- [ ] Collections are created with defined indexes on first run
- [ ] CRUD operations on each collection work from test fixtures

---

#### US-8.3: OAuth2 Authentication and JWT Tokens

**As a** musician, **I want to** sign in with my Google or Discord account, **so that** I can access my workspaces and clips securely without creating yet another password.

**Description:**
Implement OAuth2 login via Google and Discord identity providers. On successful auth, issue a JWT access token (short-lived) and refresh token (long-lived). All subsequent API requests require a valid Bearer token.

**Functional Requirements:**
- OAuth2 authorization code flow for Google and Discord
- JWT access token (15-minute expiry) and refresh token (7-day expiry)
- `POST /api/v1/auth/login/{provider}` initiates OAuth flow
- `POST /api/v1/auth/callback/{provider}` handles the redirect
- `POST /api/v1/auth/refresh` exchanges a refresh token for a new access token
- `POST /api/v1/auth/logout` revokes the refresh token
- Token payload includes: user_id, email, subscription_tier
- Protected routes return 401 for missing/invalid tokens

**Acceptance Criteria:**
- [ ] Google OAuth login returns a valid JWT on success
- [ ] Discord OAuth login returns a valid JWT on success
- [ ] Expired access tokens return 401; refresh token exchange returns a new access token
- [ ] Invalid or revoked refresh tokens return 401
- [ ] All `/api/v1/` routes (except health, auth) return 401 without a Bearer token

---

#### US-8.4: User Registration and Profile CRUD

**As a** musician, **I want to** create and manage my profile (display name, handle, avatar, bio, style tags), **so that** my identity is established on the platform.

**Description:**
On first OAuth login, a user record is created automatically with sensible defaults. The user can then update their profile. Handles must be unique. Profile data is stored in the `users` collection.

**Functional Requirements:**
- Auto-create user on first login (email, provider, default display name from OAuth)
- `GET /api/v1/users/me` returns the authenticated user's profile
- `PATCH /api/v1/users/me` updates display name, handle, bio, style tags
- `PUT /api/v1/users/me/avatar` uploads a profile image
- Handle uniqueness enforced at the database level
- Handle format validation: alphanumeric + hyphens, 3-30 characters

**Acceptance Criteria:**
- [ ] First login creates a user record with data from the OAuth provider
- [ ] `GET /api/v1/users/me` returns the full profile for the authenticated user
- [ ] `PATCH /api/v1/users/me` updates fields and returns the updated profile
- [ ] Duplicate handle returns 409 Conflict
- [ ] Invalid handle format returns 422 with a descriptive error

---

#### US-8.5: File Storage Abstraction

**As a** developer, **I want** a file storage layer that works with local filesystem now and S3-compatible storage later, **so that** audio files are managed through a single interface regardless of deployment.

**Description:**
Create a storage abstraction with a common interface (upload, download, delete, get_url) and two implementations: LocalStorage (for development) and S3Storage (for production). All audio file operations go through this layer.

**Functional Requirements:**
- `StorageBackend` abstract class with methods: `upload(path, data)`, `download(path)`, `delete(path)`, `get_url(path)`
- `LocalStorage` implementation storing files under a configurable directory
- `S3Storage` implementation using `boto3` with S3-compatible endpoints (AWS, MinIO, Backblaze B2)
- Backend selection via `STORAGE_BACKEND=local|s3` environment variable
- Files organized as: `{user_id}/{workspace_id}/clips/{clip_id}.{format}`
- Signed URLs for S3 downloads (configurable expiry)

**Acceptance Criteria:**
- [ ] `LocalStorage` uploads and downloads files correctly
- [ ] `S3Storage` uploads and downloads files correctly (tested with MinIO or localstack)
- [ ] Switching `STORAGE_BACKEND` between `local` and `s3` requires no code changes in callers
- [ ] `get_url` returns a local file path for LocalStorage and a signed URL for S3Storage
- [ ] Deleting a file removes it from storage and returns no error on missing files

---

**Stage 8 Completion Criteria:**
- FastAPI app starts and serves versioned routes at `/api/v1/`
- MongoDB is connected with indexed collections for users, workspaces, clips, and jobs
- OAuth2 login works for Google and Discord, issuing JWT tokens
- User profile CRUD is fully functional
- File storage abstraction works with local filesystem
- Health endpoint, CORS, and OpenAPI docs are operational
- All endpoints are covered by integration tests against a real MongoDB instance

---

### Stage 9: Generation API

**Overview:** Expose the core music generation pipeline over HTTP. This stage wraps the CLI's generate, workspace, clip, and preset logic in REST endpoints with async job processing and credit deduction. After this stage, any HTTP client can submit prompts, poll for results, and manage clips.

---

#### US-9.1: Generation Endpoint

**As a** musician, **I want to** submit a generation request via the API with all creative parameters, **so that** I can generate music from any client — not just the CLI.

**Description:**
The generation endpoint accepts the full parameter set (prompt, style, lyrics, BPM, key, duration, model, seed, inference steps, etc.) and returns a job ID for async tracking. Supports all three creation modes: text-to-music, sounds (one-shot/loop), and advanced mode with separate style/lyrics fields.

**Functional Requirements:**
- `POST /api/v1/generate` accepts a JSON body with all generation parameters
- Parameters: prompt, style, lyrics, vocal_language, instrumental, bpm, key, time_signature, duration, seed, inference_steps, model, weirdness, style_influence, format, thinking, mode (song|sound), sound_type (one-shot|loop)
- Validates all parameters (ranges, enums) and returns 422 on invalid input
- Creates a job record in the `jobs` collection with status `queued`
- Returns `{"job_id": "...", "status": "queued", "estimated_time_seconds": N}`
- Job is dispatched to the async task queue for processing

**Acceptance Criteria:**
- [ ] `POST /api/v1/generate` with a valid body returns 202 with a job_id
- [ ] Invalid parameters (e.g., BPM of 999) return 422 with field-level errors
- [ ] Job record is created in MongoDB with status `queued`
- [ ] Unauthenticated requests return 401
- [ ] All three modes (song, sound one-shot, sound loop) are accepted

---

#### US-9.2: Async Job Queue and Processing

**As a** developer, **I want** generation requests processed asynchronously with status tracking, **so that** clients are not blocked during the 5-60 second generation time.

**Description:**
Implement an async job processor that picks up queued jobs, forwards them to the ACE-Step-1.5 API, polls for completion, stores the resulting audio, and updates the job status. Initially uses asyncio tasks; designed for later migration to Redis/Celery.

**Functional Requirements:**
- Job processor runs as background tasks within the FastAPI process
- Job lifecycle: `queued` -> `processing` -> `completed` | `failed`
- On completion: audio files stored via the storage abstraction, clip records created in MongoDB
- On failure: error message stored in the job record, status set to `failed`
- Concurrency limit configurable (default: 2 concurrent jobs)
- `GET /api/v1/jobs/{id}/status` returns current status, progress, and result (clip IDs when complete)

**Acceptance Criteria:**
- [ ] A queued job transitions to `processing` and then `completed` when ACE-Step is running
- [ ] `GET /api/v1/jobs/{id}/status` returns the current state at each lifecycle phase
- [ ] Completed jobs include clip IDs and audio URLs in the response
- [ ] Failed jobs include an error message
- [ ] Two concurrent jobs process without deadlock or corruption

---

#### US-9.3: Clip Audio Retrieval

**As a** musician, **I want to** stream or download my generated audio clips via the API, **so that** I can listen to results from any client.

**Description:**
Serve audio files with proper content-type headers, supporting both full download and streaming via HTTP range requests.

**Functional Requirements:**
- `GET /api/v1/clips/{id}/audio` returns the audio file
- Content-Type set correctly based on format (audio/wav, audio/flac, audio/mpeg, etc.)
- Support HTTP Range headers for streaming/seeking
- `?format=mp3` query param for on-the-fly format conversion (optional, WAV by default)
- 404 if clip does not exist or does not belong to the authenticated user
- 403 if clip belongs to another user and is private

**Acceptance Criteria:**
- [ ] `GET /api/v1/clips/{id}/audio` returns a playable audio file with correct Content-Type
- [ ] Range request returns 206 Partial Content with the requested byte range
- [ ] Requesting another user's private clip returns 403
- [ ] Requesting a non-existent clip returns 404

---

#### US-9.4: Workspace and Clip CRUD

**As a** musician, **I want to** create, list, update, and delete workspaces and clips via the API, **so that** I can organize my music library from any client.

**Description:**
Expose the workspace and clip management operations as REST endpoints. Clips support search, filtering, and sorting. A default workspace is created when a new user is registered.

**Functional Requirements:**
- Workspace endpoints: `POST /api/v1/workspaces`, `GET /api/v1/workspaces`, `GET /api/v1/workspaces/{id}`, `PATCH /api/v1/workspaces/{id}`, `DELETE /api/v1/workspaces/{id}`
- Clip endpoints: `GET /api/v1/clips` (list with pagination), `GET /api/v1/clips/{id}`, `PATCH /api/v1/clips/{id}`, `DELETE /api/v1/clips/{id}`
- Clip list supports: `?workspace_id=`, `?search=`, `?style=`, `?bpm_min=`, `?bpm_max=`, `?key=`, `?model=`, `?sort=newest|oldest`, `?page=`, `?per_page=`
- Deleting a workspace with clips requires `?force=true` or returns 409
- All endpoints scoped to the authenticated user

**Acceptance Criteria:**
- [ ] Full CRUD lifecycle works for workspaces (create, list, get, update, delete)
- [ ] Full CRUD lifecycle works for clips (list, get, update, delete)
- [ ] Clip search filters by style, BPM range, key, and model
- [ ] Pagination returns correct page counts and respects per_page limits
- [ ] Deleting a non-empty workspace without `?force=true` returns 409

---

#### US-9.5: Preset CRUD

**As a** musician, **I want to** save and load generation presets via the API, **so that** I can reuse my favorite parameter combinations across sessions and devices.

**Description:**
Presets store a named snapshot of generation parameters. They can be applied when submitting a generation request by including a preset_id, with individual parameters overriding preset values.

**Functional Requirements:**
- `POST /api/v1/presets` creates a preset with name and parameter snapshot
- `GET /api/v1/presets` lists all presets for the authenticated user
- `GET /api/v1/presets/{id}` returns a single preset
- `PATCH /api/v1/presets/{id}` updates a preset
- `DELETE /api/v1/presets/{id}` deletes a preset
- `POST /api/v1/generate` accepts an optional `preset_id`; explicit parameters override preset values

**Acceptance Criteria:**
- [ ] Creating and retrieving a preset returns all saved parameters
- [ ] Generating with a preset_id applies the preset's parameters
- [ ] Explicit parameters in the generate request override preset values
- [ ] Presets are scoped to the authenticated user (no cross-user access)

---

#### US-9.6: Credit Deduction

**As a** musician, **I want** credits deducted when I generate music, **so that** the platform can enforce usage limits based on my subscription tier.

**Description:**
Each generation consumes credits from the user's balance. The generation endpoint checks the user's credit balance before processing and rejects requests when credits are insufficient. Credit costs vary by action type.

**Functional Requirements:**
- User record includes `credits_balance` and `subscription_tier` fields
- `POST /api/v1/generate` checks credit balance before queuing the job
- Credit cost: 1 credit per song generation (2 clips), 0.5 credits per sound generation
- Insufficient credits return 402 Payment Required with remaining balance
- `GET /api/v1/users/me/credits` returns current balance and usage history
- Credits are deducted atomically when the job is queued (not on completion)

**Acceptance Criteria:**
- [ ] Generation with sufficient credits succeeds and reduces the balance
- [ ] Generation with insufficient credits returns 402
- [ ] Credit balance is visible via `GET /api/v1/users/me/credits`
- [ ] Concurrent generation requests do not cause double-deduction (atomic update)

---

**Stage 9 Completion Criteria:**
- Generation endpoint accepts all parameter modes and returns async job IDs
- Job queue processes requests and tracks status through completion or failure
- Clip audio is retrievable via streaming-capable endpoints
- Workspace and clip CRUD with search/filter/sort is fully functional
- Presets are saveable and applicable to generation
- Credit deduction enforces usage limits
- All endpoints covered by integration tests against real MongoDB and ACE-Step

---

### Stage 10: Audio Processing & Iterative Generation API

**Overview:** Expose all audio editing and iterative generation modes as API endpoints. This stage wraps the CLI's crop, speed, stems, MIDI, remaster, extend, cover, remix, repaint, mashup, sample, add-vocal, and full-song operations behind REST endpoints with background task processing and lineage tracking.

---

#### US-10.1: Audio Editing Endpoints

**As a** musician, **I want to** crop, adjust speed, and remaster clips via the API, **so that** I can refine my music from any client without using the CLI.

**Description:**
Expose the non-generative audio processing operations as POST endpoints. Each operation creates a new clip (non-destructive) with lineage tracking. Operations run as background tasks since they may take seconds to minutes.

**Functional Requirements:**
- `POST /api/v1/clips/{id}/crop` with `{start, end, fade_in, fade_out, snap_to_beat}`
- `POST /api/v1/clips/{id}/speed` with `{multiplier, target_bpm, preserve_pitch}`
- `POST /api/v1/clips/{id}/remaster` with `{target_lufs}` (optional, default -14)
- All three return a job_id for async tracking (reuses the job queue from Stage 9)
- Resulting clips include `parent_clip_ids` and `generation_mode` in metadata
- Original clips are never modified

**Acceptance Criteria:**
- [ ] Crop creates a new clip with the correct duration (end - start)
- [ ] Speed adjustment with `multiplier: 2.0` produces a clip half the original duration
- [ ] Remaster produces a clip with loudness approximately at the target LUFS
- [ ] All operations return job IDs and track status via `GET /api/v1/jobs/{id}/status`
- [ ] Original clips are unchanged after any operation

---

#### US-10.2: Stems and MIDI Extraction Endpoints

**As a** musician, **I want to** extract stems and MIDI from clips via the API, **so that** I can get individual parts for remixing or DAW import.

**Description:**
Stem separation and MIDI extraction are computationally intensive and run as background tasks. Results are stored as child clips (stems) or downloadable files (MIDI).

**Functional Requirements:**
- `POST /api/v1/clips/{id}/stems` triggers stem separation (vocals, drums, bass, other)
- `POST /api/v1/clips/{id}/midi` triggers MIDI extraction (melody, chords, drums, bass)
- Both return a job_id for async tracking
- Stem results: 4 new clip records linked to the parent with appropriate labels
- MIDI results: downloadable MIDI files stored in the storage layer
- `GET /api/v1/clips/{id}/stems` returns the stem clip IDs if separation has been done
- `GET /api/v1/clips/{id}/midi` returns download URLs for extracted MIDI files

**Acceptance Criteria:**
- [ ] Stem separation produces 4 playable audio clips linked to the parent
- [ ] MIDI extraction produces downloadable .mid files
- [ ] Re-requesting stems/MIDI for a clip that already has them returns cached results
- [ ] Job status is trackable through completion
- [ ] Stems are time-aligned and equal length

---

#### US-10.3: Iterative Generation Endpoints

**As a** musician, **I want to** extend, cover, remix, repaint, mashup, sample from, and add vocals to clips via the API, **so that** I can iteratively build and refine songs from any client.

**Description:**
Expose all AI-powered iterative generation modes as POST endpoints. Each takes a source clip (or multiple clips for mashup) plus mode-specific parameters and produces a new clip with lineage tracking.

**Functional Requirements:**
- `POST /api/v1/clips/{id}/extend` with `{duration, from_point, style_override, lyrics}`
- `POST /api/v1/clips/{id}/cover` with `{style, voice_id, lyrics_override}`
- `POST /api/v1/clips/{id}/remix` with `{style}`
- `POST /api/v1/clips/{id}/repaint` with `{start, end, prompt, style}`
- `POST /api/v1/mashup` with `{clip_ids[], blend_mode, style}`
- `POST /api/v1/clips/{id}/sample` with `{start, end, role, prompt}`
- `POST /api/v1/clips/{id}/add-vocal` with `{lyrics, voice_id, vocal_style}`
- All return job_ids and deduct appropriate credits
- All produce new clips with `parent_clip_ids` and `generation_mode` set

**Acceptance Criteria:**
- [ ] Each endpoint returns a job_id and the resulting clip is accessible on completion
- [ ] Extend produces a clip longer than the source by approximately the requested duration
- [ ] Cover preserves melodic structure while changing style
- [ ] Repaint modifies only the specified time range
- [ ] Mashup accepts 2+ clip IDs and produces a single blended clip
- [ ] All new clips have correct lineage metadata linking to their source(s)

---

#### US-10.4: Full Song Assembly Endpoint

**As a** musician, **I want to** generate a full-length song from a short clip via the API, **so that** I can turn a 30-second idea into a complete 3-4 minute track.

**Description:**
Wraps the auto-extend pipeline from Stage 6 as an API endpoint. Plans a song structure and executes sequential extends. Returns a single assembled clip.

**Functional Requirements:**
- `POST /api/v1/clips/{id}/full-song` with `{target_duration, structure_plan}`
- Default target duration: 210 seconds (~3.5 minutes)
- Optional structure_plan override (e.g., `["intro", "verse", "chorus", "verse", "chorus", "bridge", "outro"]`)
- Creates a single long-running job that chains multiple extend operations
- Returns progress updates per section via the job status endpoint
- Final result is one assembled clip with all sections concatenated

**Acceptance Criteria:**
- [ ] Full-song produces a clip of approximately the target duration
- [ ] Job status shows progress per section (e.g., "Processing section 3 of 7")
- [ ] The output clip has audible structural variety (not pure repetition)
- [ ] Source clip shorter than 60 seconds is required; longer clips return 422
- [ ] Credits are deducted based on the number of extend operations performed

---

#### US-10.5: Batch Operations

**As a** musician, **I want to** run stems extraction or export on multiple clips at once, **so that** I can process an entire workspace efficiently.

**Description:**
Batch endpoints accept an array of clip IDs and queue individual operations for each. A batch job tracks overall progress across all sub-jobs.

**Functional Requirements:**
- `POST /api/v1/batch/stems` with `{clip_ids[]}`
- `POST /api/v1/batch/export` with `{clip_ids[], format}`
- Both return a batch_job_id with individual sub-job IDs
- `GET /api/v1/batch/{batch_id}/status` returns overall progress and per-clip status
- Batch size limit: 50 clips per request

**Acceptance Criteria:**
- [ ] Batch stems processes all provided clips and tracks individual status
- [ ] Batch export produces files for all clips in the requested format
- [ ] Requesting more than 50 clips returns 422
- [ ] Individual failures do not halt the entire batch (partial success reported)

---

#### US-10.6: Lineage Tracking

**As a** musician, **I want to** see the full creation history of any clip, **so that** I can trace how a song evolved through extends, covers, and remixes.

**Description:**
Every clip stores its lineage: the parent clip(s) it was derived from, the operation that created it, and the parameters used. The API exposes this as a queryable graph.

**Functional Requirements:**
- Every clip document includes: `parent_clip_ids` (array), `generation_mode`, `generation_params`
- `GET /api/v1/clips/{id}/lineage` returns the full ancestry tree (parents, grandparents, etc.)
- `GET /api/v1/clips/{id}/children` returns clips derived from this clip
- Lineage response includes clip IDs, titles, generation modes, and creation timestamps
- Maximum lineage depth: 50 levels

**Acceptance Criteria:**
- [ ] A clip created via extend shows its parent in the lineage response
- [ ] A clip with multiple parents (mashup) shows all sources
- [ ] Lineage traversal returns the full tree up to the original generation
- [ ] Children endpoint returns all clips derived from a given clip
- [ ] Lineage queries complete within 500ms for chains up to 20 levels deep

---

**Stage 10 Completion Criteria:**
- All audio editing endpoints (crop, speed, remaster) work and produce correct results
- Stems and MIDI extraction endpoints run as background tasks and cache results
- All iterative generation modes (extend, cover, remix, repaint, mashup, sample, add-vocal) are functional
- Full-song assembly chains extends and reports per-section progress
- Batch operations process multiple clips with partial failure handling
- Lineage tracking records and exposes the full clip derivation graph
- All operations are non-destructive and track parent-child relationships

---

### Stage 11: Compute Routing

**Overview:** Implement hybrid compute routing so generation requests can run on the local GPU, a remote RunPod serverless endpoint, or automatically fall back between them. This stage adds the infrastructure that makes the platform usable from anywhere — not just the machine running the local GPU.

---

#### US-11.1: Compute Routing Engine

**As a** musician, **I want** the platform to automatically choose the best compute target for my generation, **so that** I get results whether I am at my workstation or on my laptop.

**Description:**
Implement a routing engine that evaluates the configured preference (local_first, remote_first, remote_only, local_only) and the current availability of each target to decide where to send a generation request. The compute_target parameter can also be set explicitly per request.

**Functional Requirements:**
- Routing modes: `local_first`, `remote_first`, `remote_only`, `local_only`
- Default mode configurable via `COMPUTE_PREFERENCE` environment variable
- `POST /api/v1/generate` accepts optional `compute_target` parameter (`auto`, `local`, `remote`)
- `auto` uses the configured preference with fallback logic
- Local availability check: ping `http://localhost:8001/v1/stats` with 2-second timeout
- Remote availability check: verify RunPod endpoint status via RunPod API
- Fallback: if preferred target is unavailable, try the other (unless mode is `*_only`)

**Acceptance Criteria:**
- [ ] `local_first` routes to local GPU when available and falls back to remote when not
- [ ] `remote_first` routes to RunPod when available and falls back to local when not
- [ ] `local_only` returns 503 when local GPU is unavailable (no fallback)
- [ ] `remote_only` returns 503 when RunPod is unavailable (no fallback)
- [ ] Per-request `compute_target: "local"` overrides the default preference
- [ ] The chosen target is recorded in the job record and visible in status responses

---

#### US-11.2: RunPod Serverless Integration

**As a** developer, **I want** the platform to submit, poll, and retrieve results from RunPod serverless endpoints, **so that** remote GPU generation is fully automated.

**Description:**
Integrate with RunPod's serverless API to submit generation jobs, poll for status, and retrieve audio results. Handle cold starts, timeouts, and error responses gracefully.

**Functional Requirements:**
- Submit jobs to `https://api.runpod.ai/v2/{endpoint_id}/run` with RunPod API key
- Poll status at `https://api.runpod.ai/v2/{endpoint_id}/status/{job_id}`
- Retrieve results including generated audio data
- Handle RunPod-specific states: `IN_QUEUE`, `IN_PROGRESS`, `COMPLETED`, `FAILED`
- Timeout: configurable per request (default: 300 seconds)
- Retry on transient errors (5xx responses) with exponential backoff (max 3 retries)
- `RUNPOD_API_KEY` and `RUNPOD_ENDPOINT_ID` from environment variables

**Acceptance Criteria:**
- [ ] A generation request routed to RunPod returns a completed clip
- [ ] Cold start latency is tolerated without premature timeout
- [ ] RunPod errors are surfaced as meaningful messages in the job status
- [ ] Transient failures are retried before marking the job as failed
- [ ] Missing RunPod configuration disables remote routing (does not crash the app)

---

#### US-11.3: Docker Image for ACE-Step

**As a** developer, **I want** a Docker image for ACE-Step-1.5 that works as both a RunPod serverless handler and a standalone API server, **so that** remote deployment is reproducible and versioned.

**Description:**
Build and publish a Docker image based on the PyTorch CUDA runtime with ACE-Step-1.5 installed. The image supports two modes: standalone API server (for pods) and RunPod serverless handler. Model weights are loaded from a Network Volume, not baked into the image.

**Functional Requirements:**
- Dockerfile based on `pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime`
- Installs ACE-Step-1.5 from the fork repository with all dependencies
- Default CMD starts the API server (`uv run acestep-api`)
- Serverless mode: `python /app/handler.py` as alternate CMD
- Handler implements RunPod's `runpod.serverless.start()` pattern
- Model weights loaded from `/workspace/models` (Network Volume mount point)
- Image published to Docker Hub as `frankbria/ace-step:latest`
- Image size target: under 10GB

**Acceptance Criteria:**
- [ ] `docker build` completes without error
- [ ] Container starts in API server mode and responds to `/v1/stats`
- [ ] Container starts in serverless mode and processes a RunPod handler event
- [ ] Model weights are loaded from the mounted volume (not from inside the image)
- [ ] Image is pushable to Docker Hub

---

#### US-11.4: Compute Status Endpoint

**As a** musician, **I want to** check the status of available compute targets, **so that** I know whether my local GPU is busy and whether remote is available before generating.

**Description:**
A status endpoint that aggregates health information from both local and remote compute targets into a single response.

**Functional Requirements:**
- `GET /api/v1/compute/status` returns combined status of local and remote targets
- Local status: available (bool), GPU name, VRAM total/used, active jobs, loaded models
- Remote status: available (bool), provider, endpoint_id, active workers, max workers, scaling status
- Current routing preference included in response
- Timeout: 3 seconds per target check (non-blocking, parallel)

**Acceptance Criteria:**
- [ ] With local GPU running: local status shows available with GPU details
- [ ] With local GPU stopped: local status shows unavailable
- [ ] With RunPod configured: remote status shows endpoint details
- [ ] With RunPod not configured: remote status shows unavailable (not an error)
- [ ] Response returns within 5 seconds even if one target is unreachable

---

#### US-11.5: RunPod Network Volume Setup Documentation

**As a** developer, **I want** a scripted setup process for the RunPod Network Volume with model weights, **so that** remote deployment can be reproduced or recovered quickly.

**Description:**
Provide a setup script and management commands for initializing the RunPod Network Volume with ACE-Step-1.5 model weights. The volume persists model weights so they only need to be downloaded once.

**Functional Requirements:**
- Setup script: `scripts/runpod-setup.py` that creates a Network Volume, spins up a temporary pod, downloads model weights, and stops the pod
- `GET /api/v1/compute/remote/volume` returns volume info (size, used, region)
- Script configurable for region and volume size
- Documentation of the one-time setup process in code comments
- Cost estimate displayed before creating resources

**Acceptance Criteria:**
- [ ] Setup script creates a Network Volume and downloads model weights
- [ ] Volume persists after the temporary pod is stopped
- [ ] Future serverless workers or pods can mount the volume and access weights
- [ ] Script is idempotent (re-running does not create duplicate volumes)

---

**Stage 11 Completion Criteria:**
- Compute routing engine correctly selects local or remote based on preference and availability
- RunPod serverless integration submits, polls, and retrieves generation results
- Docker image builds and runs in both API and serverless modes
- Compute status endpoint reports health of all targets
- Fallback logic gracefully handles target unavailability
- Network Volume setup is scripted and documented
- Tests cover all routing modes and fallback scenarios

---

### Stage 12: Mastering Pipeline API

**Overview:** Integrate external mastering services (Dolby.io, LANDR, Bakuage) to transform final mixes into distribution-ready masters. Musicians can submit clips for professional-grade mastering, choose loudness profiles, preview multiple results, and A/B compare against the original.

---

#### US-12.1: Mastering Job Submission

**As a** musician, **I want to** submit a clip for automated mastering with a target profile, **so that** my music sounds professional and meets platform loudness standards.

**Description:**
The mastering endpoint accepts a clip ID, a mastering profile, and an optional service preference. It uploads the audio to the selected mastering API and creates a job for tracking.

**Functional Requirements:**
- `POST /api/v1/mastering/jobs` with `{clip_id, profile, service, format}`
- Profiles: `streaming` (-14 LUFS), `soundcloud` (-12 LUFS), `club` (maximum loudness), `vinyl` (wide dynamic range), `custom` (user-specified LUFS target)
- Service: `dolby` (default), `landr`, `bakuage`
- Format: output audio format (wav, mp3, flac)
- Returns a mastering_job_id with status `queued`
- Credits deducted based on service (2-5 credits)

**Acceptance Criteria:**
- [ ] Submitting a mastering job returns a job_id with status `queued`
- [ ] Each profile maps to the correct LUFS target
- [ ] Invalid profile or service returns 422
- [ ] Insufficient credits returns 402
- [ ] Job record is created in MongoDB with all parameters

---

#### US-12.2: Dolby.io Integration

**As a** developer, **I want** full integration with Dolby.io's Music Mastering API, **so that** the primary mastering service works end-to-end.

**Description:**
Implement the Dolby.io mastering flow: authenticate with JWT, upload audio to Dolby's input storage, submit a mastering job, poll for completion, retrieve metrics, and download the mastered audio.

**Functional Requirements:**
- Authenticate with Dolby.io using API key to obtain a JWT
- Upload source audio to Dolby.io input URL
- Submit mastering job with profile-specific parameters
- Poll job status until completion
- Retrieve mastering metrics: loudness (LUFS), EQ across 16 bands, stereo image analysis
- Download mastered audio and store via the storage abstraction
- Support generating up to 5 preview variants per job
- `DOLBY_API_KEY` and `DOLBY_API_SECRET` from environment variables

**Acceptance Criteria:**
- [ ] End-to-end mastering via Dolby.io produces a mastered audio file
- [ ] Mastering metrics are stored in the job record and retrievable via API
- [ ] Up to 5 previews can be generated and individually auditioned
- [ ] Missing Dolby.io credentials disable the service (not crash the app)
- [ ] Audio quality is measurably improved (LUFS closer to target)

---

#### US-12.3: LANDR and Bakuage Fallback Integrations

**As a** developer, **I want** LANDR and Bakuage mastering integrations as alternatives, **so that** the platform has fallback options and service flexibility.

**Description:**
Implement secondary mastering service integrations. LANDR provides B2B API access with genre-aware processing. Bakuage provides an open REST API as a cost-effective fallback.

**Functional Requirements:**
- LANDR integration: submit audio, select loudness and style, poll, retrieve mastered audio
- Bakuage integration: create mastering via REST API, poll status, download result
- Both services implement the same `MasteringService` interface as Dolby.io
- Service selection via the `service` parameter on the mastering endpoint
- Automatic fallback: if the primary service fails, retry with the next available service

**Acceptance Criteria:**
- [ ] LANDR mastering produces a mastered audio file (when API access is configured)
- [ ] Bakuage mastering produces a mastered audio file
- [ ] Fallback from Dolby.io to Bakuage works when Dolby.io returns an error
- [ ] Each service returns its results in the same response format

---

#### US-12.4: Mastering Preview and A/B Comparison

**As a** musician, **I want to** preview multiple mastering results and compare them against the original, **so that** I can choose the best master for my release.

**Description:**
After mastering completes, the musician can audition up to 5 preview variants and A/B compare any preview against the unmastered original. Approving a preview promotes it to the final master.

**Functional Requirements:**
- `GET /api/v1/mastering/jobs/{id}` returns job status, previews, and metrics
- `GET /api/v1/mastering/jobs/{id}/previews` returns audio URLs for each preview variant
- `POST /api/v1/mastering/jobs/{id}/approve` with `{preview_id}` promotes a preview to the final master
- Approved master is saved as a new clip with `generation_mode: mastered` and linked to the source
- A/B comparison data: original clip URL + mastered clip URL + metrics diff

**Acceptance Criteria:**
- [ ] Multiple previews are accessible after mastering completes
- [ ] Approving a preview creates a new clip with mastered metadata
- [ ] The mastered clip is linked to the original via parent_clip_ids
- [ ] Metrics (LUFS, EQ) are available for both original and mastered versions
- [ ] Rejecting all previews allows resubmission with different parameters

---

#### US-12.5: Batch Mastering

**As a** musician, **I want to** master multiple clips with the same profile at once, **so that** I can prepare an entire album with consistent sound.

**Description:**
Batch mastering applies the same mastering profile and service to multiple clips. Each clip is processed as an individual mastering job, tracked under a single batch ID.

**Functional Requirements:**
- `POST /api/v1/mastering/batch` with `{clip_ids[], profile, service}`
- Returns a batch_id with individual mastering_job_ids
- `GET /api/v1/mastering/batch/{batch_id}/status` shows overall progress
- Batch size limit: 20 clips
- Credits deducted for each clip individually

**Acceptance Criteria:**
- [ ] Batch mastering processes all provided clips
- [ ] Each clip gets its own mastering job with independent status
- [ ] Overall batch progress is trackable via the batch status endpoint
- [ ] Individual failures do not halt the batch
- [ ] Exceeding the batch limit returns 422

---

**Stage 12 Completion Criteria:**
- Mastering jobs can be submitted with any supported profile and service
- Dolby.io integration works end-to-end (auth, upload, master, metrics, download)
- LANDR and Bakuage integrations work as alternatives
- Previews are generated, auditioned, and approved
- A/B comparison data is available for original vs. mastered
- Batch mastering processes multiple clips consistently
- All mastering endpoints are covered by integration tests

---

### Stage 13: Distribution Pipeline API

**Overview:** Build the distribution pipeline — from cover art generation through SoundCloud upload to guided distribution prep for LANDR and DistroKid. This stage takes a mastered clip and packages it with metadata, artwork, and identifiers into a release-ready package.

---

#### US-13.1: Cover Art Generation

**As a** musician, **I want to** generate AI cover art based on my song's style and mood, **so that** I have professional artwork for distribution without hiring a designer.

**Description:**
Integrates with an AI image generation API to produce cover art options based on the song's title, style tags, lyrics, and mood. The musician selects their preferred art, which is attached to the clip metadata.

**Functional Requirements:**
- `POST /api/v1/clips/{id}/artwork/generate` with optional `{style_prompt}` override
- Generates 4 cover art options (1024x1024 minimum, upscaled to 3000x3000 for distribution)
- Returns URLs for all 4 options
- `POST /api/v1/clips/{id}/artwork` with `{artwork_id}` selects the preferred art
- `PUT /api/v1/clips/{id}/artwork/upload` accepts a custom image upload (JPG/PNG, 3000x3000 minimum)
- Image validation: minimum resolution, acceptable formats, no corrupt files

**Acceptance Criteria:**
- [ ] Generating artwork produces 4 image options tied to the clip
- [ ] Selecting an artwork option attaches it to the clip metadata
- [ ] Uploading custom artwork validates resolution and format
- [ ] Images below 3000x3000 are rejected with a descriptive error
- [ ] Generated artwork visually reflects the song's style tags (manual verification)

---

#### US-13.2: SoundCloud OAuth and Upload

**As a** musician, **I want to** connect my SoundCloud account and upload mastered tracks directly from the platform, **so that** I can publish music without leaving my workflow.

**Description:**
Implement the full SoundCloud OAuth 2.1 flow for account linking and the track upload endpoint. The platform handles authentication, metadata mapping, and multipart file upload.

**Functional Requirements:**
- `POST /api/v1/distribution/soundcloud/connect` initiates SoundCloud OAuth 2.1 flow
- `POST /api/v1/distribution/soundcloud/callback` handles the OAuth redirect and stores tokens
- `GET /api/v1/distribution/soundcloud/status` returns connection status
- `POST /api/v1/distribution/soundcloud/upload` with `{clip_id, metadata_overrides}` uploads a track
- Metadata mapped: title, genre, description, bpm, key_signature, isrc, sharing (public/private), artwork
- Audio format: WAV or FLAC preferred, MP3 acceptable
- Upload size limit: 500MB (SoundCloud limit)
- Token refresh handled automatically when tokens expire

**Acceptance Criteria:**
- [ ] SoundCloud OAuth flow completes and stores access/refresh tokens
- [ ] Uploading a mastered clip to SoundCloud creates a track on the user's profile
- [ ] Metadata (title, genre, BPM) is correctly set on the SoundCloud track
- [ ] Cover art is uploaded alongside the audio
- [ ] Token refresh works transparently when the access token expires

---

#### US-13.3: Release Package Assembly

**As a** musician, **I want** the platform to assemble all required assets into a release package, **so that** I have everything needed for distribution in one place.

**Description:**
A release package bundles the mastered audio, cover art, metadata, lyrics, and credits into a validated, distribution-ready bundle. This package is the input for all distribution channels.

**Functional Requirements:**
- `POST /api/v1/releases` with `{clip_id, metadata}` creates a release package
- Required metadata: title, artist, genre, release_date
- Optional metadata: album_name, description, isrc, upc, copyright, is_explicit, language, credits
- Validates: mastered audio exists, cover art meets resolution requirements, required metadata is complete
- `GET /api/v1/releases/{id}` returns the package status and contents
- `PATCH /api/v1/releases/{id}` updates metadata before submission
- Package states: `draft`, `ready`, `submitted`, `live`, `rejected`

**Acceptance Criteria:**
- [ ] Creating a release with complete metadata and mastered audio returns status `ready`
- [ ] Missing required fields return 422 with specific field errors
- [ ] Submitting a release for an unmastered clip warns the user (soft block, not hard block)
- [ ] Release metadata is editable while in `draft` or `ready` state
- [ ] Package includes audio file, artwork, and metadata JSON

---

#### US-13.4: ISRC and UPC Generation

**As a** musician, **I want** the platform to generate ISRC and UPC codes for my releases, **so that** my music is properly identified across all streaming platforms.

**Description:**
ISRC (International Standard Recording Code) identifies individual recordings. UPC/EAN identifies a release (single/album). The platform auto-generates these codes or allows the musician to enter existing ones.

**Functional Requirements:**
- Auto-generate ISRC codes for each track in a release (format: CC-XXX-YY-NNNNN)
- Auto-generate UPC/EAN-13 codes for each release
- `PATCH /api/v1/releases/{id}` allows manual ISRC/UPC entry (overrides auto-generated)
- ISRC codes are unique and never reused
- UPC codes include a valid check digit
- Codes are stored in the release package and the clip metadata

**Acceptance Criteria:**
- [ ] Auto-generated ISRC follows the standard format and is unique
- [ ] Auto-generated UPC is a valid EAN-13 with correct check digit
- [ ] Manually entered codes override auto-generated ones
- [ ] Duplicate ISRC codes are rejected
- [ ] Codes persist in both the release package and the clip record

---

#### US-13.5: Guided Distribution Prep

**As a** musician, **I want** the platform to prepare my release package for LANDR and DistroKid, **so that** I can submit to major streaming platforms with minimal friction.

**Description:**
Since LANDR, DistroKid, and TuneCore do not offer public APIs, the platform prepares the release package to each service's requirements and provides a guided flow to complete the submission.

**Functional Requirements:**
- `POST /api/v1/releases/{id}/prepare/{target}` where target is `landr`, `distrokid`, `tunecore`
- Validates the package against the target's requirements (format, resolution, metadata completeness)
- Returns a preparation checklist with pass/fail items
- Provides a downloadable bundle formatted to the target's specifications
- Generates instructions for completing the submission on the target platform
- Updates release status to `submitted` when the user confirms manual submission

**Acceptance Criteria:**
- [ ] Preparing for LANDR validates and formats the package to LANDR requirements
- [ ] A downloadable bundle is available for each target
- [ ] The preparation checklist identifies missing or non-compliant items
- [ ] Instructions are specific to each distribution target
- [ ] Release status updates to `submitted` after user confirmation

---

#### US-13.6: Distribution Status Tracking

**As a** musician, **I want to** track the status of my releases across all distribution channels, **so that** I know when my music is live and can respond to issues.

**Description:**
A unified dashboard endpoint showing the distribution status of each release across all channels. For SoundCloud (direct integration), status is polled automatically. For guided channels, the user manually updates status.

**Functional Requirements:**
- `GET /api/v1/releases` lists all releases with their distribution status per channel
- `GET /api/v1/releases/{id}/status` returns per-channel status: `draft`, `ready`, `submitted`, `in_review`, `live`, `rejected`
- SoundCloud status is updated automatically via API polling
- Guided channels: `PATCH /api/v1/releases/{id}/channels/{channel}/status` allows manual status update
- Visibility controls: `PATCH /api/v1/releases/{id}/visibility` with `{state}` (private, unlisted, public)
- Notifications triggered on status changes (live, rejected)

**Acceptance Criteria:**
- [ ] Release listing shows per-channel distribution status
- [ ] SoundCloud status reflects actual track state (checking via API)
- [ ] Manual status updates for guided channels are stored and visible
- [ ] Visibility changes update the clip's sharing state
- [ ] Status transitions follow the valid sequence (no skipping from draft to live)

---

**Stage 13 Completion Criteria:**
- Cover art generation produces options and attaches selected art to clips
- SoundCloud OAuth flow and track upload work end-to-end
- Release packages are assembled with validated metadata and assets
- ISRC and UPC codes are auto-generated with proper formatting
- Guided distribution prep produces compliant packages for LANDR and DistroKid
- Distribution status is tracked per channel and per release
- All endpoints covered by integration tests

---

### Stage 14: DAW Export & Playback API

**Overview:** Expose the DAW export bundle, audio streaming with range requests (for the global player), playback queue management, and similar-songs queries as API endpoints. This stage completes Layer 2 by providing the backend for the web player and DAW integration workflows.

---

#### US-14.1: DAW Export Endpoint

**As a** musician, **I want to** download a DAW-ready export bundle via the API, **so that** I can import stems, MIDI, and metadata into Cubase or any other DAW.

**Description:**
Wraps the CLI's DAW export logic in an API endpoint. Triggers stem separation and MIDI extraction if not already done, packages everything into a ZIP archive, and serves it for download.

**Functional Requirements:**
- `POST /api/v1/clips/{id}/export/daw` triggers DAW bundle creation (async job if stems/MIDI need extraction)
- `GET /api/v1/clips/{id}/export/daw` downloads the ZIP once ready
- ZIP structure: `SongTitle_Export/audio/{full_mix,vocals,drums,bass,other}.wav`, `midi/{melody,chords,drums,bass}.mid`, `project.json`, `artwork.jpg`
- project.json includes: BPM, key, time_signature, duration, stem references, MIDI channel assignments, markers, lyrics, style_tags, model, seed
- If stems/MIDI already exist, reuses cached results (no re-extraction)
- Credits: 1 credit for stems + 1 credit for MIDI (0 if already extracted)

**Acceptance Criteria:**
- [ ] DAW export produces a ZIP with the correct directory structure
- [ ] project.json contains all metadata fields with correct values
- [ ] MIDI files are importable into a DAW with correct tempo and channels
- [ ] Stems are time-aligned and equal length
- [ ] Cached stems/MIDI are reused without re-extraction or additional credit charge

---

#### US-14.2: Audio Streaming with Range Requests

**As a** listener, **I want to** stream audio with seeking support, **so that** the web player can play clips immediately without downloading the entire file.

**Description:**
Enhance the clip audio endpoint to fully support HTTP range requests for efficient streaming. This is the backend for the global player in the web UI.

**Functional Requirements:**
- `GET /api/v1/clips/{id}/stream` serves audio optimized for streaming
- Full HTTP Range header support (single and multi-range)
- Returns 206 Partial Content for range requests, 200 for full requests
- Content-Type, Content-Length, Content-Range, and Accept-Ranges headers set correctly
- Supports MP3 format for streaming (smaller file size) and WAV for lossless
- Connection keep-alive for continuous playback
- Rate limiting: prevent abuse of streaming endpoints

**Acceptance Criteria:**
- [ ] A web audio player can seek to any position without buffering the full file
- [ ] Range requests return 206 with correct Content-Range header
- [ ] Full request (no Range header) returns 200 with the complete file
- [ ] Streaming a 3-minute MP3 begins playback within 1 second
- [ ] Public clips are streamable without authentication; private clips require auth

---

#### US-14.3: Playback Queue Management

**As a** musician, **I want to** manage a playback queue via the API, **so that** the web player can queue up songs, support next/previous, and maintain state across page navigations.

**Description:**
Server-side playback queue that persists the user's current listening session. Supports adding, removing, reordering, and advancing through the queue.

**Functional Requirements:**
- `POST /api/v1/queue` with `{clip_ids[], position}` adds clips to the queue
- `GET /api/v1/queue` returns the current queue with playback position
- `DELETE /api/v1/queue/{clip_id}` removes a clip from the queue
- `POST /api/v1/queue/next` advances to the next clip
- `POST /api/v1/queue/previous` goes back to the previous clip
- `PUT /api/v1/queue/reorder` with `{clip_id, new_position}` reorders the queue
- `DELETE /api/v1/queue` clears the entire queue
- Repeat mode: `none`, `one`, `all`
- Shuffle mode: on/off (shuffles remaining queue, preserves play history)

**Acceptance Criteria:**
- [ ] Adding clips to the queue persists across API requests
- [ ] Next/previous navigation works correctly with repeat and shuffle modes
- [ ] Reordering updates positions without losing clips
- [ ] Queue is scoped to the authenticated user
- [ ] Queue state persists across page reloads (client can restore state from GET)

---

#### US-14.4: Similar Songs Query

**As a** musician, **I want to** find songs similar to a given clip, **so that** I can discover related music and populate a radio-style listening queue.

**Description:**
Query for clips similar to a seed clip based on style tags, genre, BPM, key, and mood. Results are drawn from the user's library and optionally from public clips.

**Functional Requirements:**
- `GET /api/v1/clips/{id}/similar` returns up to 20 similar clips
- Similarity based on: matching style tags, BPM proximity (within 10%), same key or relative key, same model/generation mode
- `?scope=mine` limits to user's own clips; `?scope=public` includes public clips; `?scope=all` (default) includes both
- `?limit=N` controls result count (default 20, max 50)
- Results ordered by similarity score (descending)
- Can be used to auto-populate a radio queue

**Acceptance Criteria:**
- [ ] Similar clips share at least one style tag or are within 10% BPM of the seed
- [ ] Scope parameter correctly filters results to own/public/all
- [ ] Results are ordered by relevance (most similar first)
- [ ] Empty result set returns 200 with an empty array (not 404)
- [ ] Query completes within 1 second for a library of 1000+ clips

---

**Stage 14 Completion Criteria:**
- DAW export produces valid ZIP bundles with stems, MIDI, metadata, and artwork
- Audio streaming with range requests enables efficient web player playback
- Playback queue supports full lifecycle (add, remove, reorder, next, previous, repeat, shuffle)
- Similar songs query returns relevant results based on musical properties
- All endpoints covered by integration tests
- **End-to-end API workflow validated:** authenticate -> generate -> edit -> master -> distribute -> export -> stream

---

