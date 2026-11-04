#!/usr/bin/env bash
# The match-records replay. Every phase runs even after a failed check, so one run
# names every failure; the exit status is 1 if any phase failed.
#
#   SAVE_ADMIN_DIR=../tag2now-save-admin tests/e2e/records/run.sh
set -u
here="$(cd "$(dirname "$0")" && pwd)"
logs="$here/../../../test-results/e2e-records"
export SAVE_ADMIN_DIR="$(cd "${SAVE_ADMIN_DIR:-$here/../../../../tag2now-save-admin}" 2>/dev/null && pwd)"
if [ ! -f "$SAVE_ADMIN_DIR/script/tdt_admin.py" ]; then
    echo "no tag2now-save-admin checkout found; set SAVE_ADMIN_DIR" >&2
    exit 2
fi
mkdir -p "$logs"

failed=0
compose() { docker compose -f "$here/compose.yml" "$@"; }
step() { "$@" || { echo "[failed: $*]"; failed=1; }; }
drive() { step compose run --rm --no-deps driver "$1"; }

compose down -v --remove-orphans
step compose build be save-admin
step compose up -d --wait postgres
step compose run --rm --no-deps be python -m alembic upgrade head
drive seed
step compose up -d --wait be save-admin
drive scenarios

compose stop save-admin
drive during-outage
sleep 3
compose start save-admin
drive after-outage

drive before-restart
compose restart be
step compose up -d --wait be
drive after-restart

compose logs --no-color be > "$logs/be.log" 2>&1
compose logs --no-color save-admin > "$logs/save-admin.log" 2>&1
compose down -v --remove-orphans
echo "logs in $logs"
[ "$failed" -eq 0 ] && echo "replay passed" || echo "replay FAILED"
exit "$failed"
