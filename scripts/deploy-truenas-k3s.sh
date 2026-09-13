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

usage() {
  cat <<'USAGE'
Usage: bash scripts/deploy-truenas-k3s.sh [--env-file PATH]
                                    [--component {all,database,service,schedule}]

Component selection (default: all):
  all       - render and apply every supported resource (legacy one-click)
  database  - render and verify only the reviewed RWO PVC contract
  service   - render and apply the Dashboard Deployment/Service/Ingress
  schedule  - render or apply only the scheduled-collection resource

Scheduling-only modes never build, copy, import, upgrade, create a Job, or
change CronJob suspension:
  --offline-render --baseline-values PATH --scheduling-overlay PATH --kube-version VERSION
  --read-only-discovery
  --server-dry-run --baseline-values PATH --scheduling-overlay PATH --kube-version VERSION

Explicit scheduling write modes never build, copy, import, or retag an image:
  --release-suspended --baseline-values PATH --scheduling-overlay PATH --kube-version VERSION
  --activate-schedule --baseline-values PATH --scheduling-overlay PATH --kube-version VERSION
  --disable-schedule --baseline-values PATH --scheduling-overlay PATH --kube-version VERSION

All renders accept --release-name NAME and --namespace NAME. Target modes bind
these values and --kube-version to live discovery before any write.

The command must run on the 1.21 Linux VM. It builds the image from the
repository, smoke-tests it, copies an archive to TrueNAS 1.20, imports it into
k3s/containerd, and installs/upgrades the Helm release.
USAGE
}

VALID_COMPONENTS=("all" "database" "service" "schedule")
COMPONENT_NAME="all"
COMPONENT_SELECTED=false
COMPONENT_BASELINE_FILE="${COMPONENT_BASELINE_FILE:-tests/fixtures/truenas_component_baseline.yaml}"
COMPONENT_BASELINE_RELEASE=""
COMPONENT_BASELINE_NAMESPACE=""
COMPONENT_BASELINE_CLAIM=""
COMPONENT_BASELINE_STORAGE=""
COMPONENT_BASELINE_ACCESS_MODES=""
COMPONENT_BASELINE_SNAPSHOT_PATH=""
COMPONENT_BASELINE_TOPOLOGY_REPLICAS=1
COMPONENT_BASELINE_TOPOLOGY_READONLY=true
COMPONENT_BASELINE_IMAGE_REPOSITORY=""
COMPONENT_BASELINE_IMAGE_TAG_PATTERN=""

ENV_FILE="${DEPLOY_ENV_FILE:-/home/gyt/a-stock/deploy/truenas/deploy.env}"
OPERATION=deploy
OPERATION_SELECTED=false
BASELINE_VALUES_FILE=''
SCHEDULING_OVERLAY_FILE=''
TARGET_KUBERNETES_VERSION=''
CLI_RELEASE_NAME=''
CLI_NAMESPACE=''

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
    --offline-render)
      set_operation offline-render
      shift
      ;;
    --read-only-discovery)
      set_operation read-only-discovery
      shift
      ;;
    --server-dry-run)
      set_operation server-dry-run
      shift
      ;;
    --release-suspended)
      set_operation release-suspended
      shift
      ;;
    --activate-schedule)
      set_operation activate-schedule
      shift
      ;;
    --disable-schedule)
      set_operation disable-schedule
      shift
      ;;
    --baseline-values)
      (($# >= 2)) || die '--baseline-values requires a path'
      BASELINE_VALUES_FILE="$2"
      shift 2
      ;;
    --scheduling-overlay)
      (($# >= 2)) || die '--scheduling-overlay requires a path'
      SCHEDULING_OVERLAY_FILE="$2"
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
    --component)
      (($# >= 2)) || die '--component requires one of all, database, service, schedule'
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

render_scheduling_packet() {
  local chart_dir="$1"
  local baseline_values="$2"
  local scheduling_overlay="$3"
  local kube_version="$4"
  local release_name="$5"
  local namespace="$6"
  shift 6
  local values_args=()

  if [[ -n "$baseline_values" ]]; then
    values_args+=(--values "$baseline_values")
  fi
  if [[ -n "$scheduling_overlay" ]]; then
    values_args+=(--values "$scheduling_overlay")
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
release = data.get("release") or {}
persistence = data.get("persistence") or {}
image = data.get("image") or {}
topology = data.get("topology") or {}
required_release = ("name", "namespace", "chart")
for key in required_release:
    if not release.get(key):
        raise SystemExit("component baseline fixture is missing release." + key)
required_persistence = ("claimName", "storageClass", "accessModes", "size", "mountPath", "snapshotPath")
for key in required_persistence:
    if not persistence.get(key):
        raise SystemExit("component baseline fixture is missing persistence." + key)
required_image = ("repository", "tagPattern")
for key in required_image:
    if not image.get(key):
        raise SystemExit("component baseline fixture is missing image." + key)
print(release.get("name", ""))
print(release.get("namespace", ""))
print(persistence.get("claimName", ""))
print(str(persistence.get("size", "")))
print(",".join(persistence.get("accessModes") or []))
print(persistence.get("snapshotPath", ""))
print(str(topology.get("replicaCount", 1)))
print("1" if topology.get("readOnlyRootFilesystem") else "0")
print(image.get("repository", ""))
print(image.get("tagPattern", ""))
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
    schedule)
      printf '%s\n' '--set' 'component=schedule'
      ;;
    *)
      die "unsupported --component: $component"
      ;;
  esac
}

component_required_scheduling_state() {
  local component="$1"
  case "$component" in
    all|database|service)
      printf '%s\n' disabled
      ;;
    schedule)
      printf '%s\n' suspended
      ;;
    *)
      die "unsupported --component: $component"
      ;;
  esac
}

sha256_text() {
  printf '%s\n' "$1" | sha256sum | awk '{print $1}'
}

