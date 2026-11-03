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

Web on <http://localhost:3000>, API on <http://localhost:8000>, Swagger at <http://localhost:8000/docs>.
The web's own `/docs` shows the same reference, but its "Try it out" needs the nginx `/api/v1/` route below.
Ports come from `WEB_PORT` / `API_PORT` — the host is shared, so a conflict is a variable
to change, not a file to edit.

`docker compose up` is the supported way to run the platform. The `uv run uvicorn` and
`npm run dev` commands in the README are development conveniences: they skip the image, so
they also skip the guarantees the image makes (ffmpeg present, absolute data paths).

## Deploy from scratch on a VPS (#342)

What a new developer needs to stand the platform up on one Ubuntu server. Host names, users and addresses for this
project's own servers are in the operator's runbook, not here. Replace `example.com` with your domain throughout.

1. **Server.** Ubuntu 22.04 or later with Docker Engine and the Compose plugin **v2.24+** (`docker compose version`),
   nginx and certbot (`apt install nginx certbot python3-certbot-nginx`). If other stacks share the box, pick free
   ports (`ss -ltn`) for the API, web and Mongo.
2. **DNS.** An `A` record for your domain pointing at the server's public address.
3. **Stack directory.** On the server:
   ```bash
   install -d -m 750 /opt/acemusic && cd /opt/acemusic
   # copy compose.yaml and scripts/deploy.sh from the repository into this directory
   cp .env.docker.example .env.docker   # from the repository
   chmod 600 .env.docker
   ```
   In `.env.docker` set at least: `ACEMUSIC_API_JWT_SECRET_KEY` (`openssl rand -hex 32`), `API_PORT`, `WEB_PORT` and
   `MONGO_PORT` bound to loopback (`127.0.0.1:8030` and so on), `ACEMUSIC_API_CORS_ALLOW_ORIGINS=https://example.com`,
   Google OAuth (`ACEMUSIC_API_GOOGLE_*`, redirect `https://example.com/auth/callback/google`), and the Stripe
   keys and prices if billing is on (success/cancel URLs on your domain). Every `ACEMUSIC_API_*` setting in the file
   reaches the API (#702).
4. **First deploy.** Images are published to GHCR by CD on every green `main`; deploy one commit:
   ```bash
   API_IMAGE=ghcr.io/<owner>/<repo>-api WEB_IMAGE=ghcr.io/<owner>/<repo>-web DEPLOY_DIR=/opt/acemusic \
     HEALTH_URL=http://127.0.0.1:8030/api/v1/health ./deploy.sh <commit sha>
   ```
   It pulls, starts the stack and waits until the API reports that SHA, rolling back if it doesn't.
5. **nginx and TLS.** A site that sends `/api/v1/` to the API and everything else to the web app, replacing
   `X-Forwarded-For` with the real client (the rate limiters trust it):
   ```nginx
   server {
       server_name example.com;
       listen 80;
       client_max_body_size 200m;
       proxy_http_version 1.1;
       proxy_set_header Host $host;
       proxy_set_header X-Forwarded-For $remote_addr;
       proxy_set_header X-Forwarded-Proto $scheme;
       location /api/v1/ { proxy_pass http://127.0.0.1:8030; proxy_read_timeout 300s; }
       location / { proxy_pass http://127.0.0.1:3030; }
   }
   ```
   Enable it, then `certbot --nginx -d example.com --redirect`. Set `ACEMUSIC_API_TRUSTED_PROXIES` to the Docker
   network's gateway and the web container's address (`docker network inspect acemusic_default`) and recreate the
   API, so rate limits key on real clients. Left unset, every client shares the proxy's bucket.
6. **Check it.** `curl https://example.com/api/v1/health` reports the deployed `build_sha`; `/docs` shows the API
   reference; signing in with Google reaches `/create`.
7. **Keep it running.**
   - *Automatic deploys:* see [Enabling it](#enabling-it), [Staging](#staging-699) and [Production](#production-700).
   - *Error tracking:* set `ACEMUSIC_API_SENTRY_DSN` in `.env.docker`.
   - *Uptime:* `scripts/uptime-monitor.sh` checks the health URL and posts to a webhook after three failed checks
     in a row (over two minutes down), and again on recovery. Copy it to `/usr/local/bin/acemusic-uptime-monitor`
     on the machine that runs it, put `HEALTH_URL=https://example.com/api/v1/health` and the webhook
     (`ALERT_WEBHOOK_URL=https://hooks.slack.com/services/...`, or `https://ntfy.sh/<topic>` with `ALERT_FORMAT=ntfy`)
     in `/etc/acemusic-uptime.env` with `chmod 600`, since the webhook URL is a secret, and run it every minute with
     a systemd timer:
     ```ini
     # /etc/systemd/system/acemusic-uptime.service
     [Service]
     Type=oneshot
     EnvironmentFile=/etc/acemusic-uptime.env
     StateDirectory=acemusic-uptime
     ExecStart=/usr/local/bin/acemusic-uptime-monitor

     # /etc/systemd/system/acemusic-uptime.timer
     [Timer]
     OnBootSec=1min
     OnUnitActiveSec=1min
     [Install]
     WantedBy=timers.target
     ```
     then `systemctl enable --now acemusic-uptime.timer`. `ALERT_FORMAT=discord` changes the payload for a Discord webhook.
     Run it from a different machine than the one it watches, or a whole-server outage takes the monitor with it.

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
push to main ──► CI (3.11, 3.12) ──► CD: publish ──► deploy to staging ──► approval ──► deploy to production
                    required           ghcr.io/…-api      ./deploy.sh <sha>     required      ./deploy.sh <same sha>
                    checks             ghcr.io/…-web      health gate,          reviewer      health gate,
                                       :<sha> + :latest   rollback on failure                 rollback on failure
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

Each environment's settings are in [Staging](#staging-699) and [Production](#production-700).
`DOCKERHUB_PUBLISH_ENABLED=true` (a repository variable) re-enables the ACE-Step publish.

On each host: install Docker, create `DEPLOY_PATH`, and put a `.env.docker` there built
from `.env.docker.example` with production values. (Named `.env.docker`, not `.env`,
because a checkout already carries a `.env` holding the development configuration — a
different schema entirely — and compose would silently load that one.) The API container loads that file whole (`env_file`), so any `ACEMUSIC_API_*` setting
you put there takes effect without being listed in `compose.yaml` (#702). The workflow ships
`compose.yaml` and `deploy.sh` on every deploy, so those are never edited in place.

### Support contact (#339)

`SUPPORT_CONTACT` in `.env.docker` is what `/support` shows, and every error page links there: an email address
becomes a `mailto:` link, an `https://` URL a link. The web container reads it per request, so changing it needs a
restart, not a rebuild. Unset, the page still explains how to get help.

### Staging (#699)

Every green `main` also deploys to staging (`https://dev.automusicstudio.com`), with no approval, through the
`deploy-staging` job. The host is on a shared box reachable only over Tailscale; its details are in the operator's
local runbook. Both deploy jobs run `scripts/ci-deploy.sh`, so staging and production roll out the same way.

| Kind | Name | Purpose |
| --- | --- | --- |
| Variable (repository) | `STAGING_DEPLOY_ENABLED` | `true` turns the staging job on; until then it is skipped |
| Variable (`staging` env) | `DEPLOY_PATH` | Host directory holding `compose.yaml` and `.env.docker` |
| Variable (`staging` env) | `DEPLOY_HEALTH_URL` | Host-local health URL `deploy.sh` gates on (the stack's own API port, not the shared box's 8000) |
| Variable (`staging` env) | `STAGING_HEALTH_URL` | Public health URL, checked after the rollout |
| Secret (`staging` env) | `DEPLOY_HOST`, `DEPLOY_USER` | SSH target over Tailscale |
| Secret (`staging` env) | `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET` | Tailscale OAuth client (scope `auth_keys`, tag `tag:ci`) the runner joins the tailnet with |

`DEPLOY_SSH_KEY` is optional and unset for staging: the box runs Tailscale SSH, so the tailnet policy authorizes the
runner, and no key with access to the host is provisioned. The policy therefore needs an `ssh` rule letting `tag:ci`
reach the staging tag as the deploy user, alongside the network grant. The runner's node is ephemeral.

The staging stack binds its ports to loopback, and nginx on the box terminates TLS and routes `/api/v1/` to the API
and everything else to the web app. nginx replaces `X-Forwarded-For` with the client address, and
`ACEMUSIC_API_TRUSTED_PROXIES` lists the Docker gateway and the web container, so the rate limiters key on real
clients.

### Production (#700)

Production promotes what staging proved: the `deploy` job needs `deploy-staging`, so it runs only in a CD run whose
staging rollout passed its health gate and whose public staging URL served the SHA. It deploys that same SHA's images;
nothing is rebuilt. The `production` environment has a required reviewer, so every promotion waits for an approval in
the run (*Review deployments*). Production deploys one at a time, and of the runs queued behind one, only the
newest is kept. Reject a promotion you don't want rather than leaving it waiting. The `production` environment
accepts deployments from protected branches only, so a dispatched run from a feature branch stops at staging.

The site is `https://www.automusicstudio.com`, on a shared production box reachable only over Tailscale (details in
the operator's local runbook). Like staging, it runs Tailscale SSH, so no key is provisioned, and its stack binds
loopback ports behind host nginx and certbot.

| Kind | Name | Purpose |
| --- | --- | --- |
| Variable (repository) | `DEPLOY_ENABLED` | `true` turns the production job on; until then it is skipped |
| Protection rule (`production` env) | Required reviewer | Approves each promotion |
| Variable (`production` env) | `DEPLOY_PATH` | Host directory holding `compose.yaml` and `.env.docker` |
| Variable (`production` env) | `DEPLOY_HEALTH_URL` | Host-local health URL `deploy.sh` gates on |
| Variable (`production` env) | `PRODUCTION_HEALTH_URL` | Public health URL, checked after the rollout |
| Secret (`production` env) | `DEPLOY_HOST`, `DEPLOY_USER` | SSH target over Tailscale |

The Tailscale OAuth client (`TS_OAUTH_CLIENT_ID` / `TS_OAUTH_SECRET`) is shared with staging. The tailnet policy needs
an `ssh` rule letting `tag:ci` reach the production tag as the deploy user, as it does for staging.

Production's `.env.docker` differs from staging's in what it talks to: Stripe **live** keys and the signing secret of a
live webhook endpoint at `https://www.automusicstudio.com/api/v1/billing/webhook`, a Google OAuth redirect of
`https://www.automusicstudio.com/api/auth/callback/google`, and CORS and Stripe return URLs on that origin.

**Rollback.**

- *A failed health gate* rolls back by itself: `deploy.sh` re-pins the previous SHA and the job fails, as on staging.
- *A healthy release you want to undo:* open the CD run that shipped the previous release and re-run its
  **Deploy to production** job, that job only: *Re-run all jobs* would rebuild and redeploy staging too. It redeploys
  that run's SHA (the images are still in GHCR) through the same health gate, after the same approval. Runs can be
  re-run for 30 days.
- *By hand, or older than that:* on the host, `./deploy.sh <sha>` in `DEPLOY_PATH`, with the same `API_IMAGE`,
  `WEB_IMAGE` and `HEALTH_URL` as in [Deploy from scratch](#deploy-from-scratch-on-a-vps-342).

As on staging, a rollback restores images, not data.

Three things that are easy to get wrong the first time:

- **GHCR packages are private by default**, independent of whether the repository is
  public. The deploy therefore logs the host into `ghcr.io` with the job's own
  `GITHUB_TOKEN` before pulling — scoped to the run, so there is no long-lived PAT to
  provision or rotate. If you would rather the host not authenticate at all, make the two
  packages public once under *Packages → Package settings*.
- **Compose version: v2.24+.** The API loads `.env.docker` through `env_file` with
  `required: false`, which older Compose rejects, so the stack will not even parse there (#702).
  The nested default (`${ACEMUSIC_BASE_URL:-${ACEMUSIC_API_LOCAL_URL:-…}}`) also needs v2.20+.
- **`build images` is not a required check yet.** Branch protection on `main` requires
  `ci (3.11)` and `ci (3.12)` only, so a Dockerfile that fails to build shows red without
  blocking the merge. Add `build images` to the required checks to close that.

## Decisions

### Single container, not a split API and worker

The job processor runs in-process inside the API's lifespan. Splitting it is nearly free —
`job_processor_enabled` already exists — and since **#427** it is safe: a worker heartbeats
each job it is running, and the startup stale sweep re-queues only jobs whose heartbeat has
stopped, so a sibling process starting mid-render never reclaims a live job (and the
`videos` collection rejects a second document for one job regardless). Still a single
container: nothing needs more than one worker yet. Splitting is a compose service and a flag.

The first deploy carrying #427 builds a unique index on `videos.job_id` at startup. A
database that already holds two `Video` documents for one job (only possible if the race
above ever ran) would refuse to start; run `uv run python scripts/dedupe_videos.py --apply`
against it first (dry run without the flag).

### Staging is automatic, production is approved (#699, #700)

Staging takes every green `main` with no approval: CI is a hard gate, and the health gate plus automatic rollback
carry the safety there. Production adds a person, approving a SHA that is already running on staging, so the
approval is of something that can be tried at `https://dev.automusicstudio.com` rather than of a diff. The approval
is an environment protection rule, so it can be removed without touching the workflow.

### Known gaps

- **A restart is a short outage.** Single VPS, single compose stack; `up -d` recreates the
  containers. Blue/green or a proxy in front would remove it. Accepted deliberately rather
  than discovered later.
- **Index changes land at rollout.** Beanie creates indexes during `init_db` at startup, so
  there is no separate migration step to gate on — schema work happens as a side effect of
  the new container booting.
- **The rollback restores images, not data.** It re-pins the previous SHA. Anything the bad
  release wrote to MongoDB stays written.
- **`/data/voice-training` is a named volume, which a host-side ACE-Step cannot see.**
  `voice_training_root` exists because the API and ACE-Step are supposed to share a
  filesystem — the API writes reference audio there and hands ACE-Step the *path*. Inside
  this stack that path is a Docker volume, so it is shared only with containers on this
  host. Voice training therefore needs that volume bound to a path ACE-Step also mounts
  (a bind mount to a shared directory, or a network filesystem) before it works against a
  remote GPU host. Everything else in the stack is unaffected.
