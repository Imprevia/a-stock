#!/bin/bash
# a-stock TrueNAS k3s 开机网络修复执行体
#
# TrueNAS 的 k3s 编排由 middlewared 管理：CNI 清单在 middleware 的 post_start 阶段
# 生成，k3s.service 与 middleware 同属 multi-user.target 并行启动，开机时 k3s 可能
# 先于 /etc/cni/net.d 完成初始化，从而停在 NetworkPluginNotReady，节点长期 NotReady。
#
# 另外 middlewared 的 add_routes_to_kube_router_table() 只在 post_start 执行一次，
# 之后不再重试；一旦错过 kube-bridge 上线的窗口，kube-router 策略路由表只剩默认
# 路由，宿主机发往 Pod 网段的流量会被送往管理网桥而丢弃，Pod 探针与 NodePort 全部超时。
#
# 本脚本只做两件事，且都是幂等的：
#   1. 在 kube-router 路由表补齐 cluster-cidr 指向 kube-bridge 的直连路由，
#      以及缺失时的 32764 策略规则；
#   2. 当节点因 CNI 未初始化而不 Ready 时，在本次开机内最多重启一次 k3s。
# 它不接管 CNI 清单、不修改 kube-router 单元、不触碰 Helm release 或业务对象。

set -uo pipefail

