#!/usr/bin/env bash
# Roll one environment forward from CI (#429, #699): ship the stack definition to the host, log the host into GHCR
# for this job only, and hand scripts/deploy.sh the SHA. deploy.sh owns the health gate, the rollback and the
# idempotence check, so its exit code is this script's verdict: a rolled-back deploy fails the job.
#
# Required: ENVIRONMENT (named in errors), DEPLOY_HOST, DEPLOY_USER, DEPLOY_PATH, IMAGE_TAG, API_IMAGE, WEB_IMAGE,
#           GHCR_USER, GHCR_TOKEN
#           DEPLOY_SSH_KEY, the private key the host trusts, unless DEPLOY_SSH_KEY_OPTIONAL=true: an environment whose
#           network authorizes SSH itself (Tailscale SSH on the staging box) leaves it unset, so no unused key with
#           access to the host is ever provisioned.
# Optional:
#           DEPLOY_HEALTH_URL, the host-local health URL deploy.sh waits on; its default (localhost:8000) is wrong on a
#           shared host where another stack owns that port.
set -euo pipefail

required=(DEPLOY_HOST DEPLOY_USER)
[[ "${DEPLOY_SSH_KEY_OPTIONAL:-}" == "true" ]] || required+=(DEPLOY_SSH_KEY)
for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "::error title=Deploy misconfigured::$name is not set on the ${ENVIRONMENT:-deploy} environment."
    exit 1
  fi
done

install -m 700 -d ~/.ssh
# BatchMode: a refused login or an unknown host key fails the job now, rather than waiting on a prompt until it
# times out. The values interpolated into remote commands come from the workflow, not from users.
key=(-o BatchMode=yes)
if [[ -n "${DEPLOY_SSH_KEY:-}" ]]; then
  printf '%s\n' "$DEPLOY_SSH_KEY" > ~/.ssh/deploy_key
  chmod 600 ~/.ssh/deploy_key
  key+=(-i ~/.ssh/deploy_key)
fi
ssh-keyscan -H "$DEPLOY_HOST" >> ~/.ssh/known_hosts 2>/dev/null
remote=(ssh "${key[@]}" "$DEPLOY_USER@$DEPLOY_HOST")

scp "${key[@]}" compose.yaml scripts/deploy.sh "$DEPLOY_USER@$DEPLOY_HOST:$DEPLOY_PATH/"

# Packages published with GITHUB_TOKEN are private by default, whatever the repository's visibility, so the host
# needs a login; the job's token expires with the job, so there is no long-lived PAT to provision or rotate.
printf '%s' "$GHCR_TOKEN" | "${remote[@]}" "docker login ghcr.io -u '$GHCR_USER' --password-stdin"

health=""
[[ -n "${DEPLOY_HEALTH_URL:-}" ]] && health="HEALTH_URL='$DEPLOY_HEALTH_URL'"
"${remote[@]}" "cd $DEPLOY_PATH && chmod +x deploy.sh && \
  API_IMAGE='$API_IMAGE' WEB_IMAGE='$WEB_IMAGE' DEPLOY_DIR='$DEPLOY_PATH' $health ./deploy.sh '$IMAGE_TAG'"
