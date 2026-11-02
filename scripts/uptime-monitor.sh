#!/usr/bin/env bash
# Uptime monitor (#342): run once a minute (systemd timer or cron, see docs/deployment.md). It alerts once when the
# health endpoint has failed FAILURES_BEFORE_ALERT checks in a row (3, so unreachable for over 2 minutes), and once
# more when it answers again.
#
# Required: HEALTH_URL          the public health URL, e.g. https://example.com/api/v1/health
#           ALERT_WEBHOOK_URL   where alerts are posted
# Optional: ALERT_FORMAT        slack (default: {"text": ...}), discord ({"content": ...}) or ntfy (plain text)
#           FAILURES_BEFORE_ALERT  default 3
#           STATE_FILE          default /var/lib/acemusic-uptime/state
#           CHECK_TIMEOUT       seconds per check, default 10
set -euo pipefail

: "${HEALTH_URL:?set HEALTH_URL}"
: "${ALERT_WEBHOOK_URL:?set ALERT_WEBHOOK_URL}"
ALERT_FORMAT="${ALERT_FORMAT:-slack}"
FAILURES_BEFORE_ALERT="${FAILURES_BEFORE_ALERT:-3}"
STATE_FILE="${STATE_FILE:-/var/lib/acemusic-uptime/state}"
CHECK_TIMEOUT="${CHECK_TIMEOUT:-10}"

failures=0
alerted=0
[[ -f "$STATE_FILE" ]] && read -r failures alerted < "$STATE_FILE" || true
# A damaged state file starts the count again rather than stopping the monitor.
[[ "$failures" =~ ^[0-9]+$ && "$alerted" =~ ^[01]$ ]] || { failures=0; alerted=0; }

alert() {
  local message="$1" body content_type="application/json" escaped
  escaped=${message//\\/\\\\}
  escaped=${escaped//\"/\\\"}
  case "$ALERT_FORMAT" in
    discord) body=$(printf '{"content": "%s"}' "$escaped") ;;
    ntfy) body="$message" content_type="text/plain" ;;
    *) body=$(printf '{"text": "%s"}' "$escaped") ;;
  esac
  # A failed alert is retried on the next run: the state below is only written once it went out.
  curl -fsS --max-time "$CHECK_TIMEOUT" -X POST -H "Content-Type: $content_type" --data "$body" "$ALERT_WEBHOOK_URL" >/dev/null
}

if curl -fsS --max-time "$CHECK_TIMEOUT" -o /dev/null "$HEALTH_URL"; then
  if (( alerted )); then
    alert "Recovered: $HEALTH_URL is answering again."
  fi
  failures=0
  alerted=0
else
  failures=$((failures + 1))
  if (( failures >= FAILURES_BEFORE_ALERT && ! alerted )); then
    alert "Down: $HEALTH_URL has failed $failures checks in a row."
    alerted=1
  fi
fi

mkdir -p "$(dirname "$STATE_FILE")"
printf '%s %s\n' "$failures" "$alerted" > "$STATE_FILE"
