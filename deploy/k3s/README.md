# k3s (web) deployment target

Unlike `deploy/raspberrypi/` (a self-contained install script), this
target's actual Kubernetes manifests and ArgoCD `Application` live in the
`myhomelab` GitOps repo, not here -- that's where every other app on this
cluster's manifests live, and where ArgoCD is already authenticated. This
directory only holds what's specific to *this repo*:

- `.github/workflows/build-k3s-image.yml` (repo root, not under here) --
  builds `app/Dockerfile` and pushes `ghcr.io/davisc01/spincycle:latest`
  to GHCR on every push to `app/**`.

The actual deployment lives at, in `myhomelab`:

- `k8s/base/spincycle/` -- namespace, PVCs (`local-path`), Deployment,
  Service, Ingress
- `k8s/apps/spincycle.yaml` -- the ArgoCD `Application` CR

After a push here builds a new image, pick it up with:

```
kubectl rollout restart deployment/spincycle -n spincycle
```

See the main [README.md](../../README.md)'s "Setup on k3s" section for
the full picture (session model, storage, why the format selector differs
from console mode, etc).
