#!/usr/bin/env bash
# Deploy every new commit of `main` by itself — but only one that passed CI on GitHub.
#
# Run by cron on the server as the moloko user (owner's request, 2026-11-04), every 2 minutes:
#   */2 * * * * /home/moloko/moloko/infrastructure/scripts/autodeploy.sh >> $HOME/autodeploy.log 2>&1
# Install / remove that line: infrastructure/scripts/autodeploy.sh --install | --uninstall
#
# Each run: fetch origin/main; nothing new → exit quietly. A new commit waits until all its
# GitHub checks are done; any failed check → it is skipped for good (logged). All green →
# fast-forward to exactly that commit and run deploy.sh (backup, build, health checks) with
# NO_PULL=1, so a commit pushed meanwhile is never deployed unchecked. A commit whose deploy
# failed is not retried (push a fix, or run deploy.sh by hand).
# Options (environment): AUTODEPLOY_REPO=owner/name (default: from the origin URL).
set -euo pipefail

export PATH="/usr/local/bin:/usr/bin:/bin:${PATH:-}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/moloko-autodeploy"
CRON_LINE="*/2 * * * * $ROOT/infrastructure/scripts/autodeploy.sh >> \$HOME/autodeploy.log 2>&1"
mkdir -p "$STATE"

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

case "${1:-}" in
  --install)
    (crontab -l 2>/dev/null | grep -v 'infrastructure/scripts/autodeploy.sh'; echo "$CRON_LINE") | crontab -
    echo "Автодеплой включён: каждые 2 минуты, журнал — ~/autodeploy.log"
    exit 0
    ;;
  --uninstall)
    (crontab -l 2>/dev/null | grep -v 'infrastructure/scripts/autodeploy.sh') | crontab - || true
    echo "Автодеплой выключен."
    exit 0
    ;;
esac

# One run at a time (a deploy takes minutes; cron starts a new run every 2).
exec 9>"$STATE/lock"
flock -n 9 || exit 0

cd "$ROOT"
git fetch --quiet origin main
target="$(git rev-parse origin/main)"
current="$(git rev-parse HEAD)"
[[ "$target" == "$current" ]] && exit 0
short="${target:0:7}"
grep -qx "$target" "$STATE/skipped" 2>/dev/null && exit 0

repo="${AUTODEPLOY_REPO:-$(git remote get-url origin | sed -E 's#^(https://github.com/|git@github.com:)##; s#\.git$##')}"
# The commit's GitHub checks: "pending", "failed <names>" or "ok".
verdict="$(curl -fsS --max-time 20 -H 'Accept: application/vnd.github+json' \
  "https://api.github.com/repos/$repo/commits/$target/check-runs?per_page=100" | python3 -c '
import json, sys
runs = json.load(sys.stdin).get("check_runs", [])
if not runs or any(r["status"] != "completed" for r in runs):
    print("pending")
else:
    bad = [r["name"] for r in runs if r["conclusion"] not in ("success", "skipped", "neutral")]
    print("failed " + ", ".join(bad) if bad else "ok")
')" || { log "$short: не удалось спросить GitHub о проверках, попробую позже"; exit 0; }

case "$verdict" in
  pending) exit 0 ;;  # CI is still running: next time
  failed*)
    log "$short: CI не прошёл (${verdict#failed }) — не выкатываю"
    echo "$target" >>"$STATE/skipped"
    exit 0
    ;;
esac

log "$short: CI зелёный — выкатываю $(git log -1 --format='%s' "$target" | cut -c1-80)"
if ! git merge --quiet --ff-only "$target"; then
  log "$short: не получилось перейти на коммит (изменения на сервере?) — не выкатываю"
  echo "$target" >>"$STATE/skipped"
  exit 0
fi
deploy_log="$HOME/deploy-auto-$short.log"
if NO_PULL=1 "$ROOT/infrastructure/scripts/deploy.sh" >"$deploy_log" 2>&1 </dev/null; then
  log "$short: выкачено ✓ (журнал: $deploy_log)"
else
  log "$short: деплой упал ✗ — смотрите $deploy_log; этот коммит больше не повторяю"
  echo "$target" >>"$STATE/skipped"
fi
# keep the logs small
ls -1t "$HOME"/deploy-auto-*.log 2>/dev/null | tail -n +11 | xargs -r rm -f
[[ -f "$HOME/autodeploy.log" ]] && tail -n 500 "$HOME/autodeploy.log" >"$STATE/log.tmp" && mv "$STATE/log.tmp" "$HOME/autodeploy.log"
exit 0
