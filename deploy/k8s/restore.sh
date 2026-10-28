#!/usr/bin/env bash
# Put a SQLite file onto the deployment's volume, replacing what is there.
#
# Stops the app so nothing writes, mounts the volume in a short-lived pod
# running the app's own image, copies FILE in under a staging name, checks it
# there, and only then swaps it in. A failure before the swap leaves the old
# store untouched and starts the app again; a failure after it leaves the app
# stopped, because what is on the volume can no longer be vouched for. Also
# how the first deploy gets its data.
#
#   KUBECONFIG=~/.kube/dev-admin deploy/k8s/restore.sh FILE
set -euo pipefail

file="${1:?usage: restore.sh FILE}"
python3 -c 'import sqlite3, sys; assert sqlite3.connect(sys.argv[1]).execute("PRAGMA integrity_check").fetchone()[0] == "ok"' "${file}"
image="$(kubectl -n acq get deployment acq -o jsonpath='{.spec.template.spec.containers[0].image}')"

swapped=0
finish() {
    status=$?
    kubectl -n acq delete pod acq-restore --ignore-not-found --wait=true >/dev/null 2>&1 || true
    if [[ ${status} -eq 0 || ${swapped} -eq 0 ]]; then
        kubectl -n acq scale deployment/acq --replicas=1 >/dev/null
        [[ ${status} -eq 0 ]] || echo "Restore failed before the swap; the old store is untouched and the app is starting again." >&2
    else
        echo "Restore failed after the swap. The app is left stopped. Check /data on the volume, then run this script again or scale deployment/acq to 1." >&2
    fi
}
trap finish EXIT

kubectl -n acq scale deployment/acq --replicas=0
kubectl -n acq wait --for=delete pod -l app=acq --timeout=180s

kubectl -n acq apply -f - <<POD
apiVersion: v1
kind: Pod
metadata:
  name: acq-restore
spec:
  securityContext:
    runAsUser: 100
    runAsGroup: 101
    fsGroup: 101
  containers:
    - name: restore
      image: ${image}
      command: ["sleep", "3600"]
      volumeMounts:
        - name: data
          mountPath: /data
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: acq-data
POD
kubectl -n acq wait --for=condition=Ready pod/acq-restore --timeout=300s

kubectl -n acq exec acq-restore -- rm -f /data/team.db.restore
kubectl -n acq cp "${file}" acq-restore:/data/team.db.restore
kubectl -n acq exec acq-restore -- /app/team-api/.venv/bin/python -c '
import sqlite3
assert sqlite3.connect("/data/team.db.restore").execute("PRAGMA integrity_check").fetchone()[0] == "ok"
'
# Nothing else has the store open, so its WAL and SHM files belong to the old
# database and must not be applied to the new one. Rename is atomic.
swapped=1
kubectl -n acq exec acq-restore -- sh -c 'rm -f /data/team.db-wal /data/team.db-shm && mv /data/team.db.restore /data/team.db'
