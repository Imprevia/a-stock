#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

log() {
  printf '[a-stock-deploy] %s\n' "$*"
}

warn() {
  printf '[a-stock-deploy][warn] %s\n' "$*" >&2
}

die() {
  printf '[a-stock-deploy][error] %s\n' "$*" >&2
  exit 1
}

is_absolute_path() {
  [[ "$1" == /* || "$1" =~ ^[[:alpha:]]:[/\\].*$ ]]
}

filesystem_available_bytes() {
  LC_ALL=C df -Pk -- "$1" | awk 'NR == 2 { printf "%.0f\n", $4 * 1024 }'
}

archive_required_bytes() {
  local image_size_bytes="$1"
  local margin_bytes=$((image_size_bytes / 4))
  local minimum_margin_bytes=$((256 * 1024 * 1024))
  if ((margin_bytes < minimum_margin_bytes)); then
    margin_bytes="$minimum_margin_bytes"
  fi
  printf '%s\n' "$((image_size_bytes + margin_bytes))"
}

bytes_to_mib_ceil() {
  printf '%s\n' "$((($1 + 1024 * 1024 - 1) / (1024 * 1024)))"
}

select_archive_temp_root() {
  local required_bytes="$1"
  local explicit=false
  local candidate canonical available_bytes duplicate existing
  local -a candidates=()
  local -a checked=()
  local -a rejected=()

  if [[ -n "${DEPLOY_TMP_ROOT:-}" ]]; then
    explicit=true
    candidates+=("$DEPLOY_TMP_ROOT")
  else
    if [[ -n "${TMPDIR:-}" ]]; then
      candidates+=("$TMPDIR")
    fi
    candidates+=(/dev/shm /tmp)
  fi

  for candidate in "${candidates[@]}"; do
    if ! is_absolute_path "$candidate"; then
      if [[ "$explicit" == true ]]; then
        die 'DEPLOY_TMP_ROOT must be an absolute path'
      fi
      rejected+=("$candidate (not absolute)")
      continue
    fi
    if [[ ! -d "$candidate" || ! -w "$candidate" || ! -x "$candidate" ]]; then
      if [[ "$explicit" == true ]]; then
        die "DEPLOY_TMP_ROOT must be an existing writable directory: $candidate"
      fi
      rejected+=("$candidate (unavailable)")
      continue
    fi
    canonical="$(readlink -f -- "$candidate")" \
      || die "failed to resolve image archive temp root: $candidate"
    duplicate=false
    for existing in "${checked[@]}"; do
      if [[ "$existing" == "$canonical" ]]; then
        duplicate=true
        break
      fi
    done
    if [[ "$duplicate" == true ]]; then
      continue
    fi
    checked+=("$canonical")
    available_bytes="$(filesystem_available_bytes "$canonical")"
    [[ "$available_bytes" =~ ^[0-9]+$ ]] \
      || die "failed to read available bytes for image archive temp root: $canonical"
    if ((available_bytes >= required_bytes)); then
      printf '%s\n' "$canonical"
      return 0
    fi
    rejected+=("$canonical ($(bytes_to_mib_ceil "$available_bytes") MiB available)")
  done

  die "image archive requires $(bytes_to_mib_ceil "$required_bytes") MiB including safety margin; checked ${rejected[*]:-no usable directories}. Set DEPLOY_TMP_ROOT to a writable filesystem with enough free space"
}

usage() {
  cat <<'USAGE'
Usage: bash scripts/deploy-truenas-k3s.sh [--env-file PATH]
                                    [--component {all,database,service}]

Component selection (default: all):
  all       - render and apply every supported resource (legacy one-click)
  database  - render and verify only the reviewed RWO PVC contract
  service   - render and apply the Dashboard Deployment/Service/Ingress

Controlled manual collection freeze (same image, full reviewed packet):
  --disable-manual-refresh --baseline-values PATH --kube-version VERSION

Controlled Fuyao sectors modes:
  --stage-sectors-off --off-values PATH --enabled-values PATH --kube-version VERSION
  --promote-sectors-capability --off-values PATH --enabled-values PATH --report PATH [--apply]
  --enable-sectors-config --off-values PATH --enabled-values PATH --kube-version VERSION
  --disable-sectors-config --off-values PATH --enabled-values PATH --kube-version VERSION

All renders accept --release-name NAME and --namespace NAME. Target modes bind
these values and --kube-version to live discovery before any write.

The command must run on the 1.21 Linux VM. It builds the image from the
repository, smoke-tests it, copies an archive to TrueNAS 1.20, imports it into
k3s/containerd, and installs/upgrades the Helm release.
USAGE
}

VALID_COMPONENTS=("all" "database" "service")
COMPONENT_NAME="all"
COMPONENT_SELECTED=false
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
COMPONENT_BASELINE_FILE="${COMPONENT_BASELINE_FILE:-$SCRIPT_DIR/../tests/fixtures/truenas_component_baseline.yaml}"
# Git Bash exposes repository paths as /<drive>/..., while native Windows
# Python resolves drive-letter paths. Normalize only when cygpath exists;
# Linux/TrueNAS execution keeps the original POSIX path unchanged.
if command -v cygpath >/dev/null 2>&1; then
  COMPONENT_BASELINE_FILE="$(cygpath -w "$COMPONENT_BASELINE_FILE")"
fi
COMPONENT_BASELINE_RELEASE=""
COMPONENT_BASELINE_NAMESPACE=""
COMPONENT_BASELINE_CLAIM=""
COMPONENT_BASELINE_STORAGE_CLASS=""
COMPONENT_BASELINE_STORAGE=""
COMPONENT_BASELINE_ACCESS_MODES=""
COMPONENT_BASELINE_MOUNT_PATH=""
COMPONENT_BASELINE_SNAPSHOT_PATH=""
COMPONENT_BASELINE_TOPOLOGY_REPLICAS=1
COMPONENT_BASELINE_TOPOLOGY_READONLY=true
COMPONENT_BASELINE_TOPOLOGY_STRATEGY="Recreate"
COMPONENT_BASELINE_AUTOMOUNT_TOKEN=false
COMPONENT_BASELINE_IMAGE_REPOSITORY=""
COMPONENT_BASELINE_IMAGE_TAG_PATTERN=""
COMPONENT_BASELINE_IMAGE_PULL_POLICY="IfNotPresent"

ENV_FILE="${DEPLOY_ENV_FILE:-/home/gyt/a-stock/deploy/truenas/deploy.env}"
OPERATION=deploy
OPERATION_SELECTED=false
BASELINE_VALUES_FILE=''
TARGET_KUBERNETES_VERSION=''
CLI_RELEASE_NAME=''
CLI_NAMESPACE=''
CLI_SECTORS_OFF_VALUES_FILE=''
CLI_SECTORS_ENABLED_VALUES_FILE=''
CLI_CAPABILITY_REPORT_FILE=''
PROMOTION_APPLY=false

set_operation() {
  local requested="$1"
  if [[ "$OPERATION_SELECTED" == true ]]; then
    die 'select exactly one operation mode'
  fi
  OPERATION="$requested"
  OPERATION_SELECTED=true
}

while (($#)); do
  case "$1" in
    --env-file)
      (($# >= 2)) || die '--env-file requires a path'
      ENV_FILE="$2"
      shift 2
      ;;
    --disable-manual-refresh)
      set_operation disable-manual-refresh
      shift
      ;;
    --stage-sectors-off)
      set_operation stage-sectors-off
      shift
      ;;
    --promote-sectors-capability)
      set_operation promote-sectors-capability
      shift
      ;;
    --enable-sectors-config)
      set_operation enable-sectors-config
      shift
      ;;
    --disable-sectors-config)
      set_operation disable-sectors-config
      shift
      ;;
    --baseline-values)
      (($# >= 2)) || die '--baseline-values requires a path'
      BASELINE_VALUES_FILE="$2"
      shift 2
      ;;
    --kube-version)
      (($# >= 2)) || die '--kube-version requires a version'
      TARGET_KUBERNETES_VERSION="$2"
      shift 2
      ;;
    --release-name)
      (($# >= 2)) || die '--release-name requires a name'
      CLI_RELEASE_NAME="$2"
      shift 2
      ;;
    --namespace)
      (($# >= 2)) || die '--namespace requires a name'
      CLI_NAMESPACE="$2"
      shift 2
      ;;
    --off-values)
      (($# >= 2)) || die '--off-values requires a path'
      CLI_SECTORS_OFF_VALUES_FILE="$2"
      shift 2
      ;;
    --enabled-values)
      (($# >= 2)) || die '--enabled-values requires a path'
      CLI_SECTORS_ENABLED_VALUES_FILE="$2"
      shift 2
      ;;
    --report)
      (($# >= 2)) || die '--report requires a path'
      CLI_CAPABILITY_REPORT_FILE="$2"
      shift 2
      ;;
    --apply)
      PROMOTION_APPLY=true
      shift
      ;;
    --component)
      (($# >= 2)) || die '--component requires one of all, database, service'
      COMPONENT_NAME="$2"
      COMPONENT_SELECTED=true
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

render_release_packet() {
  local chart_dir="$1"
  local baseline_values="$2"
  local secondary_values="$3"
  local kube_version="$4"
  local release_name="$5"
  local namespace="$6"
  shift 6
  local values_args=()

  if [[ -n "$baseline_values" ]]; then
    values_args+=(--values "$baseline_values")
  fi
  if [[ -n "$secondary_values" ]]; then
    values_args+=(--values "$secondary_values")
  fi

  helm lint --strict "$chart_dir" --kube-version "$kube_version" \
    "${values_args[@]}" "$@" >&2
  helm template "$release_name" "$chart_dir" --namespace "$namespace" \
    --kube-version "$kube_version" \
    "${values_args[@]}" "$@"
}

assert_component_value() {
  local requested="$1"
  local valid
  for valid in "${VALID_COMPONENTS[@]}"; do
    if [[ "$requested" == "$valid" ]]; then
      return 0
    fi
  done
  local joined
  joined="$(IFS='|'; printf '%s' "${VALID_COMPONENTS[*]}")"
  die "--component must be one of: ${joined}"
}

load_component_baseline() {
  local baseline_path="$1"
  if [[ ! -f "$baseline_path" ]]; then
    die "component baseline fixture not found: $baseline_path (set COMPONENT_BASELINE_FILE or copy tests/fixtures/truenas_component_baseline.yaml)"
  fi
  python3 - "$baseline_path" <<'PYEOF' || die "component baseline fixture is not valid YAML: $baseline_path"
import sys, yaml
with open(sys.argv[1]) as stream:
    data = yaml.safe_load(stream)
if not isinstance(data, dict):
    raise SystemExit("component baseline fixture must be a YAML mapping at the top level")
if data.get("schema") != "truenas-k3s-component-baseline/v1":
    raise SystemExit("component baseline fixture has an unsupported schema")
release = data.get("release") or {}
persistence = data.get("persistence") or {}
image = data.get("image") or {}
topology = data.get("topology") or {}
required_release = ("name", "namespace", "chart")
for key in required_release:
    if not release.get(key):
        raise SystemExit("component baseline fixture is missing release." + key)
required_persistence = ("enabled", "claimName", "storageClass", "accessModes", "size", "mountPath", "snapshotPath", "keep")
for key in required_persistence:
    if not persistence.get(key):
        raise SystemExit("component baseline fixture is missing persistence." + key)
if persistence.get("enabled") is not True or persistence.get("keep") is not True:
    raise SystemExit("component baseline fixture requires persistence.enabled=true and keep=true")
if persistence.get("accessModes") != ["ReadWriteOnce"]:
    raise SystemExit("component baseline fixture requires exactly one ReadWriteOnce access mode")
required_image = ("repository", "tagPattern")
for key in required_image:
    if not image.get(key):
        raise SystemExit("component baseline fixture is missing image." + key)
if image.get("pullPolicy") != "IfNotPresent" or image.get("digestPrefix") != "sha256:":
    raise SystemExit("component baseline fixture has an unsupported image identity policy")
security = topology.get("securityContext") or {}
required_topology = ("replicaCount", "strategy", "automountServiceAccountToken", "securityContext", "capabilitiesDrop")
for key in required_topology:
    if key not in topology:
        raise SystemExit("component baseline fixture is missing topology." + key)
if topology.get("replicaCount") != 1 or topology.get("strategy") != "Recreate":
    raise SystemExit("component baseline fixture requires one Recreate replica")
if topology.get("automountServiceAccountToken") is not False:
    raise SystemExit("component baseline fixture requires automountServiceAccountToken=false")
if security.get("runAsNonRoot") is not True or security.get("readOnlyRootFilesystem") is not True or security.get("allowPrivilegeEscalation") is not False:
    raise SystemExit("component baseline fixture has an unsafe security context")
if topology.get("capabilitiesDrop") != ["ALL"]:
    raise SystemExit("component baseline fixture requires capabilitiesDrop=[ALL]")
print(release.get("name", ""))
print(release.get("namespace", ""))
print(persistence.get("claimName", ""))
print(persistence.get("storageClass", ""))
print(str(persistence.get("size", "")))
print(",".join(persistence.get("accessModes") or []))
print(persistence.get("mountPath", ""))
print(persistence.get("snapshotPath", ""))
print(str(topology.get("replicaCount", 1)))
print("1" if security.get("readOnlyRootFilesystem") else "0")
print(topology.get("strategy", ""))
print("1" if topology.get("automountServiceAccountToken") else "0")
print(image.get("repository", ""))
print(image.get("tagPattern", ""))
print(image.get("pullPolicy", ""))
PYEOF
}

component_render_overrides() {
  local component="$1"
  case "$component" in
    all)
      return 0
      ;;
    database)
      printf '%s\n' '--set' 'component=database'
      ;;
    service)
      printf '%s\n' '--set' 'component=service'
      ;;
    *)
      die "unsupported --component: $component"
      ;;
  esac
}

sha256_text() {
  printf '%s\n' "$1" | sha256sum | awk '{print $1}'
}

validate_identifier() {
  local name="$1"
  local value="$2"
  [[ ${#value} -le 63 && "$value" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] || die "$name must be a Kubernetes DNS label"
}

normalize_kubernetes_version() {
  local value="$1"
  local normalized
  if ! normalized="$(python3 "$PACKET_VALIDATOR" normalize-version --version "$value")"; then
    die "invalid Kubernetes version: $value"
  fi
  printf '%s\n' "$normalized"
}

parse_server_version() {
  python3 "$PACKET_VALIDATOR" parse-version
}

require_render_has_no_cronjob() {
  local source="$1"
  local rendered="$2"
  RENDERED_PACKET_PAYLOAD="$rendered" python3 - "$source" <<'PYEOF'
import os
import sys
import yaml

try:
    documents = [
        item
        for item in yaml.safe_load_all(os.environ["RENDERED_PACKET_PAYLOAD"])
        if item is not None
    ]
except yaml.YAMLError as exc:
    raise SystemExit(f"{sys.argv[1]} is not valid YAML: {exc}")
if not all(isinstance(item, dict) for item in documents):
    raise SystemExit(f"{sys.argv[1]} must contain only YAML mappings")
cronjobs = [
    (item.get("metadata") or {}).get("name", "<unnamed>")
    for item in documents
    if item.get("kind") == "CronJob"
]
if cronjobs:
    raise SystemExit(
        f"{sys.argv[1]} must not contain an application CronJob: {', '.join(cronjobs)}"
    )
PYEOF
}

helm_release_presence() {
  local releases
  releases="$(helm list --all --namespace "$NAMESPACE" --filter "^${RELEASE_NAME}$" --output json)" || return 1
  printf '%s\n' "$releases" | python3 -c '
import json, sys
payload = json.load(sys.stdin)
if not isinstance(payload, list):
    raise SystemExit("Helm release list must be a JSON array")
matches = [item for item in payload if isinstance(item, dict) and item.get("name") == sys.argv[1]]
if len(matches) > 1:
    raise SystemExit("Helm returned duplicate release records")
print("present" if matches else "absent")
' "$RELEASE_NAME"
}

capture_exact_cronjob() {
  local cronjob_name="$1"
  local payload error_file
  [[ -n "$cronjob_name" ]] || return 1
  error_file="$(mktemp)"
  if ! payload="$(kubectl get cronjob "$cronjob_name" --namespace "$NAMESPACE" \
    --ignore-not-found -o yaml 2>"$error_file")"; then
    rm -f "$error_file"
    return 1
  fi
  rm -f "$error_file"
  printf '%s\n' "$payload" | python3 -c '
import sys, yaml
items = [item for item in yaml.safe_load_all(sys.stdin) if item is not None]
if len(items) > 1 or not all(isinstance(item, dict) for item in items):
    raise SystemExit("exact live CronJob response must contain at most one object")
if items:
    item = items[0]
    metadata = item.get("metadata")
    if item.get("kind") != "CronJob" or not isinstance(metadata, dict):
        raise SystemExit("exact live CronJob response must be a CronJob")
    if metadata.get("name") != sys.argv[1]:
        raise SystemExit(f"live CronJob name must equal {sys.argv[1]}")
    if metadata.get("namespace") != sys.argv[2]:
        raise SystemExit(f"live CronJob namespace must equal {sys.argv[2]}")
    yaml.safe_dump_all(items, sys.stdout, sort_keys=False)
' "$cronjob_name" "$NAMESPACE"
}

former_release_cronjob_name() {
  local chart_dir="$1"
  local values_file="$2"
  python3 - "$chart_dir" "$values_file" "$RELEASE_NAME" <<'PYEOF'
from pathlib import Path
import sys
import yaml

chart_dir = Path(sys.argv[1])
values_path = Path(sys.argv[2]) if sys.argv[2] else None
release_name = sys.argv[3]

def load_mapping(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        value = yaml.safe_load(stream) or {}
    if not isinstance(value, dict):
        raise SystemExit(f"values must be a mapping: {path}")
    return value

def merge(target: dict, source: dict) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge(target[key], value)
        else:
            target[key] = value

chart = load_mapping(chart_dir / "Chart.yaml")
values = load_mapping(chart_dir / "values.yaml")
if values_path is not None:
    merge(values, load_mapping(values_path))
chart_name = chart.get("name")
if not isinstance(chart_name, str) or not chart_name:
    raise SystemExit("chart name is missing")
fullname_override = values.get("fullnameOverride")
name_override = values.get("nameOverride")
if fullname_override:
    fullname = str(fullname_override)[:63].rstrip("-")
else:
    name = str(name_override or chart_name)
    fullname = release_name if name in release_name else f"{release_name}-{name}"
    fullname = fullname[:63].rstrip("-")
former_name = f"{fullname}-data-collection"[:52].rstrip("-")
if not former_name:
    raise SystemExit("former release-derived CronJob name is empty")
print(former_name)
PYEOF
}

require_cronjob_identities_absent_in_manifest() {
  local source="$1"
  local manifests="$2"
  shift 2
  MANIFEST_PAYLOAD="$manifests" python3 - "$source" "$@" <<'PYEOF'
import os
import sys
import yaml

source, *names = sys.argv[1:]
try:
    documents = [
        item
        for item in yaml.safe_load_all(os.environ["MANIFEST_PAYLOAD"])
        if item is not None
    ]
except yaml.YAMLError as exc:
    raise SystemExit(f"could not parse {source}: {exc}")
if not all(isinstance(item, dict) for item in documents):
    raise SystemExit(f"{source} must contain only YAML mappings")
matches = []
for item in documents:
    if item.get("kind") != "CronJob":
        continue
    name = (item.get("metadata") or {}).get("name")
    if name in names:
        matches.append(str(name))
if matches:
    raise SystemExit(
        f"{source} contains retired application CronJob identity: {', '.join(sorted(set(matches)))}"
    )
PYEOF
}

legacy_cronjob_identities() {
  printf '%s\n' "$GENERIC_CRONJOB_NAME" market-data-collection | awk 'NF && !seen[$0]++'
}

require_live_legacy_cronjobs_absent() {
  local phase="$1"
  local cronjob_name live_cronjob
  while IFS= read -r cronjob_name; do
    if ! live_cronjob="$(capture_exact_cronjob "$cronjob_name")"; then
      warn "$phase: could not prove exact CronJob $cronjob_name absent (API/auth/transport uncertainty)"
      return 1
    fi
    if [[ -n "$live_cronjob" ]]; then
      warn "$phase: retired CronJob $cronjob_name still exists; active, suspended, and label-drifted forms are all rejected"
      return 1
    fi
  done < <(legacy_cronjob_identities)
  log "$phase: both former CronJob identities are absent"
}

verify_generic_deploy_precondition() {
  local presence stored_manifest
  if ! presence="$(helm_release_presence)"; then
    die 'could not determine whether the target Helm release already exists'
  fi
  if [[ "$presence" == present ]]; then
    if ! stored_manifest="$(helm get manifest "$RELEASE_NAME" --namespace "$NAMESPACE")"; then
      die 'could not read the existing Helm release manifest'
    fi
    mapfile -t LEGACY_CRONJOB_NAMES < <(legacy_cronjob_identities)
    require_cronjob_identities_absent_in_manifest \
      'stored Helm release manifest' "$stored_manifest" "${LEGACY_CRONJOB_NAMES[@]}" \
      || die 'ordinary deployment requires both retired CronJob identities absent from the stored Helm manifest'
  elif [[ "$presence" != absent ]]; then
    die "unexpected Helm release presence result: $presence"
  fi

  require_live_legacy_cronjobs_absent 'ordinary deployment precondition' \
    || die 'ordinary deployment could not prove both retired CronJob identities absent from live state'
  log 'generic deployment precondition: stored and live retired CronJob identities are absent'
}

verify_database_component() {
  local packet="$1"
  printf '%s\n' "$packet" | python3 -c '
import sys, yaml
items=[i for i in yaml.safe_load_all(sys.stdin) if i is not None]
statefulsets=[i for i in items if isinstance(i, dict) and i.get("kind") == "StatefulSet"]
services=[i for i in items if isinstance(i, dict) and i.get("kind") == "Service"]
pvcs=[i for i in items if isinstance(i, dict) and i.get("kind") == "PersistentVolumeClaim"]
jobs=[i for i in items if isinstance(i, dict) and i.get("kind") == "Job"]
postgres=[i for i in statefulsets if (i.get("metadata") or {}).get("name", "").endswith("-postgresql")]
if len(postgres) != 1:
    raise SystemExit("database component must render exactly one PostgreSQL StatefulSet")
if len(services) != 1 or not (services[0].get("metadata") or {}).get("name", "").endswith("-postgresql"):
    raise SystemExit("database component must render exactly one PostgreSQL ClusterIP Service")
if len(pvcs) != 1 or not (pvcs[0].get("metadata") or {}).get("name", "").endswith("-postgresql-data"):
    raise SystemExit("database component must render exactly one independent PostgreSQL PVC")
if len(jobs) != 1:
    raise SystemExit("database component must render exactly one Job and legacy SQLite migration must be disabled")
schema_job=jobs[0]
metadata=schema_job.get("metadata") or {}
postgres_name=(postgres[0].get("metadata") or {}).get("name", "")
expected_name=postgres_name.removesuffix("-postgresql") + "-schema-migration"
if metadata.get("name") != expected_name:
    raise SystemExit(f"database component Job must be exactly {expected_name}")
annotations=metadata.get("annotations") or {}
if set((annotations.get("helm.sh/hook") or "").split(",")) != {"post-install", "post-upgrade"}:
    raise SystemExit("schema migration Job must be the post-install,post-upgrade Helm hook")
if set((annotations.get("helm.sh/hook-delete-policy") or "").split(",")) != {"before-hook-creation", "hook-succeeded"}:
    raise SystemExit("schema migration Job must retain failures and delete only before creation or after success")
schema_pod=(((schema_job.get("spec") or {}).get("template") or {}).get("spec") or {})
schema_containers=schema_pod.get("containers") or []
if len(schema_containers) != 1:
    raise SystemExit("schema migration Job must render exactly one container")
schema_container=schema_containers[0]
if schema_container.get("command") != ["alembic", "upgrade", "head"]:
    raise SystemExit("PostgreSQL schema migration Job must run only alembic upgrade head")
if schema_container.get("args") not in (None, []):
    raise SystemExit("PostgreSQL schema migration Job must not add command arguments")
env_names=[env.get("name") for env in (schema_container.get("env") or [])]
if env_names != ["MARKET_ENVIRONMENT_DATABASE_URL"]:
    raise SystemExit("PostgreSQL schema migration Job may receive only the database URL environment variable")
if schema_container.get("volumeMounts") or schema_pod.get("volumes"):
    raise SystemExit("PostgreSQL schema migration Job must not mount legacy SQLite or provider data")
if (postgres[0].get("spec") or {}).get("replicas") != 1:
    raise SystemExit("PostgreSQL StatefulSet must remain single replica")
if (services[0].get("spec") or {}).get("type") != "ClusterIP":
    raise SystemExit("PostgreSQL Service must remain ClusterIP")
if (pvcs[0].get("spec") or {}).get("accessModes") != ["ReadWriteOnce"]:
    raise SystemExit("PostgreSQL PVC must be ReadWriteOnce")
pod=((postgres[0].get("spec") or {}).get("template") or {}).get("spec") or {}
mounts=[m for c in pod.get("containers", []) for m in c.get("volumeMounts", [])]
if not any(m.get("name") == "postgresql-data" for m in mounts):
    raise SystemExit("PostgreSQL StatefulSet must mount its database PVC")
print("postgresql_component_contract_ok")
' || return 1
  log "component=database database verified: single PostgreSQL StatefulSet + ClusterIP Service + retained RWO PVC"
}

verify_live_pvc_contract() {
  local payload
  [[ -n "$COMPONENT_BASELINE_CLAIM" ]] || return 1
  if ! payload="$(kubectl get pvc "$COMPONENT_BASELINE_CLAIM" --namespace "$NAMESPACE" -o json)"; then
    warn "component PVC prerequisite missing: $COMPONENT_BASELINE_CLAIM/$NAMESPACE"
    return 1
  fi
  PVC_PAYLOAD="$payload" python3 - \
    "$COMPONENT_BASELINE_CLAIM" "$NAMESPACE" "$COMPONENT_BASELINE_STORAGE_CLASS" \
    "$COMPONENT_BASELINE_ACCESS_MODES" "$COMPONENT_BASELINE_STORAGE" <<'PYEOF'
import json, sys
payload = json.loads(__import__("os").environ["PVC_PAYLOAD"])
claim, namespace, storage_class, access_modes, storage = sys.argv[1:]
metadata = payload.get("metadata") or {}
spec = payload.get("spec") or {}
status = payload.get("status") or {}
if metadata.get("name") != claim or metadata.get("namespace") != namespace:
    raise SystemExit("PVC identity does not match the reviewed claim name/namespace")
if not metadata.get("uid") or not spec.get("volumeName"):
    raise SystemExit("PVC must expose a UID and bound volumeName")
if status.get("phase") != "Bound":
    raise SystemExit("PVC must be Bound before a component write")
if spec.get("storageClassName") != storage_class:
    raise SystemExit("PVC storageClassName does not match the reviewed baseline")
if spec.get("accessModes") != access_modes.split(","):
    raise SystemExit("PVC accessModes do not match the reviewed baseline")
if (spec.get("resources") or {}).get("requests", {}).get("storage") != storage:
    raise SystemExit("PVC requested storage does not match the reviewed baseline")
print("pvc_live_identity_ok")
PYEOF
}

verify_live_database_contract() {
  local database_base="$RELEASE_NAME" pvc_name statefulset_name pvc_payload statefulset_payload
  # The chart fullname helper appends "-a-stock" only when the release name
  # does not already contain the chart name.
  if [[ "$RELEASE_NAME" != *a-stock* ]]; then
    database_base="${RELEASE_NAME}-a-stock"
  fi
  pvc_name="${database_base}-postgresql-data"
  statefulset_name="${database_base}-postgresql"
  if ! pvc_payload="$(kubectl get pvc "$pvc_name" --namespace "$NAMESPACE" -o json)"; then
    warn "PostgreSQL PVC prerequisite missing: $pvc_name/$NAMESPACE"
    return 1
  fi
  if ! statefulset_payload="$(kubectl get statefulset "$statefulset_name" --namespace "$NAMESPACE" -o json)"; then
    warn "PostgreSQL StatefulSet prerequisite missing: $statefulset_name/$NAMESPACE"
    return 1
  fi
  PVC_PAYLOAD="$pvc_payload" STATEFULSET_PAYLOAD="$statefulset_payload" python3 - <<'PYEOF'
import json, os
pvc = json.loads(os.environ["PVC_PAYLOAD"])
sts = json.loads(os.environ["STATEFULSET_PAYLOAD"])
pvc_spec = pvc.get("spec") or {}
pvc_status = pvc.get("status") or {}
if pvc_status.get("phase") != "Bound":
    raise SystemExit("PostgreSQL PVC must be Bound before application rollout")
if pvc_spec.get("accessModes") != ["ReadWriteOnce"]:
    raise SystemExit("PostgreSQL PVC must be ReadWriteOnce")
sts_spec = sts.get("spec") or {}
sts_status = sts.get("status") or {}
if sts_spec.get("replicas") != 1 or sts_status.get("readyReplicas") != 1:
    raise SystemExit("PostgreSQL StatefulSet must report one ready replica")
PYEOF
}

verify_rendered_component_contract() {
  local packet="$1"
  local expected_image_repo="${2:-$IMAGE_REPOSITORY}"
  local expected_image_tag="${3:-$IMAGE_TAG}"
  PACKET_PAYLOAD="$packet" python3 - \
    "$COMPONENT_BASELINE_CLAIM" "$COMPONENT_BASELINE_STORAGE_CLASS" \
    "$COMPONENT_BASELINE_STORAGE" "$COMPONENT_BASELINE_ACCESS_MODES" \
    "$COMPONENT_BASELINE_MOUNT_PATH" "$COMPONENT_BASELINE_SNAPSHOT_PATH" \
    "$COMPONENT_BASELINE_TOPOLOGY_REPLICAS" "$COMPONENT_BASELINE_TOPOLOGY_STRATEGY" \
    "$expected_image_repo" "$expected_image_tag" <<'PYEOF'
import sys, yaml
import os
items = [item for item in yaml.safe_load_all(os.environ["PACKET_PAYLOAD"]) if item is not None]
(claim, storage_class, storage, access_modes, mount_path, snapshot_path,
 replicas, strategy, expected_repo, expected_tag) = sys.argv[1:]
replicas = int(replicas)
deployments = [i for i in items if i.get("kind") == "Deployment"]
cronjobs = [i for i in items if i.get("kind") == "CronJob"]
if cronjobs:
    raise SystemExit("application release must not render a CronJob")
pvcs = [i for i in items if i.get("kind") == "PersistentVolumeClaim"]
postgres = [i for i in items if i.get("kind") == "StatefulSet" and (i.get("metadata") or {}).get("name", "").endswith("-postgresql")]
postgres_mode = bool(postgres) or any(
    any(entry.get("name") == "MARKET_ENVIRONMENT_DATABASE_URL" for entry in (container.get("env") or []))
    for workload in items if workload.get("kind") == "Deployment"
    for container in (
        (((workload.get("spec") or {}).get("template") or {}).get("spec") or {}).get("containers", [])
        if workload.get("kind") == "Deployment"
        else []
    )
)
for deployment in deployments:
    spec = deployment.get("spec") or {}
    if spec.get("replicas") != replicas or (spec.get("strategy") or {}).get("type") != strategy:
        raise SystemExit("Deployment topology does not match the reviewed baseline")
    pod = (spec.get("template") or {}).get("spec") or {}
    if pod.get("automountServiceAccountToken") is not False:
        raise SystemExit("Deployment must disable service account token automount")
    containers = pod.get("containers") or []
    dashboard = next((c for c in containers if c.get("name") == "dashboard"), None)
    if dashboard is None or dashboard.get("image") != f"{expected_repo}:{expected_tag}":
        raise SystemExit("Dashboard image does not match the component image")
    security = dashboard.get("securityContext") or {}
    if security.get("readOnlyRootFilesystem") is not True or security.get("allowPrivilegeEscalation") is not False:
        raise SystemExit("Dashboard security context does not match the reviewed baseline")
    mounts = dashboard.get("volumeMounts") or []
    data_mount = next((m for m in mounts if m.get("name") == "data"), None)
    if postgres_mode:
        if data_mount is not None:
            raise SystemExit("PostgreSQL Dashboard must not mount the legacy SQLite data volume")
        if not any(entry.get("name") == "MARKET_ENVIRONMENT_DATABASE_URL" and entry.get("valueFrom") for entry in dashboard.get("env", [])):
            raise SystemExit("PostgreSQL Dashboard must reference the database Secret")
    elif data_mount is None or data_mount.get("mountPath") != mount_path:
        raise SystemExit("Dashboard data mount path does not match the reviewed baseline")
    env = {entry.get("name"): entry.get("value") for entry in dashboard.get("env", [])}
    if not postgres_mode and env.get("MARKET_ENVIRONMENT_SNAPSHOT_PATH") != snapshot_path:
        raise SystemExit("Dashboard snapshot path does not match the reviewed baseline")
if postgres_mode:
    for pvc in pvcs:
        metadata = pvc.get("metadata") or {}
        spec = pvc.get("spec") or {}
        if not metadata.get("name", "").endswith("-postgresql-data"):
            raise SystemExit("PostgreSQL mode must not render the legacy application PVC")
        if spec.get("accessModes") != ["ReadWriteOnce"]:
            raise SystemExit("PostgreSQL PVC must be ReadWriteOnce")
else:
    for pvc in pvcs:
        metadata = pvc.get("metadata") or {}
        spec = pvc.get("spec") or {}
        if metadata.get("name") != claim or spec.get("storageClassName") != storage_class:
            raise SystemExit("Rendered PVC identity does not match the reviewed baseline")
        if spec.get("accessModes") != access_modes.split(","):
            raise SystemExit("Rendered PVC accessModes do not match the reviewed baseline")
        if (spec.get("resources") or {}).get("requests", {}).get("storage") != storage:
            raise SystemExit("Rendered PVC capacity does not match the reviewed baseline")
print("rendered_component_contract_ok")
PYEOF
}

verify_component_prerequisites() {
  local component="$1"
  case "$component" in
    database)
      return 0
      ;;
    service)
      verify_live_database_contract || return 1
      ;;
    *)
      die "unsupported component prerequisite: $component"
      ;;
  esac
}

verify_service_component() {
  local packet="$1"
  if ! printf '%s\n' "$packet" | python3 -c '
import sys, yaml
items = [i for i in yaml.safe_load_all(sys.stdin) if i is not None]
kinds = {i.get("kind") for i in items}
assert "Deployment" in kinds, "service component missing Deployment; kinds=" + str(sorted(kinds))
assert "Service" in kinds, "service component missing Service; kinds=" + str(sorted(kinds))
assert "PersistentVolumeClaim" not in kinds, "service component must not render PVC; kinds=" + str(sorted(kinds))
assert "CronJob" not in kinds, "service component must not render CronJob; kinds=" + str(sorted(kinds))
'; then
    return 1
  fi
  log "component=service verified: Deployment + Service rendered without PVC or CronJob"
  return 0
}

verify_frozen_runtime_image() {
  local image_repo="$1"
  local image_tag="$2"
  local digest="$3"
  local image_ref="$image_repo:$image_tag"
  local deployments_file="$TMP_DIR/runtime-deployments.json"
  local replicasets_file="$TMP_DIR/runtime-replicasets.json"
  local pods_file="$TMP_DIR/runtime-pods.json"
  kubectl get deployment --namespace "$NAMESPACE" -l "app.kubernetes.io/instance=$RELEASE_NAME" -o json > "$deployments_file" || return 1
  kubectl get replicasets --namespace "$NAMESPACE" -l "app.kubernetes.io/instance=$RELEASE_NAME" -o json > "$replicasets_file" || return 1
  kubectl get pods --namespace "$NAMESPACE" -l "app.kubernetes.io/instance=$RELEASE_NAME" -o json > "$pods_file" || return 1
  python3 "$PACKET_VALIDATOR" verify-runtime-image \
    --release-name "$RELEASE_NAME" --namespace "$NAMESPACE" \
    --image "$image_ref" --digest "$digest" \
    --deployments "$deployments_file" --replicasets "$replicasets_file" --pods "$pods_file" || return 1
  # TrueNAS k3s 1.26 bundles an older ctr without `images info`. Build the
  # narrow JSON contract from the exact row in the stable `images ls` table.
  remote "sudo -n k3s ctr --namespace k8s.io images ls | awk -v image='$image_ref' '\$1 == image {printf \"{\\\"Name\\\":\\\"%s\\\",\\\"Target\\\":{\\\"digest\\\":\\\"%s\\\"}}\\n\", \$1, \$3; found=1} END {if (!found) exit 1}'" \
    | python3 "$PACKET_VALIDATOR" verify-containerd-image --image "$image_ref" --digest "$digest"
}

capture_containerd_image_digest() {
  local image_ref="$1"
  local digest
  digest="$(remote "sudo -n k3s ctr --namespace k8s.io images ls | awk -v image='$image_ref' '\$1 == image {print \$3; matches += 1} END {if (matches != 1) exit 1}'")" \
    || return 1
  [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
  printf '%s\n' "$digest"
}

verify_exact_containerd_image_digest() {
  local image_ref="$1"
  local expected_digest="$2"
  local actual_digest
  actual_digest="$(capture_containerd_image_digest "$image_ref")" || return 1
  [[ "$actual_digest" == "$expected_digest" ]]
}

require_all_application_cronjobs_absent() {
  local phase="$1"
  require_live_legacy_cronjobs_absent "$phase"
}

require_namespace_jobs_absent() {
  local phase="$1"
  local payload
  payload="$(kubectl get jobs --namespace "$NAMESPACE" -o json)" || return 1
  JOBS_PAYLOAD="$payload" python3 - "$phase" <<'PYEOF'
import json, os, sys
payload = json.loads(os.environ["JOBS_PAYLOAD"])
if not isinstance(payload, dict):
    raise SystemExit(f"{sys.argv[1]} Job response must be an object")
items = payload.get("items")
if not isinstance(items, list):
    raise SystemExit(f"{sys.argv[1]} Job response must contain an items list")
if items:
    names=[]
    for item in items:
        if not isinstance(item, dict):
            raise SystemExit(f"{sys.argv[1]} Job items must be objects")
        names.append(str((item.get("metadata") or {}).get("name") or "<unnamed>"))
    raise SystemExit(f"{sys.argv[1]} requires namespace Jobs absent; found: {', '.join(names)}")
PYEOF
}

require_terminal_namespace_jobs() {
  local phase="$1"
  local payload
  payload="$(kubectl get jobs --namespace "$NAMESPACE" -o json)" || return 1
  JOBS_PAYLOAD="$payload" python3 - "$phase" <<'PYEOF'
import json, os, sys
payload = json.loads(os.environ["JOBS_PAYLOAD"])
items = payload.get("items")
if not isinstance(items, list):
    raise SystemExit(f"{sys.argv[1]} Job response must contain an items list")
for item in items:
    if not isinstance(item, dict):
        raise SystemExit(f"{sys.argv[1]} Job items must be objects")
    status = item.get("status", {})
    if not isinstance(status, dict):
        raise SystemExit(f"{sys.argv[1]} Job status must be an object")
    counts = {}
    for field in ("active", "failed", "succeeded"):
        value = status.get(field, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SystemExit(
                f"{sys.argv[1]} Job status.{field} must be a non-negative integer"
            )
        counts[field] = value
    active = counts["active"]
    if active > 0:
        name = (item.get("metadata") or {}).get("name", "<unknown>")
        raise SystemExit(f"{sys.argv[1]} found active namespace Job {name}")
    conditions = status.get("conditions")
    if not isinstance(conditions, list) or not conditions:
        raise SystemExit(f"{sys.argv[1]} Job must have terminal conditions")
    terminal = set()
    for condition in conditions:
        if not isinstance(condition, dict):
            raise SystemExit(f"{sys.argv[1]} Job conditions must be objects")
        condition_type = condition.get("type")
        condition_status = condition.get("status")
        if not isinstance(condition_type, str) or not condition_type:
            raise SystemExit(f"{sys.argv[1]} Job condition.type must be non-empty")
        if not isinstance(condition_status, str) or condition_status not in {
            "True",
            "False",
            "Unknown",
        }:
            raise SystemExit(f"{sys.argv[1]} Job condition.status is invalid")
        if condition_type in {"Complete", "Failed"} and condition_status == "True":
            terminal.add(condition_type)
    if len(terminal) != 1:
        raise SystemExit(
            f"{sys.argv[1]} Job must have exactly one Complete=True or Failed=True condition"
        )
    if counts["failed"] > 0 and "Failed" not in terminal:
        raise SystemExit(f"{sys.argv[1]} failed Job count requires Failed=True")
    if counts["succeeded"] > 0 and "Complete" not in terminal:
        raise SystemExit(f"{sys.argv[1]} succeeded Job count requires Complete=True")
PYEOF
}

capture_terminal_namespace_job_evidence() {
  local phase="$1"
  local payload
  payload="$(kubectl get jobs --namespace "$NAMESPACE" -o json)" || return 1
  JOBS_PAYLOAD="$payload" python3 - "$phase" "$NAMESPACE" <<'PYEOF'
import json, os, sys

phase, namespace = sys.argv[1:]
payload = json.loads(os.environ["JOBS_PAYLOAD"])
items = payload.get("items")
if not isinstance(items, list):
    raise SystemExit(f"{phase} Job response must contain an items list")

evidence = []
names = set()
uids = set()
for item in items:
    if not isinstance(item, dict):
        raise SystemExit(f"{phase} Job items must be objects")
    metadata = item.get("metadata")
    status = item.get("status", {})
    if not isinstance(metadata, dict) or not isinstance(status, dict):
        raise SystemExit(f"{phase} Job metadata/status must be objects")
    name = metadata.get("name")
    uid = metadata.get("uid")
    item_namespace = metadata.get("namespace")
    if not isinstance(name, str) or not name:
        raise SystemExit(f"{phase} Job name must be non-empty")
    if not isinstance(uid, str) or not uid:
        raise SystemExit(f"{phase} Job {name} UID must be non-empty")
    if item_namespace is not None and item_namespace != namespace:
        raise SystemExit(f"{phase} Job {name} namespace mismatch")
    if metadata.get("deletionTimestamp") is not None:
        raise SystemExit(f"{phase} Job {name} is terminating")
    if name in names or uid in uids:
        raise SystemExit(f"{phase} Job name/UID must be unique")
    names.add(name)
    uids.add(uid)

    counts = {}
    for field in ("active", "failed", "succeeded"):
        value = status.get(field, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SystemExit(
                f"{phase} Job {name} status.{field} must be a non-negative integer"
            )
        counts[field] = value
    if counts["active"] != 0:
        raise SystemExit(f"{phase} found active namespace Job {name}")

    conditions = status.get("conditions")
    if not isinstance(conditions, list) or not conditions:
        raise SystemExit(f"{phase} Job {name} must have terminal conditions")
    terminal_conditions = []
    for condition in conditions:
        if not isinstance(condition, dict):
            raise SystemExit(f"{phase} Job {name} conditions must be objects")
        condition_type = condition.get("type")
        condition_status = condition.get("status")
        if not isinstance(condition_type, str) or not condition_type:
            raise SystemExit(f"{phase} Job {name} condition.type must be non-empty")
        if not isinstance(condition_status, str) or condition_status not in {
            "True",
            "False",
            "Unknown",
        }:
            raise SystemExit(f"{phase} Job {name} condition.status is invalid")
        if condition_type in {"Complete", "Failed"} and condition_status == "True":
            terminal_conditions.append(condition)
    if len(terminal_conditions) != 1:
        raise SystemExit(
            f"{phase} Job {name} must have exactly one Complete=True or Failed=True condition"
        )
    terminal_type = terminal_conditions[0]["type"]
    if counts["failed"] > 0 and terminal_type != "Failed":
        raise SystemExit(f"{phase} Job {name} failed count requires Failed=True")
    if counts["succeeded"] > 0 and terminal_type != "Complete":
        raise SystemExit(f"{phase} Job {name} succeeded count requires Complete=True")
    evidence.append(
        {
            "name": name,
            "uid": uid,
            "active": counts["active"],
            "failed": counts["failed"],
            "succeeded": counts["succeeded"],
            "terminalCondition": terminal_conditions[0],
        }
    )

print(
    json.dumps(
        sorted(evidence, key=lambda row: row["name"]),
        sort_keys=True,
        separators=(",", ":"),
    )
)
PYEOF
}

require_terminal_namespace_job_evidence_unchanged() {
  local phase="$1"
  local expected="$2"
  local actual
  actual="$(capture_terminal_namespace_job_evidence "$phase")" || return 1
  if [[ "$actual" != "$expected" ]]; then
    warn "$phase: namespace terminal Job evidence changed"
    return 1
  fi
  log "$phase: namespace terminal Job evidence is unchanged"
}

capture_preserved_resource_identities() {
  local packet="$1"
  local kind name identity packet_file
  local resources=()
  packet_file="$TMP_DIR/preserved-identities-packet.yaml"
  printf '%s\n' "$packet" > "$packet_file"
  mapfile -t resources < <(python3 - "$COMPONENT_BASELINE_CLAIM" "$packet_file" <<'PYEOF'
import sys, yaml
documents = [item for item in yaml.safe_load_all(open(sys.argv[2])) if isinstance(item, dict)]
names = set()
for document in documents:
    if document.get("kind") == "PersistentVolumeClaim":
        name = (document.get("metadata") or {}).get("name")
        if name:
            names.add(("pvc", name))
    if document.get("kind") != "Deployment":
        continue
    containers = (((document.get("spec") or {}).get("template") or {}).get("spec") or {}).get("containers", [])
    for container in containers:
        for entry in container.get("env") or []:
            secret = ((entry.get("valueFrom") or {}).get("secretKeyRef") or {}).get("name")
            if secret:
                names.add(("secret", secret))
if sys.argv[1]:
    names.add(("pvc", sys.argv[1]))
for kind, name in sorted(names):
    print(f"{kind}\t{name}")
PYEOF
  )
  for resource in "${resources[@]}"; do
    IFS=$'\t' read -r kind name <<< "$resource"
    case "$kind" in
      secret)
        identity="$(kubectl get secret "$name" --namespace "$NAMESPACE" \
          -o jsonpath='{.metadata.uid}{"|"}{.metadata.resourceVersion}')" || return 1
        ;;
      pvc)
        identity="$(kubectl get pvc "$name" --namespace "$NAMESPACE" \
          -o jsonpath='{.metadata.uid}{"|"}{.metadata.resourceVersion}{"|"}{.spec.volumeName}{"|"}{.status.phase}{"|"}{.status.capacity.storage}')" || return 1
        ;;
      *)
        return 1
        ;;
    esac
    [[ -n "$identity" ]] || return 1
    printf '%s\t%s\t%s\n' "$kind" "$name" "$identity"
  done
}

select_runtime_sectors_pod() {
  local required_enabled="$1"
  local deployments_file="$TMP_DIR/sectors-runtime-deployments.json"
  local replicasets_file="$TMP_DIR/sectors-runtime-replicasets.json"
  local pods_file="$TMP_DIR/sectors-runtime-pods.json"
  local desired_file="$TMP_DIR/sectors-runtime-reviewed.yaml"
  if [[ "$required_enabled" == "1" ]]; then
    printf '%s\n' "$REVIEWED_ENABLED_RENDER" > "$desired_file"
  else
    printf '%s\n' "$REVIEWED_OFF_RENDER" > "$desired_file"
  fi
  kubectl get deployment --namespace "$NAMESPACE" -l "app.kubernetes.io/instance=$RELEASE_NAME" -o json > "$deployments_file" \
    || return 1
  kubectl get replicasets --namespace "$NAMESPACE" -l "app.kubernetes.io/instance=$RELEASE_NAME" -o json > "$replicasets_file" \
    || return 1
  kubectl get pods --namespace "$NAMESPACE" -l "app.kubernetes.io/instance=$RELEASE_NAME" -o json > "$pods_file" \
    || return 1
  python3 "$PACKET_VALIDATOR" select-disabled-promotion-pod \
    --release-name "$RELEASE_NAME" \
    --namespace "$NAMESPACE" \
    --image "$FROZEN_IMAGE_REPOSITORY:$FROZEN_IMAGE_TAG" \
    --digest "$FROZEN_IMAGE_DIGEST" \
    --deployments "$deployments_file" \
    --replicasets "$replicasets_file" \
    --desired "$desired_file" \
    --require-enabled "$required_enabled" < "$pods_file"
}

verify_manual_refresh_runtime() {
  local desired_packet="$1"
  local required_value="$2"
  local deployments_file="$TMP_DIR/manual-refresh-runtime-deployments.json"
  local replicasets_file="$TMP_DIR/manual-refresh-runtime-replicasets.json"
  local pods_file="$TMP_DIR/manual-refresh-runtime-pods.json"
  local desired_file="$TMP_DIR/manual-refresh-runtime-reviewed.yaml"
  printf '%s\n' "$desired_packet" > "$desired_file"
  kubectl get deployment --namespace "$NAMESPACE" -l "app.kubernetes.io/instance=$RELEASE_NAME" -o json > "$deployments_file" \
    || return 1
  kubectl get replicasets --namespace "$NAMESPACE" -l "app.kubernetes.io/instance=$RELEASE_NAME" -o json > "$replicasets_file" \
    || return 1
  kubectl get pods --namespace "$NAMESPACE" -l "app.kubernetes.io/instance=$RELEASE_NAME" -o json > "$pods_file" \
    || return 1
  python3 "$PACKET_VALIDATOR" verify-manual-refresh-runtime \
    --release-name "$RELEASE_NAME" \
    --namespace "$NAMESPACE" \
    --image "$FROZEN_IMAGE_REPOSITORY:$FROZEN_IMAGE_TAG" \
    --digest "$FROZEN_IMAGE_DIGEST" \
    --deployments "$deployments_file" \
    --replicasets "$replicasets_file" \
    --pods "$pods_file" \
    --desired "$desired_file" \
    --require-value "$required_value" >/dev/null
}

deploy_helm_upgrade_with_component() {
  local component="$1"
  local image_repo="$2"
  local image_tag="$3"
  local -a helm_hook_args=()
  case "$component" in
    database)
      log 'component Helm write: component=database hookMode=enabled expectedSchemaHook=reviewed-release-schema-migration execution=single'
      ;;
    service)
      helm_hook_args=(--no-hooks)
      log 'component Helm write: component=service hookMode=disabled reason=schema-hook-runs-only-in-database-phase'
      ;;
    *)
      warn "unsupported component Helm write: $component"
      return 1
      ;;
  esac
  if ! render_release_packet "$OPERATION_CHART_DIR" "$VALUES_FILE" "" "$TARGET_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" \
        --set "image.repository=$image_repo" \
        --set "image.tag=$image_tag" \
        --set "component=$component" >/dev/null; then
    warn "frozen $component release packet failed to render before helm write"
    return 1
  fi
  HELM_VALUES_ARGS=(--values "$VALUES_FILE")
  helm upgrade --install "$RELEASE_NAME" "$OPERATION_CHART_DIR" \
    --namespace "$NAMESPACE" \
    --create-namespace \
    "${HELM_VALUES_ARGS[@]}" \
    --set "image.repository=$image_repo" \
    --set "image.tag=$image_tag" \
    --set "component=$component" \
    "${helm_hook_args[@]}" \
    --atomic \
    --wait \
    --timeout "$HELM_TIMEOUT"
}

deploy_component_step() {
  local component="$1"
  local image_repo="$2"
  local image_tag="$3"
  log "component step: name=$component phase=start release=$RELEASE_NAME namespace=$NAMESPACE image=$image_repo:$image_tag"
  if [[ "$GENERIC_IMMUTABLE_IMAGE_REQUIRED" == true ]]; then
    verify_exact_containerd_image_digest "$image_repo:$image_tag" "$FROZEN_IMAGE_DIGEST" \
      || { log "component step: name=$component phase=failed reason=containerd_manifest_digest_drift retryTarget=--component $component"; return 1; }
  fi
  require_namespace_jobs_absent "component=$component Helm write precondition" \
    || { log "component step: name=$component phase=failed reason=namespace_job_precondition_violated retryTarget=--component $component"; return 1; }
  local helm_exit=0
  deploy_helm_upgrade_with_component "$component" "$image_repo" "$image_tag" || helm_exit=$?
  if (( helm_exit != 0 )); then
    log "component step: name=$component phase=failed reason=helm_upgrade_rejected exitCode=$helm_exit retryTarget=--component $component"
    return "$helm_exit"
  fi
  require_namespace_jobs_absent "component=$component successful Helm write" \
    || { log "component step: name=$component phase=failed reason=namespace_job_remains_after_success retryTarget=--component $component"; return 1; }
  if [[ "$component" == database ]]; then
    log 'component step: name=database phase=hook-complete execution=single namespaceJobs=absent'
  fi
  local post_render
  post_render="$(render_release_packet "$OPERATION_CHART_DIR" "$VALUES_FILE" "" "$TARGET_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" \
    --set "image.repository=$image_repo" --set "image.tag=$image_tag" --set "component=$component")" \
    || { log "component step: name=$component phase=failed reason=post_write_render_rejected retryTarget=--component $component"; return 1; }
  verify_rendered_component_contract "$post_render" "$image_repo" "$image_tag" \
    || { log "component step: name=$component phase=failed reason=${component}_baseline_contract_violated retryTarget=--component $component"; return 1; }
  case "$component" in
    database)
      verify_database_component "$post_render" || { log "component step: name=$component phase=failed reason=database_invariant_violated retryTarget=--component $component"; return 1; }
      if [[ "$COMPONENT_SELECTED" == true ]]; then
        verify_live_database_contract || { log "component step: name=$component phase=failed reason=postgresql_live_identity_violated retryTarget=--component $component"; return 1; }
      fi
      ;;
    service)
      verify_service_component "$post_render" || { log "component step: name=$component phase=failed reason=service_resource_invariant_violated retryTarget=--component $component"; return 1; }
      DEPLOYMENT_NAME="$(kubectl -n "$NAMESPACE" get deployment \
        -l "app.kubernetes.io/instance=$RELEASE_NAME" \
        -o jsonpath='{.items[0].metadata.name}')"
      step_exit=$?
      if (( step_exit != 0 )); then
        log "component step: name=$component phase=failed reason=no_deployment_found exitCode=$step_exit"
        return "$step_exit"
      fi
      [[ -n "$DEPLOYMENT_NAME" ]] || { log "component step: name=$component phase=failed reason=no_deployment_found"; return 1; }
      kubectl -n "$NAMESPACE" rollout status "deployment/$DEPLOYMENT_NAME" --timeout=180s \
        || { step_exit=$?; log "component step: name=$component phase=failed reason=rollout_timeout exitCode=$step_exit"; return "$step_exit"; }
      if [[ "$GENERIC_IMMUTABLE_IMAGE_REQUIRED" == true ]]; then
        verify_frozen_runtime_image "$image_repo" "$image_tag" "$FROZEN_IMAGE_DIGEST" \
          || { log "component step: name=$component phase=failed reason=frozen_image_runtime_unproven retryTarget=--component $component"; return 1; }
      fi
      log "component step: name=$component phase=completed rollout=ready"
      ;;
  esac
  return 0
}

assert_component_value "$COMPONENT_NAME"

if [[ -f "$ENV_FILE" ]]; then
  # The file is an operator-owned local configuration file.
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
else
  die "environment file not found: $ENV_FILE (copy deploy/truenas/deploy.env.example first)"
fi

load_component_baseline "$COMPONENT_BASELINE_FILE" || die 'component baseline fixture failed to load; cannot enforce release/namespace/pvc/image invariants'
mapfile -t COMPONENT_BASELINE_FIELDS < <(python3 - "$COMPONENT_BASELINE_FILE" <<'PYEOF'
import sys, yaml
with open(sys.argv[1]) as stream:
    data = yaml.safe_load(stream)
release = data.get("release") or {}
persistence = data.get("persistence") or {}
image = data.get("image") or {}
topology = data.get("topology") or {}
security = topology.get("securityContext") or {}
print(release.get("name", ""))
print(release.get("namespace", ""))
print(persistence.get("claimName", ""))
print(persistence.get("storageClass", ""))
print(str(persistence.get("size", "")))
print(",".join(persistence.get("accessModes") or []))
print(persistence.get("mountPath", ""))
print(persistence.get("snapshotPath", ""))
print(str(topology.get("replicaCount", 1)))
print("1" if security.get("readOnlyRootFilesystem") else "0")
print(topology.get("strategy", ""))
print("1" if topology.get("automountServiceAccountToken") else "0")
print(image.get("repository", ""))
print(image.get("tagPattern", ""))
print(image.get("pullPolicy", ""))
PYEOF
)
COMPONENT_BASELINE_RELEASE="${COMPONENT_BASELINE_FIELDS[0]}"
COMPONENT_BASELINE_NAMESPACE="${COMPONENT_BASELINE_FIELDS[1]}"
COMPONENT_BASELINE_CLAIM="${COMPONENT_BASELINE_FIELDS[2]}"
COMPONENT_BASELINE_STORAGE_CLASS="${COMPONENT_BASELINE_FIELDS[3]}"
COMPONENT_BASELINE_STORAGE="${COMPONENT_BASELINE_FIELDS[4]}"
COMPONENT_BASELINE_ACCESS_MODES="${COMPONENT_BASELINE_FIELDS[5]}"
COMPONENT_BASELINE_MOUNT_PATH="${COMPONENT_BASELINE_FIELDS[6]}"
COMPONENT_BASELINE_SNAPSHOT_PATH="${COMPONENT_BASELINE_FIELDS[7]}"
COMPONENT_BASELINE_TOPOLOGY_REPLICAS="${COMPONENT_BASELINE_FIELDS[8]}"
COMPONENT_BASELINE_TOPOLOGY_READONLY="${COMPONENT_BASELINE_FIELDS[9]}"
COMPONENT_BASELINE_TOPOLOGY_STRATEGY="${COMPONENT_BASELINE_FIELDS[10]}"
COMPONENT_BASELINE_AUTOMOUNT_TOKEN="${COMPONENT_BASELINE_FIELDS[11]}"
COMPONENT_BASELINE_IMAGE_REPOSITORY="${COMPONENT_BASELINE_FIELDS[12]}"
COMPONENT_BASELINE_IMAGE_TAG_PATTERN="${COMPONENT_BASELINE_FIELDS[13]}"
COMPONENT_BASELINE_IMAGE_PULL_POLICY="${COMPONENT_BASELINE_FIELDS[14]}"

CONTROLLED_SECTORS_OPERATION=""
CONTROLLED_MANUAL_REFRESH_OPERATION=false
case "$OPERATION" in
  stage-sectors-off|promote-sectors-capability|enable-sectors-config|disable-sectors-config)
    [[ "$COMPONENT_SELECTED" == false ]] || die "$OPERATION does not accept --component"
    CONTROLLED_SECTORS_OPERATION="$OPERATION"
    COMPONENT_NAME=all
    COMPONENT_SELECTED=true
    ;;
  disable-manual-refresh)
    [[ "$COMPONENT_SELECTED" == false ]] || die "$OPERATION does not accept --component"
    CONTROLLED_MANUAL_REFRESH_OPERATION=true
    COMPONENT_NAME=all
    COMPONENT_SELECTED=true
    ;;
esac
if [[ "$PROMOTION_APPLY" == true && "$CONTROLLED_SECTORS_OPERATION" != promote-sectors-capability ]]; then
  die '--apply is only valid with --promote-sectors-capability'
fi
# The off-first operation uses the existing complete ordinary deployment
# implementation after adding the stricter reviewed-packet gates below.
if [[ "$CONTROLLED_SECTORS_OPERATION" == stage-sectors-off ]]; then
  OPERATION=deploy
fi

if [[ "$COMPONENT_SELECTED" == true ]]; then
  requested_release="${CLI_RELEASE_NAME:-${RELEASE_NAME:-a-stock}}"
  requested_namespace="${CLI_NAMESPACE:-${NAMESPACE:-a-stock}}"
  [[ "$requested_release" == "$COMPONENT_BASELINE_RELEASE" ]] \
    || die "release name '$requested_release' does not match component baseline fixture '$COMPONENT_BASELINE_RELEASE'"
  [[ "$requested_namespace" == "$COMPONENT_BASELINE_NAMESPACE" ]] \
    || die "namespace '$requested_namespace' does not match component baseline fixture '$COMPONENT_BASELINE_NAMESPACE'"
fi

REPO_DIR="${REPO_DIR:-/home/gyt/a-stock}"
GIT_UPDATE="${GIT_UPDATE:-false}"
TRUENAS_HOST="${TRUENAS_HOST:-}"
TRUENAS_SSH_USER="${TRUENAS_SSH_USER:-}"
TRUENAS_SSH_PORT="${TRUENAS_SSH_PORT:-22}"
K3S_API_SSH_TUNNEL="${K3S_API_SSH_TUNNEL:-true}"
K3S_API_LOCAL_PORT="${K3S_API_LOCAL_PORT:-16443}"
REMOTE_IMAGE_DIR="${REMOTE_IMAGE_DIR:-}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-localhost/a-stock-market-environment}"
BUILD_PLATFORM="${BUILD_PLATFORM:-linux/amd64}"
DEPLOY_TMP_ROOT="${DEPLOY_TMP_ROOT:-}"
NAMESPACE="${CLI_NAMESPACE:-${NAMESPACE:-a-stock}}"
RELEASE_NAME="${CLI_RELEASE_NAME:-${RELEASE_NAME:-a-stock}}"
HELM_VALUES_FILE="${HELM_VALUES_FILE:-}"
if [[ -n "$BASELINE_VALUES_FILE" ]]; then
  HELM_VALUES_FILE="$BASELINE_VALUES_FILE"
fi
FROZEN_IMAGE_REPOSITORY="${FROZEN_IMAGE_REPOSITORY:-}"
FROZEN_IMAGE_TAG="${FROZEN_IMAGE_TAG:-}"
FROZEN_IMAGE_DIGEST="${FROZEN_IMAGE_DIGEST:-}"
SECTORS_OFF_VALUES_FILE="${CLI_SECTORS_OFF_VALUES_FILE:-${SECTORS_OFF_VALUES_FILE:-}}"
SECTORS_ENABLED_VALUES_FILE="${CLI_SECTORS_ENABLED_VALUES_FILE:-${SECTORS_ENABLED_VALUES_FILE:-}}"
CAPABILITY_REPORT_FILE="${CLI_CAPABILITY_REPORT_FILE:-${CAPABILITY_REPORT_FILE:-}}"
REVIEWED_GIT_HEAD="${REVIEWED_GIT_HEAD:-}"
REVIEWED_CHART_SHA256="${REVIEWED_CHART_SHA256:-}"
REVIEWED_OFF_VALUES_SHA256="${REVIEWED_OFF_VALUES_SHA256:-}"
REVIEWED_ENABLED_VALUES_SHA256="${REVIEWED_ENABLED_VALUES_SHA256:-}"
REVIEWED_OFF_RENDER_SHA256="${REVIEWED_OFF_RENDER_SHA256:-}"
REVIEWED_ENABLED_RENDER_SHA256="${REVIEWED_ENABLED_RENDER_SHA256:-}"
REVIEWED_REPORT_SHA256="${REVIEWED_REPORT_SHA256:-}"
REVIEWED_MANUAL_OFF_VALUES_SHA256="${REVIEWED_MANUAL_OFF_VALUES_SHA256:-}"
REVIEWED_MANUAL_OFF_RENDER_SHA256="${REVIEWED_MANUAL_OFF_RENDER_SHA256:-}"
INGRESS_CLASS="${INGRESS_CLASS:-traefik}"
INGRESS_HOST="${INGRESS_HOST:-a-stock.k3s.lan}"
POSTGRES_SECRET_NAME="${POSTGRES_SECRET_NAME:-a-stock-postgresql}"
TRUENAS_INGRESS_PORT="${TRUENAS_INGRESS_PORT:-80}"
DISABLE_MANUAL_REFRESH="${DISABLE_MANUAL_REFRESH:-true}"
TAILSCALE_HOST="${TAILSCALE_HOST:-gyt.tail0007b1.ts.net}"
TAILSCALE_PORT="${TAILSCALE_PORT:-8443}"
HELM_TIMEOUT="${HELM_TIMEOUT:-5m}"
PACKET_VALIDATOR="$REPO_DIR/scripts/validate-scheduling-packet.py"

if [[ -n "$CONTROLLED_SECTORS_OPERATION" ]]; then
  [[ -n "$SECTORS_OFF_VALUES_FILE" ]] || die "$CONTROLLED_SECTORS_OPERATION requires --off-values"
  [[ -n "$SECTORS_ENABLED_VALUES_FILE" ]] || die "$CONTROLLED_SECTORS_OPERATION requires --enabled-values"
  case "$CONTROLLED_SECTORS_OPERATION" in
    stage-sectors-off|promote-sectors-capability|disable-sectors-config)
      HELM_VALUES_FILE="$SECTORS_OFF_VALUES_FILE"
      ;;
    enable-sectors-config)
      HELM_VALUES_FILE="$SECTORS_ENABLED_VALUES_FILE"
      ;;
  esac
fi

git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not a git checkout: $REPO_DIR"
[[ -f "$REPO_DIR/Dockerfile" ]] || die "Dockerfile not found under $REPO_DIR"
[[ -d "$REPO_DIR/deploy/helm/a-stock" ]] || die "Helm chart not found under $REPO_DIR/deploy/helm/a-stock"
[[ -f "$PACKET_VALIDATOR" ]] || die "packet validator not found: $PACKET_VALIDATOR"
[[ -n "$TRUENAS_HOST" ]] || die 'TRUENAS_HOST is required'
[[ -n "$TRUENAS_SSH_USER" ]] || die 'TRUENAS_SSH_USER is required'
if [[ "$OPERATION" == deploy ]]; then
  case "$COMPONENT_NAME" in
    all|service)
      [[ -n "$REMOTE_IMAGE_DIR" ]] || die 'REMOTE_IMAGE_DIR is required for all or service component deployments'
      ;;
  esac
fi
case "$CONTROLLED_SECTORS_OPERATION" in
  promote-sectors-capability|enable-sectors-config|disable-sectors-config)
    for command_name in ssh kubectl nc; do
      command -v "$command_name" >/dev/null 2>&1 || die "required command not found: $command_name"
    done
    ;;
esac
if [[ "$CONTROLLED_MANUAL_REFRESH_OPERATION" == true ]]; then
  [[ -n "$HELM_VALUES_FILE" ]] || die '--disable-manual-refresh requires --baseline-values'
fi
[[ "$GIT_UPDATE" =~ ^(true|false)$ ]] || die 'GIT_UPDATE must be true or false'
[[ "$GIT_UPDATE" == false ]] || die 'GIT_UPDATE=true is unsupported; update and review the checkout before launching deployment'

for command_name in git sha256sum helm python3 diff; do
  command -v "$command_name" >/dev/null 2>&1 || die "required command not found: $command_name"
done
python3 -c 'import yaml' >/dev/null 2>&1 || die 'python3 PyYAML is required'
if [[ "$OPERATION" == deploy ]]; then
  for command_name in ssh kubectl nc; do
    command -v "$command_name" >/dev/null 2>&1 || die "required command not found: $command_name"
  done
  case "$COMPONENT_NAME" in
    all|service)
      for command_name in podman curl scp; do
        command -v "$command_name" >/dev/null 2>&1 || die "required command not found: $command_name"
      done
      ;;
  esac
fi

cd "$REPO_DIR"
if [[ -n "$HELM_VALUES_FILE" ]] && ! is_absolute_path "$HELM_VALUES_FILE"; then
  HELM_VALUES_FILE="$REPO_DIR/$HELM_VALUES_FILE"
fi
if [[ -n "$HELM_VALUES_FILE" ]]; then
  [[ -f "$HELM_VALUES_FILE" ]] || die "HELM_VALUES_FILE does not exist: $HELM_VALUES_FILE"
fi
if [[ -n "$SECTORS_OFF_VALUES_FILE" ]] && ! is_absolute_path "$SECTORS_OFF_VALUES_FILE"; then
  SECTORS_OFF_VALUES_FILE="$REPO_DIR/$SECTORS_OFF_VALUES_FILE"
fi
if [[ -n "$SECTORS_ENABLED_VALUES_FILE" ]] && ! is_absolute_path "$SECTORS_ENABLED_VALUES_FILE"; then
  SECTORS_ENABLED_VALUES_FILE="$REPO_DIR/$SECTORS_ENABLED_VALUES_FILE"
fi
if [[ -n "$CONTROLLED_SECTORS_OPERATION" ]]; then
  [[ -f "$SECTORS_OFF_VALUES_FILE" ]] || die "sectors off values file does not exist: $SECTORS_OFF_VALUES_FILE"
  [[ -f "$SECTORS_ENABLED_VALUES_FILE" ]] || die "sectors enabled values file does not exist: $SECTORS_ENABLED_VALUES_FILE"
  case "$CONTROLLED_SECTORS_OPERATION" in
    stage-sectors-off|promote-sectors-capability|disable-sectors-config)
      HELM_VALUES_FILE="$SECTORS_OFF_VALUES_FILE"
      ;;
    enable-sectors-config)
      HELM_VALUES_FILE="$SECTORS_ENABLED_VALUES_FILE"
      ;;
  esac
fi
if [[ -n "$CAPABILITY_REPORT_FILE" ]] && ! is_absolute_path "$CAPABILITY_REPORT_FILE"; then
  CAPABILITY_REPORT_FILE="$REPO_DIR/$CAPABILITY_REPORT_FILE"
fi
if [[ "$CONTROLLED_SECTORS_OPERATION" == promote-sectors-capability ]]; then
  [[ -n "$CAPABILITY_REPORT_FILE" ]] || die '--promote-sectors-capability requires --report'
  [[ -f "$CAPABILITY_REPORT_FILE" ]] || die "capability report does not exist: $CAPABILITY_REPORT_FILE"
fi
validate_scalar() {
  local name="$1"
  local value="$2"
  [[ "$value" =~ ^[A-Za-z0-9._:/-]+$ ]] || die "$name contains unsupported characters: $value"
}

if [[ -n "$CONTROLLED_SECTORS_OPERATION" ]]; then
  [[ -n "$TARGET_KUBERNETES_VERSION" ]] || die "$CONTROLLED_SECTORS_OPERATION requires --kube-version"
fi

validate_identifier RELEASE_NAME "$RELEASE_NAME"
validate_identifier NAMESPACE "$NAMESPACE"
validate_scalar IMAGE_REPOSITORY "$IMAGE_REPOSITORY"
validate_scalar POSTGRES_SECRET_NAME "$POSTGRES_SECRET_NAME"
validate_scalar INGRESS_CLASS "$INGRESS_CLASS"
validate_scalar INGRESS_HOST "$INGRESS_HOST"
if [[ -n "${STORAGE_CLASS:-}" ]]; then
  validate_scalar STORAGE_CLASS "$STORAGE_CLASS"
fi
[[ "$TRUENAS_SSH_PORT" =~ ^[0-9]+$ ]] || die 'TRUENAS_SSH_PORT must be numeric'
[[ "$K3S_API_LOCAL_PORT" =~ ^[0-9]+$ ]] || die 'K3S_API_LOCAL_PORT must be numeric'
((K3S_API_LOCAL_PORT >= 1024 && K3S_API_LOCAL_PORT <= 65535)) || die 'K3S_API_LOCAL_PORT must be between 1024 and 65535'
[[ "$K3S_API_SSH_TUNNEL" =~ ^(true|false)$ ]] || die 'K3S_API_SSH_TUNNEL must be true or false'
[[ "$TRUENAS_INGRESS_PORT" =~ ^[0-9]+$ ]] || die 'TRUENAS_INGRESS_PORT must be numeric'
[[ "$DISABLE_MANUAL_REFRESH" =~ ^(true|false)$ ]] || die 'DISABLE_MANUAL_REFRESH must be true or false'
if [[ "$CONTROLLED_MANUAL_REFRESH_OPERATION" == true ]]; then
  for command_name in ssh kubectl nc; do
    command -v "$command_name" >/dev/null 2>&1 || die "required command not found: $command_name"
  done
  [[ -n "$TARGET_KUBERNETES_VERSION" ]] || die '--disable-manual-refresh requires --kube-version'
fi

if [[ -n "$TARGET_KUBERNETES_VERSION" ]]; then
  TARGET_KUBERNETES_VERSION="$(normalize_kubernetes_version "$TARGET_KUBERNETES_VERSION")"
fi

EARLY_RENDER_ARGS=()
COMPONENT_RENDER_ARGS=()
if [[ -n "$CONTROLLED_SECTORS_OPERATION" || "$CONTROLLED_MANUAL_REFRESH_OPERATION" == true ]]; then
  [[ -n "$FROZEN_IMAGE_REPOSITORY" && -n "$FROZEN_IMAGE_TAG" ]] \
    || die "$OPERATION requires frozen image repository and tag"
  validate_scalar FROZEN_IMAGE_REPOSITORY "$FROZEN_IMAGE_REPOSITORY"
  validate_scalar FROZEN_IMAGE_TAG "$FROZEN_IMAGE_TAG"
  if [[ "$CONTROLLED_SECTORS_OPERATION" != stage-sectors-off ]]; then
    [[ -n "$FROZEN_IMAGE_DIGEST" ]] || die "$OPERATION requires frozen image repository, tag, and digest"
  fi
  if [[ -n "$FROZEN_IMAGE_DIGEST" ]]; then
    [[ "$FROZEN_IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] \
      || die 'FROZEN_IMAGE_DIGEST must be sha256 followed by 64 lowercase hex characters'
  fi
  EARLY_RENDER_ARGS+=(--set "image.repository=$FROZEN_IMAGE_REPOSITORY")
  EARLY_RENDER_ARGS+=(--set "image.tag=$FROZEN_IMAGE_TAG")
fi

LOCAL_KUBERNETES_VERSION="${TARGET_KUBERNETES_VERSION:-1.27.0}"

# Resolve the image reference before any render path. Reviewed controlled
# operations do not build or transfer an image, but their complete Helm packet
# still needs a defined tag for schema/render compatibility.
if [[ "$OPERATION" == deploy ]]; then
  if [[ -z "${IMAGE_TAG:-}" ]]; then
    IMAGE_TAG="$(date +%Y%m%d-%H%M%S)-$(git rev-parse --short HEAD)"
  fi
else
  IMAGE_TAG="${IMAGE_TAG:-unused}"
fi
if [[ "$CONTROLLED_SECTORS_OPERATION" == stage-sectors-off ]]; then
  [[ "$IMAGE_REPOSITORY" == "$FROZEN_IMAGE_REPOSITORY" && "$IMAGE_TAG" == "$FROZEN_IMAGE_TAG" ]] \
    || die 'stage-sectors-off IMAGE_REPOSITORY/IMAGE_TAG must equal the frozen image identity'
fi
validate_scalar IMAGE_TAG "$IMAGE_TAG"
if [[ "$OPERATION" == deploy ]]; then
  IMAGE="${IMAGE_REPOSITORY}:${IMAGE_TAG}"
  ARCHIVE_NAME="a-stock-market-environment-${IMAGE_TAG}.tar"
else
  IMAGE="${FROZEN_IMAGE_REPOSITORY:-${IMAGE_REPOSITORY}}:${FROZEN_IMAGE_TAG:-$IMAGE_TAG}"
fi

if [[ "$OPERATION" == deploy || -n "$CONTROLLED_SECTORS_OPERATION" || "$CONTROLLED_MANUAL_REFRESH_OPERATION" == true ]]; then
  case "$OPERATION" in
    deploy)
      if [[ "$COMPONENT_SELECTED" == true ]]; then
        case "$COMPONENT_NAME" in
          database)
            COMPONENT_RENDER_ARGS=(--set "component=database")
            PREFLIGHT_IMAGE_REPOSITORY="$IMAGE_REPOSITORY"
            PREFLIGHT_IMAGE_TAG="$IMAGE_TAG"
            ;;
          service)
            COMPONENT_RENDER_ARGS=(--set "component=service")
            PREFLIGHT_IMAGE_REPOSITORY="$IMAGE_REPOSITORY"
            PREFLIGHT_IMAGE_TAG="$IMAGE_TAG"
            ;;
          all)
            COMPONENT_RENDER_ARGS=()
            PREFLIGHT_IMAGE_REPOSITORY="$IMAGE_REPOSITORY"
            PREFLIGHT_IMAGE_TAG="$IMAGE_TAG"
            ;;
          *)
            die "unsupported --component for deploy: $COMPONENT_NAME"
            ;;
        esac
        COMPONENT_RENDER_ARGS+=(--set "image.repository=$PREFLIGHT_IMAGE_REPOSITORY")
        COMPONENT_RENDER_ARGS+=(--set "image.tag=$PREFLIGHT_IMAGE_TAG")
        if ! RENDERED_PACKET="$(render_release_packet "$REPO_DIR/deploy/helm/a-stock" "$HELM_VALUES_FILE" "" "$LOCAL_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" "${EARLY_RENDER_ARGS[@]}" "${COMPONENT_RENDER_ARGS[@]}")"; then
          die "component=$COMPONENT_NAME final merged Helm values are invalid"
        fi
        require_render_has_no_cronjob "component=$COMPONENT_NAME preflight packet" "$RENDERED_PACKET" \
          || die "component=$COMPONENT_NAME packet contains a retired CronJob"
        GENERIC_RENDER_SHA256="$(printf '%s\n' "$RENDERED_PACKET" | sha256sum | awk '{print $1}')"
        log "component summary: phase=preflight component=$COMPONENT_NAME packetDigest=$GENERIC_RENDER_SHA256 cronjobs=absent release=$RELEASE_NAME namespace=$NAMESPACE"
        case "$COMPONENT_NAME" in
          database)
            log "component step: name=database phase=preflight image=$PREFLIGHT_IMAGE_REPOSITORY:$PREFLIGHT_IMAGE_TAG"
            verify_database_component "$RENDERED_PACKET" || die 'component=database invariant check failed'
            verify_rendered_component_contract "$RENDERED_PACKET" "$PREFLIGHT_IMAGE_REPOSITORY" "$PREFLIGHT_IMAGE_TAG" \
              || die 'component=database rendered contract does not match the baseline fixture'
            log "component step: name=database phase=verified packetDigest=$GENERIC_RENDER_SHA256"
            log "component=database: preflight verified; target write will run after live prerequisites"
            ;;
          service)
            log "component step: name=service phase=preflight image=$PREFLIGHT_IMAGE_REPOSITORY:$PREFLIGHT_IMAGE_TAG"
            verify_service_component "$RENDERED_PACKET" || die 'component=service invariant check failed'
            verify_rendered_component_contract "$RENDERED_PACKET" "$PREFLIGHT_IMAGE_REPOSITORY" "$PREFLIGHT_IMAGE_TAG" \
              || die 'component=service rendered contract does not match the baseline fixture'
            log "component step: name=service phase=verified packetDigest=$GENERIC_RENDER_SHA256"
            log "component=service: preflight verified; target write will run after live prerequisites"
            ;;
          all)
            log "all components: order=database->service preflight start release=$RELEASE_NAME"
            COMPLETED_COMPONENTS=""
            FAILED_COMPONENT=""
            FAILED_REASON=""
            for step in database service; do
              case "$step" in
                database|service)
                  step_repo="$IMAGE_REPOSITORY"
                  step_tag="$IMAGE_TAG"
                  ;;
              esac
              step_packet="$(render_release_packet "$REPO_DIR/deploy/helm/a-stock" "$HELM_VALUES_FILE" "" "$LOCAL_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" \
                --set "image.repository=$step_repo" --set "image.tag=$step_tag" --set "component=$step")" \
                || { FAILED_COMPONENT="$step"; FAILED_REASON="component_packet_render_failed"; log "component step: name=$step phase=failed reason=component_packet_render_failed"; break; }
              step_digest="$(printf '%s\n' "$step_packet" | sha256sum | awk '{print $1}')"
              case "$step" in
                database) verify_database_component "$step_packet" || { FAILED_COMPONENT="$step"; FAILED_REASON="database_invariant_violated"; break; } ;;
                service) verify_service_component "$step_packet" || { FAILED_COMPONENT="$step"; FAILED_REASON="service_invariant_violated"; break; } ;;
              esac
              require_render_has_no_cronjob "component=$step packet" "$step_packet" \
                || { FAILED_COMPONENT="$step"; FAILED_REASON="retired_cronjob_rendered"; break; }
              verify_rendered_component_contract "$step_packet" "$step_repo" "$step_tag" \
                || { FAILED_COMPONENT="$step"; FAILED_REASON="${step}_baseline_contract_violated"; break; }
              log "component step: name=$step phase=verified packetDigest=$step_digest image=$step_repo:$step_tag"
              COMPLETED_COMPONENTS+=" $step"
            done
            if [[ -n "$FAILED_COMPONENT" ]]; then
              log "all components: status=partial order=database->service completed=$COMPLETED_COMPONENTS failed=$FAILED_COMPONENT reason=$FAILED_REASON retryTarget=rerun with the failed component alone"
              exit 1
            fi
            log "all components: status=verified order=database->service completed=$COMPLETED_COMPONENTS release=$RELEASE_NAME namespace=$NAMESPACE"
            ;;
        esac
      else
        if ! RENDERED_PACKET="$(render_release_packet "$REPO_DIR/deploy/helm/a-stock" "$HELM_VALUES_FILE" "" "$LOCAL_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" "${EARLY_RENDER_ARGS[@]}")"; then
          die 'final merged Helm values are invalid'
        fi
        require_render_has_no_cronjob 'ordinary deployment packet' "$RENDERED_PACKET" \
          || die 'ordinary deployment packet contains a retired CronJob'
        GENERIC_RENDER_SHA256="$(sha256_text "$RENDERED_PACKET")"
      fi
      ;;
    promote-sectors-capability|enable-sectors-config|disable-sectors-config|disable-manual-refresh)
      if ! RENDERED_PACKET="$(render_release_packet "$REPO_DIR/deploy/helm/a-stock" "$HELM_VALUES_FILE" "" "$LOCAL_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" "${EARLY_RENDER_ARGS[@]}")"; then
        die "$OPERATION reviewed packet failed to render"
      fi
      require_render_has_no_cronjob "$OPERATION reviewed packet" "$RENDERED_PACKET" \
        || die "$OPERATION requires both application CronJobs absent"
      GENERIC_RENDER_SHA256="$(sha256_text "$RENDERED_PACKET")"
      if [[ "$CONTROLLED_MANUAL_REFRESH_OPERATION" == true ]]; then
        printf '%s\n' "$RENDERED_PACKET" | python3 "$PACKET_VALIDATOR" validate-manual-refresh-packet \
          --release-name "$RELEASE_NAME" --namespace "$NAMESPACE" \
          --image "$FROZEN_IMAGE_REPOSITORY:$FROZEN_IMAGE_TAG" --require-value 0 >/dev/null \
          || die 'reviewed manual-off packet violates the disabled runtime contract'
      fi
      ;;
  esac
fi

if [[ -n "$CONTROLLED_SECTORS_OPERATION" ]]; then
  REVIEWED_OFF_RENDER="$(render_release_packet "$REPO_DIR/deploy/helm/a-stock" "$SECTORS_OFF_VALUES_FILE" "" "$LOCAL_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" "${EARLY_RENDER_ARGS[@]}")" \
    || die 'reviewed sectors-off packet failed to render'
  REVIEWED_ENABLED_RENDER="$(render_release_packet "$REPO_DIR/deploy/helm/a-stock" "$SECTORS_ENABLED_VALUES_FILE" "" "$LOCAL_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" "${EARLY_RENDER_ARGS[@]}")" \
    || die 'reviewed sectors-enabled packet failed to render'
  printf '%s\n' "$REVIEWED_OFF_RENDER" | python3 "$PACKET_VALIDATOR" validate-sectors-packet \
    --release-name "$RELEASE_NAME" --namespace "$NAMESPACE" --require-enabled 0 >/dev/null \
    || die 'reviewed sectors-off packet violates the disabled runtime contract'
  printf '%s\n' "$REVIEWED_ENABLED_RENDER" | python3 "$PACKET_VALIDATOR" validate-sectors-packet \
    --release-name "$RELEASE_NAME" --namespace "$NAMESPACE" --require-enabled 1 >/dev/null \
    || die 'reviewed sectors-enabled packet violates the enabled runtime contract'
  python3 "$PACKET_VALIDATOR" compare-sectors-config-only \
    --current <(printf '%s\n' "$REVIEWED_OFF_RENDER") \
    --desired <(printf '%s\n' "$REVIEWED_ENABLED_RENDER") \
    --release-name "$RELEASE_NAME" --namespace "$NAMESPACE" \
    --image "$FROZEN_IMAGE_REPOSITORY:$FROZEN_IMAGE_TAG" \
    --from-enabled 0 --to-enabled 1 \
    || die 'reviewed sectors profiles differ outside the enabled flag'
fi
chart_sha256() {
  git ls-files -z -- deploy/helm/a-stock \
    | sort -z \
    | xargs -0 sha256sum \
    | sha256sum \
    | awk '{print $1}'
}

verify_hash() {
  local label="$1"
  local expected="$2"
  local actual="$3"
  [[ -n "$expected" ]] || die "$label expected SHA-256 is required"
  [[ "$expected" == "$actual" ]] || die "$label SHA-256 drift: expected $expected, got $actual"
}

verify_reviewed_deploy_source() {
  [[ "$REVIEWED_GIT_HEAD" =~ ^[0-9a-f]{40}$ ]] \
    || die 'generic all/service deploy requires REVIEWED_GIT_HEAD as a full lowercase commit SHA'
  [[ "$(git rev-parse HEAD)" == "$REVIEWED_GIT_HEAD" ]] \
    || die 'reviewed Git HEAD does not match the checked-out source'
  if [[ -n "$FROZEN_IMAGE_DIGEST" && ! "$FROZEN_IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    die 'FROZEN_IMAGE_DIGEST must be sha256 followed by 64 lowercase hex characters'
  fi
}

# Reviewed controlled operations require a clean working tree.
assert_clean_worktree() {
  [[ -z "$(git status --porcelain --untracked-files=all)" ]] \
    || die 'reviewed operations require a clean working tree'
}

verify_controlled_sectors_packet() {
  [[ -n "$REVIEWED_GIT_HEAD" ]] || die 'REVIEWED_GIT_HEAD is required'
  [[ "$(git rev-parse HEAD)" == "$REVIEWED_GIT_HEAD" ]] \
    || die 'reviewed Git HEAD does not match the checked-out source'
  verify_hash 'reviewed chart' "$REVIEWED_CHART_SHA256" "$(chart_sha256)"
  verify_hash 'reviewed sectors-off values' "$REVIEWED_OFF_VALUES_SHA256" \
    "$(sha256sum "$SECTORS_OFF_VALUES_FILE" | awk '{print $1}')"
  verify_hash 'reviewed sectors-enabled values' "$REVIEWED_ENABLED_VALUES_SHA256" \
    "$(sha256sum "$SECTORS_ENABLED_VALUES_FILE" | awk '{print $1}')"
  verify_hash 'reviewed sectors-off render' "$REVIEWED_OFF_RENDER_SHA256" \
    "$(sha256_text "$REVIEWED_OFF_RENDER")"
  verify_hash 'reviewed sectors-enabled render' "$REVIEWED_ENABLED_RENDER_SHA256" \
    "$(sha256_text "$REVIEWED_ENABLED_RENDER")"
  if [[ "$CONTROLLED_SECTORS_OPERATION" == promote-sectors-capability ]]; then
    verify_hash 'reviewed capability report' "$REVIEWED_REPORT_SHA256" \
      "$(sha256sum "$CAPABILITY_REPORT_FILE" | awk '{print $1}')"
  fi
}

verify_controlled_manual_refresh_packet() {
  [[ "$REVIEWED_GIT_HEAD" =~ ^[0-9a-f]{40}$ ]] \
    || die 'REVIEWED_GIT_HEAD must be a full lowercase commit SHA'
  [[ "$(git rev-parse HEAD)" == "$REVIEWED_GIT_HEAD" ]] \
    || die 'reviewed Git HEAD does not match the checked-out source'
  verify_hash 'reviewed chart' "$REVIEWED_CHART_SHA256" "$(chart_sha256)"
  verify_hash 'reviewed manual-off values' "$REVIEWED_MANUAL_OFF_VALUES_SHA256" \
    "$(sha256sum "$HELM_VALUES_FILE" | awk '{print $1}')"
  verify_hash 'reviewed manual-off render' "$REVIEWED_MANUAL_OFF_RENDER_SHA256" \
    "$(sha256_text "$RENDERED_PACKET")"
}

GENERIC_IMMUTABLE_IMAGE_REQUIRED=false
if [[ "$OPERATION" == deploy && -z "$CONTROLLED_SECTORS_OPERATION" \
      && ( "$COMPONENT_NAME" == all || "$COMPONENT_NAME" == service ) ]]; then
  GENERIC_IMMUTABLE_IMAGE_REQUIRED=true
  assert_clean_worktree
  verify_reviewed_deploy_source
fi
if [[ -n "$CONTROLLED_SECTORS_OPERATION" ]]; then
  assert_clean_worktree
  verify_controlled_sectors_packet
fi
if [[ "$CONTROLLED_MANUAL_REFRESH_OPERATION" == true ]]; then
  assert_clean_worktree
  verify_controlled_manual_refresh_packet
  REVIEWED_MANUAL_OFF_RENDER="$RENDERED_PACKET"
fi

if [[ "$OPERATION" == deploy ]]; then
  if [[ -z "${IMAGE_TAG:-}" ]]; then
    IMAGE_TAG="$(date +%Y%m%d-%H%M%S)-$(git rev-parse --short HEAD)"
  fi
  validate_scalar IMAGE_TAG "$IMAGE_TAG"
  IMAGE="${IMAGE_REPOSITORY}:${IMAGE_TAG}"
  ARCHIVE_NAME="a-stock-market-environment-${IMAGE_TAG}.tar"
else
  IMAGE="${FROZEN_IMAGE_REPOSITORY:-${IMAGE_REPOSITORY}}:${FROZEN_IMAGE_TAG:-${IMAGE_TAG:-unused}}"
fi
DEPLOY_IMAGE_REPOSITORY="$IMAGE_REPOSITORY"
DEPLOY_IMAGE_TAG="$IMAGE_TAG"
if [[ -n "$CONTROLLED_SECTORS_OPERATION" ]]; then
  DEPLOY_IMAGE_REPOSITORY="$FROZEN_IMAGE_REPOSITORY"
  DEPLOY_IMAGE_TAG="$FROZEN_IMAGE_TAG"
fi
if [[ "$CONTROLLED_MANUAL_REFRESH_OPERATION" == true ]]; then
  DEPLOY_IMAGE_REPOSITORY="$FROZEN_IMAGE_REPOSITORY"
  DEPLOY_IMAGE_TAG="$FROZEN_IMAGE_TAG"
fi
SSH_TARGET="${TRUENAS_SSH_USER}@${TRUENAS_HOST}"
remote() {
  ssh -o BatchMode=yes -o ConnectTimeout=10 -p "$TRUENAS_SSH_PORT" "$SSH_TARGET" "$@"
}

TMP_DIR="$(mktemp -d -t a-stock-deploy.XXXXXX)"
ARCHIVE_TMP_DIR=''
SMOKE_NAME="a-stock-smoke-$$"
SMOKE_CREATED=false
K3S_TUNNEL_PID=''
GENERIC_CRONJOB_NAME=''
cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM HUP
  if [[ "$SMOKE_CREATED" == true ]]; then
    podman rm -f "$SMOKE_NAME" >/dev/null 2>&1 || true
  fi
  if [[ -n "$K3S_TUNNEL_PID" ]]; then
    kill "$K3S_TUNNEL_PID" >/dev/null 2>&1 || true
    wait "$K3S_TUNNEL_PID" 2>/dev/null || true
  fi
  if [[ -n "$ARCHIVE_TMP_DIR" ]]; then
    case "$ARCHIVE_TMP_DIR" in
      */a-stock-deploy-image.*)
        chmod -R u+w "$ARCHIVE_TMP_DIR" >/dev/null 2>&1 || true
        rm -rf -- "$ARCHIVE_TMP_DIR"
        ;;
      *)
        warn "refusing to remove unexpected image archive temp directory: $ARCHIVE_TMP_DIR"
        ;;
    esac
  fi
  chmod -R u+w "$TMP_DIR" >/dev/null 2>&1 || true
  rm -rf -- "$TMP_DIR"
  exit "$exit_code"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

SOURCE_CHART_DIR="$REPO_DIR/deploy/helm/a-stock"
OPERATION_CHART_DIR="$SOURCE_CHART_DIR"
OPERATION_BASELINE_VALUES="$HELM_VALUES_FILE"
case "$OPERATION" in
  deploy|disable-manual-refresh|promote-sectors-capability|enable-sectors-config|disable-sectors-config)
    command -v flock >/dev/null 2>&1 || die 'required command not found: flock'
    COMMON_GIT_DIR="$(git rev-parse --git-common-dir)"
    if [[ "$COMMON_GIT_DIR" != /* ]]; then
      COMMON_GIT_DIR="$REPO_DIR/$COMMON_GIT_DIR"
    fi
    exec 9>"$COMMON_GIT_DIR/a-stock-release.lock"
    flock -n 9 || die 'another reviewed release operation holds the release lock'
    ;;
esac
case "$OPERATION" in
  deploy|disable-manual-refresh|promote-sectors-capability|enable-sectors-config|disable-sectors-config)
    SNAPSHOT_DIR="$TMP_DIR/release-packet"
    mkdir -p "$SNAPSHOT_DIR"
    cp -R "$SOURCE_CHART_DIR" "$SNAPSHOT_DIR/chart"
    diff -qr "$SOURCE_CHART_DIR" "$SNAPSHOT_DIR/chart" >/dev/null || die 'chart changed while freezing the release packet'
    OPERATION_CHART_DIR="$SNAPSHOT_DIR/chart"
    if [[ -n "$HELM_VALUES_FILE" ]]; then
      cp "$HELM_VALUES_FILE" "$SNAPSHOT_DIR/baseline.yaml"
      OPERATION_BASELINE_VALUES="$SNAPSHOT_DIR/baseline.yaml"
    fi
    if [[ -n "$CONTROLLED_SECTORS_OPERATION" ]]; then
      cp "$SECTORS_OFF_VALUES_FILE" "$SNAPSHOT_DIR/sectors-off.yaml"
      cp "$SECTORS_ENABLED_VALUES_FILE" "$SNAPSHOT_DIR/sectors-enabled.yaml"
      SECTORS_OFF_VALUES_FILE="$SNAPSHOT_DIR/sectors-off.yaml"
      SECTORS_ENABLED_VALUES_FILE="$SNAPSHOT_DIR/sectors-enabled.yaml"
      case "$CONTROLLED_SECTORS_OPERATION" in
        stage-sectors-off|promote-sectors-capability|disable-sectors-config)
          OPERATION_BASELINE_VALUES="$SECTORS_OFF_VALUES_FILE"
          ;;
        enable-sectors-config)
          OPERATION_BASELINE_VALUES="$SECTORS_ENABLED_VALUES_FILE"
          ;;
      esac
    fi
    SNAPSHOT_RENDER_ARGS=("${EARLY_RENDER_ARGS[@]}" "${COMPONENT_RENDER_ARGS[@]}")
    if ! SNAPSHOT_RENDER="$(render_release_packet "$OPERATION_CHART_DIR" "$OPERATION_BASELINE_VALUES" "" "$LOCAL_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" "${SNAPSHOT_RENDER_ARGS[@]}")"; then
      die 'frozen release packet render failed'
    fi
    if [[ "$(sha256_text "$SNAPSHOT_RENDER")" != "$(sha256_text "$RENDERED_PACKET")" ]]; then
      die 'release packet changed while freezing its sources'
    fi
    require_render_has_no_cronjob 'frozen release packet' "$SNAPSHOT_RENDER" \
      || die 'frozen release packet contains a retired CronJob'
    if [[ -n "$CONTROLLED_SECTORS_OPERATION" ]]; then
      SNAPSHOT_OFF_RENDER="$(render_release_packet "$OPERATION_CHART_DIR" "$SECTORS_OFF_VALUES_FILE" "" "$LOCAL_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" "${EARLY_RENDER_ARGS[@]}")" \
        || die 'frozen reviewed sectors-off packet failed to render'
      SNAPSHOT_ENABLED_RENDER="$(render_release_packet "$OPERATION_CHART_DIR" "$SECTORS_ENABLED_VALUES_FILE" "" "$LOCAL_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" "${EARLY_RENDER_ARGS[@]}")" \
        || die 'frozen reviewed sectors-enabled packet failed to render'
      [[ "$(sha256_text "$SNAPSHOT_OFF_RENDER")" == "$REVIEWED_OFF_RENDER_SHA256" ]] \
        || die 'frozen reviewed sectors-off packet hash drifted'
      [[ "$(sha256_text "$SNAPSHOT_ENABLED_RENDER")" == "$REVIEWED_ENABLED_RENDER_SHA256" ]] \
        || die 'frozen reviewed sectors-enabled packet hash drifted'
      REVIEWED_OFF_RENDER="$SNAPSHOT_OFF_RENDER"
      REVIEWED_ENABLED_RENDER="$SNAPSHOT_ENABLED_RENDER"
    fi
    if [[ "$CONTROLLED_MANUAL_REFRESH_OPERATION" == true ]]; then
      [[ "$(sha256_text "$SNAPSHOT_RENDER")" == "$REVIEWED_MANUAL_OFF_RENDER_SHA256" ]] \
        || die 'frozen reviewed manual-off packet hash drifted'
      REVIEWED_MANUAL_OFF_RENDER="$SNAPSHOT_RENDER"
    fi
    chmod -R a-w "$SNAPSHOT_DIR"
    RENDERED_PACKET="$SNAPSHOT_RENDER"
    ;;
esac

if [[ "$OPERATION" == deploy && "$GENERIC_IMMUTABLE_IMAGE_REQUIRED" != true && -n "$(git status --porcelain)" ]]; then
  warn 'working tree is dirty; the image will include the current checkout as-is'
fi

log "checking SSH and non-interactive sudo on $SSH_TARGET"
remote 'sudo -n true' >/dev/null
if [[ "$OPERATION" == deploy ]]; then
  remote "test -d '$REMOTE_IMAGE_DIR' && test -w '$REMOTE_IMAGE_DIR'" || die "remote image directory is missing or not writable: $REMOTE_IMAGE_DIR"
fi

if [[ -z "${KUBECONFIG:-}" ]]; then
  KUBECONFIG="$TMP_DIR/k3s.yaml"
  log 'fetching a temporary k3s kubeconfig from TrueNAS'
  remote 'sudo -n cat /etc/rancher/k3s/k3s.yaml' > "$KUBECONFIG"
  if [[ "$K3S_API_SSH_TUNNEL" == true ]]; then
    log "opening a loopback SSH tunnel for the k3s API on 127.0.0.1:$K3S_API_LOCAL_PORT"
    ssh -o BatchMode=yes -o ConnectTimeout=10 -o ExitOnForwardFailure=yes \
      -p "$TRUENAS_SSH_PORT" -N \
      -L "127.0.0.1:${K3S_API_LOCAL_PORT}:127.0.0.1:6443" \
      "$SSH_TARGET" &
    K3S_TUNNEL_PID=$!
    for _ in 1 2 3 4 5; do
      nc -z -w 1 127.0.0.1 "$K3S_API_LOCAL_PORT" >/dev/null 2>&1 && break
      kill -0 "$K3S_TUNNEL_PID" >/dev/null 2>&1 || die 'k3s API SSH tunnel exited before becoming ready'
      sleep 1
    done
    nc -z -w 1 127.0.0.1 "$K3S_API_LOCAL_PORT" >/dev/null 2>&1 || die 'k3s API SSH tunnel did not become ready'
    sed -i "s#https://127.0.0.1:6443#https://127.0.0.1:${K3S_API_LOCAL_PORT}#" "$KUBECONFIG"
  else
    TRUENAS_API_HOST="${TRUENAS_API_HOST:-$TRUENAS_HOST}"
    sed -i "s#https://127.0.0.1:6443#https://${TRUENAS_API_HOST}:6443#" "$KUBECONFIG"
  fi
  chmod 600 "$KUBECONFIG"
  export KUBECONFIG
else
  [[ -f "$KUBECONFIG" ]] || die "KUBECONFIG does not exist: $KUBECONFIG"
fi

log 'checking target k3s capabilities'
NODE_ARCH="$(kubectl get nodes -o jsonpath='{.items[0].status.nodeInfo.architecture}')"
[[ -n "$NODE_ARCH" ]] || die 'no k3s node was returned'
VERSION_RESPONSE="$(kubectl get --raw /version)"
if ! ACTUAL_KUBERNETES_VERSION="$(printf '%s\n' "$VERSION_RESPONSE" | parse_server_version)"; then
  die 'could not reliably determine the target Kubernetes version'
fi
if [[ -n "$TARGET_KUBERNETES_VERSION" && "$ACTUAL_KUBERNETES_VERSION" != "$TARGET_KUBERNETES_VERSION" ]]; then
  die "target Kubernetes version drift: expected $TARGET_KUBERNETES_VERSION, got $ACTUAL_KUBERNETES_VERSION"
fi
TARGET_KUBERNETES_VERSION="$ACTUAL_KUBERNETES_VERSION"
if [[ "$BUILD_PLATFORM" != "linux/${NODE_ARCH}" ]]; then
  warn "build platform $BUILD_PLATFORM differs from node architecture $NODE_ARCH"
fi

if [[ "$OPERATION" == deploy || "$OPERATION" == disable-manual-refresh || "$OPERATION" == promote-sectors-capability || "$OPERATION" == enable-sectors-config || "$OPERATION" == disable-sectors-config ]]; then
  if ! GENERIC_CRONJOB_NAME="$(former_release_cronjob_name "$OPERATION_CHART_DIR" "$OPERATION_BASELINE_VALUES")"; then
    die 'could not derive the former release-owned CronJob identity from chart values'
  fi
  verify_generic_deploy_precondition
  if [[ "$OPERATION" == deploy ]]; then
    require_namespace_jobs_absent 'ordinary deployment initial precondition' \
      || die 'ordinary deployment requires namespace Jobs absent before build or Helm write'
  fi
fi

if [[ -n "$CONTROLLED_SECTORS_OPERATION" && "$CONTROLLED_SECTORS_OPERATION" != stage-sectors-off ]]; then
  [[ "$(helm_release_presence)" == present ]] \
    || die "$CONTROLLED_SECTORS_OPERATION requires an existing Helm release"
fi
if [[ "$CONTROLLED_MANUAL_REFRESH_OPERATION" == true ]]; then
  [[ "$(helm_release_presence)" == present ]] \
    || die '--disable-manual-refresh requires an existing Helm release'
fi

if [[ "$CONTROLLED_SECTORS_OPERATION" == stage-sectors-off ]]; then
  require_all_application_cronjobs_absent 'stage-sectors-off precondition' \
    || die 'stage-sectors-off could not prove both application CronJobs absent'
  require_namespace_jobs_absent 'stage-sectors-off precondition' \
    || die 'stage-sectors-off requires namespace Jobs absent'
  PRESERVED_IDENTITIES_BEFORE="$(capture_preserved_resource_identities "$REVIEWED_OFF_RENDER")" \
    || die 'stage-sectors-off could not capture Secret/PVC metadata before execution'
fi

if [[ "$CONTROLLED_MANUAL_REFRESH_OPERATION" == true ]]; then
  FROZEN_IMAGE="$FROZEN_IMAGE_REPOSITORY:$FROZEN_IMAGE_TAG"
  MANUAL_CURRENT_MANIFEST="$TMP_DIR/manual-refresh-current-manifest.yaml"
  MANUAL_DESIRED_MANIFEST="$TMP_DIR/manual-refresh-desired-manifest.yaml"
  MANUAL_CURRENT_HOOKS="$TMP_DIR/manual-refresh-current-hooks.yaml"
  MANUAL_DESIRED_HOOKS="$TMP_DIR/manual-refresh-desired-hooks.yaml"
  MANUAL_LIVE_BEFORE_MANIFEST="$TMP_DIR/manual-refresh-live-before.yaml"
  MANUAL_LIVE_AFTER_MANIFEST="$TMP_DIR/manual-refresh-live-after.yaml"
  MANUAL_POST_MANIFEST="$TMP_DIR/manual-refresh-post-manifest.yaml"
  printf '%s\n' "$REVIEWED_MANUAL_OFF_RENDER" \
    | python3 "$PACKET_VALIDATOR" extract-helm-documents --part release \
      > "$MANUAL_DESIRED_MANIFEST" \
    || die '--disable-manual-refresh could not extract the reviewed release manifest'
  printf '%s\n' "$REVIEWED_MANUAL_OFF_RENDER" \
    | python3 "$PACKET_VALIDATOR" extract-helm-documents --part hooks \
      > "$MANUAL_DESIRED_HOOKS" \
    || die '--disable-manual-refresh could not extract the reviewed Helm hooks'

  verify_frozen_runtime_image "$FROZEN_IMAGE_REPOSITORY" "$FROZEN_IMAGE_TAG" "$FROZEN_IMAGE_DIGEST" \
    || die '--disable-manual-refresh could not prove the exact Ready frozen runtime image'
  require_all_application_cronjobs_absent '--disable-manual-refresh precondition' \
    || die '--disable-manual-refresh could not prove both application CronJobs absent'
  require_terminal_namespace_jobs '--disable-manual-refresh precondition' \
    || die '--disable-manual-refresh requires every namespace Job to be terminal'
  verify_live_database_contract \
    || die '--disable-manual-refresh requires a healthy reviewed PostgreSQL runtime'
  PRESERVED_IDENTITIES_BEFORE="$(capture_preserved_resource_identities "$REVIEWED_MANUAL_OFF_RENDER")" \
    || die '--disable-manual-refresh could not capture Secret/PVC metadata before execution'

  helm get manifest "$RELEASE_NAME" --namespace "$NAMESPACE" > "$MANUAL_CURRENT_MANIFEST"
  helm get hooks "$RELEASE_NAME" --namespace "$NAMESPACE" > "$MANUAL_CURRENT_HOOKS"
  python3 "$PACKET_VALIDATOR" compare-hooks-exact \
    --current "$MANUAL_CURRENT_HOOKS" --desired "$MANUAL_DESIRED_HOOKS"
  python3 "$PACKET_VALIDATOR" compare-manual-refresh-only \
    --current "$MANUAL_CURRENT_MANIFEST" --desired "$MANUAL_DESIRED_MANIFEST" \
    --release-name "$RELEASE_NAME" --namespace "$NAMESPACE" --image "$FROZEN_IMAGE"
  kubectl get deployment,service,cronjob,statefulset,pvc --namespace "$NAMESPACE" \
    -l "app.kubernetes.io/instance=$RELEASE_NAME" -o yaml > "$MANUAL_LIVE_BEFORE_MANIFEST"
  python3 "$PACKET_VALIDATOR" compare-manual-refresh-live-desired \
    --release-name "$RELEASE_NAME" --namespace "$NAMESPACE" \
    --desired "$MANUAL_CURRENT_MANIFEST" < "$MANUAL_LIVE_BEFORE_MANIFEST"
  verify_manual_refresh_runtime "$(cat "$MANUAL_CURRENT_MANIFEST")" 1 \
    || die '--disable-manual-refresh requires one exact Ready Pod with manual refresh enabled'

  # Rebind every local and target fact immediately before the only write.
  assert_clean_worktree
  verify_controlled_manual_refresh_packet
  MANUAL_PRE_WRITE_RENDER="$(render_release_packet "$OPERATION_CHART_DIR" "$OPERATION_BASELINE_VALUES" "" \
    "$TARGET_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" "${EARLY_RENDER_ARGS[@]}")" \
    || die '--disable-manual-refresh reviewed packet failed immediately before Helm write'
  [[ "$(sha256_text "$MANUAL_PRE_WRITE_RENDER")" == "$REVIEWED_MANUAL_OFF_RENDER_SHA256" ]] \
    || die '--disable-manual-refresh reviewed packet hash drifted immediately before Helm write'
  printf '%s\n' "$MANUAL_PRE_WRITE_RENDER" | python3 "$PACKET_VALIDATOR" validate-manual-refresh-packet \
    --release-name "$RELEASE_NAME" --namespace "$NAMESPACE" \
    --image "$FROZEN_IMAGE" --require-value 0 >/dev/null \
    || die '--disable-manual-refresh immediate packet violates the disabled runtime contract'
  verify_generic_deploy_precondition
  [[ "$(helm_release_presence)" == present ]] \
    || die '--disable-manual-refresh release disappeared before Helm write'
  helm get manifest "$RELEASE_NAME" --namespace "$NAMESPACE" > "$MANUAL_CURRENT_MANIFEST"
  helm get hooks "$RELEASE_NAME" --namespace "$NAMESPACE" > "$MANUAL_CURRENT_HOOKS"
  python3 "$PACKET_VALIDATOR" compare-hooks-exact \
    --current "$MANUAL_CURRENT_HOOKS" --desired "$MANUAL_DESIRED_HOOKS"
  python3 "$PACKET_VALIDATOR" compare-manual-refresh-only \
    --current "$MANUAL_CURRENT_MANIFEST" --desired "$MANUAL_DESIRED_MANIFEST" \
    --release-name "$RELEASE_NAME" --namespace "$NAMESPACE" --image "$FROZEN_IMAGE"
  kubectl get deployment,service,cronjob,statefulset,pvc --namespace "$NAMESPACE" \
    -l "app.kubernetes.io/instance=$RELEASE_NAME" -o yaml > "$MANUAL_LIVE_BEFORE_MANIFEST"
  python3 "$PACKET_VALIDATOR" compare-manual-refresh-live-desired \
    --release-name "$RELEASE_NAME" --namespace "$NAMESPACE" \
    --desired "$MANUAL_CURRENT_MANIFEST" < "$MANUAL_LIVE_BEFORE_MANIFEST"
  verify_live_database_contract \
    || die '--disable-manual-refresh PostgreSQL runtime drifted before Helm write'
  verify_frozen_runtime_image "$FROZEN_IMAGE_REPOSITORY" "$FROZEN_IMAGE_TAG" "$FROZEN_IMAGE_DIGEST" \
    || die '--disable-manual-refresh frozen runtime image drifted before Helm write'
  verify_manual_refresh_runtime "$(cat "$MANUAL_CURRENT_MANIFEST")" 1 \
    || die '--disable-manual-refresh runtime manual-refresh state drifted before Helm write'
  require_all_application_cronjobs_absent '--disable-manual-refresh immediate pre-write' \
    || die '--disable-manual-refresh scheduling drifted before Helm write'
  require_terminal_namespace_jobs '--disable-manual-refresh immediate pre-write' \
    || die '--disable-manual-refresh found a non-terminal namespace Job before Helm write'
  PRESERVED_IDENTITIES_PRE_WRITE="$(capture_preserved_resource_identities "$REVIEWED_MANUAL_OFF_RENDER")" \
    || die '--disable-manual-refresh could not recapture Secret/PVC metadata before Helm write'
  [[ "$PRESERVED_IDENTITIES_PRE_WRITE" == "$PRESERVED_IDENTITIES_BEFORE" ]] \
    || die '--disable-manual-refresh Secret/PVC metadata drifted before Helm write'

  log "disabling manual refresh with hook-free same-image packet image=$FROZEN_IMAGE"
  helm upgrade "$RELEASE_NAME" "$OPERATION_CHART_DIR" \
    --namespace "$NAMESPACE" \
    --values "$OPERATION_BASELINE_VALUES" \
    --set "image.repository=$FROZEN_IMAGE_REPOSITORY" \
    --set "image.tag=$FROZEN_IMAGE_TAG" \
    --set component=all \
    --no-hooks \
    --atomic \
    --wait \
    --timeout "$HELM_TIMEOUT"
  DEPLOYMENT_NAME="$(kubectl -n "$NAMESPACE" get deployment \
    -l "app.kubernetes.io/instance=$RELEASE_NAME" \
    -o jsonpath='{.items[0].metadata.name}')"
  [[ -n "$DEPLOYMENT_NAME" ]] || die '--disable-manual-refresh postcondition found no Dashboard Deployment'
  kubectl -n "$NAMESPACE" rollout status "deployment/$DEPLOYMENT_NAME" --timeout=180s
  helm get manifest "$RELEASE_NAME" --namespace "$NAMESPACE" > "$MANUAL_POST_MANIFEST"
  helm get hooks "$RELEASE_NAME" --namespace "$NAMESPACE" > "$MANUAL_CURRENT_HOOKS"
  python3 "$PACKET_VALIDATOR" compare-hooks-exact \
    --current "$MANUAL_CURRENT_HOOKS" --desired "$MANUAL_DESIRED_HOOKS"
  python3 "$PACKET_VALIDATOR" compare-release-exact \
    --current "$MANUAL_POST_MANIFEST" --desired "$MANUAL_DESIRED_MANIFEST"
  kubectl get deployment,service,cronjob,statefulset,pvc --namespace "$NAMESPACE" \
    -l "app.kubernetes.io/instance=$RELEASE_NAME" -o yaml > "$MANUAL_LIVE_AFTER_MANIFEST"
  python3 "$PACKET_VALIDATOR" compare-manual-refresh-live-desired \
    --release-name "$RELEASE_NAME" --namespace "$NAMESPACE" \
    --desired "$MANUAL_DESIRED_MANIFEST" < "$MANUAL_LIVE_AFTER_MANIFEST"
  verify_live_database_contract \
    || die '--disable-manual-refresh postcondition requires a healthy reviewed PostgreSQL runtime'
  verify_frozen_runtime_image "$FROZEN_IMAGE_REPOSITORY" "$FROZEN_IMAGE_TAG" "$FROZEN_IMAGE_DIGEST" \
    || die '--disable-manual-refresh postcondition could not prove the frozen runtime image'
  verify_manual_refresh_runtime "$REVIEWED_MANUAL_OFF_RENDER" 0 \
    || die '--disable-manual-refresh postcondition requires one exact Ready Pod with manual refresh disabled'
  require_all_application_cronjobs_absent '--disable-manual-refresh postcondition' \
    || die '--disable-manual-refresh postcondition could not prove both application CronJobs absent'
  require_terminal_namespace_jobs '--disable-manual-refresh postcondition' \
    || die '--disable-manual-refresh postcondition requires every namespace Job to be terminal'
  PRESERVED_IDENTITIES_AFTER="$(capture_preserved_resource_identities "$REVIEWED_MANUAL_OFF_RENDER")" \
    || die '--disable-manual-refresh postcondition could not capture Secret/PVC metadata'
  [[ "$PRESERVED_IDENTITIES_AFTER" == "$PRESERVED_IDENTITIES_BEFORE" ]] \
    || die '--disable-manual-refresh changed preserved Secret/PVC metadata'
  log "manual refresh disabled with same frozen image=$FROZEN_IMAGE"
  exit 0
fi

if [[ "$OPERATION" == promote-sectors-capability || "$OPERATION" == enable-sectors-config || "$OPERATION" == disable-sectors-config ]]; then
  FROZEN_IMAGE="$FROZEN_IMAGE_REPOSITORY:$FROZEN_IMAGE_TAG"
  verify_frozen_runtime_image "$FROZEN_IMAGE_REPOSITORY" "$FROZEN_IMAGE_TAG" "$FROZEN_IMAGE_DIGEST" \
    || die "$OPERATION could not prove the exact Ready frozen runtime image"
  require_all_application_cronjobs_absent "$OPERATION precondition" \
    || die "$OPERATION could not prove both application CronJobs absent"
  require_namespace_jobs_absent "$OPERATION precondition" \
    || die "$OPERATION requires namespace Jobs absent"
  PRESERVED_IDENTITIES_BEFORE="$(capture_preserved_resource_identities "$REVIEWED_OFF_RENDER")" \
    || die "$OPERATION could not capture Secret/PVC metadata before execution"

  if [[ "$OPERATION" == promote-sectors-capability ]]; then
    PROMOTION_CURRENT_MANIFEST="$TMP_DIR/promotion-current-manifest.yaml"
    PROMOTION_DESIRED_MANIFEST="$TMP_DIR/promotion-desired-manifest.yaml"
    PROMOTION_LIVE_MANIFEST="$TMP_DIR/promotion-live-manifest.yaml"
    printf '%s\n' "$REVIEWED_OFF_RENDER" > "$PROMOTION_DESIRED_MANIFEST"
    helm get manifest "$RELEASE_NAME" --namespace "$NAMESPACE" > "$PROMOTION_CURRENT_MANIFEST"
    python3 "$PACKET_VALIDATOR" compare-release-exact \
      --current "$PROMOTION_CURRENT_MANIFEST" --desired "$PROMOTION_DESIRED_MANIFEST"
    kubectl get deployment,service,cronjob --namespace "$NAMESPACE" \
      -l "app.kubernetes.io/instance=$RELEASE_NAME" -o yaml > "$PROMOTION_LIVE_MANIFEST"
    python3 "$PACKET_VALIDATOR" compare-live-desired \
      --release-name "$RELEASE_NAME" --namespace "$NAMESPACE" \
      --desired "$PROMOTION_DESIRED_MANIFEST" < "$PROMOTION_LIVE_MANIFEST"
    PROMOTION_POD="$(select_runtime_sectors_pod 0)" \
      || die 'production promotion requires one exact Ready sectors-off Pod'
    verify_hash 'reviewed capability report' "$REVIEWED_REPORT_SHA256" \
      "$(sha256sum "$CAPABILITY_REPORT_FILE" | awk '{print $1}')"
    PROMOTION_ARGS=(
      python -m src.market_environment.cli capabilities promote
      --input - --provider fuyao --dataset sectors --revision fuyao-market-v2
    )
    if [[ "$PROMOTION_APPLY" == true ]]; then
      PROMOTION_ARGS+=(--apply)
    fi
    log "streaming reviewed capability report to exact Ready Pod $PROMOTION_POD (apply=$PROMOTION_APPLY)"
    kubectl exec -i --namespace "$NAMESPACE" "$PROMOTION_POD" -c dashboard -- \
      "${PROMOTION_ARGS[@]}" < "$CAPABILITY_REPORT_FILE"
    verify_frozen_runtime_image "$FROZEN_IMAGE_REPOSITORY" "$FROZEN_IMAGE_TAG" "$FROZEN_IMAGE_DIGEST" \
      || die 'promotion postcondition could not prove the frozen runtime image'
    select_runtime_sectors_pod 0 >/dev/null \
      || die 'promotion postcondition requires the exact Ready Pod to remain sectors-off'
    require_all_application_cronjobs_absent 'promotion postcondition' \
      || die 'promotion postcondition could not prove both application CronJobs absent'
    require_namespace_jobs_absent 'promotion postcondition' \
      || die 'promotion postcondition requires namespace Jobs absent'
    PRESERVED_IDENTITIES_AFTER="$(capture_preserved_resource_identities "$REVIEWED_OFF_RENDER")" \
      || die 'promotion postcondition could not capture Secret/PVC metadata'
    [[ "$PRESERVED_IDENTITIES_AFTER" == "$PRESERVED_IDENTITIES_BEFORE" ]] \
      || die 'promotion changed preserved Secret/PVC metadata'
    log "controlled promotion completed: pod=$PROMOTION_POD image=$FROZEN_IMAGE apply=$PROMOTION_APPLY"
    exit 0
  fi

  CURRENT_MANIFEST="$TMP_DIR/sectors-current-manifest.yaml"
  DESIRED_MANIFEST="$TMP_DIR/sectors-desired-manifest.yaml"
  LIVE_BEFORE_MANIFEST="$TMP_DIR/sectors-live-before.yaml"
  LIVE_AFTER_MANIFEST="$TMP_DIR/sectors-live-after.yaml"
  POST_MANIFEST="$TMP_DIR/sectors-post-manifest.yaml"
  helm get manifest "$RELEASE_NAME" --namespace "$NAMESPACE" > "$CURRENT_MANIFEST"
  if [[ "$OPERATION" == enable-sectors-config ]]; then
    CONFIG_FROM=0
    CONFIG_TO=1
    CONFIG_VALUES="$SECTORS_ENABLED_VALUES_FILE"
    CONFIG_RENDER="$REVIEWED_ENABLED_RENDER"
    CONFIG_RENDER_SHA256="$REVIEWED_ENABLED_RENDER_SHA256"
  else
    CONFIG_FROM=1
    CONFIG_TO=0
    CONFIG_VALUES="$SECTORS_OFF_VALUES_FILE"
    CONFIG_RENDER="$REVIEWED_OFF_RENDER"
    CONFIG_RENDER_SHA256="$REVIEWED_OFF_RENDER_SHA256"
  fi
  printf '%s\n' "$CONFIG_RENDER" > "$DESIRED_MANIFEST"
  python3 "$PACKET_VALIDATOR" compare-sectors-config-only \
    --current "$CURRENT_MANIFEST" --desired "$DESIRED_MANIFEST" \
    --release-name "$RELEASE_NAME" --namespace "$NAMESPACE" \
    --image "$FROZEN_IMAGE" --from-enabled "$CONFIG_FROM" --to-enabled "$CONFIG_TO"
  kubectl get deployment,service,cronjob --namespace "$NAMESPACE" \
    -l "app.kubernetes.io/instance=$RELEASE_NAME" -o yaml > "$LIVE_BEFORE_MANIFEST"
  python3 "$PACKET_VALIDATOR" compare-live-desired \
    --release-name "$RELEASE_NAME" --namespace "$NAMESPACE" \
    --desired "$CURRENT_MANIFEST" < "$LIVE_BEFORE_MANIFEST"
  select_runtime_sectors_pod "$CONFIG_FROM" >/dev/null \
    || die "$OPERATION live Pod does not match the expected pre-rollout sectors state"

  assert_clean_worktree
  PRE_WRITE_RENDER="$(render_release_packet "$OPERATION_CHART_DIR" "$CONFIG_VALUES" "" "$TARGET_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" \
    --set "image.repository=$FROZEN_IMAGE_REPOSITORY" --set "image.tag=$FROZEN_IMAGE_TAG")" \
    || die "$OPERATION frozen packet failed immediately before Helm write"
  [[ "$(sha256_text "$PRE_WRITE_RENDER")" == "$CONFIG_RENDER_SHA256" ]] \
    || die "$OPERATION frozen packet hash drifted immediately before Helm write"
  verify_generic_deploy_precondition
  log "applying hook-free same-image sectors config: $CONFIG_FROM -> $CONFIG_TO"
  helm upgrade "$RELEASE_NAME" "$OPERATION_CHART_DIR" \
    --namespace "$NAMESPACE" \
    --values "$CONFIG_VALUES" \
    --set "image.repository=$FROZEN_IMAGE_REPOSITORY" \
    --set "image.tag=$FROZEN_IMAGE_TAG" \
    --set component=all \
    --no-hooks \
    --atomic \
    --wait \
    --timeout "$HELM_TIMEOUT"
  DEPLOYMENT_NAME="$(kubectl -n "$NAMESPACE" get deployment \
    -l "app.kubernetes.io/instance=$RELEASE_NAME" \
    -o jsonpath='{.items[0].metadata.name}')"
  [[ -n "$DEPLOYMENT_NAME" ]] || die "$OPERATION postcondition found no Dashboard Deployment"
  kubectl -n "$NAMESPACE" rollout status "deployment/$DEPLOYMENT_NAME" --timeout=180s
  helm get manifest "$RELEASE_NAME" --namespace "$NAMESPACE" > "$POST_MANIFEST"
  python3 "$PACKET_VALIDATOR" compare-release-exact \
    --current "$POST_MANIFEST" --desired "$DESIRED_MANIFEST"
  kubectl get deployment,service,cronjob --namespace "$NAMESPACE" \
    -l "app.kubernetes.io/instance=$RELEASE_NAME" -o yaml > "$LIVE_AFTER_MANIFEST"
  python3 "$PACKET_VALIDATOR" compare-live-desired \
    --release-name "$RELEASE_NAME" --namespace "$NAMESPACE" \
    --desired "$DESIRED_MANIFEST" < "$LIVE_AFTER_MANIFEST"
  verify_frozen_runtime_image "$FROZEN_IMAGE_REPOSITORY" "$FROZEN_IMAGE_TAG" "$FROZEN_IMAGE_DIGEST" \
    || die "$OPERATION postcondition could not prove the frozen runtime image"
  select_runtime_sectors_pod "$CONFIG_TO" >/dev/null \
    || die "$OPERATION postcondition Pod has the wrong sectors state"
  require_all_application_cronjobs_absent "$OPERATION postcondition" \
    || die "$OPERATION postcondition could not prove both application CronJobs absent"
  require_namespace_jobs_absent "$OPERATION postcondition" \
    || die "$OPERATION postcondition requires namespace Jobs absent"
  PRESERVED_IDENTITIES_AFTER="$(capture_preserved_resource_identities "$CONFIG_RENDER")" \
    || die "$OPERATION postcondition could not capture Secret/PVC metadata"
  [[ "$PRESERVED_IDENTITIES_AFTER" == "$PRESERVED_IDENTITIES_BEFORE" ]] \
    || die "$OPERATION changed preserved Secret/PVC metadata"
  log "same-image sectors config completed: $CONFIG_FROM -> $CONFIG_TO image=$FROZEN_IMAGE"
  exit 0
fi

if [[ "$OPERATION" == deploy ]]; then
VALUES_FILE="$TMP_DIR/values.yaml"
if [[ -z "$HELM_VALUES_FILE" ]]; then
  {
  printf 'replicaCount: 1\n'
  printf 'image:\n'
  printf '  repository: "%s"\n' "$IMAGE_REPOSITORY"
  printf '  tag: "%s"\n' "$IMAGE_TAG"
  printf '  pullPolicy: IfNotPresent\n'
  printf 'ingress:\n'
  printf '  enabled: true\n'
  printf '  className: "%s"\n' "$INGRESS_CLASS"
  printf '  host: "%s"\n' "$INGRESS_HOST"
  printf '  path: /\n'
  printf '  pathType: Prefix\n'
  printf '  annotations:\n'
  printf '    traefik.ingress.kubernetes.io/router.entrypoints: web\n'
  printf 'persistence:\n'
  printf '  enabled: true\n'
  printf '  storageClass: "%s"\n' "$STORAGE_CLASS"
  printf '  size: 2Gi\n'
  printf '  keep: true\n'
  printf 'database:\n'
  printf '  enabled: true\n'
  printf '  existingSecret: "%s"\n' "$POSTGRES_SECRET_NAME"
  printf '  persistence:\n'
  printf '    enabled: true\n'
  printf '    storageClass: "%s"\n' "$STORAGE_CLASS"
  printf '    size: 5Gi\n'
  printf '    keep: true\n'
  printf 'marketEnvironment:\n'
  printf '  timezone: Asia/Shanghai\n'
  printf '  persistentCache: true\n'
  printf '  settlementTime: "15:10"\n'
  if [[ "$DISABLE_MANUAL_REFRESH" == true ]]; then
    printf 'extraEnv:\n'
    printf '  - name: MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED\n'
    printf '    value: "0"\n'
  fi
  } > "$VALUES_FILE"
else
  cp "$OPERATION_BASELINE_VALUES" "$VALUES_FILE"
fi

RENDERED_PACKET="$(render_release_packet "$OPERATION_CHART_DIR" "$VALUES_FILE" "" "$TARGET_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" --set "image.repository=$DEPLOY_IMAGE_REPOSITORY" --set "image.tag=$DEPLOY_IMAGE_TAG" --set "component=$COMPONENT_NAME")"
require_render_has_no_cronjob 'ordinary deployment render' "$RENDERED_PACKET" \
  || die 'ordinary deployment render contains a retired CronJob'
GENERIC_RENDER_SHA256="$(sha256_text "$RENDERED_PACKET")"
if ! PRE_WRITE_RENDER="$(render_release_packet "$OPERATION_CHART_DIR" "$VALUES_FILE" "" "$TARGET_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" --set "image.repository=$DEPLOY_IMAGE_REPOSITORY" --set "image.tag=$DEPLOY_IMAGE_TAG" --set "component=$COMPONENT_NAME")"; then
  die 'frozen generic release packet failed immediately before helm write'
fi
if [[ "$(sha256_text "$PRE_WRITE_RENDER")" != "$GENERIC_RENDER_SHA256" ]]; then
  die 'frozen generic release packet drifted before helm write'
fi
require_render_has_no_cronjob 'frozen generic release packet' "$PRE_WRITE_RENDER" \
  || die "frozen generic release packet contains a retired CronJob ($COMPONENT_NAME)"

if [[ "$COMPONENT_NAME" == "database" ]]; then
  log "component=database: skipping image build/smoke/save/scp/import; PVC contract is verified by the rendered packet only"
else
  log "building $IMAGE"
  helm lint --strict "$OPERATION_CHART_DIR"
  podman build \
    --platform "$BUILD_PLATFORM" \
    --format docker \
    --tag "$IMAGE" \
    "$REPO_DIR"

  log 'running local health smoke test'
  podman rm -f "$SMOKE_NAME" >/dev/null 2>&1 || true
  podman run --rm --detach \
    --name "$SMOKE_NAME" \
    --publish 18000:8000 \
    --env MARKET_ENVIRONMENT_DATABASE_URL=postgresql+psycopg://smoke:smoke@127.0.0.1:1/smoke \
    "$IMAGE" >/dev/null
  SMOKE_CREATED=true
  curl --fail --show-error --silent \
    --retry 15 --retry-all-errors --retry-connrefused --retry-delay 2 \
    http://127.0.0.1:18000/api/health >/dev/null
  curl --fail --show-error --silent \
    --retry 5 --retry-all-errors --retry-connrefused --retry-delay 1 \
    http://127.0.0.1:18000/ >/dev/null
  podman stop "$SMOKE_NAME" >/dev/null
  SMOKE_CREATED=false

  IMAGE_SIZE_RAW="$(podman image inspect --format '{{.Size}}' "$IMAGE")"
  [[ "$IMAGE_SIZE_RAW" =~ ^[1-9][0-9]{0,17}$ ]] \
    || die "could not determine a positive local image size for $IMAGE"
  IMAGE_SIZE_BYTES=$((10#$IMAGE_SIZE_RAW))
  ARCHIVE_REQUIRED_BYTES="$(archive_required_bytes "$IMAGE_SIZE_BYTES")"
  ARCHIVE_TMP_ROOT="$(select_archive_temp_root "$ARCHIVE_REQUIRED_BYTES")"
  ARCHIVE_TMP_DIR="$(mktemp -d -p "$ARCHIVE_TMP_ROOT" a-stock-deploy-image.XXXXXX)" \
    || die "failed to create image archive temp directory under $ARCHIVE_TMP_ROOT"
  ARCHIVE_AVAILABLE_BYTES="$(filesystem_available_bytes "$ARCHIVE_TMP_DIR")"
  [[ "$ARCHIVE_AVAILABLE_BYTES" =~ ^[0-9]+$ ]] \
    || die "failed to confirm available bytes for image archive workspace: $ARCHIVE_TMP_DIR"
  if ((ARCHIVE_AVAILABLE_BYTES < ARCHIVE_REQUIRED_BYTES)); then
    die "image archive workspace dropped below the required $(bytes_to_mib_ceil "$ARCHIVE_REQUIRED_BYTES") MiB before export"
  fi
  log "image archive workspace: root=$ARCHIVE_TMP_ROOT available=$(bytes_to_mib_ceil "$ARCHIVE_AVAILABLE_BYTES")MiB required=$(bytes_to_mib_ceil "$ARCHIVE_REQUIRED_BYTES")MiB"

  ARCHIVE_PATH="$ARCHIVE_TMP_DIR/$ARCHIVE_NAME"
  CHECKSUM_PATH="${ARCHIVE_PATH}.sha256"
  log "exporting $ARCHIVE_NAME"
  podman save --format docker-archive --output "$ARCHIVE_PATH" "$IMAGE"
  (
    cd "$ARCHIVE_TMP_DIR"
    sha256sum "$ARCHIVE_NAME" > "${ARCHIVE_NAME}.sha256"
  )
  ARCHIVE_SHA256="$(awk '{print $1}' "$CHECKSUM_PATH")"
  [[ "$ARCHIVE_SHA256" =~ ^[0-9a-f]{64}$ ]] \
    || die "could not determine the archive SHA-256 for $ARCHIVE_NAME"

  log "copying archive to $SSH_TARGET:$REMOTE_IMAGE_DIR"
  scp -P "$TRUENAS_SSH_PORT" "$ARCHIVE_PATH" "$CHECKSUM_PATH" \
    "$SSH_TARGET:$REMOTE_IMAGE_DIR/"
  rm -rf -- "$ARCHIVE_TMP_DIR"
  ARCHIVE_TMP_DIR=''

  log 'verifying and importing the image into k3s containerd'
  remote "set -eu
cd '$REMOTE_IMAGE_DIR'
sha256sum --check '$ARCHIVE_NAME.sha256'
sudo -n k3s ctr --namespace k8s.io images import '$ARCHIVE_NAME'
sudo -n k3s ctr --namespace k8s.io images list | grep -F -- '$IMAGE' >/dev/null
"
  if [[ "$GENERIC_IMMUTABLE_IMAGE_REQUIRED" == true ]]; then
    DISCOVERED_IMAGE_DIGEST="$(capture_containerd_image_digest "$IMAGE")" \
      || die 'generic all/service deploy could not resolve one exact containerd manifest digest after import'
    if [[ -n "$FROZEN_IMAGE_DIGEST" && "$FROZEN_IMAGE_DIGEST" != "$DISCOVERED_IMAGE_DIGEST" ]]; then
      die "generic all/service imported image digest drift: expected $FROZEN_IMAGE_DIGEST, got $DISCOVERED_IMAGE_DIGEST"
    fi
    FROZEN_IMAGE_REPOSITORY="$IMAGE_REPOSITORY"
    FROZEN_IMAGE_TAG="$IMAGE_TAG"
    FROZEN_IMAGE_DIGEST="$DISCOVERED_IMAGE_DIGEST"
    log "generic all/service image frozen: reviewedHead=$REVIEWED_GIT_HEAD archiveSha256=$ARCHIVE_SHA256 image=$IMAGE manifestDigest=$FROZEN_IMAGE_DIGEST"
  fi
  if [[ "$CONTROLLED_SECTORS_OPERATION" == stage-sectors-off ]]; then
    DISCOVERED_IMAGE_DIGEST="$(capture_containerd_image_digest "$IMAGE")" \
      || die 'stage-sectors-off could not resolve one exact containerd manifest digest after import'
    if [[ -n "$FROZEN_IMAGE_DIGEST" && "$FROZEN_IMAGE_DIGEST" != "$DISCOVERED_IMAGE_DIGEST" ]]; then
      die "stage-sectors-off imported image digest drift: expected $FROZEN_IMAGE_DIGEST, got $DISCOVERED_IMAGE_DIGEST"
    fi
    FROZEN_IMAGE_DIGEST="$DISCOVERED_IMAGE_DIGEST"
    log "stage-sectors-off froze imported image identity: $IMAGE@$FROZEN_IMAGE_DIGEST"
  fi
fi

verify_generic_deploy_precondition
require_namespace_jobs_absent 'ordinary deployment immediate pre-write' \
  || die 'ordinary deployment requires namespace Jobs absent immediately before the first Helm write'
if ! PRE_WRITE_RENDER="$(render_release_packet "$OPERATION_CHART_DIR" "$VALUES_FILE" "" "$TARGET_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" --set "image.repository=$DEPLOY_IMAGE_REPOSITORY" --set "image.tag=$DEPLOY_IMAGE_TAG" "${EARLY_RENDER_ARGS[@]}" "${COMPONENT_RENDER_ARGS[@]}")"; then
  die 'frozen generic release packet failed immediately before helm write'
fi
if [[ "$(sha256_text "$PRE_WRITE_RENDER")" != "$GENERIC_RENDER_SHA256" ]]; then
  die 'frozen generic release packet drifted before helm write'
fi
require_render_has_no_cronjob 'immediate pre-write release packet' "$PRE_WRITE_RENDER" \
  || die "frozen generic release packet contains a retired CronJob ($COMPONENT_NAME)"

HELM_VALUES_ARGS=(--values "$VALUES_FILE")

log "staged component deployment: order=database->service component=$COMPONENT_NAME release=$RELEASE_NAME namespace=$NAMESPACE"
COMPLETED_COMPONENTS=""
FAILED_COMPONENT=""
FAILED_REASON=""

deploy_step_or_exit() {
  local step_name="$1"
  local image_repo="$2"
  local image_tag="$3"
  local step_exit=0
  if [[ "$step_name" != database ]] && ! verify_component_prerequisites "$step_name"; then
    FAILED_COMPONENT="$step_name"
    FAILED_REASON="${step_name}_prerequisite_failed"
    log "component step: name=$step_name phase=failed reason=$FAILED_REASON retryTarget=--component $step_name"
    log "staged component deployment: status=partial order=database->service completed=$COMPLETED_COMPONENTS failed=$FAILED_COMPONENT reason=$FAILED_REASON retryTarget=--component $step_name"
    exit 1
  fi
  deploy_component_step "$step_name" "$image_repo" "$image_tag" || step_exit=$?
  if (( step_exit != 0 )); then
    FAILED_COMPONENT="$step_name"
    FAILED_REASON="${step_name}_phase_rejected"
    log "staged component deployment: failed at component=$FAILED_COMPONENT reason=$FAILED_REASON exitCode=$step_exit retryTarget=--component $FAILED_COMPONENT"
    exit "$step_exit"
  fi
}

if [[ "$COMPONENT_NAME" == "all" ]]; then
  deploy_step_or_exit database "$IMAGE_REPOSITORY" "$IMAGE_TAG"
  COMPLETED_COMPONENTS+=" database"
  deploy_step_or_exit service "$IMAGE_REPOSITORY" "$IMAGE_TAG"
  COMPLETED_COMPONENTS+=" service"

  # Component writes are intentionally staged, but the Helm release must end
  # with one complete stored manifest so future upgrades cannot inherit a
  # service-only or database-only release state.
  log 'component=all consolidating complete Helm release manifest'
  verify_generic_deploy_precondition
  require_namespace_jobs_absent 'component=all final convergence precondition' \
    || die 'component=all requires namespace Jobs absent before hook-free final convergence'
  FULL_PACKET="$(render_release_packet "$OPERATION_CHART_DIR" "$VALUES_FILE" "" "$TARGET_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" \
    --set "image.repository=$DEPLOY_IMAGE_REPOSITORY" --set "image.tag=$DEPLOY_IMAGE_TAG" --set component=all)" \
    || die 'component=all complete release packet render failed'
  [[ "$(sha256_text "$FULL_PACKET")" == "$GENERIC_RENDER_SHA256" ]] \
    || die 'component=all complete release packet drifted from preflight'
  require_render_has_no_cronjob 'component=all complete release packet' "$FULL_PACKET" \
    || die 'component=all complete release packet contains a retired CronJob'
  if [[ "$GENERIC_IMMUTABLE_IMAGE_REQUIRED" == true ]]; then
    verify_exact_containerd_image_digest "$DEPLOY_IMAGE_REPOSITORY:$DEPLOY_IMAGE_TAG" "$FROZEN_IMAGE_DIGEST" \
      || die 'component=all complete release containerd manifest digest drifted before Helm write'
  fi
  log 'component=all final Helm write: hookMode=disabled reason=full-release-convergence'
  helm upgrade --install "$RELEASE_NAME" "$OPERATION_CHART_DIR" \
    --namespace "$NAMESPACE" \
    --create-namespace \
    "${HELM_VALUES_ARGS[@]}" \
    --set "image.repository=$DEPLOY_IMAGE_REPOSITORY" \
    --set "image.tag=$DEPLOY_IMAGE_TAG" \
    --set component=all \
    --no-hooks \
    --atomic \
    --wait \
    --timeout "$HELM_TIMEOUT"
  require_namespace_jobs_absent 'component=all final convergence postcondition' \
    || die 'component=all final convergence left a namespace Job behind'
  FULL_POST_RENDER="$(render_release_packet "$OPERATION_CHART_DIR" "$VALUES_FILE" "" "$TARGET_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" \
    --set "image.repository=$DEPLOY_IMAGE_REPOSITORY" --set "image.tag=$DEPLOY_IMAGE_TAG" --set component=all)" \
    || die 'component=all complete post-write render failed'
  verify_rendered_component_contract "$FULL_POST_RENDER" "$DEPLOY_IMAGE_REPOSITORY" "$DEPLOY_IMAGE_TAG" \
    || die 'component=all complete release contract failed'
  if ! printf '%s\n' "$FULL_POST_RENDER" | python3 -c '
import sys, yaml
items = [item for item in yaml.safe_load_all(sys.stdin) if item]
deployments = [item for item in items if item.get("kind") == "Deployment"]
statefulsets = [item for item in items if item.get("kind") == "StatefulSet" and (item.get("metadata") or {}).get("name", "").endswith("-postgresql")]
services = [item for item in items if item.get("kind") == "Service"]
postgres_services = [item for item in services if (item.get("metadata") or {}).get("name", "").endswith("-postgresql")]
dashboard_services = [item for item in services if not (item.get("metadata") or {}).get("name", "").endswith("-postgresql")]
pvcs = [item for item in items if item.get("kind") == "PersistentVolumeClaim" and (item.get("metadata") or {}).get("name", "").endswith("-postgresql-data")]
jobs = [item for item in items if item.get("kind") == "Job"]
expected_schema_job = (statefulsets[0].get("metadata") or {}).get("name", "").removesuffix("-postgresql") + "-schema-migration" if len(statefulsets) == 1 else ""
if len(deployments) != 1 or len(statefulsets) != 1 or len(postgres_services) != 1 or len(dashboard_services) != 1 or len(pvcs) != 1 or len(jobs) != 1 or (jobs[0].get("metadata") or {}).get("name") != expected_schema_job:
    raise SystemExit("complete release must render database and service resources exactly once")
'; then
    die 'component=all complete service contract failed'
  fi
  DEPLOYMENT_NAME="$(kubectl -n "$NAMESPACE" get deployment \
    -l "app.kubernetes.io/instance=$RELEASE_NAME" \
    -o jsonpath='{.items[0].metadata.name}')"
  [[ -n "$DEPLOYMENT_NAME" ]] || die 'component=all complete release deployment is missing'
  kubectl -n "$NAMESPACE" rollout status "deployment/$DEPLOYMENT_NAME" --timeout=180s \
    || die 'component=all complete release rollout failed'
  if [[ "$GENERIC_IMMUTABLE_IMAGE_REQUIRED" == true ]]; then
    verify_frozen_runtime_image "$DEPLOY_IMAGE_REPOSITORY" "$DEPLOY_IMAGE_TAG" "$FROZEN_IMAGE_DIGEST" \
      || die 'component=all complete release could not prove the frozen runtime image'
  fi
  log 'component=all complete Helm release manifest consolidated'
fi

if [[ "$COMPONENT_NAME" == "database" ]]; then
  deploy_step_or_exit database "$IMAGE_REPOSITORY" "$IMAGE_TAG"
  COMPLETED_COMPONENTS+=" database"
fi

if [[ "$COMPONENT_NAME" == "service" ]]; then
  deploy_step_or_exit service "$IMAGE_REPOSITORY" "$IMAGE_TAG"
  COMPLETED_COMPONENTS+=" service"
fi

if [[ -n "$FAILED_COMPONENT" ]]; then
  log "staged component deployment: status=partial order=database->service completed=$COMPLETED_COMPONENTS failed=$FAILED_COMPONENT reason=$FAILED_REASON"
  exit 1
fi

verify_generic_deploy_precondition
require_namespace_jobs_absent 'ordinary deployment successful postcondition' \
  || die 'ordinary deployment completed without proving namespace Jobs absent'

if [[ "$CONTROLLED_SECTORS_OPERATION" == stage-sectors-off ]]; then
  STAGE_POST_MANIFEST="$TMP_DIR/sectors-stage-post-manifest.yaml"
  STAGE_LIVE_MANIFEST="$TMP_DIR/sectors-stage-live.yaml"
  helm get manifest "$RELEASE_NAME" --namespace "$NAMESPACE" > "$STAGE_POST_MANIFEST"
  python3 "$PACKET_VALIDATOR" compare-release-exact \
    --current "$STAGE_POST_MANIFEST" \
    --desired <(printf '%s\n' "$REVIEWED_OFF_RENDER")
  kubectl get deployment,service,cronjob --namespace "$NAMESPACE" \
    -l "app.kubernetes.io/instance=$RELEASE_NAME" -o yaml > "$STAGE_LIVE_MANIFEST"
  python3 "$PACKET_VALIDATOR" compare-live-desired \
    --release-name "$RELEASE_NAME" --namespace "$NAMESPACE" \
    --desired <(printf '%s\n' "$REVIEWED_OFF_RENDER") < "$STAGE_LIVE_MANIFEST"
  verify_frozen_runtime_image "$FROZEN_IMAGE_REPOSITORY" "$FROZEN_IMAGE_TAG" "$FROZEN_IMAGE_DIGEST" \
    || die 'stage-sectors-off postcondition could not prove the frozen runtime image'
  select_runtime_sectors_pod 0 >/dev/null \
    || die 'stage-sectors-off postcondition requires one exact Ready sectors-off Pod'
  require_all_application_cronjobs_absent 'stage-sectors-off postcondition' \
    || die 'stage-sectors-off postcondition could not prove both application CronJobs absent'
  require_namespace_jobs_absent 'stage-sectors-off postcondition' \
    || die 'stage-sectors-off postcondition requires namespace Jobs absent'
  PRESERVED_IDENTITIES_AFTER="$(capture_preserved_resource_identities "$REVIEWED_OFF_RENDER")" \
    || die 'stage-sectors-off postcondition could not capture Secret/PVC metadata'
  [[ "$PRESERVED_IDENTITIES_AFTER" == "$PRESERVED_IDENTITIES_BEFORE" ]] \
    || die 'stage-sectors-off changed preserved Secret/PVC metadata'
fi


log "staged component deployment: status=completed order=database->service completed=$COMPLETED_COMPONENTS release=$RELEASE_NAME namespace=$NAMESPACE"
log "internal URL: http://${TRUENAS_HOST}:${TRUENAS_INGRESS_PORT}/"
log "Tailscale URL after NGINX is configured: https://${TAILSCALE_HOST}:${TAILSCALE_PORT}/"
if [[ "$GENERIC_IMMUTABLE_IMAGE_REQUIRED" == true ]]; then
  log "component summary: order=database->service status=completed component=$COMPONENT_NAME packetDigest=$GENERIC_RENDER_SHA256 release=$RELEASE_NAME namespace=$NAMESPACE reviewedHead=$REVIEWED_GIT_HEAD archiveSha256=$ARCHIVE_SHA256 image=$IMAGE manifestDigest=$FROZEN_IMAGE_DIGEST"
else
  log "component summary: order=database->service status=completed component=$COMPONENT_NAME packetDigest=$GENERIC_RENDER_SHA256 release=$RELEASE_NAME namespace=$NAMESPACE image=$IMAGE"
fi
exit 0
fi

if [[ -z "$HELM_VALUES_FILE" ]]; then
  if [[ -z "${STORAGE_CLASS:-}" ]]; then
    STORAGE_CLASS="$(kubectl get storageclass -o jsonpath='{range .items[*]}{.metadata.annotations.storageclass\.kubernetes\.io/is-default-class}{"|"}{.metadata.name}{"\n"}{end}' | awk -F'|' '$1 == "true" { print $2; exit }')"
  fi
  [[ -n "${STORAGE_CLASS:-}" ]] || die 'STORAGE_CLASS is empty and no default StorageClass was found'
  kubectl get storageclass "$STORAGE_CLASS" >/dev/null
  kubectl get ingressclass "$INGRESS_CLASS" >/dev/null
  kubectl -n kube-system get svc traefik >/dev/null
  TRAEFIK_PORTS="$(kubectl -n kube-system get svc traefik -o jsonpath='{range .spec.ports[*]}{.name}{"="}{.port}{"/"}{.nodePort}{" "}{end}')"
  log "node=$NODE_ARCH storageClass=$STORAGE_CLASS ingressClass=$INGRESS_CLASS traefik=$TRAEFIK_PORTS"
else
  log "node=$NODE_ARCH helmValues=$HELM_VALUES_FILE"
fi
