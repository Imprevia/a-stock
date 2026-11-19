"""TrueNAS k3s 开机网络修复受管单元的离线回归测试。

这些测试不接触真实主机：`ip`、`systemctl` 与 `k3s` 全部由临时目录里的
stub 替换，`/sys/class/net` 由 `A_STOCK_K3S_REPAIR_SYS_CLASS_NET` 重定向。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SYSTEMD_DIR = ROOT / "deploy" / "truenas" / "systemd"
REPAIR_SCRIPT = SYSTEMD_DIR / "k3s-network-repair.sh"
UNIT_FILE = SYSTEMD_DIR / "a-stock-k3s-network-repair.service"
INSTALLER = ROOT / "deploy" / "truenas" / "install-k3s-network-repair.sh"

BASH = shutil.which("bash")

# 每个 stub 都把调用追加到 $STUB_LOG，并把状态读写限制在 $STUB_STATE，
# 这样测试断言的是“发生了哪些调用”，而不是输出文本。
IP_STUB = r"""#!/bin/bash
set -uo pipefail
printf 'ip %s\n' "$*" >>"$STUB_LOG"
state=$STUB_STATE
key() { printf '%s' "${1//\//_}"; }
verb="$1 $2"
shift 2
case "$verb" in
    "route show")
        if [[ ${1:-} == table ]]; then
            shift
            cidr=${2:-}
            [[ -n $cidr ]] || exit 0
            iface=$(cat "$state/route-$(key "$cidr")" 2>/dev/null) || exit 0
            [[ -n $iface ]] && printf '%s dev %s scope link\n' "$cidr" "$iface"
        else
            cat "$state/default-route" 2>/dev/null || exit 0
        fi
        ;;
    "route replace")
        cidr=$1
        iface=$3
        printf '%s' "$iface" >"$state/route-$(key "$cidr")"
        ;;
    "rule show")
        cat "$state/rules" 2>/dev/null || exit 0
        ;;
    "rule add")
        printf '%s\n' "ip rule add $*" >>"$state/rule-adds"
        ;;
    "-4 -o")
        # ip -4 -o addr show dev <dev> scope global
        dev=$4
        cat "$state/addr-$dev" 2>/dev/null || exit 0
        ;;
    "-4 route")
        cat "$state/default-route" 2>/dev/null || exit 0
        ;;
    *)
        echo "unexpected ip invocation: $verb $*" >&2
        exit 90
        ;;
esac
exit 0
"""

SYSTEMCTL_STUB = r"""#!/bin/bash
set -uo pipefail
printf 'systemctl %s\n' "$*" >>"$STUB_LOG"
state=$STUB_STATE
case "$1" in
    is-active)
        unit=$3
        [[ $(cat "$state/unit-$unit" 2>/dev/null || echo inactive) == active ]]
        exit
        ;;
    is-enabled)
        unit=$3
        [[ $(cat "$state/enabled-$unit" 2>/dev/null || echo disabled) == enabled ]]
        exit
        ;;
    start)
        printf 'active' >"$state/unit-$2"
        ;;
    restart)
        printf '%s\n' "systemctl $*" >>"$state/restarts"
        printf 'active' >"$state/unit-$2"
        # 默认模拟“重启后 CNI 恢复”；restart-does-not-heal 存在时保持 NotReady。
        [[ -e $state/restart-does-not-heal ]] || printf 'Ready' >"$state/node-ready"
        ;;
    *)
        echo "unexpected systemctl invocation: $*" >&2
        exit 90
        ;;
esac
exit 0
"""

K3S_STUB = r"""#!/bin/bash
set -uo pipefail
printf 'k3s %s\n' "$*" >>"$STUB_LOG"
state=$STUB_STATE
[[ $1 == kubectl ]] || exit 90
ready=$(cat "$state/node-ready" 2>/dev/null || echo NotReady)
# 复刻 kubectl 语义：查询不存在的节点没有任何输出，等价于 NotReady。
queried=""
for word in "$@"; do
    case $word in
        node) shift_next=1 ;;
        *) if [[ ${shift_next:-0} == 1 ]]; then queried=$word; shift_next=0; fi ;;
    esac
