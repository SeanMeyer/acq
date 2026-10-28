#!/usr/bin/env bash
# Copy the trial's SQLite store off the cluster.
#
# Uses SQLite's online backup inside the running pod, so the copy is
# consistent while the app keeps serving, then copies it to DEST (default
# ~/acq-backups). The volume is the only other copy, so a backup that stays
# in the cluster doesn't protect against losing it.
#
#   KUBECONFIG=~/.kube/dev-admin deploy/k8s/backup.sh [DEST]
set -euo pipefail

dest="${1:-${HOME}/acq-backups}"
mkdir -p "${dest}"
out="${dest}/acq-$(date -u +%Y%m%dT%H%M%SZ).db"
pod="$(kubectl -n acq get pod -l app=acq -o jsonpath='{.items[0].metadata.name}')"

kubectl -n acq exec "${pod}" -- /app/team-api/.venv/bin/python -c '
import sqlite3
src = sqlite3.connect("/data/team.db")
dst = sqlite3.connect("/data/backup.db")
src.backup(dst)
dst.close()
'
kubectl -n acq cp "${pod}:/data/backup.db" "${out}" >/dev/null
kubectl -n acq exec "${pod}" -- rm -f /data/backup.db

# Refuse to call a copy that SQLite can't open a backup.
python3 -c 'import sqlite3, sys; c = sqlite3.connect(sys.argv[1]); assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"; print(sys.argv[1], c.execute("select count(*) from questions").fetchone()[0], "questions")' "${out}"
