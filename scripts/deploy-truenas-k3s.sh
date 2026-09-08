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
  TARGET_KUBERNETES_VERSION="$(normalize_kubernetes_version "$TARGET_KUBERNETES_VERSION")"

  if ! RENDERED_PACKET="$(render_scheduling_packet "$CHART_DIR" "$BASELINE_VALUES_FILE" "$SCHEDULING_OVERLAY_FILE" "$TARGET_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE")"; then
    die 'offline scheduling render failed'
  fi
  if ! PACKET_INSPECTION="$(inspect_scheduling_packet "$RENDERED_PACKET" any "$TARGET_KUBERNETES_VERSION")"; then
    die 'offline scheduling packet validation failed'
  fi
  report_effective_trigger "$PACKET_INSPECTION"
  printf '%s\n' "$RENDERED_PACKET"
  exit 0
fi

if [[ -f "$ENV_FILE" ]]; then
  # The file is an operator-owned local configuration file.
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
else
  die "environment file not found: $ENV_FILE (copy deploy/truenas/deploy.env.example first)"
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
  [[ -n "$REMOTE_IMAGE_DIR" ]] || die 'REMOTE_IMAGE_DIR is required'
fi
[[ "$GIT_UPDATE" =~ ^(true|false)$ ]] || die 'GIT_UPDATE must be true or false'
[[ "$GIT_UPDATE" == false ]] || die 'GIT_UPDATE=true is unsupported; update and review the checkout before launching deployment'

for command_name in git sha256sum helm python3 ssh kubectl nc diff; do
  command -v "$command_name" >/dev/null 2>&1 || die "required command not found: $command_name"
done
python3 -c 'import yaml' >/dev/null 2>&1 || die 'python3 PyYAML is required'
if [[ "$OPERATION" == deploy ]]; then
  for command_name in podman curl scp; do
    command -v "$command_name" >/dev/null 2>&1 || die "required command not found: $command_name"
  done
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
fi
if [[ -n "$GATE_C_AUTHORIZATION_REF" ]]; then
  validate_scalar GATE_C_AUTHORIZATION_REF "$GATE_C_AUTHORIZATION_REF"
fi

case "$OPERATION" in
  server-dry-run|release-suspended|activate-schedule|disable-schedule)
    [[ -n "$HELM_VALUES_FILE" ]] || die "$OPERATION requires baseline values"
    [[ -n "$SCHEDULING_OVERLAY_FILE" ]] || die "$OPERATION requires a scheduling overlay"
    [[ -n "$TARGET_KUBERNETES_VERSION" ]] || die "$OPERATION requires --kube-version"
    ;;
esac
if [[ "$OPERATION" == deploy && -n "$SCHEDULING_OVERLAY_FILE" ]]; then
  die 'ordinary deployment does not accept a scheduling overlay; use an explicit reviewed scheduling mode'
fi

if [[ -n "$TARGET_KUBERNETES_VERSION" ]]; then
  TARGET_KUBERNETES_VERSION="$(normalize_kubernetes_version "$TARGET_KUBERNETES_VERSION")"
fi

EARLY_RENDER_ARGS=()
if [[ -z "$HELM_VALUES_FILE" ]]; then
  EARLY_RENDER_ARGS+=(--set "marketEnvironment.scheduledCollection.enabled=$SCHEDULED_COLLECTION_ENABLED")
  EARLY_RENDER_ARGS+=(--set "marketEnvironment.scheduledCollection.suspend=$SCHEDULED_COLLECTION_SUSPEND")
