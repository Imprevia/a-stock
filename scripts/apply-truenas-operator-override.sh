#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

# This path is deliberately narrower than the Helm entry point. It is only a
# repair tool for the already-existing, non-Helm CronJob on the verified
# TrueNAS k3s 1.26 controller. It never creates storage or touches workloads.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
DEFAULT_MANIFEST="$SCRIPT_DIR/../deploy/truenas/market-data-collection-cronjob-1.26-controller-shanghai.yaml"
MANIFEST="${OPERATOR_OVERRIDE_MANIFEST:-$DEFAULT_MANIFEST}"
# These identities are intentionally constants. An operator override must not
# be repointed at a different workload, database Service, or Secret by
# environment. The CronJob has no database volume; all runtime state is
# reached through the in-cluster PostgreSQL Service and Secret.
NAMESPACE="a-stock"
CRONJOB_NAME="market-data-collection"
EXPECTED_IMAGE="localhost/a-stock-market-environment:20260906-005226-2075b6e"
EXPECTED_DATABASE_SERVICE="market-environment-postgresql"
EXPECTED_DATABASE_SECRET="a-stock-postgresql"
KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
KUBECTL_SUBCOMMAND="${KUBECTL_SUBCOMMAND:-}"
KUBECTL_SUDO="${KUBECTL_SUDO:-false}"
TIMEDATECTL_BIN="${TIMEDATECTL_BIN:-timedatectl}"
SYSTEMCTL_BIN="${SYSTEMCTL_BIN:-systemctl}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
APPLY=false

log() { printf '[a-stock-operator-override] %s\n' "$*"; }
die() { printf '[a-stock-operator-override][error] %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'USAGE'
Usage: bash scripts/apply-truenas-operator-override.sh [--apply]

The default operation is read-only validation plus a server-side dry-run.
Pass --apply only after reviewing the dry-run output. The script requires an
existing exact, non-Helm-owned market-data-collection CronJob, the in-cluster
PostgreSQL Service, and an existing Secret with the database connection keys.
The CronJob must not mount a database PVC. It refuses to create or delete
resources.

For TrueNAS k3s, run with KUBECTL_BIN=k3s KUBECTL_SUBCOMMAND=kubectl and, when
needed, KUBECTL_SUDO=true KUBECONFIG=/etc/rancher/k3s/k3s.yaml.
USAGE
}

