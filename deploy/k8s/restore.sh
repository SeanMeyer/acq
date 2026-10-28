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
sha="$(shasum -a 256 "${file}" | cut -d' ' -f1)"
# The restore pod runs the app's own image, so it needs whatever the
# deployment needs to pull it.
image="$(kubectl -n acq get deployment acq -o jsonpath='{.spec.template.spec.containers[0].image}')"
pull_secrets="$(kubectl -n acq get deployment acq -o jsonpath='{.spec.template.spec.imagePullSecrets}')"

swapped=0
finish() {
    status=$?
    # The volume attaches to one pod at a time, so the app can't start while
    # the restore pod might still hold it.
    if ! kubectl -n acq delete pod acq-restore --ignore-not-found --wait=true --timeout=180s; then
        echo "Couldn't remove pod acq-restore, which holds the volume. The app is left stopped; delete that pod, then scale deployment/acq to 1." >&2
        exit 1
    fi
    if [[ ${status} -eq 0 || ${swapped} -eq 0 ]]; then
        kubectl -n acq scale deployment/acq --replicas=1 >/dev/null
        if [[ ${status} -ne 0 ]]; then
            echo "Restore failed before the swap; the old store is untouched and the app is starting again." >&2
        elif ! kubectl -n acq rollout status deployment/acq --timeout=300s; then
            echo "The restored store is in place but the app didn't come up on it. The previous store is in /data/pre-restore-* on the volume." >&2
            exit 1
        fi
    else
        echo "Restore failed during the swap. The app is left stopped. The previous store is in /data/pre-restore-* on the volume; put it back or run this script again, then scale deployment/acq to 1." >&2
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
  imagePullSecrets: ${pull_secrets:-[]}
  securityContext:
    runAsUser: 100
    runAsGroup: 101
    fsGroup: 101
  containers:
    - name: restore
      image: ${image}
      imagePullPolicy: IfNotPresent
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
# integrity_check says the copy is a database, the checksum that it is the
# file that was sent.
kubectl -n acq exec acq-restore -- /app/team-api/.venv/bin/python -c '
import hashlib, sqlite3, sys
path = "/data/team.db.restore"
assert hashlib.sha256(open(path, "rb").read()).hexdigest() == sys.argv[1], "copy differs from the file sent"
conn = sqlite3.connect(path)
assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
conn.close()
' "${sha}"
kubectl -n acq exec acq-restore -- rm -f /data/team.db.restore-wal /data/team.db.restore-shm
# The old store's WAL can still hold committed writes, so its files move
# aside as a set rather than being deleted; that set is how to undo this by
# hand. From here the volume is no longer the old store, so a failure leaves
# the app stopped.
swapped=1
kubectl -n acq exec acq-restore -- sh -c '
set -e
old=/data/pre-restore-$(date -u +%Y%m%dT%H%M%SZ)
mkdir "$old"
for f in /data/team.db /data/team.db-wal /data/team.db-shm; do
    if [ -e "$f" ]; then mv "$f" "$old/"; fi
done
mv /data/team.db.restore /data/team.db
echo "Previous store kept in $old"
'
