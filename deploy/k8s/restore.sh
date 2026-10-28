#!/usr/bin/env bash
# Put a SQLite file onto the trial's volume, replacing what is there.
#
# Stops the app first so nothing writes during the copy, mounts the volume in
# a short-lived pod, copies FILE in as /data/team.db, then starts the app
# again. Also how the first deploy gets its data.
#
#   KUBECONFIG=~/.kube/dev-admin deploy/k8s/restore.sh FILE
set -euo pipefail

file="${1:?usage: restore.sh FILE}"
python3 -c 'import sqlite3, sys; assert sqlite3.connect(sys.argv[1]).execute("PRAGMA integrity_check").fetchone()[0] == "ok"' "${file}"

kubectl -n acq scale deployment/acq --replicas=0
kubectl -n acq wait --for=delete pod -l app=acq --timeout=120s || true

kubectl -n acq apply -f - <<'POD'
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
      image: busybox:1.37
      command: ["sleep", "3600"]
      volumeMounts:
        - name: data
          mountPath: /data
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: acq-data
POD
trap 'kubectl -n acq delete pod acq-restore --wait=false >/dev/null 2>&1 || true' EXIT
kubectl -n acq wait --for=condition=Ready pod/acq-restore --timeout=300s

kubectl -n acq exec acq-restore -- rm -f /data/team.db /data/team.db-wal /data/team.db-shm
kubectl -n acq cp "${file}" acq-restore:/data/team.db
kubectl -n acq delete pod acq-restore --wait=true
trap - EXIT

kubectl -n acq scale deployment/acq --replicas=1
kubectl -n acq rollout status deployment/acq --timeout=300s
