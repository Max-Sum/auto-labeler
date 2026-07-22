# Installation

The published image is `ghcr.io/max-sum/auto-labeler:latest`. The GitHub
Container Registry package must be public, or the cluster needs an image pull
secret with access to it.

Install the RBAC rules, hook configuration, and operator into `kube-system`:

```shell
kubectl apply -n kube-system -f kubernetes/rbac.yaml
kubectl apply -n kube-system -f kubernetes/config.yaml
kubectl apply -n kube-system -f kubernetes/operator.yaml
```

Verify the rollout and inspect logs:

```shell
kubectl rollout status -n kube-system deployment/auto-labeler
kubectl logs -n kube-system deployment/auto-labeler --tail=100
```

To exercise the labeler with the sample deployment:

```shell
kubectl apply -f sample-workload.yaml
```
