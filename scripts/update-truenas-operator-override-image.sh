#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

# Exact-resource repair for the already-existing, non-Helm collection CronJob.
# This path changes only the collector image.  It never creates/deletes a
# CronJob, changes suspension, or touches database storage.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
MANIFEST="${OPERATOR_OVERRIDE_MANIFEST:-$SCRIPT_DIR/../deploy/truenas/market-data-collection-cronjob-1.26-controller-shanghai.yaml}"
NAMESPACE="a-stock"
CRONJOB_NAME="market-data-collection"
EXPECTED_REPOSITORY="localhost/a-stock-market-environment"
OLD_IMAGE="${OPERATOR_OVERRIDE_OLD_IMAGE:-$EXPECTED_REPOSITORY:20260906-005226-2075b6e}"
KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
KUBECTL_SUBCOMMAND="${KUBECTL_SUBCOMMAND:-}"
KUBECTL_SUDO="${KUBECTL_SUDO:-false}"
TIMEDATECTL_BIN="${TIMEDATECTL_BIN:-timedatectl}"
SYSTEMCTL_BIN="${SYSTEMCTL_BIN:-systemctl}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
EXPECTED_DATABASE_SERVICE="market-environment-postgresql"
EXPECTED_DATABASE_SECRET="a-stock-postgresql"
IMAGE=""
APPLY=false

log() { printf '[a-stock-operator-image] %s\n' "$*"; }
die() { printf '[a-stock-operator-image][error] %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'USAGE'
Usage: bash scripts/update-truenas-operator-override-image.sh --image IMAGE [--apply]

The default operation is read-only validation plus server-side dry-run.  The
exact existing market-data-collection CronJob must be non-Helm-owned and use
the old frozen image.  --apply changes only its collector image.
USAGE
}

