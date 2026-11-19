#!/bin/bash
# 在 TrueNAS 上安装/核查 a-stock k3s 开机网络修复单元。
#
# 用法：
#   sudo bash deploy/truenas/install-k3s-network-repair.sh            安装并启用
#   sudo bash deploy/truenas/install-k3s-network-repair.sh --check    只读核查漂移
#
# 只写入两个主机路径：/usr/local/libexec/a-stock/k3s-network-repair.sh 与
# /etc/systemd/system/a-stock-k3s-network-repair.service。
# 不修改 CNI 清单、kube-router 单元、k3s 配置、Helm release 或任何业务对象。

set -euo pipefail

readonly UNIT_NAME=a-stock-k3s-network-repair.service
readonly SCRIPT_TARGET=/usr/local/libexec/a-stock/k3s-network-repair.sh
readonly UNIT_TARGET=/etc/systemd/system/$UNIT_NAME
readonly SOURCE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/systemd
readonly SCRIPT_SOURCE=$SOURCE_DIR/k3s-network-repair.sh
readonly UNIT_SOURCE=$SOURCE_DIR/$UNIT_NAME

log() { printf '%s\n' "$*"; }
fail() {
    printf '错误：%s\n' "$*" >&2
    exit 1
}

mode=${1:-install}
case $mode in
    install | --check | check) ;;
    -h | --help | help)
        sed -n '2,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
        exit 0
        ;;
    *) fail "未知参数：$mode（支持 install 与 --check）" ;;
esac

[[ -r $SCRIPT_SOURCE ]] || fail "缺少执行体源文件 $SCRIPT_SOURCE"
[[ -r $UNIT_SOURCE ]] || fail "缺少单元源文件 $UNIT_SOURCE"

if [[ $mode == install ]]; then
    dependencies=(bash ip awk systemctl install)
    for dependency in "${dependencies[@]}"; do
        command -v "$dependency" >/dev/null || fail "缺少命令 $dependency"
    done
    (( EUID == 0 )) || fail "安装需要 root 权限"
fi

files_match() {
    local source=$1 target=$2
    [[ -r $target ]] && cmp -s "$source" "$target"
}

drift=0
if files_match "$SCRIPT_SOURCE" "$SCRIPT_TARGET"; then
    log "执行体已是最新：$SCRIPT_TARGET"
else
    log "执行体漂移：$SCRIPT_TARGET"
    drift=1
fi
if files_match "$UNIT_SOURCE" "$UNIT_TARGET"; then
    log "单元已是最新：$UNIT_TARGET"
else
    log "单元漂移：$UNIT_TARGET"
    drift=1
fi
if systemctl is-enabled --quiet "$UNIT_NAME" 2>/dev/null; then
    log "单元已启用：$UNIT_NAME"
else
    log "单元未启用：$UNIT_NAME"
    drift=1
fi
if systemctl is-active --quiet "$UNIT_NAME" 2>/dev/null; then
    log "单元处于 active：$UNIT_NAME"
else
    log "单元未处于 active：$UNIT_NAME"
    drift=1
fi

if [[ $mode != install ]]; then
    if (( drift == 0 )); then
        log "核查结果：主机与仓库一致"
    else
        log "核查结果：存在漂移，需重新执行安装"
    fi
    exit "$drift"
fi

install -D -m 0755 "$SCRIPT_SOURCE" "$SCRIPT_TARGET"
install -D -m 0644 "$UNIT_SOURCE" "$UNIT_TARGET"
log "已写入 $SCRIPT_TARGET 与 $UNIT_TARGET"

systemctl daemon-reload
systemctl enable "$UNIT_NAME"
# RemainAfterExit=yes 使单元在成功后保持 active，重复 `start` 不会再执行 ExecStart；
# 安装与升级必须用 restart 才能让新版本立刻跑一次真实修复。
systemctl restart "$UNIT_NAME"
log "已启用并执行 $UNIT_NAME"

if ! bash "$SCRIPT_TARGET" check; then
    fail "安装后的只读核查未通过，请查看 journalctl -u $UNIT_NAME"
fi
log "安装完成，只读核查通过"