report_effective_trigger() {
  local inspection="$1"
  local state strategy controller_timezone schedule time_zone

  IFS=$'\t' read -r state strategy controller_timezone schedule time_zone < <(
    printf '%s\n' "$inspection" | python3 -c '
import json, sys
item = json.load(sys.stdin)
print("\t".join("-" if item.get(key) is None else str(item[key]) for key in ("state", "strategy", "controllerTimeZone", "schedule", "timeZone")))
'
  )
  if [[ "$state" == disabled ]]; then
    log 'scheduling packet: disabled; no CronJob is rendered'
    return
  fi

  if [[ "$strategy" == controller ]]; then
    log "scheduling packet: state=$state strategy=controller controllerTimeZone=$controller_timezone cron=$schedule effectiveShanghai=16:30 weekdays"
  else
    local minute hour day_of_month month day_of_week
    IFS=' ' read -r minute hour day_of_month month day_of_week <<< "$schedule"
    [[ "$minute" =~ ^[0-9]{1,2}$ && "$hour" =~ ^[0-9]{1,2}$ ]] || die 'rendered native schedule is malformed'
    [[ "$day_of_month" == '*' && "$month" == '*' && "$day_of_week" == '1-5' ]] || die 'rendered native schedule has an unsupported shape'
    log "scheduling packet: state=$state strategy=native timeZone=$time_zone cron=$schedule effectiveShanghai=$(printf '%02d:%02d' "$((10#$hour))" "$((10#$minute))") weekdays"
  fi
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

inspect_scheduling_packet() {
  local rendered="$1"
  local required_state="${2:-any}"
  local kube_version="$3"
  printf '%s\n' "$rendered" | python3 "$PACKET_VALIDATOR" inspect \
    --release-name "$RELEASE_NAME" \
    --namespace "$NAMESPACE" \
    --kube-version "$kube_version" \
    --require-state "$required_state"
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
  local payload
  [[ -n "$cronjob_name" ]] || return 1
  payload="$(kubectl get cronjob "$cronjob_name" --namespace "$NAMESPACE" \
    --ignore-not-found -o yaml)" || return 1
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

exact_cronjob_safety_state() {
  python3 -c '
import sys, yaml

items = [item for item in yaml.safe_load_all(sys.stdin) if item is not None]
if not items:
    print("absent")
    raise SystemExit(0)
if len(items) != 1 or not isinstance(items[0], dict):
    raise SystemExit("exact CronJob safety response must contain at most one object")
spec = items[0].get("spec")
if isinstance(spec, dict) and type(spec.get("suspend")) is bool and spec["suspend"] is True:
    print("suspended")
else:
    print("needs-suspend")
'
}

capture_live_cronjobs() {
  [[ -n "$GENERIC_CRONJOB_NAME" ]] || return 1
  capture_exact_cronjob "$GENERIC_CRONJOB_NAME"
}

resolve_generic_cronjob_name() {
  local kube_version="$1"
  local identity_render inspection name
  local identity_args=(
    --set 'persistence.enabled=true'
    --set 'marketEnvironment.timezone=Asia/Shanghai'
    --set 'marketEnvironment.settlementTime=15:10'
    --set 'marketEnvironment.scheduledCollection.enabled=true'
    --set 'marketEnvironment.scheduledCollection.suspend=true'
    --set 'marketEnvironment.scheduledCollection.controllerTimeZoneVerified=true'
    --set 'marketEnvironment.scheduledCollection.controllerCanaryVerified=false'
    --set 'marketEnvironment.scheduledCollection.timeZone=Asia/Shanghai'
  )
  if [[ "$kube_version" == 1.26.* ]]; then
    identity_args+=(
      --set 'marketEnvironment.scheduledCollection.timezoneStrategy=controller'
      --set 'marketEnvironment.scheduledCollection.controllerTimeZone=Etc/UTC'
      --set-string 'marketEnvironment.scheduledCollection.schedule=30 8 * * 1-5'
    )
  else
    identity_args+=(
      --set 'marketEnvironment.scheduledCollection.timezoneStrategy=native'
      --set-string 'marketEnvironment.scheduledCollection.schedule=30 16 * * 1-5'
    )
  fi
  identity_render="$(render_scheduling_packet \
    "$OPERATION_CHART_DIR" "$OPERATION_BASELINE_VALUES" "$OPERATION_SCHEDULING_OVERLAY" \
    "$kube_version" "$RELEASE_NAME" "$NAMESPACE" \
    "${EARLY_RENDER_ARGS[@]}" "${identity_args[@]}")" || return 1
  inspection="$(inspect_scheduling_packet "$identity_render" suspended "$kube_version")" || return 1
  name="$(printf '%s\n' "$inspection" | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')" || return 1
  [[ -n "$name" ]] || return 1
  printf '%s\n' "$name"
}

require_generic_schedule_disabled() {
  local source="$1"
  local manifests="$2"
  if ! inspect_scheduling_packet "$manifests" disabled "$TARGET_KUBERNETES_VERSION" >/dev/null; then
    die "generic deployment requires $source scheduling to be off/absent; run the reviewed --disable-schedule mode first"
  fi
}

verify_generic_deploy_precondition() {
  local presence stored_manifest live_cronjobs
  if ! presence="$(helm_release_presence)"; then
    die 'could not determine whether the target Helm release already exists'
  fi
  if [[ "$presence" == present ]]; then
    if ! stored_manifest="$(helm get manifest "$RELEASE_NAME" --namespace "$NAMESPACE")"; then
      die 'could not read the existing Helm release manifest'
    fi
    require_generic_schedule_disabled 'stored Helm release' "$stored_manifest"
  elif [[ "$presence" != absent ]]; then
    die "unexpected Helm release presence result: $presence"
  fi

  if ! live_cronjobs="$(capture_live_cronjobs)"; then
    die 'could not read live release CronJobs before generic deployment'
  fi
  require_generic_schedule_disabled 'live release' "$live_cronjobs"
  log 'generic deployment precondition: stored and live scheduling are off/absent'
}

verify_database_component() {
  local packet="$1"
  local has_pvc has_existing_claim
  has_pvc="$(printf '%s\n' "$packet" | python3 -c 'import sys, yaml
items=[i for i in yaml.safe_load_all(sys.stdin) if i is not None]
print("yes" if any(isinstance(i, dict) and i.get("kind") == "PersistentVolumeClaim" for i in items) else "no")')"
  has_existing_claim="$(printf '%s\n' "$packet" | python3 -c 'import sys, yaml
items=[i for i in yaml.safe_load_all(sys.stdin) if i is not None]
m=[i for i in items if isinstance(i, dict) and i.get("kind") == "PersistentVolumeClaim"]
print("yes" if m and any(i.get("spec", {}).get("claimName") for i in m) else "no")' || true)"
  if [[ "$has_pvc" == "yes" ]]; then
    log "component=database database verified: chart-managed PVC rendered"
    printf '%s\n' "$packet" | python3 -c '
import sys, yaml
items=[i for i in yaml.safe_load_all(sys.stdin) if i is not None]
m=[i for i in items if isinstance(i, dict) and i.get("kind") == "PersistentVolumeClaim"]
if not m:
    raise SystemExit("chart-managed PVC path did not render a PersistentVolumeClaim")
pvc = next((i for i in m if isinstance(i.get("spec"), dict)), m[0])
meta = pvc.get("metadata") or {}
spec = pvc.get("spec") or {}
if meta.get("name") != "'"$COMPONENT_BASELINE_CLAIM"'":
    raise SystemExit("database PVC name drift: expected '"$COMPONENT_BASELINE_CLAIM"' got " + str(meta.get("name")))
if meta.get("namespace") and meta.get("namespace") != "'"$COMPONENT_BASELINE_NAMESPACE"'":
    raise SystemExit("database PVC namespace drift: expected '"$COMPONENT_BASELINE_NAMESPACE"' got " + str(meta.get("namespace")))
modes = spec.get("accessModes") or []
if "'"$COMPONENT_BASELINE_ACCESS_MODES"'" not in ",".join(modes):
    raise SystemExit("database PVC accessModes drift: expected '"$COMPONENT_BASELINE_ACCESS_MODES"' got " + repr(modes))
storage = spec.get("resources", {}).get("requests", {}).get("storage")
if storage and storage != "'"$COMPONENT_BASELINE_STORAGE"'":
    raise SystemExit("database PVC storage drift: expected '"$COMPONENT_BASELINE_STORAGE"' got " + str(storage))
print("pvc_identity_ok")
' || return 1
    log "component=database database verified: PVC identity matches baseline fixture (name=$COMPONENT_BASELINE_CLAIM namespace=$COMPONENT_BASELINE_NAMESPACE storage=$COMPONENT_BASELINE_STORAGE accessModes=$COMPONENT_BASELINE_ACCESS_MODES)"
  else
    log "component=database database verified: existingClaim path (no PVC object rendered; verify reviewed existingClaim $COMPONENT_BASELINE_CLAIM is bound to namespace $COMPONENT_BASELINE_NAMESPACE with accessModes=$COMPONENT_BASELINE_ACCESS_MODES and storage=$COMPONENT_BASELINE_STORAGE)"
  fi
  return 0
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

verify_schedule_component() {
  local packet="$1"
  if ! printf '%s\n' "$packet" | python3 -c '
import sys, yaml
items = [i for i in yaml.safe_load_all(sys.stdin) if i is not None]
cronjobs = [i for i in items if isinstance(i, dict) and i.get("kind") == "CronJob"]
assert len(cronjobs) == 1, "schedule component must render exactly one CronJob; got " + str(len(cronjobs))
spec = cronjobs[0].get("spec", {})
suspend_value = spec.get("suspend")
assert suspend_value is True, "schedule component must render suspended CronJob; got suspend=" + repr(suspend_value)
'; then
    return 1
  fi
  log "component=schedule verified: suspended CronJob rendered"
  return 0
}

deploy_helm_upgrade_with_component() {
  local component="$1"
  local image_repo="$2"
  local image_tag="$3"
  if ! render_scheduling_packet "$OPERATION_CHART_DIR" "$VALUES_FILE" "$OPERATION_SCHEDULING_OVERLAY" "$TARGET_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" \
        --set "image.repository=$image_repo" \
        --set "image.tag=$image_tag" \
        --set "component=$component" >/dev/null; then
    warn "frozen $component release packet failed to render before helm write"
    return 1
  fi
  HELM_VALUES_ARGS=(--values "$VALUES_FILE")
  if [[ -n "$OPERATION_SCHEDULING_OVERLAY" ]]; then
    HELM_VALUES_ARGS+=(--values "$OPERATION_SCHEDULING_OVERLAY")
  fi
  helm upgrade --install "$RELEASE_NAME" "$OPERATION_CHART_DIR" \
    --namespace "$NAMESPACE" \
    --create-namespace \
    "${HELM_VALUES_ARGS[@]}" \
    --set "image.repository=$image_repo" \
    --set "image.tag=$image_tag" \
    --set "component=$component" \
    --atomic \
    --wait \
    --timeout "$HELM_TIMEOUT"
}

deploy_component_step() {
  local component="$1"
  local image_repo="$2"
  local image_tag="$3"
  log "component step: name=$component phase=start release=$RELEASE_NAME namespace=$NAMESPACE image=$image_repo:$image_tag"
  local helm_exit=0
  deploy_helm_upgrade_with_component "$component" "$image_repo" "$image_tag" || helm_exit=$?
  if (( helm_exit != 0 )); then
    log "component step: name=$component phase=failed reason=helm_upgrade_rejected exitCode=$helm_exit retryTarget=--component $component"
    exit "$helm_exit"
  fi
  local post_render
  post_render="$(render_scheduling_packet "$OPERATION_CHART_DIR" "$VALUES_FILE" "$OPERATION_SCHEDULING_OVERLAY" "$TARGET_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" \
    --set "image.repository=$image_repo" --set "image.tag=$image_tag" --set "component=$component")" \
    || { log "component step: name=$component phase=failed reason=post_write_render_rejected"; exit 1; }
  case "$component" in
    database) verify_database_component "$post_render" || { log "component step: name=$component phase=failed reason=database_invariant_violated"; exit 1; } ;;
    service)
      verify_service_component "$post_render" || { log "component step: name=$component phase=failed reason=service_resource_invariant_violated"; return 1; }
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
      log "component step: name=$component phase=completed rollout=ready"
      ;;
    schedule)
      verify_schedule_component "$post_render" || { log "component step: name=$component phase=failed reason=schedule_invariant_violated"; exit 1; }
      log "component step: name=$component phase=completed cronjobState=suspended"
      ;;
  esac
  return 0
}

recover_generic_deploy_schedule() {
  local phase="$1"
  local live_cronjobs inspection state cronjob_name verified
  if ! live_cronjobs="$(capture_live_cronjobs)"; then
    warn "$phase: could not read live CronJobs; scheduling state is uncertain"
    return 1
  fi
  if ! inspection="$(inspect_scheduling_packet "$live_cronjobs" any "$TARGET_KUBERNETES_VERSION")"; then
    warn "$phase: live CronJobs could not be validated; scheduling state is uncertain"
    return 1
  fi
  state="$(printf '%s\n' "$inspection" | python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])')" || return 1
  if [[ "$state" == active ]]; then
    cronjob_name="$(printf '%s\n' "$inspection" | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')" || return 1
    warn "$phase: forcing $cronjob_name to suspend=true"
    if ! kubectl patch cronjob "$cronjob_name" --namespace "$NAMESPACE" \
      --type=merge --patch '{"spec":{"suspend":true}}'; then
      warn "$phase: emergency suspend command failed; checking the exact resource state"
    fi
    if ! live_cronjobs="$(capture_live_cronjobs)"; then
      warn "$phase: could not verify the emergency suspend; scheduling state is uncertain"
      return 1
    fi
    if ! verified="$(inspect_scheduling_packet "$live_cronjobs" suspended "$TARGET_KUBERNETES_VERSION")"; then
      warn "$phase: emergency suspend postcondition failed; scheduling state is uncertain"
      return 1
    fi
    state="$(printf '%s\n' "$verified" | python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])')" || return 1
  fi
  if [[ "$state" != disabled && "$state" != suspended ]]; then
    log "$phase: scheduling is uncertain (state=$state); Helm atomic rollback left no active CronJob to recover"
    return 0
  fi
  log "$phase: scheduling is $state"
}

ensure_cronjob_suspended_or_absent() {
  local phase="$1"
  local cronjob_name="$2"
  local live_cronjob state patch_succeeded=true
  if ! live_cronjob="$(capture_exact_cronjob "$cronjob_name")"; then
    warn "$phase: could not read exact CronJob $cronjob_name; scheduling state is uncertain"
    return 1
  fi
  if ! state="$(printf '%s\n' "$live_cronjob" | exact_cronjob_safety_state)"; then
    warn "$phase: exact CronJob $cronjob_name safety state could not be determined; scheduling state is uncertain"
    return 1
  fi
  if [[ "$state" == needs-suspend ]]; then
    warn "$phase: forcing $cronjob_name to suspend=true"
    if ! kubectl patch cronjob "$cronjob_name" --namespace "$NAMESPACE" \
      --type=merge --patch '{"spec":{"suspend":true}}'; then
      patch_succeeded=false
      warn "$phase: emergency suspend command failed; checking the exact resource state"
    fi
    if ! live_cronjob="$(capture_exact_cronjob "$cronjob_name")"; then
      warn "$phase: could not verify the emergency suspend; scheduling state is uncertain"
      return 1
    fi
    if ! state="$(printf '%s\n' "$live_cronjob" | exact_cronjob_safety_state)"; then
      warn "$phase: emergency suspend response safety state could not be determined; scheduling state is uncertain"
      return 1
    fi
    if [[ "$patch_succeeded" == false && ( "$state" == absent || "$state" == suspended ) ]]; then
      warn "$phase: emergency suspend command failed but exact readback proved $state"
    fi
  fi
  if [[ "$state" != absent && "$state" != suspended ]]; then
    warn "$phase: expected $cronjob_name to be absent or suspended, got $state; scheduling state is uncertain"
    return 1
  fi
  log "$phase: exact CronJob $cronjob_name is $state"
}

require_exact_cronjob_absent() {
  local phase="$1"
  local cronjob_name="$2"
  local live_cronjob state
  if ! live_cronjob="$(capture_exact_cronjob "$cronjob_name")"; then
    warn "$phase: could not read exact CronJob $cronjob_name; deletion is unproven"
    return 1
  fi
  if ! state="$(printf '%s\n' "$live_cronjob" | exact_cronjob_safety_state)"; then
    warn "$phase: exact CronJob $cronjob_name state could not be determined; deletion is unproven"
    return 1
  fi
  if [[ "$state" != absent ]]; then
    warn "$phase: exact CronJob $cronjob_name still exists; deletion is unproven"
    return 1
  fi
  log "$phase: exact CronJob $cronjob_name is absent"
}

if [[ "$OPERATION" == offline-render ]]; then
  REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  CHART_DIR="$REPO_DIR/deploy/helm/a-stock"
  PACKET_VALIDATOR="$REPO_DIR/scripts/validate-scheduling-packet.py"
  RELEASE_NAME="${CLI_RELEASE_NAME:-a-stock}"
  NAMESPACE="${CLI_NAMESPACE:-a-stock}"
  [[ -n "$BASELINE_VALUES_FILE" ]] || die '--offline-render requires --baseline-values'
  [[ -n "$SCHEDULING_OVERLAY_FILE" ]] || die '--offline-render requires --scheduling-overlay'
  [[ -n "$TARGET_KUBERNETES_VERSION" ]] || die '--offline-render requires --kube-version'
  [[ -f "$BASELINE_VALUES_FILE" ]] || die "baseline values file does not exist: $BASELINE_VALUES_FILE"
  [[ -f "$SCHEDULING_OVERLAY_FILE" ]] || die "scheduling overlay does not exist: $SCHEDULING_OVERLAY_FILE"
  [[ -f "$PACKET_VALIDATOR" ]] || die "packet validator not found: $PACKET_VALIDATOR"
  command -v helm >/dev/null 2>&1 || die 'required command not found: helm'
  command -v python3 >/dev/null 2>&1 || die 'required command not found: python3'
  python3 -c 'import yaml' >/dev/null 2>&1 || die 'python3 PyYAML is required'
  validate_identifier RELEASE_NAME "$RELEASE_NAME"
  validate_identifier NAMESPACE "$NAMESPACE"
  if [[ -n "$COMPONENT_BASELINE_RELEASE" && "$RELEASE_NAME" != "$COMPONENT_BASELINE_RELEASE" ]]; then
    die "release name '$RELEASE_NAME' does not match component baseline fixture '$COMPONENT_BASELINE_RELEASE'"
  fi
  if [[ -n "$COMPONENT_BASELINE_NAMESPACE" && "$NAMESPACE" != "$COMPONENT_BASELINE_NAMESPACE" ]]; then
    die "namespace '$NAMESPACE' does not match component baseline fixture '$COMPONENT_BASELINE_NAMESPACE'"
  fi
  assert_component_value "$COMPONENT_NAME"
  TARGET_KUBERNETES_VERSION="$(normalize_kubernetes_version "$TARGET_KUBERNETES_VERSION")"
  mapfile -t COMPONENT_OVERRIDES < <(component_render_overrides "$COMPONENT_NAME")

  if ! RENDERED_PACKET="$(render_scheduling_packet "$CHART_DIR" "$BASELINE_VALUES_FILE" "$SCHEDULING_OVERLAY_FILE" "$TARGET_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" "${COMPONENT_OVERRIDES[@]}")"; then
    die 'offline scheduling render failed'
  fi
  if ! PACKET_INSPECTION="$(inspect_scheduling_packet "$RENDERED_PACKET" any "$TARGET_KUBERNETES_VERSION")"; then
    die 'offline scheduling packet validation failed'
  fi
  report_effective_trigger "$PACKET_INSPECTION"
  printf '%s\n' "$RENDERED_PACKET"
  exit 0
fi

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
print(release.get("name", ""))
print(release.get("namespace", ""))
print(persistence.get("claimName", ""))
print(str(persistence.get("size", "")))
print(",".join(persistence.get("accessModes") or []))
print(persistence.get("mountPath", ""))
print(persistence.get("snapshotPath", ""))
print(str(topology.get("replicaCount", 1)))
print("1" if topology.get("readOnlyRootFilesystem") else "0")
print(image.get("repository", ""))
print(image.get("tagPattern", ""))
PYEOF
)
COMPONENT_BASELINE_RELEASE="${COMPONENT_BASELINE_FIELDS[0]}"
COMPONENT_BASELINE_NAMESPACE="${COMPONENT_BASELINE_FIELDS[1]}"
COMPONENT_BASELINE_CLAIM="${COMPONENT_BASELINE_FIELDS[2]}"
COMPONENT_BASELINE_STORAGE="${COMPONENT_BASELINE_FIELDS[3]}"
COMPONENT_BASELINE_ACCESS_MODES="${COMPONENT_BASELINE_FIELDS[4]}"
COMPONENT_BASELINE_MOUNT_PATH="${COMPONENT_BASELINE_FIELDS[5]}"
COMPONENT_BASELINE_SNAPSHOT_PATH="${COMPONENT_BASELINE_FIELDS[6]}"
COMPONENT_BASELINE_TOPOLOGY_REPLICAS="${COMPONENT_BASELINE_FIELDS[7]}"
COMPONENT_BASELINE_TOPOLOGY_READONLY="${COMPONENT_BASELINE_FIELDS[8]}"
COMPONENT_BASELINE_IMAGE_REPOSITORY="${COMPONENT_BASELINE_FIELDS[9]}"
COMPONENT_BASELINE_IMAGE_TAG_PATTERN="${COMPONENT_BASELINE_FIELDS[10]}"

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
NAMESPACE="${CLI_NAMESPACE:-${NAMESPACE:-a-stock}}"
RELEASE_NAME="${CLI_RELEASE_NAME:-${RELEASE_NAME:-a-stock}}"
HELM_VALUES_FILE="${HELM_VALUES_FILE:-}"
if [[ -n "$BASELINE_VALUES_FILE" ]]; then
  HELM_VALUES_FILE="$BASELINE_VALUES_FILE"
fi
SCHEDULING_OVERLAY_FILE="${SCHEDULING_OVERLAY_FILE:-}"
SERVER_DRY_RUN_AUTHORIZED="${SERVER_DRY_RUN_AUTHORIZED:-false}"
SERVER_DRY_RUN_VERB="${SERVER_DRY_RUN_VERB:-create}"
SUSPENDED_RELEASE_AUTHORIZED="${SUSPENDED_RELEASE_AUTHORIZED:-false}"
SCHEDULE_ACTIVATION_AUTHORIZED="${SCHEDULE_ACTIVATION_AUTHORIZED:-false}"
SCHEDULE_ROLLBACK_AUTHORIZED="${SCHEDULE_ROLLBACK_AUTHORIZED:-false}"
SCHEDULE_ROLLBACK_AUTHORIZATION_REF="${SCHEDULE_ROLLBACK_AUTHORIZATION_REF:-}"
GATE_B_AUTHORIZATION_REF="${GATE_B_AUTHORIZATION_REF:-}"
GATE_C_AUTHORIZATION_REF="${GATE_C_AUTHORIZATION_REF:-}"
GATE_C_CATCH_UP_MODE="${GATE_C_CATCH_UP_MODE:-}"
REVIEWED_GIT_HEAD="${REVIEWED_GIT_HEAD:-}"
REVIEWED_CHART_SHA256="${REVIEWED_CHART_SHA256:-}"
REVIEWED_BASELINE_SHA256="${REVIEWED_BASELINE_SHA256:-}"
REVIEWED_OVERLAY_SHA256="${REVIEWED_OVERLAY_SHA256:-}"
REVIEWED_RENDER_SHA256="${REVIEWED_RENDER_SHA256:-}"
FROZEN_IMAGE_REPOSITORY="${FROZEN_IMAGE_REPOSITORY:-}"
FROZEN_IMAGE_TAG="${FROZEN_IMAGE_TAG:-}"
FROZEN_IMAGE_DIGEST="${FROZEN_IMAGE_DIGEST:-}"
INGRESS_CLASS="${INGRESS_CLASS:-traefik}"
INGRESS_HOST="${INGRESS_HOST:-a-stock.k3s.lan}"
TRUENAS_INGRESS_PORT="${TRUENAS_INGRESS_PORT:-80}"
SCHEDULED_COLLECTION_ENABLED="${SCHEDULED_COLLECTION_ENABLED:-false}"
SCHEDULED_COLLECTION_SUSPEND="${SCHEDULED_COLLECTION_SUSPEND:-true}"
DISABLE_MANUAL_REFRESH="${DISABLE_MANUAL_REFRESH:-true}"
TAILSCALE_HOST="${TAILSCALE_HOST:-gyt.tail0007b1.ts.net}"
TAILSCALE_PORT="${TAILSCALE_PORT:-8443}"
HELM_TIMEOUT="${HELM_TIMEOUT:-5m}"
PACKET_VALIDATOR="$REPO_DIR/scripts/validate-scheduling-packet.py"

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
[[ "$GIT_UPDATE" =~ ^(true|false)$ ]] || die 'GIT_UPDATE must be true or false'
[[ "$GIT_UPDATE" == false ]] || die 'GIT_UPDATE=true is unsupported; update and review the checkout before launching deployment'

for command_name in git sha256sum helm python3 diff; do
  command -v "$command_name" >/dev/null 2>&1 || die "required command not found: $command_name"
done
python3 -c 'import yaml' >/dev/null 2>&1 || die 'python3 PyYAML is required'
if [[ "$OPERATION" == deploy ]]; then
  case "$COMPONENT_NAME" in
    all|service)
      for command_name in ssh kubectl nc podman curl scp; do
        command -v "$command_name" >/dev/null 2>&1 || die "required command not found: $command_name"
      done
      ;;
  esac
