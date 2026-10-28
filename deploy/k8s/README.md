# Kubernetes

One pod running the team API, with its SQLite store on a persistent volume.
It is a single writer, so it runs one replica with the `Recreate` strategy, and
a restart or a move to another node means a short outage. Agents keep searching
their local copy meanwhile, and their writes wait in the outbox.

This directory is a kustomize base. A real deployment adds an overlay for what
depends on the cluster: how traffic reaches the `acq` Service (an Ingress or a
Gateway API `HTTPRoute`), node placement, and the storage class.

## First deploy

The image is published to `ghcr.io/seanmeyer/acq-team-api`, tagged with each
commit SHA. GHCR creates a new package as private, so after the first publish
either make the package public (package settings, Change visibility) or give
the overlay an `imagePullSecret`. Pin the overlay to a SHA tag rather than
`latest`, so a pod restart never brings in an untested build.

```sh
# One env file holding all four settings (kubectl won't mix an env file with --from-literal):
#   ACQ_JWT_SECRET=<openssl rand -hex 32>
#   GITHUB_CLIENT_ID=...
#   GITHUB_CLIENT_SECRET=...
#   ACQ_ALLOWED_GITHUB_USERS=alice,bob
kubectl apply -k <overlay> --dry-run=server     # admission and quota problems show here
kubectl apply -k <overlay>
kubectl -n acq create secret generic acq-config --from-env-file=<that file>
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
| Pick up a new image | set the overlay's tag to the new commit SHA, back up, then `kubectl apply -k <overlay>` |
| Change who's allowed | edit `ACQ_ALLOWED_GITHUB_USERS` in the `acq-config` secret, then `kubectl -n acq rollout restart deployment/acq` |
| Back up | `deploy/k8s/backup.sh [DEST]` |
| Restore | `deploy/k8s/restore.sh FILE` (stops the app while it copies) |

`backup.sh` uses SQLite's online backup, so it is consistent while the app
serves, and copies the result off the cluster. Keep backups somewhere other
than the volume they protect.
