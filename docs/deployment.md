# Deployment

The platform ships as two images plus MongoDB, described by one `compose.yaml` that is
both the local stack and the production topology. Merging to `main` publishes SHA-tagged
images and rolls them out; nobody SSHes anywhere.

## Run the whole stack locally

```bash
cp .env.docker.example .env.docker
sed -i "s|^ACEMUSIC_API_JWT_SECRET_KEY=.*|ACEMUSIC_API_JWT_SECRET_KEY=$(openssl rand -hex 32)|" .env.docker
docker compose --env-file .env.docker up --build
```

Web on <http://localhost:3000>, API on <http://localhost:8000>, Swagger at `/docs`.
Ports come from `WEB_PORT` / `API_PORT` — the host is shared, so a conflict is a variable
to change, not a file to edit.

`docker compose up` is the supported way to run the platform. The `uv run uvicorn` and
`npm run dev` commands in the README are development conveniences: they skip the image, so
they also skip the guarantees the image makes (ffmpeg present, absolute data paths).

## What the images guarantee

- **ffmpeg is installed.** Free-tier video watermarking (#401), flac/mp3 conversion, batch
  transcode and Studio mixdowns all shell out to it. CI installed it and production ran on
  trust; now it is a layer.
- **Data paths are absolute.** `ACEMUSIC_API_VOICE_TRAINING_ROOT=/data/voice-training` and
  `ACEMUSIC_STORAGE_LOCAL_ROOT=/data/storage`, both mounted as named volumes. Their code
  defaults are CWD-relative (`./acemusic-voice-training`, `Path.cwd()/"storage"`), which in
  a container means "inside the writable layer, gone on the next deploy".

  These are set as environment, not by changing the defaults. `voice_training_root` is
  deliberately relative so the API and ACE-Step share a filesystem, and the value is sent
  verbatim to ACE-Step (`api/tasks/voice_training.py`) — changing the default would change
  what ACE-Step receives.
- **The API runs as a non-root user** and answers `GET /api/v1/health`, which now reports
  `build_sha`: the commit the image was built from.

## The pipeline

```
push to main ──► CI (3.11, 3.12) ──► CD: publish ──► CD: deploy
                    required           ghcr.io/…-api      scp compose.yaml + deploy.sh
                    checks             ghcr.io/…-web      ssh → ./deploy.sh <sha>
                                       :<sha> + :latest   health gate → rollback on failure
```

CD triggers on `workflow_run` when CI **completes successfully** on `main`, rather than on
`push`. It keys off CI's verdict instead of re-deciding it.

Images go to **GHCR**, authenticated with the built-in `GITHUB_TOKEN`. That is the point:
`docker-publish.yml` never published anything for want of Docker Hub credentials, and a
pipeline that needs no new secrets cannot fail that way. Docker Hub remains correct for the
ACE-Step worker image, which RunPod pulls.

### Rollout, health gate, rollback

`scripts/deploy.sh` runs on the host and owns all of it, so the same rollout can be run by
hand and — more importantly — can be tested (`tests/test_deploy_script.py`).

The gate is **not** "does something answer 200". It is "does the API report the SHA we
just deployed". Those differ in exactly the case worth engineering for: a new image that
crash-loops leaves the previous container serving happily, and a liveness check calls that
a successful deploy. On timeout the script re-pins the previous SHA, waits for it to come
back, and exits non-zero — a deploy that leaves the site down must not report green.

Re-running the same SHA is a no-op, gated on what is actually serving rather than on the
recorded tag alone, so a stack that has since fallen over is still brought back.

### Enabling it

The deploy job is skipped until it is configured — *skipped*, not green having done
nothing, which is the failure mode this work exists to remove.

| Kind | Name | Purpose |
| --- | --- | --- |
| Variable | `DEPLOY_ENABLED` | `true` turns the deploy job on |
| Variable | `DEPLOY_PATH` | Host directory holding `compose.yaml` and `.env.docker` (default `/srv/acemusic`) |
| Variable | `PRODUCTION_HEALTH_URL` | Public health URL, checked independently after the rollout |
| Variable | `DOCKERHUB_PUBLISH_ENABLED` | `true` re-enables the ACE-Step publish |
| Secret (`production` env) | `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` | SSH target |

On the host: install Docker, create `DEPLOY_PATH`, and put a `.env.docker` there built
from `.env.docker.example` with production values. (Named `.env.docker`, not `.env`,
because a checkout already carries a `.env` holding the development configuration — a
different schema entirely — and compose would silently load that one.) The workflow ships
`compose.yaml` and `deploy.sh` on every deploy, so those are never edited in place.

Three things that are easy to get wrong the first time:

- **GHCR packages are private by default**, independent of whether the repository is
  public. The deploy therefore logs the host into `ghcr.io` with the job's own
  `GITHUB_TOKEN` before pulling — scoped to the run, so there is no long-lived PAT to
  provision or rotate. If you would rather the host not authenticate at all, make the two
  packages public once under *Packages → Package settings*.
- **Compose version.** `compose.yaml` uses a nested default
  (`${ACEMUSIC_BASE_URL:-${ACEMUSIC_API_LOCAL_URL:-…}}`) so the worker's URL inherits the
  probe's rather than silently diverging. Docker Compose **v2.20+** resolves this
  correctly; it is verified on the version used to build this stack. On anything older,
  set both variables explicitly in `.env.docker`.
- **`build images` is not a required check yet.** Branch protection on `main` requires
  `ci (3.11)` and `ci (3.12)` only, so a Dockerfile that fails to build shows red without
  blocking the merge. Add `build images` to the required checks to close that.

## Decisions

### Single container, not a split API and worker

The job processor runs in-process inside the API's lifespan. Splitting it is nearly free —
`job_processor_enabled` already exists — but it makes **#427** live: the stale-requeue
window is shorter than a video render's worst case, so multiple worker processes are
precisely the deployment that turns that latent race into double provider billing and
racing `Video` documents.

Single container until #427 is closed. Then splitting is a compose service and a flag.

### Deploys are fully automatic

No human approval step. CI is already a hard gate with two required checks and strict
up-to-date enforcement, and the health gate plus automatic rollback carry the safety —
which a person approving a diff they have not run does not.

Reversible either way: an environment protection rule on `production` adds a click without
touching the workflow. Revisit if a bad deploy ever gets past the gate.

### Known gaps

- **A restart is a short outage.** Single VPS, single compose stack; `up -d` recreates the
  containers. Blue/green or a proxy in front would remove it. Accepted deliberately rather
  than discovered later.
- **Index changes land at rollout.** Beanie creates indexes during `init_db` at startup, so
  there is no separate migration step to gate on — schema work happens as a side effect of
  the new container booting.
- **The rollback restores images, not data.** It re-pins the previous SHA. Anything the bad
  release wrote to MongoDB stays written.
