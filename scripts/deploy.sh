#!/usr/bin/env bash
#
# Roll the platform stack forward to one image tag, or put it back the way it was (#429).
#
#   ./deploy.sh <image-tag>
#
# Run on the deployment host — the CD workflow's only job is to ship this a SHA over SSH.
# The logic lives here rather than in workflow YAML so it can be tested (see
# tests/test_deploy_script.py) and so an operator can run the exact same rollout by hand.
#
# The health gate checks that the API reports the SHA we just deployed, not merely that
# something answers 200. Those differ in the case that matters: a new image that crash-
# loops leaves the previous container serving happily, and a liveness check calls that a
# successful deploy.
#
# Environment:
#   DEPLOY_DIR       directory holding compose.yaml and .env  (default: repo root)
#   HEALTH_URL       API health endpoint  (default: http://localhost:8000/api/v1/health)
#   HEALTH_TIMEOUT   seconds to wait for the new build  (default: 180)
#   HEALTH_INTERVAL  seconds between probes  (default: 5)
#   STATE_FILE       records the deployed tag  (default: $DEPLOY_DIR/.deployed-tag)

set -euo pipefail

TAG="${1:-}"
DEPLOY_DIR="${DEPLOY_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
HEALTH_URL="${HEALTH_URL:-http://localhost:8000/api/v1/health}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"
HEALTH_INTERVAL="${HEALTH_INTERVAL:-5}"
STATE_FILE="${STATE_FILE:-$DEPLOY_DIR/.deployed-tag}"

log() { printf '[deploy] %s\n' "$*"; }
# $1 is the message and $2 the exit code — "$*" here would print the code as part of the
# sentence ("...is already running (.deploy.lock) 3").
die() { printf '[deploy] %s\n' "$1" >&2; exit "${2:-1}"; }

if [[ -z "$TAG" ]]; then
  die "usage: deploy.sh <image-tag>" 2
fi

# One rollout at a time. The CD workflow already serialises itself with
# `concurrency: production`, but that only covers workflow runs — it does nothing about an
# operator running this by hand while a deploy is in flight, which is exactly when someone
# would. Two interleaved rollouts can leave the stack on a mixed set of images.
LOCK_FILE="${LOCK_FILE:-$DEPLOY_DIR/.deploy.lock}"
if [[ -z "${DEPLOY_LOCK_HELD:-}" ]]; then
  export DEPLOY_LOCK_HELD=1
  status=0
  # --conflict-exit-code distinguishes "could not get the lock" from "the deploy itself
  # failed"; both are 1 by default, and they call for opposite responses.
  flock --nonblock --conflict-exit-code 3 "$LOCK_FILE" "$0" "$@" || status=$?
  if (( status == 3 )); then
    die "another deploy is already running ($LOCK_FILE)" 3
  fi
  exit "$status"
fi

compose() {
  IMAGE_TAG="$1" docker compose --project-directory "$DEPLOY_DIR" "${@:2}"
}

# The SHA the API says it is running, or empty if it is not answering.
running_sha() {
  local body
  body="$(curl -fsS --max-time 5 "$HEALTH_URL" 2>/dev/null)" || return 0
  # Deliberately not jq: the deployment host should need docker and curl, nothing else.
  printf '%s' "$body" | sed -n 's/.*"build_sha"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p'
}

# Poll until the API reports $1, or give up. Returns non-zero on timeout.
await_sha() {
  local want="$1" deadline=$((SECONDS + HEALTH_TIMEOUT)) seen
  while (( SECONDS < deadline )); do
    seen="$(running_sha)"
    if [[ "$seen" == "$want" ]]; then
      return 0
    fi
    sleep "$HEALTH_INTERVAL"
  done
  log "timed out after ${HEALTH_TIMEOUT}s waiting for build_sha=$want (last seen: '${seen:-no response}')"
  return 1
}

roll_to() {
  local tag="$1"
  compose "$tag" pull
  # --no-build: compose.yaml carries a `build:` section so the same file serves local
  # development, and without this a tag that failed to pull would silently fall back to
  # building from source the deployment host does not have. Failing on the pull is the
  # honest outcome.
  compose "$tag" up -d --remove-orphans --no-build
}

PREVIOUS="$(cat "$STATE_FILE" 2>/dev/null | tr -d '[:space:]' || true)"

# Idempotence: re-running the same deploy is a no-op. Gated on what is actually serving,
# not on the state file alone — the file records the last deploy, and a stack that has
# since fallen over must still be brought back rather than reported as already done.
if [[ "$PREVIOUS" == "$TAG" && "$(running_sha)" == "$TAG" ]]; then
  log "$TAG is already deployed and serving — nothing to do"
  exit 0
fi

log "deploying $TAG (currently: ${PREVIOUS:-none})"
roll_to "$TAG"

if await_sha "$TAG"; then
  printf '%s\n' "$TAG" > "$STATE_FILE"
  log "$TAG is live"
  exit 0
fi

# The deploy failed. Leaving the site down while reporting green is the one outcome worth
# engineering against, so from here every path exits non-zero.
if [[ -z "$PREVIOUS" ]]; then
  die "$TAG did not come up healthy, and there is no previous deploy to roll back to"
fi

log "rollback: restoring $PREVIOUS"
roll_to "$PREVIOUS"

if await_sha "$PREVIOUS"; then
  printf '%s\n' "$PREVIOUS" > "$STATE_FILE"
  die "$TAG failed its health gate; rolled back to $PREVIOUS"
fi

die "$TAG failed its health gate AND the rollback to $PREVIOUS did not come up — the stack needs a human"