done
known="$(cat "$state/nodes" 2>/dev/null) $(cat "$state/extra-nodes" 2>/dev/null)"
node_exists=1
if [[ -n $queried ]]; then
    node_exists=0
    for candidate in $known; do
        [[ $candidate == "$queried" ]] && node_exists=1
    done
fi
case "$*" in
    *get\ nodes*) cat "$state/nodes" 2>/dev/null || exit 0 ;;
    *podCIDR*)
        (( node_exists )) || exit 0
        cat "$state/pod-cidr" 2>/dev/null || exit 0
        ;;
    *conditions*status*)
        if (( node_exists )) && [[ $ready == Ready ]]; then printf 'True'; else printf 'False'; fi
        ;;
    *conditions*message*) (( node_exists )) || exit 0; [[ $ready == Ready ]] || cat "$state/node-message" 2>/dev/null ;;
    *conditions*reason*) (( node_exists )) || exit 0; [[ $ready == Ready ]] || cat "$state/node-reason" 2>/dev/null ;;
    *)
        echo "unexpected k3s invocation: $*" >&2
        exit 90
        ;;
esac
exit 0
"""


class Host:
    """一台被 stub 化的“主机”：PATH、状态目录与 sysfs 替身。"""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.bin_dir = tmp_path / "bin"
        self.state_dir = tmp_path / "state"
        self.sys_class_net = tmp_path / "sys-class-net"
        self.log = tmp_path / "calls.log"
        self.cni_dir = tmp_path / "cni"
        self.config = tmp_path / "k3s-config.yaml"
        self.run_dir = tmp_path / "run"

        self.bin_dir.mkdir()
        self.state_dir.mkdir()
        self.sys_class_net.mkdir()
        self.cni_dir.mkdir()
        self.log.write_text("", encoding="utf-8")

        for name, body in (
            ("ip", IP_STUB),
            ("systemctl", SYSTEMCTL_STUB),
            ("k3s", K3S_STUB),
        ):
            target = self.bin_dir / name
            target.write_text(body, encoding="utf-8")
            target.chmod(0o755)

        self.set_unit_active("k3s.service", True)
        self.set_unit_active("kube-router.service", True)
        self.set_node_ready(True)
        self.set_bridge_up(True)
        self.set_route("172.16.0.0/16", "kube-bridge")
        self.set_rule_present(True)
        self.set_default_iface("br0")
        self.set_addr("br0", "192.168.1.20/24")
        self.set_cluster_cidr("172.16.0.0/16")
        self.set_cni_conf(True)
        self.set_nodes("ix-truenas")

    # --- 主机状态构造 -------------------------------------------------
    def path(self, name: str) -> Path:
        return self.state_dir / name

    @staticmethod
    def route_key(cidr: str) -> str:
        return cidr.replace("/", "_")

    def set_unit_active(self, unit: str, active: bool) -> None:
        self.path(f"unit-{unit}").write_text("active" if active else "inactive", encoding="utf-8")

    def set_node_ready(self, ready: bool) -> None:
        self.path("node-ready").write_text("Ready" if ready else "NotReady", encoding="utf-8")

    def set_node_failure(self, reason: str, message: str) -> None:
        self.set_node_ready(False)
        self.path("node-reason").write_text(reason, encoding="utf-8")
        self.path("node-message").write_text(message, encoding="utf-8")

    def set_bridge_up(self, up: bool) -> None:
        bridge_dir = self.sys_class_net / "kube-bridge"
        bridge_dir.mkdir(exist_ok=True)
        (bridge_dir / "operstate").write_text("up" if up else "down", encoding="utf-8")

    def set_cni_conf(self, present: bool) -> None:
        conflist = self.cni_dir / "10-kuberouter.conflist"
        if present:
            conflist.write_text("{}\n", encoding="utf-8")
        elif conflist.exists():
            conflist.unlink()

    def set_route(self, cidr: str, iface: str | None) -> None:
        target = self.path(f"route-{self.route_key(cidr)}")
        if iface is None:
            if target.exists():
                target.unlink()
        else:
            target.write_text(iface, encoding="utf-8")

    def route_iface(self, cidr: str) -> str | None:
        target = self.path(f"route-{self.route_key(cidr)}")
        return target.read_text(encoding="utf-8") if target.exists() else None

    def set_rule_present(self, present: bool) -> None:
        self.path("rules").write_text(
            "0:\tfrom all lookup local\n"
            + ("32764:\tfrom 172.16.0.0/16 lookup kube-router\n" if present else "")
            + "32766:\tfrom all lookup main\n",
            encoding="utf-8",
        )

    def set_default_iface(self, iface: str) -> None:
        self.path("default-route").write_text(
            f"default via 192.168.1.1 dev {iface} proto static\n", encoding="utf-8"
        )

    def set_addr(self, dev: str, cidr: str) -> None:
        # 复刻 `ip -4 -o addr` 的真实列序：序号、设备、inet、CIDR。
        self.path(f"addr-{dev}").write_text(
            f"7: {dev}    inet {cidr} brd + scope global {dev}\n", encoding="utf-8"
        )

    def set_nodes(self, *names: str) -> None:
        """设置 `kubectl get nodes` 的返回；多于一个时脚本应判定为歧义。"""
        self.path("nodes").write_text(" ".join(names), encoding="utf-8")

    def set_extra_nodes(self, *names: str) -> None:
        """额外声明“集群里存在”的节点名，用于 node 级查询，不影响歧义判定。"""
        self.path("extra-nodes").write_text(" ".join(names), encoding="utf-8")

    def set_cluster_cidr(self, cidr: str) -> None:
        self.config.write_text(f"cluster-cidr: {cidr}\n", encoding="utf-8")

    def restarts(self) -> list[str]:
        target = self.path("restarts")
        if not target.exists():
            return []
        return [line for line in target.read_text(encoding="utf-8").splitlines() if line]

    def rule_adds(self) -> list[str]:
        target = self.path("rule-adds")
        if not target.exists():
            return []
        return [line for line in target.read_text(encoding="utf-8").splitlines() if line]

    def calls(self, since: int = 0) -> list[str]:
        lines = [line for line in self.log.read_text(encoding="utf-8").splitlines() if line]
        return lines[since:]

    def call_count(self) -> int:
        return len(self.calls())

    # --- 运行 ---------------------------------------------------------
    def run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return self.run_with_node_name(arguments[0], *arguments[1:])

    def run_with_node_name(
        self, mode: str, node_name: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": f"{self.bin_dir}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}",
            "STUB_LOG": str(self.log),
            "STUB_STATE": str(self.state_dir),
            "A_STOCK_K3S_REPAIR_CONFIG": str(self.config),
            "A_STOCK_K3S_REPAIR_CNI_DIR": str(self.cni_dir),
            "A_STOCK_K3S_REPAIR_STATE_DIR": str(self.run_dir),
            "A_STOCK_K3S_REPAIR_SYS_CLASS_NET": str(self.sys_class_net),
            "A_STOCK_K3S_REPAIR_WAIT_SECONDS": "1",
            "A_STOCK_K3S_REPAIR_POLL_SECONDS": "0.1",
            "A_STOCK_K3S_REPAIR_NODE_WAIT_SECONDS": "1",
            "HOME": str(self.tmp_path),
        }
        if node_name is not None:
            env["A_STOCK_K3S_REPAIR_NODE_NAME"] = node_name
        return subprocess.run(
            [BASH, str(REPAIR_SCRIPT), mode],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
            check=False,
        )


@pytest.fixture()
def host(tmp_path: Path) -> Host:
    assert BASH, "离线测试需要 bash"
    return Host(tmp_path)


# --- 资产约束 ---------------------------------------------------------
def test_repair_assets_exist_and_are_executable() -> None:
    assert REPAIR_SCRIPT.is_file()
    assert UNIT_FILE.is_file()
    assert INSTALLER.is_file()
    assert os.access(REPAIR_SCRIPT, os.X_OK), "执行体必须可执行"
    assert os.access(INSTALLER, os.X_OK), "安装入口必须可执行"


@pytest.mark.parametrize("script", [REPAIR_SCRIPT, INSTALLER], ids=lambda path: path.name)
def test_scripts_parse_and_avoid_destructive_commands(script: Path) -> None:
    completed = subprocess.run(
        [BASH, "-n", str(script)], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr

    content = script.read_text(encoding="utf-8")
    for forbidden in (
        "kubectl delete",
        "helm uninstall",
        "helm rollback",
        "rm -rf /",
        "mkfs",
        "iptables -F",
        "reboot",
        "shutdown -",
        "\ndocker ",
    ):
        assert forbidden not in content, f"{script.name} 不得包含 {forbidden}"


def test_unit_is_boot_enabled_oneshot_after_kubernetes_units() -> None:
    content = UNIT_FILE.read_text(encoding="utf-8")
    assert "Type=oneshot" in content
    assert "ExecStart=/usr/local/libexec/a-stock/k3s-network-repair.sh sync" in content
    assert "WantedBy=multi-user.target" in content
    assert "RemainAfterExit=yes" in content

    after = next(line for line in content.splitlines() if line.startswith("After="))
    for required in (
        "k3s.service",
        "kube-router.service",
        "middlewared.service",
        "network-online.target",
    ):
        assert required in after, f"After= 必须包含 {required}"

    # 启动限流必须写在 [Unit] 段，否则 systemd 会忽略并告警。
    unit_section = content.split("[Service]", 1)[0]
    assert "StartLimitBurst=" in unit_section
    assert "StartLimitIntervalSec=" in unit_section


def test_installer_only_writes_two_host_paths() -> None:
    content = INSTALLER.read_text(encoding="utf-8")
    assert "/usr/local/libexec/a-stock/k3s-network-repair.sh" in content
    assert "/etc/systemd/system/a-stock-k3s-network-repair.service" in content
    assert content.count("install -D") == 2
    # RemainAfterExit=yes 下 `enable --now` 对已 active 的单元不会重跑 ExecStart，
    # 安装/升级必须显式 restart 才能立即执行修复。
    assert "systemctl enable " in content
    assert "systemctl restart " in content
    # 安装入口不得替 middleware 接管 CNI 清单或 kube-router 单元。
    for forbidden in ("/etc/cni/net.d", "kube-router.service", "k3s.service"):
        assert forbidden not in content


# --- 执行体行为 -------------------------------------------------------
def test_healthy_host_is_not_modified(host: Host) -> None:
    completed = host.run("sync")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert host.restarts() == []
    assert host.rule_adds() == []
    assert "route replace" not in "\n".join(host.calls())


def test_missing_route_is_added_once_and_idempotent(host: Host) -> None:
    host.set_route("172.16.0.0/16", None)

    first = host.run("sync")
    assert first.returncode == 0, first.stdout + first.stderr
    assert host.route_iface("172.16.0.0/16") == "kube-bridge"

    marker = host.call_count()
    second = host.run("sync")
    assert second.returncode == 0, second.stdout + second.stderr
    assert host.route_iface("172.16.0.0/16") == "kube-bridge"
    assert "route replace" not in "\n".join(host.calls(since=marker)), "第二次运行应完全幂等"


def test_missing_rule_is_added_with_expected_priority(host: Host) -> None:
    host.set_rule_present(False)

    completed = host.run("sync")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert host.rule_adds() == [
        "ip rule add from 172.16.0.0/16 lookup kube-router priority 32764"
    ]


def test_route_pointing_at_management_bridge_is_corrected(host: Host) -> None:
    host.set_route("172.16.0.0/16", "br0")

    completed = host.run("sync")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert host.route_iface("172.16.0.0/16") == "kube-bridge"


def test_cluster_cidr_falls_back_to_node_pod_cidr(host: Host) -> None:
    host.config.unlink()
    host.set_cluster_cidr("10.42.0.0/16")
    # 配置文件缺失后，podCIDR 成为唯一来源。
    host.path("pod-cidr").write_text("10.42.0.0/16", encoding="utf-8")
    host.set_route("10.42.0.0/16", None)

    completed = host.run("sync")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert host.route_iface("10.42.0.0/16") == "kube-bridge"


def test_cni_not_initialized_triggers_single_k3s_restart(host: Host) -> None:
    host.set_node_failure(
        "NetworkPluginNotReady",
        "container runtime network not ready: NetworkReady=false "
        "message:Network plugin returns error: cni plugin not initialized",
    )

    completed = host.run("sync")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert len(host.restarts()) == 1, "本次开机只允许重启一次 k3s"
    assert (host.run_dir / "k3s-restarts").read_text(encoding="utf-8").strip() == "1"


def test_non_cni_failure_does_not_restart_k3s(host: Host) -> None:
    host.set_node_failure("KubeletNotReady", "container runtime is down")

    completed = host.run("sync")

    assert completed.returncode != 0, "非 CNI 故障必须 fail closed"
    assert host.restarts() == [], "不得因无关故障重启 k3s"


def test_restart_budget_is_respected(host: Host) -> None:
    host.set_node_failure(
        "NetworkPluginNotReady", "cni plugin not initialized"
    )
    host.run_dir.mkdir(parents=True, exist_ok=True)
    (host.run_dir / "k3s-restarts").write_text("1\n", encoding="utf-8")

    completed = host.run("sync")

    assert completed.returncode != 0
    assert host.restarts() == [], "已用尽预算时不得再次重启"


def test_restart_that_does_not_heal_fails(host: Host) -> None:
    host.set_node_failure("NetworkPluginNotReady", "cni plugin not initialized")
    host.path("restart-does-not-heal").write_text("", encoding="utf-8")

    completed = host.run("sync")

    assert completed.returncode != 0
    assert len(host.restarts()) == 1


def test_management_overlap_is_rejected(host: Host) -> None:
    host.set_cluster_cidr("192.168.1.0/24")
    host.set_addr("br0", "192.168.1.20/24")
    host.set_route("192.168.1.0/24", None)
    host.set_rule_present(False)

    completed = host.run("sync")

    assert completed.returncode != 0
    assert "重叠" in completed.stdout + completed.stderr
    assert host.route_iface("192.168.1.0/24") is None
    assert host.rule_adds() == []


@pytest.mark.parametrize(
    "cidr",
    ["172.16.0.0/31", "172.16.0.0/33", "300.1.0.0/16", "172.16.0/16", "not-a-cidr"],
)
def test_invalid_cluster_cidr_is_rejected(host: Host, cidr: str) -> None:
    host.set_cluster_cidr(cidr)

    completed = host.run("sync")

    assert completed.returncode != 0
    assert "route replace" not in "\n".join(host.calls())
    assert host.rule_adds() == []


def test_missing_cni_conf_fails_instead_of_writing_routes(host: Host) -> None:
    host.set_cni_conf(False)
    host.set_route("172.16.0.0/16", None)

    completed = host.run("sync")

    assert completed.returncode != 0
    assert host.route_iface("172.16.0.0/16") is None


def test_check_is_read_only_and_reports_drift(host: Host) -> None:
    host.set_rule_present(False)

    completed = host.run("check")

    assert completed.returncode == 1, "存在漂移时 check 必须返回 1"
    assert "需要修复" in completed.stdout
    assert host.restarts() == []
    assert host.rule_adds() == []
    assert "route replace" not in "\n".join(host.calls())
    assert host.route_iface("172.16.0.0/16") == "kube-bridge"


def test_check_passes_on_ready_host(host: Host) -> None:
    completed = host.run("check")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "全部就绪" in completed.stdout


def test_node_name_comes_from_cluster_not_hostname(host: Host) -> None:
    """TrueNAS 的主机名是 truenas，k3s 节点名是 ix-truenas，不能混用。"""
    completed = host.run("check")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    status_calls = [call for call in host.calls() if "get node ix-truenas" in call]
    assert status_calls, "必须用集群节点名查询状态"
    assert all("get node ix-truenas" in call for call in status_calls), status_calls


def test_ambiguous_multi_node_cluster_requires_explicit_name(host: Host) -> None:
    host.set_nodes("ix-truenas", "ix-truenas-2")

    completed = host.run("check")

    # 多节点时不得猜测：podCIDR/Condition 查询会退化为 hostname，进而查不到 Ready。
    assert completed.returncode != 0
    assert "非 Ready" in completed.stdout


def test_explicit_node_name_override_wins(host: Host) -> None:
    host.set_nodes("ix-truenas", "ix-truenas-2")
    host.set_extra_nodes("ix-truenas")

    completed = host.run_with_node_name("check", "ix-truenas")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "get node ix-truenas" in "\n".join(host.calls())


def test_unknown_subcommand_fails(host: Host) -> None:
    completed = host.run("--frobnicate")

    assert completed.returncode == 2
    assert "用法" in completed.stderr + completed.stdout