fi
if [[ "$OPERATION" == release-suspended || "$OPERATION" == activate-schedule || "$OPERATION" == disable-schedule ]]; then
  [[ -n "$FROZEN_IMAGE_REPOSITORY" && -n "$FROZEN_IMAGE_TAG" && -n "$FROZEN_IMAGE_DIGEST" ]] || die "$OPERATION requires frozen image repository, tag, and digest"
  validate_scalar FROZEN_IMAGE_REPOSITORY "$FROZEN_IMAGE_REPOSITORY"
  validate_scalar FROZEN_IMAGE_TAG "$FROZEN_IMAGE_TAG"
  [[ "$FROZEN_IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] || die 'FROZEN_IMAGE_DIGEST must be sha256 followed by 64 lowercase hex characters'
  EARLY_RENDER_ARGS+=(--set "image.repository=$FROZEN_IMAGE_REPOSITORY")
  EARLY_RENDER_ARGS+=(--set "image.tag=$FROZEN_IMAGE_TAG")
fi

if [[ "$OPERATION" != read-only-discovery ]]; then
  LOCAL_KUBERNETES_VERSION="${TARGET_KUBERNETES_VERSION:-1.27.0}"
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
fi

sha256_text() {
  printf '%s\n' "$1" | sha256sum | awk '{print $1}'
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
    ;;
esac

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
cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM HUP
  if [[ "$ACTIVATION_IN_FLIGHT" == true ]]; then
    suspend_after_uncertain_activation "$ACTIVATION_CRONJOB_NAME"
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
  exit "$exit_code"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

OPERATION_CHART_DIR="$REPO_DIR/deploy/helm/a-stock"
OPERATION_BASELINE_VALUES="$HELM_VALUES_FILE"
OPERATION_SCHEDULING_OVERLAY="$SCHEDULING_OVERLAY_FILE"
case "$OPERATION" in
  server-dry-run|release-suspended|activate-schedule|disable-schedule)
    command -v flock >/dev/null 2>&1 || die 'required command not found: flock'
    COMMON_GIT_DIR="$(git rev-parse --git-common-dir)"
    if [[ "$COMMON_GIT_DIR" != /* ]]; then
      COMMON_GIT_DIR="$REPO_DIR/$COMMON_GIT_DIR"
    fi
    exec 9>"$COMMON_GIT_DIR/a-stock-scheduling-release.lock"
    flock -n 9 || die 'another reviewed scheduling operation holds the release lock'
    SNAPSHOT_DIR="$TMP_DIR/reviewed-packet"
    mkdir -p "$SNAPSHOT_DIR"
    cp -R "$REPO_DIR/deploy/helm/a-stock" "$SNAPSHOT_DIR/chart"
    cp "$HELM_VALUES_FILE" "$SNAPSHOT_DIR/baseline.yaml"
    cp "$SCHEDULING_OVERLAY_FILE" "$SNAPSHOT_DIR/overlay.yaml"
    diff -qr "$REPO_DIR/deploy/helm/a-stock" "$SNAPSHOT_DIR/chart" >/dev/null || die 'chart changed while freezing the reviewed packet'
    verify_hash baseline "$REVIEWED_BASELINE_SHA256" "$(sha256sum "$SNAPSHOT_DIR/baseline.yaml" | awk '{print $1}')"
    verify_hash overlay "$REVIEWED_OVERLAY_SHA256" "$(sha256sum "$SNAPSHOT_DIR/overlay.yaml" | awk '{print $1}')"
    if ! SNAPSHOT_RENDER="$(render_scheduling_packet "$SNAPSHOT_DIR/chart" "$SNAPSHOT_DIR/baseline.yaml" "$SNAPSHOT_DIR/overlay.yaml" "$LOCAL_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" "${EARLY_RENDER_ARGS[@]}")"; then
      die 'frozen scheduling packet render failed'
    fi
    verify_hash render "$REVIEWED_RENDER_SHA256" "$(sha256_text "$SNAPSHOT_RENDER")"
    chmod -R a-w "$SNAPSHOT_DIR"
    RENDERED_PACKET="$SNAPSHOT_RENDER"
    OPERATION_CHART_DIR="$SNAPSHOT_DIR/chart"
    OPERATION_BASELINE_VALUES="$SNAPSHOT_DIR/baseline.yaml"
    OPERATION_SCHEDULING_OVERLAY="$SNAPSHOT_DIR/overlay.yaml"
    log "reviewed packet binding: head=$REVIEWED_GIT_HEAD chart=$REVIEWED_CHART_SHA256 baseline=$REVIEWED_BASELINE_SHA256 overlay=$REVIEWED_OVERLAY_SHA256 render=$REVIEWED_RENDER_SHA256"
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
  fi
  ACTIVATION_IN_FLIGHT=false
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
  cp "$HELM_VALUES_FILE" "$VALUES_FILE"
fi

if ! RENDERED_PACKET="$(render_scheduling_packet "$REPO_DIR/deploy/helm/a-stock" "$VALUES_FILE" "$SCHEDULING_OVERLAY_FILE" "$TARGET_KUBERNETES_VERSION" "$RELEASE_NAME" "$NAMESPACE" --set "image.repository=$IMAGE_REPOSITORY" --set "image.tag=$IMAGE_TAG")"; then
  die 'final deployment values failed target-version rendering before build'
fi
if ! PACKET_INSPECTION="$(inspect_scheduling_packet "$RENDERED_PACKET" disabled "$TARGET_KUBERNETES_VERSION")"; then
  die 'normal deployment cannot create or activate scheduled collection'
fi

log "building $IMAGE"
helm lint --strict "$REPO_DIR/deploy/helm/a-stock"
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

HELM_VALUES_ARGS=(--values "$VALUES_FILE")
if [[ -n "$SCHEDULING_OVERLAY_FILE" ]]; then
  HELM_VALUES_ARGS+=(--values "$SCHEDULING_OVERLAY_FILE")
fi

log "installing Helm release $RELEASE_NAME/$NAMESPACE"
helm upgrade --install "$RELEASE_NAME" "$REPO_DIR/deploy/helm/a-stock" \
  --namespace "$NAMESPACE" \
  --create-namespace \
  "${HELM_VALUES_ARGS[@]}" \
  --set "image.repository=$IMAGE_REPOSITORY" \
  --set "image.tag=$IMAGE_TAG" \
  --wait \
  --timeout "$HELM_TIMEOUT"

DEPLOYMENT_NAME="$(kubectl -n "$NAMESPACE" get deployment \
  -l "app.kubernetes.io/instance=$RELEASE_NAME" \
  -o jsonpath='{.items[0].metadata.name}')"
[[ -n "$DEPLOYMENT_NAME" ]] || die 'Helm completed but no Dashboard Deployment was found'
kubectl -n "$NAMESPACE" rollout status "deployment/$DEPLOYMENT_NAME" --timeout=180s
kubectl -n "$NAMESPACE" get deployment,pods,service,ingress,pvc

log "checking the deployment endpoint through $TRUENAS_HOST:$TRUENAS_INGRESS_PORT"
curl --fail --show-error --silent \
  --max-time 15 \
  --header "Host: $INGRESS_HOST" \
  "http://${TRUENAS_HOST}:${TRUENAS_INGRESS_PORT}/api/health" >/dev/null

log 'deployment completed'
log "internal URL: http://${TRUENAS_HOST}:${TRUENAS_INGRESS_PORT}/"
log "Tailscale URL after NGINX is configured: https://${TAILSCALE_HOST}:${TAILSCALE_PORT}/"
if [[ -n "$HELM_VALUES_FILE" ]]; then
  log "scheduled collection settings follow $HELM_VALUES_FILE"
elif [[ "$SCHEDULED_COLLECTION_SUSPEND" == true ]]; then
  log 'CronJob is suspended; do not unsuspend without accepted Gate B canary evidence and separate Gate C authorization'
fi
