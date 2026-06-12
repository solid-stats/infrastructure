#!/usr/bin/env bash
# NOTE: The Job spec is created inline (kubectl apply -f -); no manifest
# file is written to k8s/staging/. This Job is purely operator-driven and never reaches the CD glob.
set -euo pipefail

required() {
  if [ -z "${!1:-}" ]; then
    echo "FATAL: $1 is required but not set" >&2
    exit 64
  fi
}

namespace="${K8S_NAMESPACE:-solid-stats-staging}"
job_name="apply-s3-lifecycle-$(date -u +%Y%m%d%H%M%S)"
configmap_name="s3-lifecycle-policy-$(date -u +%Y%m%d%H%M%S)"
timeout="${JOB_TIMEOUT:-120s}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIFECYCLE_JSON="${SCRIPT_DIR}/../config/s3/backups-lifecycle.json"

# Abort if lifecycle config file is missing
test -f "$LIFECYCLE_JSON" || { echo "FATAL: $LIFECYCLE_JSON not found" >&2; exit 64; }

echo "INFO: applying S3 lifecycle config from ${LIFECYCLE_JSON}"
echo "INFO: namespace=${namespace} job=${job_name} configmap=${configmap_name}"

# Create a temporary ConfigMap from the lifecycle JSON file.
# This avoids shell-escaping hazards — JSON contains double-quotes which break
# heredoc/variable substitution in shell-generated YAML.
kubectl create configmap "$configmap_name" \
  --from-file=backups-lifecycle.json="$LIFECYCLE_JSON" \
  --namespace="$namespace" \
  -o yaml --dry-run=client | kubectl apply -f -

# Apply the lifecycle config via a one-shot in-cluster Job so S3 credentials
# never leave the cluster. The Job mounts the ConfigMap and calls aws s3api.
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${job_name}
  namespace: ${namespace}
  labels:
    app.kubernetes.io/name: apply-s3-lifecycle
    app.kubernetes.io/part-of: solid-stats
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 86400
  template:
    metadata:
      labels:
        app.kubernetes.io/name: apply-s3-lifecycle
        app.kubernetes.io/part-of: solid-stats
    spec:
      restartPolicy: Never
      serviceAccountName: postgres-backup
      automountServiceAccountToken: false
      volumes:
        - name: lifecycle-config
          configMap:
            name: ${configmap_name}
      containers:
        - name: apply-s3-lifecycle
          image: postgres:17-alpine
          imagePullPolicy: IfNotPresent
          volumeMounts:
            - name: lifecycle-config
              mountPath: /config
              readOnly: true
          env:
            - name: AWS_ACCESS_KEY_ID
              valueFrom:
                secretKeyRef:
                  name: server-2-runtime
                  key: S3_ACCESS_KEY_ID
            - name: AWS_SECRET_ACCESS_KEY
              valueFrom:
                secretKeyRef:
                  name: server-2-runtime
                  key: S3_SECRET_ACCESS_KEY
            - name: S3_BUCKET
              valueFrom:
                secretKeyRef:
                  name: server-2-runtime
                  key: S3_BUCKET
            - name: AWS_DEFAULT_REGION
              value: ru-1
            - name: AWS_EC2_METADATA_DISABLED
              value: "true"
            - name: S3_ENDPOINT
              value: https://s3.twcstorage.ru
          resources:
            requests:
              cpu: 50m
              memory: 128Mi
            limits:
              cpu: 200m
              memory: 256Mi
          securityContext:
            allowPrivilegeEscalation: false
          command:
            - sh
            - -ec
            - |
              apk add --no-cache aws-cli
              export AWS_CONFIG_FILE=/tmp/aws-config
              aws configure set default.s3.addressing_style path

              get_output=\$(aws --endpoint-url="\$S3_ENDPOINT" s3api get-bucket-lifecycle-configuration \
                --bucket "\$S3_BUCKET" 2>&1) && get_rc=0 || get_rc=\$?

              if echo "\$get_output" | grep -q "NotImplemented"; then
                echo "FATAL: Timeweb S3 endpoint does not support lifecycle API. S3-03 empirical proof did not complete successfully. Do not apply retention policy." >&2
                exit 1
              elif [ "\$get_rc" -eq 0 ]; then
                echo "WARN: bucket already has a lifecycle configuration — review before applying" >&2
              elif echo "\$get_output" | grep -q "NoSuchLifecycleConfiguration"; then
                echo "INFO: no existing lifecycle config (expected on first apply)"
              else
                echo "FATAL: unexpected error from get-bucket-lifecycle-configuration: \$get_output" >&2
                exit 1
              fi

              aws --endpoint-url="\$S3_ENDPOINT" s3api put-bucket-lifecycle-configuration \
                --bucket "\$S3_BUCKET" \
                --lifecycle-configuration file:///config/backups-lifecycle.json

              echo "lifecycle configuration applied successfully"
EOF

# Wait for Job completion
if ! kubectl -n "$namespace" wait --for=condition=complete "job/$job_name" --timeout="$timeout"; then
  echo "ERROR: Job did not complete within ${timeout}" >&2
  kubectl -n "$namespace" describe "job/$job_name" || true
  kubectl -n "$namespace" logs "job/$job_name" --all-containers=true || true
  kubectl -n "$namespace" delete "job/$job_name" --ignore-not-found
  kubectl -n "$namespace" delete configmap "$configmap_name" --ignore-not-found
  exit 1
fi

kubectl -n "$namespace" logs "job/$job_name" --all-containers=true

# Cleanup (ttl also covers cleanup, this is belt-and-suspenders)
kubectl -n "$namespace" delete "job/$job_name" --ignore-not-found
kubectl -n "$namespace" delete configmap "$configmap_name" --ignore-not-found