fi

cd "$REPO_DIR"
if [[ -n "$HELM_VALUES_FILE" && "$HELM_VALUES_FILE" != /* ]]; then
  HELM_VALUES_FILE="$REPO_DIR/$HELM_VALUES_FILE"
fi
if [[ -n "$HELM_VALUES_FILE" ]]; then
  [[ -f "$HELM_VALUES_FILE" ]] || die "HELM_VALUES_FILE does not exist: $HELM_VALUES_FILE"
fi
if [[ -n "$SCHEDULING_OVERLAY_FILE" && "$SCHEDULING_OVERLAY_FILE" != /* ]]; then
  SCHEDULING_OVERLAY_FILE="$REPO_DIR/$SCHEDULING_OVERLAY_FILE"
fi
if [[ -n "$SCHEDULING_OVERLAY_FILE" ]]; then
  [[ -f "$SCHEDULING_OVERLAY_FILE" ]] || die "SCHEDULING_OVERLAY_FILE does not exist: $SCHEDULING_OVERLAY_FILE"
fi

validate_scalar() {
  local name="$1"
  local value="$2"
  [[ "$value" =~ ^[A-Za-z0-9._:/-]+$ ]] || die "$name contains unsupported characters: $value"
}

require_generic_deploy_values() {
  local chart_dir="$1"
  local baseline_values="$2"
  if [[ -n "$baseline_values" ]]; then
    python3 "$PACKET_VALIDATOR" validate-generic-deploy-values \
      --values "$chart_dir/values.yaml" \
      --values "$baseline_values" \
      || return 1
  elif [[ "$SCHEDULED_COLLECTION_ENABLED" != false || "$SCHEDULED_COLLECTION_SUSPEND" != true ]]; then
    return 1
  fi
}

validate_identifier RELEASE_NAME "$RELEASE_NAME"
validate_identifier NAMESPACE "$NAMESPACE"
validate_scalar IMAGE_REPOSITORY "$IMAGE_REPOSITORY"
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
[[ "$SCHEDULED_COLLECTION_ENABLED" =~ ^(true|false)$ ]] || die 'SCHEDULED_COLLECTION_ENABLED must be true or false'
[[ "$SCHEDULED_COLLECTION_SUSPEND" =~ ^(true|false)$ ]] || die 'SCHEDULED_COLLECTION_SUSPEND must be true or false'
[[ "$DISABLE_MANUAL_REFRESH" =~ ^(true|false)$ ]] || die 'DISABLE_MANUAL_REFRESH must be true or false'
[[ "$SERVER_DRY_RUN_AUTHORIZED" =~ ^(true|false)$ ]] || die 'SERVER_DRY_RUN_AUTHORIZED must be true or false'
[[ "$SUSPENDED_RELEASE_AUTHORIZED" =~ ^(true|false)$ ]] || die 'SUSPENDED_RELEASE_AUTHORIZED must be true or false'
[[ "$SCHEDULE_ACTIVATION_AUTHORIZED" =~ ^(true|false)$ ]] || die 'SCHEDULE_ACTIVATION_AUTHORIZED must be true or false'
[[ "$SCHEDULE_ROLLBACK_AUTHORIZED" =~ ^(true|false)$ ]] || die 'SCHEDULE_ROLLBACK_AUTHORIZED must be true or false'
[[ "$SERVER_DRY_RUN_VERB" == create ]] || die 'SERVER_DRY_RUN_VERB must be create for the absent CronJob admission probe'
if [[ -n "$GATE_B_AUTHORIZATION_REF" ]]; then
  validate_scalar GATE_B_AUTHORIZATION_REF "$GATE_B_AUTHORIZATION_REF"
  [[ "$GATE_B_AUTHORIZATION_REF" != rollback-v1:* ]] \
    || die 'Gate B authorization must not use the rollback-v1 namespace'
fi
if [[ -n "$GATE_C_AUTHORIZATION_REF" ]]; then
  validate_scalar GATE_C_AUTHORIZATION_REF "$GATE_C_AUTHORIZATION_REF"
  [[ "$GATE_C_AUTHORIZATION_REF" != rollback-v1:* ]] \
    || die 'Gate C authorization must not use the rollback-v1 namespace'
fi
if [[ -n "$SCHEDULE_ROLLBACK_AUTHORIZATION_REF" ]]; then
  validate_scalar SCHEDULE_ROLLBACK_AUTHORIZATION_REF "$SCHEDULE_ROLLBACK_AUTHORIZATION_REF"
fi

case "$OPERATION" in
  server-dry-run|release-suspended|activate-schedule|disable-schedule)
    [[ -n "$HELM_VALUES_FILE" ]] || die "$OPERATION requires baseline values"
    [[ -n "$SCHEDULING_OVERLAY_FILE" ]] || die "$OPERATION requires a scheduling overlay"
    [[ -n "$TARGET_KUBERNETES_VERSION" ]] || die "$OPERATION requires --kube-version"
    ;;
esac
if [[ "$OPERATION" == deploy && -n "$SCHEDULING_OVERLAY_FILE" && "$COMPONENT_NAME" == "all" ]]; then
  die 'ordinary all-component deployment does not accept a scheduling overlay; use an explicit reviewed scheduling mode'
fi
if [[ "$OPERATION" == deploy ]]; then
  require_generic_deploy_values "$REPO_DIR/deploy/helm/a-stock" "$HELM_VALUES_FILE" \
    || die 'ordinary deployment requires scheduledCollection.enabled=false and scheduledCollection.suspend=true before Helm rendering'
fi

if [[ -n "$TARGET_KUBERNETES_VERSION" ]]; then
  TARGET_KUBERNETES_VERSION="$(normalize_kubernetes_version "$TARGET_KUBERNETES_VERSION")"
fi

EARLY_RENDER_ARGS=()
if [[ "$OPERATION" == release-suspended || "$OPERATION" == activate-schedule || "$OPERATION" == disable-schedule ]]; then
  [[ -n "$FROZEN_IMAGE_REPOSITORY" && -n "$FROZEN_IMAGE_TAG" && -n "$FROZEN_IMAGE_DIGEST" ]] || die "$OPERATION requires frozen image repository, tag, and digest"
  validate_scalar FROZEN_IMAGE_REPOSITORY "$FROZEN_IMAGE_REPOSITORY"
  validate_scalar FROZEN_IMAGE_TAG "$FROZEN_IMAGE_TAG"
  [[ "$FROZEN_IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] || die 'FROZEN_IMAGE_DIGEST must be sha256 followed by 64 lowercase hex characters'
  EARLY_RENDER_ARGS+=(--set "image.repository=$FROZEN_IMAGE_REPOSITORY")
  EARLY_RENDER_ARGS+=(--set "image.tag=$FROZEN_IMAGE_TAG")
fi

LOCAL_KUBERNETES_VERSION="${TARGET_KUBERNETES_VERSION:-1.27.0}"

# Resolve the image reference before any render path. Read-only and reviewed
# scheduling operations do not build or transfer an image, but their complete
# Helm packet still needs a defined tag for schema/render compatibility.
if [[ "$OPERATION" == deploy ]]; then
  if [[ -z "${IMAGE_TAG:-}" ]]; then
    IMAGE_TAG="$(date +%Y%m%d-%H%M%S)-$(git rev-parse --short HEAD)"
  fi
else
  IMAGE_TAG="${IMAGE_TAG:-unused}"
fi
validate_scalar IMAGE_TAG "$IMAGE_TAG"
if [[ "$OPERATION" == deploy ]]; then
  IMAGE="${IMAGE_REPOSITORY}:${IMAGE_TAG}"
  ARCHIVE_NAME="a-stock-market-environment-${IMAGE_TAG}.tar"
else
  IMAGE="${FROZEN_IMAGE_REPOSITORY:-${IMAGE_REPOSITORY}}:${FROZEN_IMAGE_TAG:-$IMAGE_TAG}"
fi

if [[ "$OPERATION" != read-only-discovery ]]; then
  case "$OPERATION" in
    deploy)
      if [[ "$COMPONENT_SELECTED" == true ]]; then
        case "$COMPONENT_NAME" in
          database)
            REQUIRED_SCHEDULING_STATE="disabled"
            COMPONENT_RENDER_ARGS=(--set "component=database")
            PREFLIGHT_IMAGE_REPOSITORY="$IMAGE_REPOSITORY"
            PREFLIGHT_IMAGE_TAG="$IMAGE_TAG"
            ;;
          schedule)
            REQUIRED_SCHEDULING_STATE="suspended"
            COMPONENT_RENDER_ARGS=(--set "component=schedule")
            if [[ -z "${FROZEN_IMAGE_REPOSITORY:-}" || -z "${FROZEN_IMAGE_TAG:-}" || -z "${FROZEN_IMAGE_DIGEST:-}" ]]; then
              die '--component schedule deploy requires FROZEN_IMAGE_REPOSITORY, FROZEN_IMAGE_TAG, and FROZEN_IMAGE_DIGEST from a previously reviewed --component all or --component service run'
            fi
            if ! [[ "$FROZEN_IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]; then
              die 'FROZEN_IMAGE_DIGEST must be sha256 followed by 64 lowercase hex characters'
            fi
            PREFLIGHT_IMAGE_REPOSITORY="$FROZEN_IMAGE_REPOSITORY"
            PREFLIGHT_IMAGE_TAG="$FROZEN_IMAGE_TAG"
            ;;
          service)
            REQUIRED_SCHEDULING_STATE="disabled"
            COMPONENT_RENDER_ARGS=(--set "component=service")
            PREFLIGHT_IMAGE_REPOSITORY="$IMAGE_REPOSITORY"
            PREFLIGHT_IMAGE_TAG="$IMAGE_TAG"
            ;;
          all)
            REQUIRED_SCHEDULING_STATE="disabled"
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
        if [[ "$COMPONENT_NAME" == "schedule" ]]; then
          if [[ "$PREFLIGHT_IMAGE_REPOSITORY" != "$IMAGE_REPOSITORY" || "$PREFLIGHT_IMAGE_TAG" != "$IMAGE_TAG" ]]; then
            log "component=schedule frozen image provenance verified: $PREFLIGHT_IMAGE_REPOSITORY:$PREFLIGHT_IMAGE_TAG digest=$FROZEN_IMAGE_DIGEST"
          fi
        fi
        if ! RENDERED_PACKET="$(render_scheduling_packet "$REPO_DIR/deploy/helm/a-stock" "$HELM_VALUES_FILE" "$SCHEDULING_OVERLAY_FILE" "$LOCAL_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" "${EARLY_RENDER_ARGS[@]}" "${COMPONENT_RENDER_ARGS[@]}")"; then
          die "component=$COMPONENT_NAME final merged Helm values are invalid"
        fi
        if ! PACKET_INSPECTION="$(inspect_scheduling_packet "$RENDERED_PACKET" "$REQUIRED_SCHEDULING_STATE" "$LOCAL_KUBERNETES_VERSION")"; then
          die "component=$COMPONENT_NAME rejected the final scheduling state"
        fi
        report_effective_trigger "$PACKET_INSPECTION"
        GENERIC_RENDER_SHA256="$(printf '%s\n' "$RENDERED_PACKET" | sha256sum | awk '{print $1}')"
        log "component summary: phase=preflight component=$COMPONENT_NAME packetDigest=$GENERIC_RENDER_SHA256 state=$REQUIRED_SCHEDULING_STATE release=$RELEASE_NAME namespace=$NAMESPACE"
        case "$COMPONENT_NAME" in
          database)
            log "component step: name=database phase=preflight image=$PREFLIGHT_IMAGE_REPOSITORY:$PREFLIGHT_IMAGE_TAG"
            verify_database_component "$RENDERED_PACKET" || die 'component=database invariant check failed'
            log "component step: name=database phase=verified packetDigest=$GENERIC_RENDER_SHA256"
            log "component=database: preflight verified; rerun with --component all (or service) to apply; this invocation does not access the target cluster, build images, or modify resources"
            exit 0
            ;;
          schedule)
            log "component step: name=schedule phase=preflight image=$PREFLIGHT_IMAGE_REPOSITORY:$PREFLIGHT_IMAGE_TAG"
            verify_schedule_component "$RENDERED_PACKET" || die 'component=schedule invariant check failed'
            if [[ "$PREFLIGHT_IMAGE_REPOSITORY" != "$IMAGE_REPOSITORY" || "$PREFLIGHT_IMAGE_TAG" != "$IMAGE_TAG" ]]; then
              log "component step: name=schedule phase=verified frozenImage=$PREFLIGHT_IMAGE_REPOSITORY:$PREFLIGHT_IMAGE_TAG digest=$FROZEN_IMAGE_DIGEST"
            fi
            log "component step: name=schedule phase=verified packetDigest=$GENERIC_RENDER_SHA256 cronjobState=suspended"
            log "component=schedule: preflight verified for frozen image $PREFLIGHT_IMAGE_REPOSITORY:$PREFLIGHT_IMAGE_TAG; rerun with --component all (or service) to apply; this invocation does not access the target cluster or modify resources"
            exit 0
            ;;
          service)
            log "component step: name=service phase=preflight image=$PREFLIGHT_IMAGE_REPOSITORY:$PREFLIGHT_IMAGE_TAG"
            verify_service_component "$RENDERED_PACKET" || die 'component=service invariant check failed'
            log "component step: name=service phase=verified packetDigest=$GENERIC_RENDER_SHA256"
            log "component=service: preflight verified; rerun with --component all under Gate B authorization to apply; this invocation does not access the target cluster, build images, or modify resources"
            exit 0
            ;;
          all)
            log "all components: order=database->service->schedule preflight start release=$RELEASE_NAME"
            COMPLETED_COMPONENTS=""
            FAILED_COMPONENT=""
            FAILED_REASON=""
            for step in database service schedule; do
              case "$step" in
                database|service)
                  step_repo="$IMAGE_REPOSITORY"
                  step_tag="$IMAGE_TAG"
                  ;;
                schedule)
                  if [[ -z "${FROZEN_IMAGE_REPOSITORY:-}" || -z "${FROZEN_IMAGE_TAG:-}" || -z "${FROZEN_IMAGE_DIGEST:-}" ]]; then
                    log "component step: name=schedule phase=skipped reason=baseline_disabled no FROZEN_IMAGE_* provided; rerun with --component schedule separately after providing FROZEN_IMAGE_* to deploy the schedule layer"
                    continue
                  fi
                  if ! [[ "$FROZEN_IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]; then
                    FAILED_COMPONENT="schedule"
                    FAILED_REASON="invalid_frozen_image_digest"
                    log "component step: name=schedule phase=failed reason=invalid_frozen_image_digest retryTarget=rerun with sha256:64hex digest"
                    break
                  fi
                  step_repo="$FROZEN_IMAGE_REPOSITORY"
                  step_tag="$FROZEN_IMAGE_TAG"
                  ;;
              esac
              step_packet="$(render_scheduling_packet "$REPO_DIR/deploy/helm/a-stock" "$HELM_VALUES_FILE" "$SCHEDULING_OVERLAY_FILE" "$LOCAL_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" \
                --set "image.repository=$step_repo" --set "image.tag=$step_tag" --set "component=$step")" \
                || { FAILED_COMPONENT="$step"; FAILED_REASON="component_packet_render_failed"; log "component step: name=$step phase=failed reason=component_packet_render_failed"; break; }
              step_digest="$(printf '%s\n' "$step_packet" | sha256sum | awk '{print $1}')"
              case "$step" in
                database) verify_database_component "$step_packet" || { FAILED_COMPONENT="$step"; FAILED_REASON="database_invariant_violated"; break; } ;;
                service) verify_service_component "$step_packet" || { FAILED_COMPONENT="$step"; FAILED_REASON="service_invariant_violated"; break; } ;;
                schedule)
                  if [[ "$step_repo" != "$IMAGE_REPOSITORY" || "$step_tag" != "$IMAGE_TAG" ]]; then
                    log "component step: name=schedule phase=verified frozenImage=$step_repo:$step_tag digest=$FROZEN_IMAGE_DIGEST"
                  fi
                  verify_schedule_component "$step_packet" || { FAILED_COMPONENT="$step"; FAILED_REASON="schedule_invariant_violated"; break; } ;;
              esac
              log "component step: name=$step phase=verified packetDigest=$step_digest image=$step_repo:$step_tag"
              COMPLETED_COMPONENTS+=" $step"
            done
            if [[ -n "$FAILED_COMPONENT" ]]; then
              log "all components: status=partial order=database->service->schedule completed=$COMPLETED_COMPONENTS failed=$FAILED_COMPONENT reason=$FAILED_REASON retryTarget=rerun with the failed component alone"
              exit 1
            fi
            log "all components: status=verified order=database->service->schedule completed=$COMPLETED_COMPONENTS release=$RELEASE_NAME namespace=$NAMESPACE"
            ;;
        esac
      else
        if ! RENDERED_PACKET="$(render_scheduling_packet "$REPO_DIR/deploy/helm/a-stock" "$HELM_VALUES_FILE" "$SCHEDULING_OVERLAY_FILE" "$LOCAL_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" "${EARLY_RENDER_ARGS[@]}")"; then
          die 'final merged Helm values are invalid'
        fi
        case "$OPERATION" in
          deploy)
            REQUIRED_SCHEDULING_STATE=disabled
            ;;
          *)
            die "unsupported operation: $OPERATION"
            ;;
        esac
        if ! PACKET_INSPECTION="$(inspect_scheduling_packet "$RENDERED_PACKET" "$REQUIRED_SCHEDULING_STATE" "$LOCAL_KUBERNETES_VERSION")"; then
          die "operation $OPERATION rejected the final scheduling state"
        fi
        report_effective_trigger "$PACKET_INSPECTION"
        GENERIC_RENDER_SHA256="$(sha256_text "$RENDERED_PACKET")"
      fi
      ;;
    server-dry-run|release-suspended|activate-schedule|disable-schedule)
      if ! RENDERED_PACKET="$(render_scheduling_packet "$REPO_DIR/deploy/helm/a-stock" "$HELM_VALUES_FILE" "$SCHEDULING_OVERLAY_FILE" "$LOCAL_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" "${EARLY_RENDER_ARGS[@]}")"; then
        die 'final merged Helm values are invalid'
      fi
      case "$OPERATION" in
        deploy|disable-schedule)
          REQUIRED_SCHEDULING_STATE=disabled
          ;;
        server-dry-run|release-suspended)
          REQUIRED_SCHEDULING_STATE=suspended
          ;;
        activate-schedule)
          REQUIRED_SCHEDULING_STATE=active
          ;;
        *)
          die "unsupported operation: $OPERATION"
          ;;
      esac
      if ! PACKET_INSPECTION="$(inspect_scheduling_packet "$RENDERED_PACKET" "$REQUIRED_SCHEDULING_STATE" "$LOCAL_KUBERNETES_VERSION")"; then
        die "operation $OPERATION rejected the final scheduling state"
      fi
      report_effective_trigger "$PACKET_INSPECTION"
      GENERIC_RENDER_SHA256="$(sha256_text "$RENDERED_PACKET")"
      ;;
  esac
fi

rollback_binding_payload() {
  printf '%s\n' \
    'schema=rollback-v1' \
    'operation=--disable-schedule' \
    "release=$RELEASE_NAME" \
    "namespace=$NAMESPACE" \
    "kubernetesVersion=$TARGET_KUBERNETES_VERSION" \
    "reviewedHead=$REVIEWED_GIT_HEAD" \
    "chartSha256=$REVIEWED_CHART_SHA256" \
    "baselineSha256=$REVIEWED_BASELINE_SHA256" \
    "overlaySha256=$REVIEWED_OVERLAY_SHA256" \
    "renderSha256=$REVIEWED_RENDER_SHA256"
}

verify_rollback_authorization_ref() {
  local reference="$1"
  local expected_digest supplied_digest approval_id
  if [[ ! "$reference" =~ ^rollback-v1:([A-Za-z0-9][A-Za-z0-9._-]{0,127}):([0-9a-f]{64})$ ]]; then
    die 'SCHEDULE_ROLLBACK_AUTHORIZATION_REF must match rollback-v1:<approval-id>:<binding-sha256>'
  fi
  approval_id="${BASH_REMATCH[1]}"
  supplied_digest="${BASH_REMATCH[2]}"
  expected_digest="$(rollback_binding_payload | sha256sum | awk '{print $1}')"
  [[ "$supplied_digest" == "$expected_digest" ]] \
    || die 'schedule rollback authorization binding does not match the exact disable-schedule packet'
  log "rollback authorization verified: approval=$approval_id binding=$supplied_digest"
}

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

verify_reviewed_sources() {
  local require_packet="$1"
  local head upstream_head
  [[ -n "$REVIEWED_GIT_HEAD" ]] || die 'REVIEWED_GIT_HEAD is required'
  [[ -z "$(git status --porcelain --untracked-files=all)" ]] || die 'reviewed scheduling operations require a clean working tree'
  head="$(git rev-parse HEAD)"
  [[ "$head" == "$REVIEWED_GIT_HEAD" ]] || die "reviewed HEAD drift: expected $REVIEWED_GIT_HEAD, got $head"
  upstream_head="$(git rev-parse '@{upstream}' 2>/dev/null)" || die 'reviewed branch must have an upstream'
  [[ "$head" == "$upstream_head" ]] || die "reviewed branch differs from its upstream: $upstream_head"
  verify_hash chart "$REVIEWED_CHART_SHA256" "$(chart_sha256)"
  if [[ "$require_packet" == true ]]; then
    verify_hash baseline "$REVIEWED_BASELINE_SHA256" "$(sha256sum "$HELM_VALUES_FILE" | awk '{print $1}')"
    verify_hash overlay "$REVIEWED_OVERLAY_SHA256" "$(sha256sum "$SCHEDULING_OVERLAY_FILE" | awk '{print $1}')"
    verify_hash render "$REVIEWED_RENDER_SHA256" "$(sha256_text "$RENDERED_PACKET")"
  fi
}

validate_activation_window() {
  local phase="$1"
  local inspection log_value
  if ! inspection="$(
    printf '%s\n' "$PACKET_INSPECTION" \
      | python3 "$PACKET_VALIDATOR" validate-activation-window \
        --mode "$GATE_C_CATCH_UP_MODE"
  )"; then
    die "Gate C $phase activation window validation failed"
  fi
  log_value="${inspection//$'\n'/ }"
  log "Gate C activation window ($phase): $log_value"
}

case "$OPERATION" in
  read-only-discovery)
    verify_reviewed_sources false
    ;;
  server-dry-run|release-suspended|activate-schedule|disable-schedule)
    verify_reviewed_sources true
    ;;
esac

case "$OPERATION" in
  server-dry-run)
    [[ "$SERVER_DRY_RUN_AUTHORIZED" == true ]] || die '--server-dry-run requires SERVER_DRY_RUN_AUTHORIZED=true'
    [[ -n "$GATE_B_AUTHORIZATION_REF" ]] || die '--server-dry-run requires an exact GATE_B_AUTHORIZATION_REF'
    ;;
  release-suspended)
    [[ "$SUSPENDED_RELEASE_AUTHORIZED" == true ]] || die '--release-suspended requires SUSPENDED_RELEASE_AUTHORIZED=true'
    [[ -n "$GATE_B_AUTHORIZATION_REF" ]] || die '--release-suspended requires an exact GATE_B_AUTHORIZATION_REF'
    ;;
  activate-schedule)
    [[ "$SCHEDULE_ACTIVATION_AUTHORIZED" == true ]] || die '--activate-schedule requires SCHEDULE_ACTIVATION_AUTHORIZED=true'
    [[ -n "$GATE_C_AUTHORIZATION_REF" ]] || die '--activate-schedule requires an exact GATE_C_AUTHORIZATION_REF'
    [[ "$GATE_C_CATCH_UP_MODE" == next-schedule || "$GATE_C_CATCH_UP_MODE" == immediate-catch-up ]] || die 'Gate C requires GATE_C_CATCH_UP_MODE=next-schedule or immediate-catch-up'
    validate_activation_window preflight
    ;;
  disable-schedule)
    [[ "$SCHEDULE_ROLLBACK_AUTHORIZED" == true ]] || die '--disable-schedule requires SCHEDULE_ROLLBACK_AUTHORIZED=true'
    [[ -n "$SCHEDULE_ROLLBACK_AUTHORIZATION_REF" ]] || die '--disable-schedule requires an exact SCHEDULE_ROLLBACK_AUTHORIZATION_REF'
    [[ -z "$GATE_B_AUTHORIZATION_REF" || "$SCHEDULE_ROLLBACK_AUTHORIZATION_REF" != "$GATE_B_AUTHORIZATION_REF" ]] || die 'schedule rollback authorization must be independent of Gate B authorization'
    [[ -z "$GATE_C_AUTHORIZATION_REF" || "$SCHEDULE_ROLLBACK_AUTHORIZATION_REF" != "$GATE_C_AUTHORIZATION_REF" ]] || die 'schedule rollback authorization must be independent of Gate C authorization'
    verify_rollback_authorization_ref "$SCHEDULE_ROLLBACK_AUTHORIZATION_REF"
    ;;
esac

SSH_TARGET="${TRUENAS_SSH_USER}@${TRUENAS_HOST}"
remote() {
  ssh -o BatchMode=yes -o ConnectTimeout=10 -p "$TRUENAS_SSH_PORT" "$SSH_TARGET" "$@"
}

TMP_DIR="$(mktemp -d -t a-stock-deploy.XXXXXX)"
SMOKE_NAME="a-stock-smoke-$$"
SMOKE_CREATED=false
K3S_TUNNEL_PID=''
ACTIVATION_IN_FLIGHT=false
ACTIVATION_CRONJOB_NAME=''
DISABLE_IN_FLIGHT=false
DISABLE_CRONJOB_NAME=''
GENERIC_DEPLOY_IN_FLIGHT=false
GENERIC_CRONJOB_NAME=''
cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM HUP
  if [[ "$ACTIVATION_IN_FLIGHT" == true ]]; then
    suspend_after_uncertain_activation "$ACTIVATION_CRONJOB_NAME"
  fi
  if [[ "$DISABLE_IN_FLIGHT" == true ]]; then
    DISABLE_IN_FLIGHT=false
    if ! ensure_cronjob_suspended_or_absent 'disable-schedule failure recovery' "$DISABLE_CRONJOB_NAME"; then
      warn 'disable-schedule failed closed but the exact CronJob state remains uncertain; operator intervention is required'
    fi
  fi
  if [[ "$SMOKE_CREATED" == true ]]; then
    podman rm -f "$SMOKE_NAME" >/dev/null 2>&1 || true
  fi
  if [[ -n "$K3S_TUNNEL_PID" ]]; then
    kill "$K3S_TUNNEL_PID" >/dev/null 2>&1 || true
    wait "$K3S_TUNNEL_PID" 2>/dev/null || true
  fi
  chmod -R u+w "$TMP_DIR" >/dev/null 2>&1 || true
  rm -rf "$TMP_DIR"
  if [[ "$GENERIC_DEPLOY_IN_FLIGHT" == true ]]; then
    recover_generic_deploy_schedule 'generic deployment failure recovery' || true
  fi
  exit "$exit_code"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

SOURCE_CHART_DIR="$REPO_DIR/deploy/helm/a-stock"
OPERATION_CHART_DIR="$SOURCE_CHART_DIR"
OPERATION_BASELINE_VALUES="$HELM_VALUES_FILE"
OPERATION_SCHEDULING_OVERLAY="$SCHEDULING_OVERLAY_FILE"
case "$OPERATION" in
  deploy|server-dry-run|release-suspended|activate-schedule|disable-schedule)
    command -v flock >/dev/null 2>&1 || die 'required command not found: flock'
    COMMON_GIT_DIR="$(git rev-parse --git-common-dir)"
    if [[ "$COMMON_GIT_DIR" != /* ]]; then
      COMMON_GIT_DIR="$REPO_DIR/$COMMON_GIT_DIR"
    fi
    exec 9>"$COMMON_GIT_DIR/a-stock-scheduling-release.lock"
    flock -n 9 || die 'another reviewed scheduling operation holds the release lock'
    ;;
esac
case "$OPERATION" in
  deploy|server-dry-run|release-suspended|activate-schedule|disable-schedule)
    SNAPSHOT_DIR="$TMP_DIR/release-packet"
    mkdir -p "$SNAPSHOT_DIR"
    cp -R "$SOURCE_CHART_DIR" "$SNAPSHOT_DIR/chart"
    diff -qr "$SOURCE_CHART_DIR" "$SNAPSHOT_DIR/chart" >/dev/null || die 'chart changed while freezing the release packet'
    OPERATION_CHART_DIR="$SNAPSHOT_DIR/chart"
    if [[ -n "$HELM_VALUES_FILE" ]]; then
      cp "$HELM_VALUES_FILE" "$SNAPSHOT_DIR/baseline.yaml"
      OPERATION_BASELINE_VALUES="$SNAPSHOT_DIR/baseline.yaml"
    fi
    if [[ -n "$SCHEDULING_OVERLAY_FILE" ]]; then
      cp "$SCHEDULING_OVERLAY_FILE" "$SNAPSHOT_DIR/overlay.yaml"
      OPERATION_SCHEDULING_OVERLAY="$SNAPSHOT_DIR/overlay.yaml"
    fi
    if [[ "$OPERATION" == deploy ]]; then
      require_generic_deploy_values "$OPERATION_CHART_DIR" "$OPERATION_BASELINE_VALUES" \
        || die 'frozen ordinary deployment packet requires scheduledCollection.enabled=false and scheduledCollection.suspend=true before Helm rendering'
    fi
    SNAPSHOT_RENDER_ARGS=("${EARLY_RENDER_ARGS[@]}" "${COMPONENT_RENDER_ARGS[@]}")
    if ! SNAPSHOT_RENDER="$(render_scheduling_packet "$OPERATION_CHART_DIR" "$OPERATION_BASELINE_VALUES" "$OPERATION_SCHEDULING_OVERLAY" "$LOCAL_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" "${SNAPSHOT_RENDER_ARGS[@]}")"; then
      die 'frozen release packet render failed'
    fi
    if [[ "$(sha256_text "$SNAPSHOT_RENDER")" != "$(sha256_text "$RENDERED_PACKET")" ]]; then
      die 'release packet changed while freezing its sources'
    fi
    if ! inspect_scheduling_packet "$SNAPSHOT_RENDER" "$REQUIRED_SCHEDULING_STATE" "$LOCAL_KUBERNETES_VERSION" >/dev/null; then
      die 'frozen release packet failed scheduling validation'
    fi
    if [[ "$OPERATION" != deploy ]]; then
      verify_hash baseline "$REVIEWED_BASELINE_SHA256" "$(sha256sum "$OPERATION_BASELINE_VALUES" | awk '{print $1}')"
      verify_hash overlay "$REVIEWED_OVERLAY_SHA256" "$(sha256sum "$OPERATION_SCHEDULING_OVERLAY" | awk '{print $1}')"
      verify_hash render "$REVIEWED_RENDER_SHA256" "$(sha256_text "$SNAPSHOT_RENDER")"
      log "reviewed packet binding: head=$REVIEWED_GIT_HEAD chart=$REVIEWED_CHART_SHA256 baseline=$REVIEWED_BASELINE_SHA256 overlay=$REVIEWED_OVERLAY_SHA256 render=$REVIEWED_RENDER_SHA256"
    fi
    chmod -R a-w "$SNAPSHOT_DIR"
    RENDERED_PACKET="$SNAPSHOT_RENDER"
    ;;
esac

if [[ "$OPERATION" == deploy && -n "$(git status --porcelain)" ]]; then
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

if [[ "$OPERATION" == deploy ]]; then
  if ! RESOLVED_CRONJOB_NAME="$(resolve_generic_cronjob_name "$TARGET_KUBERNETES_VERSION")"; then
    die 'could not resolve the release-derived application cronjob name'
  fi
  GENERIC_CRONJOB_NAME="$RESOLVED_CRONJOB_NAME"
  verify_generic_deploy_precondition
elif [[ "$OPERATION" == disable-schedule ]]; then
  if ! RESOLVED_CRONJOB_NAME="$(resolve_generic_cronjob_name "$TARGET_KUBERNETES_VERSION")"; then
    die 'could not resolve the release-derived application cronjob name'
  fi
  DISABLE_CRONJOB_NAME="$RESOLVED_CRONJOB_NAME"
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
  printf 'marketEnvironment:\n'
  printf '  timezone: Asia/Shanghai\n'
  printf '  snapshotPath: /data/snapshots.sqlite3\n'
  printf '  persistentCache: true\n'
  printf '  settlementTime: "15:10"\n'
  printf '  scheduledCollection:\n'
  printf '    enabled: %s\n' "$SCHEDULED_COLLECTION_ENABLED"
  printf '    suspend: %s\n' "$SCHEDULED_COLLECTION_SUSPEND"
  if [[ "$DISABLE_MANUAL_REFRESH" == true ]]; then
    printf 'extraEnv:\n'
    printf '  - name: MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED\n'
    printf '    value: "0"\n'
  fi
  } > "$VALUES_FILE"
else
  cp "$OPERATION_BASELINE_VALUES" "$VALUES_FILE"
fi

RENDERED_PACKET="$(render_scheduling_packet "$OPERATION_CHART_DIR" "$VALUES_FILE" "$OPERATION_SCHEDULING_OVERLAY" "$TARGET_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" --set "image.repository=$IMAGE_REPOSITORY" --set "image.tag=$IMAGE_TAG" --set "component=$COMPONENT_NAME")"
REQUIRED_DEPLOY_SCHEDULING_STATE="$(component_required_scheduling_state "$COMPONENT_NAME")"
GENERIC_RENDER_SHA256="$(sha256_text "$RENDERED_PACKET")"
if ! PRE_WRITE_RENDER="$(render_scheduling_packet "$OPERATION_CHART_DIR" "$VALUES_FILE" "$OPERATION_SCHEDULING_OVERLAY" "$TARGET_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" --set "image.repository=$IMAGE_REPOSITORY" --set "image.tag=$IMAGE_TAG" --set "component=$COMPONENT_NAME")"; then
  die 'frozen generic release packet failed immediately before helm write'
fi
if [[ "$(sha256_text "$PRE_WRITE_RENDER")" != "$GENERIC_RENDER_SHA256" ]]; then
  die 'frozen generic release packet drifted before helm write'
fi
if ! inspect_scheduling_packet "$PRE_WRITE_RENDER" "$REQUIRED_DEPLOY_SCHEDULING_STATE" "$TARGET_KUBERNETES_VERSION" >/dev/null; then
  die "frozen generic release packet could create or activate scheduled collection ($COMPONENT_NAME)"
fi

if [[ "$COMPONENT_NAME" == "database" ]]; then
  log "component=database: skipping image build/smoke/save/scp/import; PVC contract is verified by the rendered packet only"
elif [[ "$COMPONENT_NAME" == "schedule" ]]; then
  log "component=schedule: skipping image build/smoke/save/scp/import; reusing frozen image $FROZEN_IMAGE_REPOSITORY:$FROZEN_IMAGE_TAG"
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
    --env MARKET_ENVIRONMENT_SNAPSHOT_PATH=/tmp/snapshots.sqlite3 \
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

  ARCHIVE_PATH="$TMP_DIR/$ARCHIVE_NAME"
  CHECKSUM_PATH="${ARCHIVE_PATH}.sha256"
  log "exporting $ARCHIVE_NAME"
  podman save --format docker-archive --output "$ARCHIVE_PATH" "$IMAGE"
  (
    cd "$TMP_DIR"
    sha256sum "$ARCHIVE_NAME" > "${ARCHIVE_NAME}.sha256"
  )

  log "copying archive to $SSH_TARGET:$REMOTE_IMAGE_DIR"
  scp -P "$TRUENAS_SSH_PORT" "$ARCHIVE_PATH" "$CHECKSUM_PATH" \
    "$SSH_TARGET:$REMOTE_IMAGE_DIR/"

  log 'verifying and importing the image into k3s containerd'
  remote "set -eu
cd '$REMOTE_IMAGE_DIR'
sha256sum --check '$ARCHIVE_NAME.sha256'
sudo -n k3s ctr --namespace k8s.io images import '$ARCHIVE_NAME'
sudo -n k3s ctr --namespace k8s.io images list | grep -F -- '$IMAGE' >/dev/null
"
fi

verify_generic_deploy_precondition
if ! PRE_WRITE_RENDER="$(render_scheduling_packet "$OPERATION_CHART_DIR" "$VALUES_FILE" "$OPERATION_SCHEDULING_OVERLAY" "$TARGET_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" --set "image.repository=$IMAGE_REPOSITORY" --set "image.tag=$IMAGE_TAG" "${EARLY_RENDER_ARGS[@]}" "${COMPONENT_RENDER_ARGS[@]}")"; then
  die 'frozen generic release packet failed immediately before helm write'
fi
if [[ "$(sha256_text "$PRE_WRITE_RENDER")" != "$GENERIC_RENDER_SHA256" ]]; then
  die 'frozen generic release packet drifted before helm write'
fi
if ! inspect_scheduling_packet "$PRE_WRITE_RENDER" "$REQUIRED_DEPLOY_SCHEDULING_STATE" "$TARGET_KUBERNETES_VERSION" >/dev/null; then
  die "frozen generic release packet could create or activate scheduled collection ($COMPONENT_NAME)"
fi

HELM_VALUES_ARGS=(--values "$VALUES_FILE")
if [[ -n "$OPERATION_SCHEDULING_OVERLAY" ]]; then
  HELM_VALUES_ARGS+=(--values "$OPERATION_SCHEDULING_OVERLAY")
fi

log "staged component deployment: order=database->service->schedule component=$COMPONENT_NAME release=$RELEASE_NAME namespace=$NAMESPACE"
GENERIC_DEPLOY_IN_FLIGHT=true
COMPLETED_COMPONENTS=""
FAILED_COMPONENT=""
FAILED_REASON=""

deploy_step_or_exit() {
  local step_name="$1"
  local image_repo="$2"
  local image_tag="$3"
  local step_exit=0
  deploy_component_step "$step_name" "$image_repo" "$image_tag" || step_exit=$?
  if (( step_exit != 0 )); then
    FAILED_COMPONENT="$step_name"
    FAILED_REASON="${step_name}_phase_rejected"
    log "staged component deployment: failed at component=$FAILED_COMPONENT reason=$FAILED_REASON exitCode=$step_exit retryTarget=rerun with --component $FAILED_COMPONENT"
    exit "$step_exit"
  fi
}

if [[ "$COMPONENT_NAME" == "service" || "$COMPONENT_NAME" == "all" ]]; then
  deploy_step_or_exit database "$IMAGE_REPOSITORY" "$IMAGE_TAG"
  COMPLETED_COMPONENTS+=" database"
fi

if [[ -z "$FAILED_COMPONENT" && ( "$COMPONENT_NAME" == "service" || "$COMPONENT_NAME" == "all" ) ]]; then
  deploy_step_or_exit service "$IMAGE_REPOSITORY" "$IMAGE_TAG"
  COMPLETED_COMPONENTS+=" service"
fi

if [[ -z "$FAILED_COMPONENT" && ( "$COMPONENT_NAME" == "schedule" || "$COMPONENT_NAME" == "all" ) ]]; then
  SCHEDULE_REPO="$FROZEN_IMAGE_REPOSITORY"
  SCHEDULE_TAG="$FROZEN_IMAGE_TAG"
  if [[ -z "$SCHEDULE_REPO" || -z "$SCHEDULE_TAG" ]]; then
    log "staged component deployment: schedule phase=skipped reason=baseline_disabled no FROZEN_IMAGE_* provided; rerun with --component schedule after providing FROZEN_IMAGE_* to deploy the schedule layer"
  else
    deploy_step_or_exit schedule "$SCHEDULE_REPO" "$SCHEDULE_TAG"
    COMPLETED_COMPONENTS+=" schedule"
  fi
fi

if [[ "$COMPONENT_NAME" == "database" ]]; then
  deploy_step_or_exit database "$IMAGE_REPOSITORY" "$IMAGE_TAG"
  COMPLETED_COMPONENTS+=" database"
fi

if [[ -n "$FAILED_COMPONENT" ]]; then
  log "staged component deployment: status=partial order=database->service->schedule completed=$COMPLETED_COMPONENTS failed=$FAILED_COMPONENT reason=$FAILED_REASON"
  exit 1
fi

if ! POST_DEPLOY_CRONJOBS="$(capture_live_cronjobs)"; then
  die 'could not read live CronJobs after staged component deployment'
fi
require_generic_schedule_disabled 'post-deploy live release' "$POST_DEPLOY_CRONJOBS"

GENERIC_DEPLOY_IN_FLIGHT=false

log "staged component deployment: status=completed order=database->service->schedule completed=$COMPLETED_COMPONENTS release=$RELEASE_NAME namespace=$NAMESPACE"
log "internal URL: http://${TRUENAS_HOST}:${TRUENAS_INGRESS_PORT}/"
log "Tailscale URL after NGINX is configured: https://${TAILSCALE_HOST}:${TAILSCALE_PORT}/"
if [[ -n "$HELM_VALUES_FILE" ]]; then
  log "scheduled collection settings follow $HELM_VALUES_FILE"
elif [[ "$SCHEDULED_COLLECTION_SUSPEND" == true ]]; then
  log 'CronJob is suspended; do not unsuspend without accepted Gate B canary evidence and separate Gate C authorization'
fi

log "component summary: order=database->service->schedule status=completed component=$COMPONENT_NAME packetDigest=$GENERIC_RENDER_SHA256 release=$RELEASE_NAME namespace=$NAMESPACE image=$IMAGE"
exit 0
fi

if [[ "$OPERATION" == read-only-discovery ]]; then
  log "read-only discovery: Kubernetes $TARGET_KUBERNETES_VERSION"
  helm history "$RELEASE_NAME" --namespace "$NAMESPACE"
  helm get values "$RELEASE_NAME" --namespace "$NAMESPACE" --all
  kubectl -n "$NAMESPACE" get deployment,service,cronjob,job,pvc -o yaml
  kubectl get pv -o yaml
  exit 0
fi

if [[ "$OPERATION" == server-dry-run ]]; then
  log "server-side dry-run: exact suspended CronJob; release=$RELEASE_NAME namespace=$NAMESPACE Kubernetes=$TARGET_KUBERNETES_VERSION verb=create"
  [[ "$(kubectl auth can-i create cronjobs.batch --namespace "$NAMESPACE")" == yes ]] || die 'target identity cannot create cronjobs.batch for the admission probe'
  printf '%s\n' "$RENDERED_PACKET" \
    | python3 "$PACKET_VALIDATOR" extract-suspended --release-name "$RELEASE_NAME" --namespace "$NAMESPACE" --require-state suspended \
    | kubectl create --namespace "$NAMESPACE" --dry-run=server --validate=true -f -
  log 'server-side dry-run completed; no canary, validation Job, or unsuspend action was created'
  exit 0
fi

capture_live_release() {
  local destination="$1"
  kubectl get deployment,service,cronjob \
    --namespace "$NAMESPACE" \
    -l "app.kubernetes.io/instance=$RELEASE_NAME" \
    -o yaml > "$destination"
}

suspend_after_uncertain_activation() {
  local cronjob_name="$1"
  ACTIVATION_IN_FLIGHT=false
  warn "activation did not complete safely; forcing $cronjob_name back to suspend=true"
  if ! kubectl patch cronjob "$cronjob_name" --namespace "$NAMESPACE" \
    --type=merge --patch '{"spec":{"suspend":true}}'; then
    warn 'emergency suspend failed; target state is uncertain and requires operator intervention'
  fi
}

if [[ "$OPERATION" == release-suspended || "$OPERATION" == activate-schedule || "$OPERATION" == disable-schedule ]]; then
  FROZEN_IMAGE="$FROZEN_IMAGE_REPOSITORY:$FROZEN_IMAGE_TAG"
  DEPLOYMENTS_JSON="$TMP_DIR/deployments.json"
  REPLICASETS_JSON="$TMP_DIR/replicasets.json"
  PODS_JSON="$TMP_DIR/pods.json"
  kubectl get deployment --namespace "$NAMESPACE" -l "app.kubernetes.io/instance=$RELEASE_NAME" -o json > "$DEPLOYMENTS_JSON"
  kubectl get replicasets --namespace "$NAMESPACE" -l "app.kubernetes.io/instance=$RELEASE_NAME" -o json > "$REPLICASETS_JSON"
  kubectl get pods --namespace "$NAMESPACE" -l "app.kubernetes.io/instance=$RELEASE_NAME" -o json > "$PODS_JSON"
  python3 "$PACKET_VALIDATOR" verify-runtime-image \
    --release-name "$RELEASE_NAME" --image "$FROZEN_IMAGE" --digest "$FROZEN_IMAGE_DIGEST" \
    --deployments "$DEPLOYMENTS_JSON" --replicasets "$REPLICASETS_JSON" --pods "$PODS_JSON"
  remote "sudo -n k3s ctr --namespace k8s.io images info '$FROZEN_IMAGE'" \
    | python3 "$PACKET_VALIDATOR" verify-containerd-image --image "$FROZEN_IMAGE" --digest "$FROZEN_IMAGE_DIGEST"

  CURRENT_MANIFEST="$TMP_DIR/current-manifest.yaml"
  DESIRED_MANIFEST="$TMP_DIR/desired-manifest.yaml"
  LIVE_BEFORE_MANIFEST="$TMP_DIR/live-before.yaml"
  LIVE_AFTER_MANIFEST="$TMP_DIR/live-after.yaml"
  helm get manifest "$RELEASE_NAME" --namespace "$NAMESPACE" > "$CURRENT_MANIFEST"
  printf '%s\n' "$RENDERED_PACKET" > "$DESIRED_MANIFEST"
  if [[ "$OPERATION" == release-suspended ]]; then
    python3 "$PACKET_VALIDATOR" compare-add-suspended \
      --release-name "$RELEASE_NAME" --namespace "$NAMESPACE" \
      --current "$CURRENT_MANIFEST" --desired "$DESIRED_MANIFEST"
  elif [[ "$OPERATION" == activate-schedule ]]; then
    python3 "$PACKET_VALIDATOR" compare-suspend-only \
      --release-name "$RELEASE_NAME" --namespace "$NAMESPACE" \
      --current "$CURRENT_MANIFEST" --desired "$DESIRED_MANIFEST"
  else
    python3 "$PACKET_VALIDATOR" compare-remove-cronjob \
      --release-name "$RELEASE_NAME" --namespace "$NAMESPACE" \
      --current "$CURRENT_MANIFEST" --desired "$DESIRED_MANIFEST"
    CURRENT_PACKET_INSPECTION="$(inspect_scheduling_packet "$(cat "$CURRENT_MANIFEST")" any "$TARGET_KUBERNETES_VERSION")" \
      || die 'could not identify the current scheduling state for disable-schedule'
    CURRENT_SCHEDULING_STATE="$(printf '%s\n' "$CURRENT_PACKET_INSPECTION" | python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])')"
    if [[ "$CURRENT_SCHEDULING_STATE" == active || "$CURRENT_SCHEDULING_STATE" == suspended ]]; then
      CURRENT_CRONJOB_NAME="$(printf '%s\n' "$CURRENT_PACKET_INSPECTION" | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
      [[ -n "$CURRENT_CRONJOB_NAME" ]] || die 'disable-schedule current CronJob name is missing'
      [[ "$CURRENT_CRONJOB_NAME" == "$DISABLE_CRONJOB_NAME" ]] \
        || die 'disable-schedule stored and release-derived CronJob names differ'
    fi
  fi
  capture_live_release "$LIVE_BEFORE_MANIFEST"
  python3 "$PACKET_VALIDATOR" compare-live-desired \
    --release-name "$RELEASE_NAME" --namespace "$NAMESPACE" \
    --desired "$CURRENT_MANIFEST" < "$LIVE_BEFORE_MANIFEST"

  verify_reviewed_sources true
  if ! PRE_WRITE_RENDER="$(render_scheduling_packet "$OPERATION_CHART_DIR" "$OPERATION_BASELINE_VALUES" "$OPERATION_SCHEDULING_OVERLAY" "$TARGET_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" "${EARLY_RENDER_ARGS[@]}")"; then
    die 'frozen scheduling packet changed before release'
  fi
  verify_hash render "$REVIEWED_RENDER_SHA256" "$(sha256_text "$PRE_WRITE_RENDER")"

  if [[ "$OPERATION" == activate-schedule ]]; then
    ACTIVATION_CRONJOB_NAME="$(
      printf '%s\n' "$PACKET_INSPECTION" \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])'
    )"
    [[ -n "$ACTIVATION_CRONJOB_NAME" ]] || die 'activation CronJob name is missing'
    validate_activation_window pre-write
    ACTIVATION_IN_FLIGHT=true
  elif [[ "$OPERATION" == disable-schedule ]]; then
    DISABLE_IN_FLIGHT=true
  fi
  log "applying reviewed $OPERATION packet to $RELEASE_NAME/$NAMESPACE without building or importing an image"
  if ! helm upgrade "$RELEASE_NAME" "$OPERATION_CHART_DIR" \
    --namespace "$NAMESPACE" \
    --values "$OPERATION_BASELINE_VALUES" \
    --values "$OPERATION_SCHEDULING_OVERLAY" \
    --set "image.repository=$FROZEN_IMAGE_REPOSITORY" \
    --set "image.tag=$FROZEN_IMAGE_TAG" \
    --atomic \
    --wait \
    --timeout "$HELM_TIMEOUT"; then
    die "$OPERATION failed; Helm atomic rollback was requested"
  fi

  capture_live_release "$LIVE_AFTER_MANIFEST"
  if ! python3 "$PACKET_VALIDATOR" compare-live-desired \
    --release-name "$RELEASE_NAME" --namespace "$NAMESPACE" \
    --desired "$DESIRED_MANIFEST" < "$LIVE_AFTER_MANIFEST"; then
    die "$OPERATION postcondition failed; target state must be re-audited"
  fi
  if [[ "$REQUIRED_SCHEDULING_STATE" != disabled ]]; then
    CRONJOB_NAME="$(printf '%s\n' "$PACKET_INSPECTION" | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
    kubectl get cronjob "$CRONJOB_NAME" --namespace "$NAMESPACE" -o yaml
  elif [[ "$OPERATION" == disable-schedule ]]; then
    if ! require_exact_cronjob_absent 'disable-schedule postcondition' "$DISABLE_CRONJOB_NAME"; then
      die 'disable-schedule could not prove exact CronJob deletion'
    fi
  fi
  ACTIVATION_IN_FLIGHT=false
  DISABLE_IN_FLIGHT=false
  log "$OPERATION completed; no canary or provider-backed Job was created"
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