while (($#)); do
  case "$1" in
    --image) (($# >= 2)) || die '--image requires a value'; IMAGE="$2"; shift 2 ;;
    --manifest) (($# >= 2)) || die '--manifest requires a path'; MANIFEST="$2"; shift 2 ;;
    --apply) APPLY=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[[ -f "$MANIFEST" ]] || die "override manifest not found: $MANIFEST"
[[ "$IMAGE" =~ ^${EXPECTED_REPOSITORY//./\\.}:[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] \
  || die "image must be an immutable tag under $EXPECTED_REPOSITORY"
[[ "$IMAGE" != "$OLD_IMAGE" ]] || die 'new image must differ from the old frozen image'

KUBECTL_CMD=("$KUBECTL_BIN")
[[ -z "$KUBECTL_SUBCOMMAND" ]] || KUBECTL_CMD+=("$KUBECTL_SUBCOMMAND")
if [[ "$KUBECTL_SUDO" == true ]]; then
  if [[ -n "${KUBECONFIG:-}" ]]; then
    KUBECTL_CMD=(sudo env "KUBECONFIG=$KUBECONFIG" "${KUBECTL_CMD[@]}")
  else
    KUBECTL_CMD=(sudo "${KUBECTL_CMD[@]}")
  fi
elif [[ "$KUBECTL_SUDO" != false ]]; then
  die 'KUBECTL_SUDO must be true or false'
fi
kubectl_run() { "${KUBECTL_CMD[@]}" "$@"; }

read_controller_timezone() {
  local host_timezone controller_environment controller_timezone=''
  host_timezone="$($TIMEDATECTL_BIN show -p Timezone --value 2>/dev/null)" \
    || die 'could not read host timezone'
  host_timezone="${host_timezone#Timezone=}"
  [[ "$host_timezone" == Asia/Shanghai ]] || die "host timezone must be Asia/Shanghai, got $host_timezone"
  controller_environment="$($SYSTEMCTL_BIN show k3s -p Environment --value 2>/dev/null)" \
    || die 'could not read k3s controller environment'
  if [[ "$controller_environment" =~ (^|[[:space:]])TZ=([^[:space:]]+) ]]; then
    controller_timezone="${BASH_REMATCH[2]}"
  fi
  [[ -z "$controller_timezone" || "$controller_timezone" == Asia/Shanghai ]] \
    || die "k3s controller TZ must be Asia/Shanghai or unset, got $controller_timezone"
  log "timezone verified: host=Asia/Shanghai controller=${controller_timezone:-inherited-host}"
}

validate_resource() {
  local mode="$1" source="$2"
  MODE="$mode" EXPECTED_IMAGE="$IMAGE" EXPECTED_OLD_IMAGE="$OLD_IMAGE" \
    EXPECTED_DATABASE_SERVICE="$EXPECTED_DATABASE_SERVICE" EXPECTED_DATABASE_SECRET="$EXPECTED_DATABASE_SECRET" \
    NAMESPACE="$NAMESPACE" CRONJOB_NAME="$CRONJOB_NAME" \
    "$PYTHON_BIN" - "$source" <<'PY'
import os, sys, yaml

with open(sys.argv[1], encoding='utf-8') as stream:
    docs = [item for item in yaml.safe_load_all(stream) if item is not None]
if len(docs) != 1 or not isinstance(docs[0], dict):
    raise SystemExit('expected one CronJob object')
item = docs[0]
meta, spec = item.get('metadata') or {}, item.get('spec') or {}
if item.get('apiVersion') != 'batch/v1' or item.get('kind') != 'CronJob':
    raise SystemExit('expected batch/v1 CronJob')
if meta.get('name') != os.environ['CRONJOB_NAME'] or meta.get('namespace') != os.environ['NAMESPACE']:
    raise SystemExit('CronJob identity drifted')
if meta.get('labels') != {
    'app.kubernetes.io/name': 'market-data-collection',
    'app.kubernetes.io/part-of': 'a-stock',
    'app.kubernetes.io/component': 'data-collection',
}:
    raise SystemExit('CronJob labels drifted')
if meta.get('ownerReferences') or meta.get('managedFields') and any(
    (entry or {}).get('manager') == 'helm' for entry in meta['managedFields']):
    raise SystemExit('CronJob must remain non-Helm-owned')
if any(str(k).startswith('meta.helm.sh/') for k in (meta.get('annotations') or {})):
    raise SystemExit('CronJob has Helm ownership annotations')
if spec.get('schedule') != '30 16 * * 1-5' or spec.get('suspend') is not False:
    raise SystemExit('schedule or suspend drifted')
if spec.get('concurrencyPolicy') != 'Forbid' or spec.get('startingDeadlineSeconds') != 1800:
    raise SystemExit('CronJob policy drifted')
if spec.get('successfulJobsHistoryLimit') != 3 or spec.get('failedJobsHistoryLimit') != 3:
    raise SystemExit('CronJob history limits drifted')
job = (spec.get('jobTemplate') or {}).get('spec') or {}
if job.get('backoffLimit') != 0 or job.get('activeDeadlineSeconds') != 3600:
    raise SystemExit('Job policy drifted')
pod_template = job.get('template') or {}
pod, pod_meta = pod_template.get('spec') or {}, pod_template.get('metadata') or {}
if pod_meta.get('labels') != {
    'app.kubernetes.io/name': 'market-data-collection',
    'app.kubernetes.io/part-of': 'a-stock',
    'app.kubernetes.io/component': 'data-collection',
}:
    raise SystemExit('Pod labels drifted')
containers = pod.get('containers') or []
if len(containers) != 1 or containers[0].get('name') != 'collector':
    raise SystemExit('collector container shape drifted')
container = containers[0]
expected_image = os.environ['EXPECTED_IMAGE'] if os.environ['MODE'] == 'desired' else os.environ['EXPECTED_OLD_IMAGE']
if container.get('image') != expected_image:
    raise SystemExit(f'expected image {expected_image}, got {container.get("image")}')
if container.get('imagePullPolicy') != 'IfNotPresent' or container.get('command') != [
    'python', '-m', 'src.market_environment.cli', 'snapshots', 'scheduled-refresh']:
    raise SystemExit('collector image policy or command drifted')
expected_environment = {
    'TZ': {'name': 'TZ', 'value': 'Asia/Shanghai'},
    'MARKET_ENVIRONMENT_DATABASE_URL': {
        'name': 'MARKET_ENVIRONMENT_DATABASE_URL',
        'valueFrom': {'secretKeyRef': {'name': os.environ['EXPECTED_DATABASE_SECRET'], 'key': 'DATABASE_URL'}},
    },
    'MARKET_ENVIRONMENT_DATABASE_HOST': {'name': 'MARKET_ENVIRONMENT_DATABASE_HOST', 'value': os.environ['EXPECTED_DATABASE_SERVICE']},
    'MARKET_ENVIRONMENT_DATABASE_PORT': {'name': 'MARKET_ENVIRONMENT_DATABASE_PORT', 'value': '5432'},
    'MARKET_ENVIRONMENT_DATABASE_NAME': {
        'name': 'MARKET_ENVIRONMENT_DATABASE_NAME',
        'valueFrom': {'secretKeyRef': {'name': os.environ['EXPECTED_DATABASE_SECRET'], 'key': 'POSTGRES_DB'}},
    },
    'MARKET_ENVIRONMENT_DATABASE_USER': {
        'name': 'MARKET_ENVIRONMENT_DATABASE_USER',
        'valueFrom': {'secretKeyRef': {'name': os.environ['EXPECTED_DATABASE_SECRET'], 'key': 'POSTGRES_USER'}},
    },
    'MARKET_ENVIRONMENT_DATABASE_PASSWORD': {
        'name': 'MARKET_ENVIRONMENT_DATABASE_PASSWORD',
        'valueFrom': {'secretKeyRef': {'name': os.environ['EXPECTED_DATABASE_SECRET'], 'key': 'POSTGRES_PASSWORD'}},
    },
    'MARKET_ENVIRONMENT_DATABASE_SSLMODE': {'name': 'MARKET_ENVIRONMENT_DATABASE_SSLMODE', 'value': 'prefer'},
    'MARKET_ENVIRONMENT_PERSISTENT_CACHE': {'name': 'MARKET_ENVIRONMENT_PERSISTENT_CACHE', 'value': '1'},
    'MARKET_ENVIRONMENT_SETTLEMENT_TIME': {'name': 'MARKET_ENVIRONMENT_SETTLEMENT_TIME', 'value': '15:10'},
}
if {x.get('name'): x for x in container.get('env') or []} != expected_environment:
    raise SystemExit('collector environment drifted')
if container.get('resources') != {'requests': {'cpu': '100m', 'memory': '256Mi'}, 'limits': {'cpu': '1', 'memory': '1Gi'}}:
    raise SystemExit('collector resources drifted')
if container.get('securityContext') != {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True, 'capabilities': {'drop': ['ALL']}}:
    raise SystemExit('collector security context drifted')
if pod.get('restartPolicy') != 'Never' or pod.get('automountServiceAccountToken') is not False:
    raise SystemExit('Pod security policy drifted')
if pod.get('securityContext') != {'runAsNonRoot': True, 'runAsUser': 10001, 'runAsGroup': 10001, 'fsGroup': 10001, 'seccompProfile': {'type': 'RuntimeDefault'}}:
    raise SystemExit('Pod security context drifted')
if pod.get('volumes') != [{'name': 'tmp', 'emptyDir': {}}]:
    raise SystemExit('temp volume drifted')
if container.get('volumeMounts') != [{'name': 'tmp', 'mountPath': '/tmp'}]:
    raise SystemExit('volume mounts drifted')
print('validated', os.environ['MODE'], 'image=', container['image'])
PY
}

desired_manifest="$(mktemp)"
trap 'rm -f -- "$desired_manifest"' EXIT
IMAGE="$IMAGE" "$PYTHON_BIN" - "$MANIFEST" "$desired_manifest" <<'PY'
import os, sys, yaml
with open(sys.argv[1], encoding='utf-8') as stream:
    item = yaml.safe_load(stream)
item['spec']['jobTemplate']['spec']['template']['spec']['containers'][0]['image'] = os.environ['IMAGE']
with open(sys.argv[2], 'w', encoding='utf-8') as stream:
    yaml.safe_dump(item, stream, sort_keys=False)
PY

read_controller_timezone
validate_resource desired "$desired_manifest" || die 'desired exact manifest validation failed'
existing_cronjob="$(kubectl_run -n "$NAMESPACE" get cronjob "$CRONJOB_NAME" -o yaml 2>/dev/null)" \
  || die "could not read exact CronJob $NAMESPACE/$CRONJOB_NAME"
existing_file="$(mktemp)"
trap 'rm -f -- "$desired_manifest" "$existing_file"' EXIT
printf '%s\n' "$existing_cronjob" > "$existing_file"
validate_resource live "$existing_file" || die 'live CronJob is not the expected old exact resource'

if command -v k3s >/dev/null 2>&1; then
  image_digest="$(sudo -n k3s ctr --namespace k8s.io images list 2>/dev/null | awk -v image="$IMAGE" '$1 == image {print $3}')"
  [[ "$image_digest" =~ ^sha256:[0-9a-f]{64}$ ]] || die "candidate image is not imported in local k3s containerd: $IMAGE"
  log "candidate image verified in containerd: $IMAGE digest=$image_digest"
else
  log 'containerd verification delegated to the TrueNAS invocation environment'
fi

kubectl_run -n "$NAMESPACE" apply --dry-run=server --field-manager=a-stock-operator-override-image -f "$desired_manifest" \
  || die 'server-side dry-run failed'
if [[ "$APPLY" != true ]]; then
  log 'dry-run passed; no resource was changed (re-run with --apply after review)'
  exit 0
fi
kubectl_run -n "$NAMESPACE" apply --field-manager=a-stock-operator-override-image -f "$desired_manifest" \
  || die 'exact CronJob image update failed'
updated="$(kubectl_run -n "$NAMESPACE" get cronjob "$CRONJOB_NAME" -o yaml 2>/dev/null)" || die 'could not read CronJob after apply'
printf '%s\n' "$updated" > "$existing_file"
validate_resource desired "$existing_file" || die 'post-apply exact CronJob validation failed'
log "postcondition=exact CronJob image=$IMAGE schedule=30 16 * * 1-5 suspend=false PostgreSQLService=$EXPECTED_DATABASE_SERVICE Secret=$EXPECTED_DATABASE_SECRET"
