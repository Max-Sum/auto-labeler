#!/bin/sh
set -eu

if [ -z "${KUBECONFIG:-}" ]; then
    service_account_dir=/var/run/secrets/kubernetes.io/serviceaccount
    kubeconfig_path=/tmp/auto-labeler-kubeconfig
    kube_port=${KUBERNETES_SERVICE_PORT_HTTPS:-443}

    : "${KUBERNETES_SERVICE_HOST:?Kubernetes service host is not available}"
    test -r "${service_account_dir}/ca.crt"
    test -r "${service_account_dir}/token"

    umask 077
    cat >"${kubeconfig_path}" <<EOF
apiVersion: v1
kind: Config
clusters:
- name: in-cluster
  cluster:
    certificate-authority: ${service_account_dir}/ca.crt
    server: https://${KUBERNETES_SERVICE_HOST}:${kube_port}
contexts:
- name: in-cluster
  context:
    cluster: in-cluster
    user: service-account
current-context: in-cluster
users:
- name: service-account
  user:
    tokenFile: ${service_account_dir}/token
EOF
    export KUBECONFIG=${kubeconfig_path}
fi

exec /sbin/tini -- /shell-operator "$@"