while (($#)); do
  case "$1" in
    --apply)
      APPLY=true
      shift
      ;;
    --manifest)
      (($# >= 2)) || die '--manifest requires a path'
      MANIFEST="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

[[ -f "$MANIFEST" ]] || die "override manifest not found: $MANIFEST"

KUBECTL_CMD=("$KUBECTL_BIN")
if [[ -n "$KUBECTL_SUBCOMMAND" ]]; then
  KUBECTL_CMD+=("$KUBECTL_SUBCOMMAND")
fi
if [[ "$KUBECTL_SUDO" == true ]]; then
  if [[ -n "${KUBECONFIG:-}" ]]; then
    # Preserve the explicit kubeconfig through sudo; relying on sudoers' env
    # allow-list would make the target context ambiguous.
    KUBECTL_CMD=(sudo env "KUBECONFIG=$KUBECONFIG" "${KUBECTL_CMD[@]}")
  else
    KUBECTL_CMD=(sudo "${KUBECTL_CMD[@]}")
  fi
elif [[ "$KUBECTL_SUDO" != false ]]; then
  die 'KUBECTL_SUDO must be true or false'
fi

kubectl_run() {
  "${KUBECTL_CMD[@]}" "$@"
}

read_controller_timezone() {
  local host_timezone controller_environment controller_timezone
  host_timezone="$("$TIMEDATECTL_BIN" show -p Timezone --value 2>/dev/null)" \
    || die 'could not read host timezone with timedatectl'
  host_timezone="${host_timezone#Timezone=}"
  [[ "$host_timezone" == Asia/Shanghai ]] \
    || die "host timezone must be Asia/Shanghai, got $host_timezone"

  controller_environment="$("$SYSTEMCTL_BIN" show k3s -p Environment --value 2>/dev/null)" \
    || die 'could not read k3s controller environment'
  controller_timezone=''
  if [[ "$controller_environment" =~ (^|[[:space:]])TZ=([^[:space:]]+) ]]; then
    controller_timezone="${BASH_REMATCH[2]}"
  fi
  if [[ -n "$controller_timezone" && "$controller_timezone" != Asia/Shanghai ]]; then
    die "k3s controller TZ must be Asia/Shanghai or unset, got $controller_timezone"
  fi
  log "timezone verified: host=Asia/Shanghai controller=${controller_timezone:-inherited-host}"
}

validate_yaml() {
  local mode="$1"
  local source="$2"
  local input_file="$source"
  local cleanup_input=false
  if [[ "$source" == "-" ]]; then
    input_file="$(mktemp)"
    cleanup_input=true
    cat > "$input_file"
  fi
  local status
  if EXPECTED_IMAGE="$EXPECTED_IMAGE" EXPECTED_DATABASE_SERVICE="$EXPECTED_DATABASE_SERVICE" \
    EXPECTED_DATABASE_SECRET="$EXPECTED_DATABASE_SECRET" NAMESPACE="$NAMESPACE" \
    CRONJOB_NAME="$CRONJOB_NAME" MODE="$mode" \
    "$PYTHON_BIN" - "$input_file" <<'PY'
import json
import os
import sys

import yaml

source = sys.argv[1]
with open(source, encoding="utf-8") as stream:
    documents = [item for item in yaml.safe_load_all(stream) if item is not None]
if len(documents) != 1 or not isinstance(documents[0], dict):
    raise SystemExit("expected exactly one YAML object")
item = documents[0]
metadata = item.get("metadata")
spec = item.get("spec")
if item.get("apiVersion") != "batch/v1" or item.get("kind") != "CronJob":
    raise SystemExit("override must be a batch/v1 CronJob")
if not isinstance(metadata, dict) or metadata.get("name") != os.environ["CRONJOB_NAME"]:
    raise SystemExit("CronJob name does not match the exact override target")
if metadata.get("namespace") != os.environ["NAMESPACE"]:
    raise SystemExit("CronJob namespace does not match the exact override target")
if not isinstance(spec, dict):
    raise SystemExit("CronJob spec must be a mapping")
if "timeZone" in spec:
    raise SystemExit("k3s 1.26 override must omit spec.timeZone")
if os.environ["MODE"] == "manifest" and spec.get("schedule") != "30 16 * * 1-5":
    raise SystemExit("override schedule must be 30 16 * * 1-5")
if spec.get("suspend") is not False:
    raise SystemExit("override CronJob must be active (spec.suspend=false)")
if spec.get("concurrencyPolicy") != "Forbid":
    raise SystemExit("override CronJob must use concurrencyPolicy=Forbid")
if spec.get("startingDeadlineSeconds") != 1800:
    raise SystemExit("override CronJob must use startingDeadlineSeconds=1800")
if spec.get("successfulJobsHistoryLimit") != 3 or spec.get("failedJobsHistoryLimit") != 3:
    raise SystemExit("override Job history limits drifted")

job_spec = ((spec.get("jobTemplate") or {}).get("spec") or {})
if job_spec.get("backoffLimit") != 0 or job_spec.get("activeDeadlineSeconds") != 3600:
    raise SystemExit("override Job deadlines/backoff drifted")
pod = ((job_spec.get("template") or {}).get("spec") or {})
pod_metadata = ((job_spec.get("template") or {}).get("metadata") or {})
expected_labels = {
    "app.kubernetes.io/name": "market-data-collection",
    "app.kubernetes.io/part-of": "a-stock",
    "app.kubernetes.io/component": "data-collection",
}
if any((pod_metadata.get("labels") or {}).get(key) != value for key, value in expected_labels.items()):
    raise SystemExit("override pod labels drifted")
containers = pod.get("containers") or []
if len(containers) != 1 or containers[0].get("name") != "collector":
    raise SystemExit("override must contain exactly one collector container")
container = containers[0]
if container.get("image") != os.environ["EXPECTED_IMAGE"]:
    raise SystemExit("override image is not the frozen image")
if container.get("imagePullPolicy") != "IfNotPresent":
    raise SystemExit("override imagePullPolicy must be IfNotPresent")
if container.get("resources") != {
    "requests": {"cpu": "100m", "memory": "256Mi"},
    "limits": {"cpu": "1", "memory": "1Gi"},
}:
    raise SystemExit("override container resources drifted")
if container.get("command") != ["python", "-m", "src.market_environment.cli", "snapshots", "scheduled-refresh"]:
    raise SystemExit("override command drifted")
if pod.get("restartPolicy") != "Never":
    raise SystemExit("override restartPolicy must be Never")
expected_environment = {
    "TZ": {"name": "TZ", "value": "Asia/Shanghai"},
    "MARKET_ENVIRONMENT_DATABASE_URL": {
        "name": "MARKET_ENVIRONMENT_DATABASE_URL",
        "valueFrom": {"secretKeyRef": {"name": os.environ["EXPECTED_DATABASE_SECRET"], "key": "DATABASE_URL"}},
    },
    "MARKET_ENVIRONMENT_DATABASE_HOST": {
        "name": "MARKET_ENVIRONMENT_DATABASE_HOST",
        "value": os.environ["EXPECTED_DATABASE_SERVICE"],
    },
    "MARKET_ENVIRONMENT_DATABASE_PORT": {"name": "MARKET_ENVIRONMENT_DATABASE_PORT", "value": "5432"},
    "MARKET_ENVIRONMENT_DATABASE_NAME": {
        "name": "MARKET_ENVIRONMENT_DATABASE_NAME",
        "valueFrom": {"secretKeyRef": {"name": os.environ["EXPECTED_DATABASE_SECRET"], "key": "POSTGRES_DB"}},
    },
    "MARKET_ENVIRONMENT_DATABASE_USER": {
        "name": "MARKET_ENVIRONMENT_DATABASE_USER",
        "valueFrom": {"secretKeyRef": {"name": os.environ["EXPECTED_DATABASE_SECRET"], "key": "POSTGRES_USER"}},
    },
    "MARKET_ENVIRONMENT_DATABASE_PASSWORD": {
        "name": "MARKET_ENVIRONMENT_DATABASE_PASSWORD",
        "valueFrom": {"secretKeyRef": {"name": os.environ["EXPECTED_DATABASE_SECRET"], "key": "POSTGRES_PASSWORD"}},
    },
    "MARKET_ENVIRONMENT_DATABASE_SSLMODE": {"name": "MARKET_ENVIRONMENT_DATABASE_SSLMODE", "value": "prefer"},
    "MARKET_ENVIRONMENT_PERSISTENT_CACHE": {"name": "MARKET_ENVIRONMENT_PERSISTENT_CACHE", "value": "1"},
    "MARKET_ENVIRONMENT_SETTLEMENT_TIME": {"name": "MARKET_ENVIRONMENT_SETTLEMENT_TIME", "value": "15:10"},
}
environment = {entry.get("name"): entry for entry in (container.get("env") or [])}
if environment != expected_environment:
    raise SystemExit("override environment drifted")
volumes = pod.get("volumes") or []
if volumes != [
    {"name": "tmp", "emptyDir": {}},
]:
    raise SystemExit("override volumes drifted")
mounts = container.get("volumeMounts") or []
if mounts != [
    {"name": "tmp", "mountPath": "/tmp"},
]:
    raise SystemExit("override volume mounts drifted")
if pod.get("automountServiceAccountToken") is not False:
    raise SystemExit("override must disable service-account token automount")
security = pod.get("securityContext") or {}
if security != {
    "runAsNonRoot": True,
    "runAsUser": 10001,
    "runAsGroup": 10001,
    "fsGroup": 10001,
    "seccompProfile": {"type": "RuntimeDefault"},
}:
    raise SystemExit("override pod security context drifted")
container_security = container.get("securityContext") or {}
if container_security != {
    "allowPrivilegeEscalation": False,
    "readOnlyRootFilesystem": True,
    "capabilities": {"drop": ["ALL"]},
}:
    raise SystemExit("override container security context drifted")

labels = metadata.get("labels") or {}
annotations = metadata.get("annotations") or {}
required_labels = {
    "app.kubernetes.io/name": "market-data-collection",
    "app.kubernetes.io/part-of": "a-stock",
    "app.kubernetes.io/component": "data-collection",
}
if any(labels.get(key) != value for key, value in required_labels.items()):
    raise SystemExit("override application labels drifted")
if labels.get("app.kubernetes.io/managed-by") == "Helm":
    raise SystemExit("override manifest must not declare Helm ownership")
if any(str(key).startswith("meta.helm.sh/") for key in annotations):
    raise SystemExit("override manifest must not declare Helm ownership annotations")
if metadata.get("ownerReferences"):
    raise SystemExit("override must not declare controller ownership")

if os.environ["MODE"] == "live":
    if any(str(key).startswith("meta.helm.sh/") for key in annotations):
        raise SystemExit("refusing to modify a CronJob with Helm ownership annotations")
    if any((entry or {}).get("manager") == "helm" for entry in (metadata.get("managedFields") or [])):
        raise SystemExit("refusing to modify a CronJob with Helm managed fields")
print(json.dumps({"schedule": spec.get("schedule"), "image": container.get("image")}, sort_keys=True))
PY
  then
    status=0
  else
    status=$?
  fi
  if [[ "$cleanup_input" == true ]]; then
    rm -f -- "$input_file"
  fi
  return "$status"
}

validate_database_secret() {
  local input_file
  input_file="$(mktemp)"
  cat > "$input_file"
  local status
  if EXPECTED_DATABASE_SECRET="$EXPECTED_DATABASE_SECRET" NAMESPACE="$NAMESPACE" "$PYTHON_BIN" - "$input_file" <<'PY'
import json
import os
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    payload = json.load(stream)
metadata = payload.get("metadata") or {}
if payload.get("kind") != "Secret":
    raise SystemExit("database lookup returned a non-Secret object")
if metadata.get("name") != os.environ["EXPECTED_DATABASE_SECRET"] or metadata.get("namespace") != os.environ["NAMESPACE"]:
    raise SystemExit("database Secret identity does not match the exact override Secret")
if payload.get("type") not in (None, "Opaque"):
    raise SystemExit("database Secret must be Opaque")
required = {"DATABASE_URL", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"}
data = payload.get("data") or {}
missing = sorted(required - set(data))
if missing:
    raise SystemExit("database Secret is missing required keys: " + ",".join(missing))
print(json.dumps({"name": metadata["name"], "keys": sorted(data)}, sort_keys=True))
PY
  then
    status=0
  else
    status=$?
  fi
  rm -f -- "$input_file"
  return "$status"
}

validate_database_service() {
  local input_file
  input_file="$(mktemp)"
  cat > "$input_file"
  local status
  if EXPECTED_DATABASE_SERVICE="$EXPECTED_DATABASE_SERVICE" NAMESPACE="$NAMESPACE" "$PYTHON_BIN" - "$input_file" <<'PY'
import json
import os
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    payload = json.load(stream)
metadata = payload.get("metadata") or {}
spec = payload.get("spec") or {}
if payload.get("kind") != "Service":
    raise SystemExit("database lookup returned a non-Service object")
if metadata.get("name") != os.environ["EXPECTED_DATABASE_SERVICE"] or metadata.get("namespace") != os.environ["NAMESPACE"]:
    raise SystemExit("database Service identity does not match the exact override Service")
if spec.get("type") != "ClusterIP":
    raise SystemExit("database Service must remain ClusterIP")
ports = spec.get("ports") or []
if not any(item.get("port") == 5432 for item in ports if isinstance(item, dict)):
    raise SystemExit("database Service must expose PostgreSQL port 5432")
print(json.dumps({"name": metadata["name"], "type": spec["type"]}, sort_keys=True))
PY
  then
    status=0
  else
    status=$?
  fi
  rm -f -- "$input_file"
  return "$status"
}

read_controller_timezone
validate_yaml manifest "$MANIFEST" >/dev/null || die 'override manifest validation failed'

existing_cronjob="$(kubectl_run -n "$NAMESPACE" get cronjob "$CRONJOB_NAME" -o yaml 2>/dev/null)" \
  || die "could not read exact CronJob $NAMESPACE/$CRONJOB_NAME"
[[ -n "$existing_cronjob" ]] || die "exact CronJob $NAMESPACE/$CRONJOB_NAME does not exist; refusing to create it"
printf '%s\n' "$existing_cronjob" | validate_yaml live - >/dev/null \
  || die 'existing CronJob is Helm-owned or has an unsupported shape/drift'

secret_json="$(kubectl_run -n "$NAMESPACE" get secret "$EXPECTED_DATABASE_SECRET" -o json 2>/dev/null)" \
  || die "could not read exact database Secret $NAMESPACE/$EXPECTED_DATABASE_SECRET"
printf '%s\n' "$secret_json" | validate_database_secret \
  || die 'database Secret is missing or has drifted'

service_json="$(kubectl_run -n "$NAMESPACE" get service "$EXPECTED_DATABASE_SERVICE" -o json 2>/dev/null)" \
  || die "could not read exact database Service $NAMESPACE/$EXPECTED_DATABASE_SERVICE"
printf '%s\n' "$service_json" | validate_database_service \
  || die 'database Service is missing or has drifted'

log "exact target verified: CronJob=$NAMESPACE/$CRONJOB_NAME PostgreSQLService=$NAMESPACE/$EXPECTED_DATABASE_SERVICE Secret=$NAMESPACE/$EXPECTED_DATABASE_SECRET"
kubectl_run -n "$NAMESPACE" apply --dry-run=server \
  --field-manager=a-stock-operator-override -f "$MANIFEST" \
  || die 'server-side dry-run failed'
if [[ "$APPLY" != true ]]; then
  log 'dry-run passed; no resource was changed (re-run with --apply after review)'
  exit 0
fi

kubectl_run -n "$NAMESPACE" apply \
  --field-manager=a-stock-operator-override -f "$MANIFEST" \
  || die 'operator override apply failed'
updated_cronjob="$(kubectl_run -n "$NAMESPACE" get cronjob "$CRONJOB_NAME" -o yaml 2>/dev/null)" \
  || die 'could not read exact CronJob after apply'
printf '%s\n' "$updated_cronjob" | validate_yaml live - >/dev/null \
  || die 'post-apply CronJob shape is invalid'
printf '%s\n' "$updated_cronjob" | EXPECTED_IMAGE="$EXPECTED_IMAGE" "$PYTHON_BIN" -c '
import sys, yaml
item = yaml.safe_load(sys.stdin)
schedule = item["spec"].get("schedule")
image = item["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0].get("image")
if schedule != "30 16 * * 1-5":
    raise SystemExit("post-apply schedule must be 30 16 * * 1-5")
if image != __import__("os").environ["EXPECTED_IMAGE"]:
    raise SystemExit("post-apply image is not the frozen image")
print("postcondition=exact CronJob schedule=30 16 * * 1-5 suspend=false")
'
log 'operator override applied; PostgreSQL Secret/Service/Deployment were read-only and untouched'