readonly PROGRAM=${0##*/}
readonly DEFAULT_CLUSTER_CIDR=172.16.0.0/16
readonly DEFAULT_BRIDGE=kube-bridge
readonly DEFAULT_TABLE=kube-router
readonly RULE_PRIORITY=32764

BRIDGE=${A_STOCK_K3S_REPAIR_BRIDGE:-$DEFAULT_BRIDGE}
TABLE=${A_STOCK_K3S_REPAIR_TABLE:-$DEFAULT_TABLE}
K3S_CONFIG_FILE=${A_STOCK_K3S_REPAIR_CONFIG:-/etc/rancher/k3s/config.yaml}
CNI_CONF_DIR=${A_STOCK_K3S_REPAIR_CNI_DIR:-/etc/cni/net.d}
SYS_CLASS_NET=${A_STOCK_K3S_REPAIR_SYS_CLASS_NET:-/sys/class/net}
STATE_DIR=${A_STOCK_K3S_REPAIR_STATE_DIR:-/run/a-stock-k3s-network-repair}
WAIT_SECONDS=${A_STOCK_K3S_REPAIR_WAIT_SECONDS:-180}
NODE_WAIT_SECONDS=${A_STOCK_K3S_REPAIR_NODE_WAIT_SECONDS:-120}
POLL_SECONDS=${A_STOCK_K3S_REPAIR_POLL_SECONDS:-2}

log() {
    printf '%s %s: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$PROGRAM" "$*"
}

fail() {
    log "错误：$*"
    return 1
}

usage() {
    cat <<'EOF'
用法：k3s-network-repair.sh [sync|check]

  sync   补齐 kube-router 策略路由，并在 CNI 就绪后确保 k3s 重新达到 Ready（默认）
  check  只读核对路由、策略规则与节点状态，需要修复时以退出码 1 结束
EOF
}

ipv4_to_int() {
    local a b c d
    IFS=. read -r a b c d <<<"$1"
    printf '%s\n' "$(( (10#$a << 24) | (10#$b << 16) | (10#$c << 8) | 10#$d ))"
}

cidr_mask() {
    local prefix=$1
    if (( prefix == 0 )); then
        printf '0\n'
        return 0
    fi
    printf '%s\n' "$(( (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF ))"
}

# 校验 IPv4 CIDR：格式、每个八位组取值范围与前缀长度。
validate_cidr() {
    local cidr=$1 octet prefix
    if [[ ! $cidr =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})/([0-9]{1,2})$ ]]; then
        fail "cluster-cidr '$cidr' 不是 IPv4 CIDR"
        return 1
    fi
    for octet in "${BASH_REMATCH[@]:1:4}"; do
        if (( 10#$octet > 255 )); then
            fail "cluster-cidr '$cidr' 含非法八位组 '$octet'"
            return 1
        fi
    done
    prefix=${BASH_REMATCH[5]}
    if (( 10#$prefix > 30 )); then
        fail "cluster-cidr '$cidr' 前缀长度必须不大于 30"
        return 1
    fi
    return 0
}

# 节点名不能直接用 hostname：TrueNAS 主机名是 `truenas`，而 k3s 节点名由 middleware
# 注册为 `ix-truenas`，用 hostname 查询会永远查不到 Ready。按显式覆盖、k3s 配置、
# 集群实际节点、hostname 的顺序解析；集群多于一个节点时不猜测，退回 hostname 并记录告警。
resolve_node_name() {
    local name="" nodes
    if [[ -n ${A_STOCK_K3S_REPAIR_NODE_NAME:-} ]]; then
        name=$A_STOCK_K3S_REPAIR_NODE_NAME
    elif [[ -r $K3S_CONFIG_FILE ]]; then
        name=$(awk '$1 == "node-name:" { print $2; exit }' "$K3S_CONFIG_FILE")
    fi
    if [[ -z $name ]]; then
        nodes=$(k3s kubectl get nodes -o jsonpath='{.items[*].metadata.name}' 2>/dev/null)
        if [[ -n $nodes && $nodes != *" "* ]]; then
            name=$nodes
        elif [[ -n $nodes ]]; then
            log "告警：集群有多个节点（$nodes），无法确定本机节点名，回退 hostname；请设置 A_STOCK_K3S_REPAIR_NODE_NAME"
        fi
    fi
    if [[ -z $name ]]; then
        name=$(hostname)
    fi
    printf '%s\n' "$name"
}

node_name() {
    printf '%s\n' "$NODE_NAME"
}

# cluster-cidr 以 k3s 配置文件为准；配置缺失时依次回退到节点 podCIDR 与内置默认值。
resolve_cluster_cidr() {
    local value=""
    if [[ -r $K3S_CONFIG_FILE ]]; then
        value=$(awk '$1 == "cluster-cidr:" { print $2; exit }' "$K3S_CONFIG_FILE")
    fi
    if [[ -z $value ]]; then
        value=$(k3s kubectl get node "$(node_name)" -o jsonpath='{.spec.podCIDR}' 2>/dev/null)
    fi
    if [[ -z $value ]]; then
        value=$DEFAULT_CLUSTER_CIDR
    fi
    printf '%s\n' "$value"
}

cni_conf_present() {
    compgen -G "$CNI_CONF_DIR/*.conflist" >/dev/null && return 0
    compgen -G "$CNI_CONF_DIR/*.conf" >/dev/null && return 0
    return 1
}

wait_for_cni_conf() {
    local deadline=$(( SECONDS + WAIT_SECONDS ))
    while (( SECONDS < deadline )); do
        if cni_conf_present; then
            log "CNI 清单已存在（$CNI_CONF_DIR）"
            return 0
        fi
        sleep "$POLL_SECONDS"
    done
    fail "${WAIT_SECONDS}s 内未出现 $CNI_CONF_DIR 下的 CNI 清单"
}

bridge_is_up() {
    local state_file=$SYS_CLASS_NET/$BRIDGE/operstate
    [[ -r $state_file ]] || return 1
    local state
    state=$(<"$state_file") || return 1
    [[ $state == up || $state == unknown ]]
}

wait_for_bridge() {
    local deadline=$(( SECONDS + WAIT_SECONDS ))
    while (( SECONDS < deadline )); do
        if bridge_is_up; then
            log "网桥 $BRIDGE 已就绪"
            return 0
        fi
        sleep "$POLL_SECONDS"
    done
    fail "${WAIT_SECONDS}s 内未等到 $BRIDGE 进入 up 状态"
}

# 管理与集群网段重叠会让策略路由把管理流量送进 Pod 网桥，必须 fail closed。
ensure_no_management_overlap() {
    local cidr=$1 iface cluster_int cluster_mask addr net mask
    iface=$(ip -4 route show default 2>/dev/null |
        awk '{ for (i = 1; i <= NF; i++) if ($i == "dev") { print $(i + 1); exit } }')
    if [[ -z $iface || $iface == "$BRIDGE" ]]; then
        return 0
    fi
    cluster_int=$(ipv4_to_int "${cidr%%/*}")
    cluster_mask=$(cidr_mask "${cidr##*/}")
    while read -r addr; do
        [[ -n $addr ]] || continue
        net=$(ipv4_to_int "${addr%%/*}")
        mask=$(cidr_mask "${addr##*/}")
        if (( (net & mask & cluster_mask) == (cluster_int & cluster_mask) )); then
            fail "cluster-cidr '$cidr' 与管理网段 '$addr'（$iface）重叠"
            return 1
        fi
    done < <(ip -4 -o addr show dev "$iface" scope global 2>/dev/null | awk '{ print $4 }')
    return 0
}

route_interface() {
    local cidr=$1
    ip route show table "$TABLE" "$cidr" 2>/dev/null |
        awk '{ for (i = 1; i <= NF; i++) if ($i == "dev") { print $(i + 1); exit } }'
}

ensure_route() {
    local cidr=$1 current
    current=$(route_interface "$cidr")
    if [[ $current == "$BRIDGE" ]]; then
        log "路由表 $TABLE 已含 $cidr dev $BRIDGE"
        return 0
    fi
    if [[ -n $current ]]; then
        log "路由表 $TABLE 中 $cidr 指向 $current，改写为 $BRIDGE"
    fi
    if ! ip route replace "$cidr" dev "$BRIDGE" scope link table "$TABLE"; then
        fail "写入路由 $cidr dev $BRIDGE table $TABLE 失败（需要 root 权限）"
        return 1
    fi
    log "已写入路由 $cidr dev $BRIDGE table $TABLE"
}

rule_present() {
    local cidr=$1
    ip rule show 2>/dev/null | awk -v cidr="$cidr" -v tbl="$TABLE" '
        $1 == "32764:" && $2 == "from" && $3 == cidr && $4 == "lookup" && $5 == tbl { found = 1 }
        END { exit found ? 0 : 1 }
    '
}

ensure_rule() {
    local cidr=$1
    if rule_present "$cidr"; then
        log "策略规则 from $cidr lookup $TABLE 已存在"
        return 0
    fi
    if ! ip rule add from "$cidr" lookup "$TABLE" priority "$RULE_PRIORITY"; then
        fail "写入策略规则 from $cidr lookup $TABLE 失败（需要 root 权限）"
        return 1
    fi
    log "已写入策略规则 from $cidr lookup $TABLE priority $RULE_PRIORITY"
}

service_is_active() {
    systemctl is-active --quiet "$1"
}

node_condition() {
    local field=$1
    k3s kubectl get node "$(node_name)" \
        -o jsonpath="{.status.conditions[?(@.type==\"Ready\")].$field}" 2>/dev/null
}

node_is_ready() {
    [[ $(node_condition status) == True ]]
}

wait_for_node_ready() {
    local seconds=${1:-$NODE_WAIT_SECONDS}
    local deadline=$(( SECONDS + seconds ))
    while (( SECONDS < deadline )); do
        if node_is_ready; then
            return 0
        fi
        sleep "$POLL_SECONDS"
    done
    return 1
}

restart_budget_file() {
    printf '%s/k3s-restarts\n' "$STATE_DIR"
}

read_restart_count() {
    local file count=""
    file=$(restart_budget_file)
    if [[ -r $file ]]; then
        read -r count <"$file" || true
    fi
    if [[ ! $count =~ ^[0-9]+$ ]]; then
        count=0
    fi
    printf '%s\n' "$count"
}

# 只在 kubelet 明确报出 CNI 未初始化时重启，避免对无关故障抖动整个控制面。
restart_needed() {
    local message
    message="$(node_condition message) $(node_condition reason)"
    [[ $message == *"cni plugin not initialized"* || $message == *NetworkPluginNotReady* ]]
}

repair_k3s_health() {
    if ! service_is_active k3s.service; then
        log "k3s.service 未处于 active，尝试启动"
        if ! systemctl start k3s.service; then
            fail "systemctl start k3s.service 失败"
            return 1
        fi
    fi

    if wait_for_node_ready; then
        log "节点 $(node_name) 已 Ready"
        return 0
    fi

    if ! restart_needed; then
        fail "节点 $(node_name) 仍未 Ready，且原因不是 CNI 未初始化，拒绝重启 k3s"
        return 1
    fi

    if (( $(read_restart_count) >= 1 )); then
        fail "本次开机已重启过 k3s 且仍为 CNI 未初始化，交由人工处理"
        return 1
    fi

    log "节点因 CNI 未初始化未就绪，重启 k3s.service（本次开机首次）"
    if ! { mkdir -p "$STATE_DIR" && printf '1\n' >"$(restart_budget_file)"; }; then
        fail "无法记录重启预算到 $STATE_DIR"
        return 1
    fi
    if ! systemctl restart k3s.service; then
        fail "systemctl restart k3s.service 失败"
        return 1
    fi
    if ! wait_for_node_ready; then
        fail "重启 k3s 后节点仍未 Ready"
        return 1
    fi
    log "重启 k3s 后节点 $(node_name) 已 Ready"
}

run_sync() {
    local cidr source=$K3S_CONFIG_FILE
    cidr=$(resolve_cluster_cidr)
    validate_cidr "$cidr" || return 1
    if [[ ! -r $K3S_CONFIG_FILE ]]; then
        source="podCIDR 或内置默认值"
    fi
    log "使用 cluster-cidr $cidr（来源 $source）"

    wait_for_cni_conf || return 1
    wait_for_bridge || return 1
    ensure_no_management_overlap "$cidr" || return 1
    ensure_route "$cidr" || return 1
    ensure_rule "$cidr" || return 1
    repair_k3s_health || return 1
}

run_check() {
    local cidr problems=0
    cidr=$(resolve_cluster_cidr)
    validate_cidr "$cidr" || return 1
    printf 'cluster-cidr: %s\n' "$cidr"
    if service_is_active k3s.service; then
        printf 'k3s.service: active\n'
    else
        printf 'k3s.service: inactive\n'
        problems=$(( problems + 1 ))
    fi
    if cni_conf_present; then
        printf 'CNI 清单: 存在\n'
    else
        printf 'CNI 清单: 缺失\n'
        problems=$(( problems + 1 ))
    fi
    if bridge_is_up; then
        printf '网桥 %s: up\n' "$BRIDGE"
    else
        printf '网桥 %s: 不可用\n' "$BRIDGE"
        problems=$(( problems + 1 ))
    fi
    if [[ $(route_interface "$cidr") == "$BRIDGE" ]]; then
        printf '路由表 %s: %s dev %s\n' "$TABLE" "$cidr" "$BRIDGE"
    else
        printf '路由表 %s: 缺少 %s dev %s\n' "$TABLE" "$cidr" "$BRIDGE"
        problems=$(( problems + 1 ))
    fi
    if rule_present "$cidr"; then
        printf '策略规则: from %s lookup %s\n' "$cidr" "$TABLE"
    else
        printf '策略规则: 缺少 from %s lookup %s\n' "$cidr" "$TABLE"
        problems=$(( problems + 1 ))
    fi
    if node_is_ready; then
        printf '节点 %s: Ready\n' "$(node_name)"
    else
        printf '节点 %s: 非 Ready\n' "$(node_name)"
        problems=$(( problems + 1 ))
    fi
    if (( problems > 0 )); then
        printf '核查结果：需要修复（%d 项）\n' "$problems"
        return 1
    fi
    printf '核查结果：全部就绪\n'
    return 0
}

main() {
    local mode=${1:-sync}
    NODE_NAME=$(resolve_node_name)
    export NODE_NAME
    case $mode in
        sync) run_sync ;;
        check) run_check ;;
        -h | --help | help) usage ;;
        *) usage >&2; return 2 ;;
    esac
}

main "$@"