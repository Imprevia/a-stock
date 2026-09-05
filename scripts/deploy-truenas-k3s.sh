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

The command must run on the 1.21 Linux VM. It builds the image from the
repository, smoke-tests it, copies an archive to TrueNAS 1.20, imports it into
k3s/containerd, and installs/upgrades the Helm release.
USAGE
}

ENV_FILE="${DEPLOY_ENV_FILE:-/home/gyt/a-stock/deploy/truenas/deploy.env}"
while (($#)); do
  case "$1" in
    --env-file)
      (($# >= 2)) || die '--env-file requires a path'
      ENV_FILE="$2"
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
GIT_REMOTE="${GIT_REMOTE:-origin}"
GIT_REF="${GIT_REF:-}"
TRUENAS_HOST="${TRUENAS_HOST:-}"
TRUENAS_SSH_USER="${TRUENAS_SSH_USER:-}"
TRUENAS_SSH_PORT="${TRUENAS_SSH_PORT:-22}"
K3S_API_SSH_TUNNEL="${K3S_API_SSH_TUNNEL:-true}"
K3S_API_LOCAL_PORT="${K3S_API_LOCAL_PORT:-16443}"
REMOTE_IMAGE_DIR="${REMOTE_IMAGE_DIR:-}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-localhost/a-stock-market-environment}"
BUILD_PLATFORM="${BUILD_PLATFORM:-linux/amd64}"
NAMESPACE="${NAMESPACE:-a-stock}"
RELEASE_NAME="${RELEASE_NAME:-a-stock}"
HELM_VALUES_FILE="${HELM_VALUES_FILE:-}"
INGRESS_CLASS="${INGRESS_CLASS:-traefik}"
INGRESS_HOST="${INGRESS_HOST:-a-stock.k3s.lan}"
TRUENAS_INGRESS_PORT="${TRUENAS_INGRESS_PORT:-80}"
SCHEDULED_COLLECTION_ENABLED="${SCHEDULED_COLLECTION_ENABLED:-true}"
SCHEDULED_COLLECTION_SUSPEND="${SCHEDULED_COLLECTION_SUSPEND:-true}"
DISABLE_MANUAL_REFRESH="${DISABLE_MANUAL_REFRESH:-true}"
TAILSCALE_HOST="${TAILSCALE_HOST:-gyt.tail0007b1.ts.net}"
TAILSCALE_PORT="${TAILSCALE_PORT:-8443}"
HELM_TIMEOUT="${HELM_TIMEOUT:-5m}"

[[ -d "$REPO_DIR/.git" ]] || die "not a git checkout: $REPO_DIR"
[[ -f "$REPO_DIR/Dockerfile" ]] || die "Dockerfile not found under $REPO_DIR"
[[ -d "$REPO_DIR/deploy/helm/a-stock" ]] || die "Helm chart not found under $REPO_DIR/deploy/helm/a-stock"
[[ -n "$TRUENAS_HOST" ]] || die 'TRUENAS_HOST is required'
[[ -n "$TRUENAS_SSH_USER" ]] || die 'TRUENAS_SSH_USER is required'
[[ -n "$REMOTE_IMAGE_DIR" ]] || die 'REMOTE_IMAGE_DIR is required'
[[ "$GIT_UPDATE" =~ ^(true|false)$ ]] || die 'GIT_UPDATE must be true or false'

for command_name in podman git curl ssh scp sha256sum helm kubectl nc; do
  command -v "$command_name" >/dev/null 2>&1 || die "required command not found: $command_name"
done

cd "$REPO_DIR"
if [[ -n "$HELM_VALUES_FILE" && "$HELM_VALUES_FILE" != /* ]]; then
  HELM_VALUES_FILE="$REPO_DIR/$HELM_VALUES_FILE"
fi
if [[ -n "$HELM_VALUES_FILE" ]]; then
  [[ -f "$HELM_VALUES_FILE" ]] || die "HELM_VALUES_FILE does not exist: $HELM_VALUES_FILE"
fi
if [[ "$GIT_UPDATE" == true ]]; then
  [[ -z "$(git status --porcelain)" ]] || die 'GIT_UPDATE=true requires a clean working tree'
  log "updating repository from $GIT_REMOTE"
  git fetch --tags "$GIT_REMOTE"
  if [[ -n "$GIT_REF" ]]; then
    git checkout "$GIT_REF"
  else
    git pull --ff-only "$GIT_REMOTE"
  fi
fi

if [[ -z "${IMAGE_TAG:-}" ]]; then
  IMAGE_TAG="$(date +%Y%m%d-%H%M%S)-$(git rev-parse --short HEAD)"
fi
IMAGE="${IMAGE_REPOSITORY}:${IMAGE_TAG}"
ARCHIVE_NAME="a-stock-market-environment-${IMAGE_TAG}.tar"

validate_scalar() {
  local name="$1"
  local value="$2"
  [[ "$value" =~ ^[A-Za-z0-9._:/-]+$ ]] || die "$name contains unsupported characters: $value"
}

validate_scalar IMAGE_REPOSITORY "$IMAGE_REPOSITORY"
validate_scalar IMAGE_TAG "$IMAGE_TAG"
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

SSH_TARGET="${TRUENAS_SSH_USER}@${TRUENAS_HOST}"
remote() {
  ssh -o BatchMode=yes -o ConnectTimeout=10 -p "$TRUENAS_SSH_PORT" "$SSH_TARGET" "$@"
}

TMP_DIR="$(mktemp -d -t a-stock-deploy.XXXXXX)"
SMOKE_NAME="a-stock-smoke-$$"
K3S_TUNNEL_PID=''
cleanup() {
  podman rm -f "$SMOKE_NAME" >/dev/null 2>&1 || true
  if [[ -n "$K3S_TUNNEL_PID" ]]; then
    kill "$K3S_TUNNEL_PID" >/dev/null 2>&1 || true
    wait "$K3S_TUNNEL_PID" 2>/dev/null || true
  fi
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

if [[ -n "$(git status --porcelain)" ]]; then
  warn 'working tree is dirty; the image will include the current checkout as-is'
fi

log "checking SSH and non-interactive sudo on $SSH_TARGET"
remote 'sudo -n true' >/dev/null
remote "test -d '$REMOTE_IMAGE_DIR' && test -w '$REMOTE_IMAGE_DIR'" || die "remote image directory is missing or not writable: $REMOTE_IMAGE_DIR"

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
if [[ "$BUILD_PLATFORM" != "linux/${NODE_ARCH}" ]]; then
  warn "build platform $BUILD_PLATFORM differs from node architecture $NODE_ARCH"
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
curl --fail --show-error --silent \
  --retry 15 --retry-all-errors --retry-connrefused --retry-delay 2 \
  http://127.0.0.1:18000/api/health >/dev/null
curl --fail --show-error --silent \
  --retry 5 --retry-all-errors --retry-connrefused --retry-delay 1 \
  http://127.0.0.1:18000/ >/dev/null
podman stop "$SMOKE_NAME" >/dev/null

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

log "installing Helm release $RELEASE_NAME/$NAMESPACE"
helm upgrade --install "$RELEASE_NAME" "$REPO_DIR/deploy/helm/a-stock" \
  --namespace "$NAMESPACE" \
  --create-namespace \
  --values "$VALUES_FILE" \
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
  log 'CronJob is suspended; after a manual Job check, set SCHEDULED_COLLECTION_SUSPEND=false and run this command again'
fi
