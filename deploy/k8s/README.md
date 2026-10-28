# Kubernetes

One pod running the team API, with its SQLite store on a persistent volume.
It is a single writer, so it runs one replica with the `Recreate` strategy, and
a restart or a move to another node means a short outage. Agents keep searching
their local copy meanwhile, and their writes wait in the outbox.

This directory is a kustomize base. A real deployment adds an overlay for what
depends on the cluster: how traffic reaches the `acq` Service (an Ingress or a
Gateway API `HTTPRoute`), node placement, and the storage class.

## First deploy

```sh
kubectl apply -k <overlay> --dry-run=server     # admission and quota problems show here
kubectl apply -k <overlay>
kubectl -n acq create secret generic acq-config \
  --from-literal=ACQ_JWT_SECRET="$(openssl rand -hex 32)" \
  --from-env-file=<file with GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET> \
  --from-literal=ACQ_ALLOWED_GITHUB_USERS=alice,bob
```

The GitHub OAuth app's callback is `https://<host>/auth/callback`, and it needs
device flow enabled so agents can get keys with `scripts/setup-agent.py`.
`ACQ_ALLOWED_GITHUB_USERS` decides who can sign in or hold a key; GitHub
sign-in alone admits any GitHub account.

To start from existing data, run `restore.sh` with a SQLite file before
anyone uses it.

## Operating it

| Task | Command |
|---|---|
| Pick up a new image | `kubectl -n acq rollout restart deployment/acq` |
| Change who's allowed | edit `ACQ_ALLOWED_GITHUB_USERS` in the `acq-config` secret, then restart |
| Back up | `deploy/k8s/backup.sh [DEST]` |
| Restore | `deploy/k8s/restore.sh FILE` (stops the app while it copies) |

`backup.sh` uses SQLite's online backup, so it is consistent while the app
serves, and copies the result off the cluster. Keep backups somewhere other
than the volume they protect.

The image is published to `ghcr.io/seanmeyer/acq-team-api` on every push to
`main`.
