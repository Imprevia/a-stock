from __future__ import annotations

import copy
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "apply-truenas-operator-override.sh"
MANIFEST = ROOT / "deploy" / "truenas" / "market-data-collection-cronjob-1.26-controller-shanghai.yaml"


def _cronjob() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def _write_yaml(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _write_tool(path: Path, variable: str) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        f"print(os.environ.get({variable!r}, ''))\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_fake_kubectl(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
import pathlib
import sys

args = sys.argv[1:]
with open(os.environ["FAKE_KUBECTL_LOG"], "a", encoding="utf-8") as stream:
    stream.write(json.dumps(args) + "\\n")

def emit(path_variable):
    value = os.environ.get(path_variable, "")
    if value:
        sys.stdout.write(pathlib.Path(value).read_text(encoding="utf-8"))

if "get" in args and "cronjob" in args:
    marker = pathlib.Path(os.environ["FAKE_APPLY_MARKER"])
    emit("FAKE_AFTER_CRONJOB" if marker.exists() else "FAKE_CRONJOB")
elif "get" in args and "pvc" in args:
    emit("FAKE_PVC")
elif "apply" in args:
    if "--dry-run=server" not in args:
        pathlib.Path(os.environ["FAKE_APPLY_MARKER"]).write_text("applied", encoding="utf-8")
else:
    raise SystemExit("unexpected kubectl arguments: " + repr(args))
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_fake_sudo(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import os
import pathlib
import sys

args = sys.argv[1:]
with open(os.environ["FAKE_SUDO_LOG"], "a", encoding="utf-8") as stream:
    stream.write(" ".join(args) + "\\n")
if len(args) < 4 or args[0] != "env" or not args[1].startswith("KUBECONFIG="):
    raise SystemExit("sudo must receive env KUBECONFIG=... <kubectl>")
key, value = args[1].split("=", 1)
child_env = {**os.environ, key: value}
os.execvpe(args[2], args[2:], child_env)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _run_override(
    tmp_path: Path,
    *,
    live: dict | None = None,
    pvc_phase: str = "Bound",
    host_timezone: str = "Asia/Shanghai",
    controller_environment: str = "",
    apply: bool = False,
    manifest: dict | None = None,
    after: dict | None = None,
    extra_env: dict[str, str] | None = None,
    sudo: bool = False,
    kubeconfig: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    live_path = tmp_path / "live.yaml"
    after_path = tmp_path / "after.yaml"
    pvc_path = tmp_path / "pvc.json"
    manifest_path = tmp_path / "override.yaml"
    log_path = tmp_path / "kubectl.log"
    marker_path = tmp_path / "applied"
    kubectl = tmp_path / "kubectl"
    sudo_bin = tmp_path / "sudo"
    timedatectl = tmp_path / "timedatectl"
    systemctl = tmp_path / "systemctl"

    if live is not None:
        _write_yaml(live_path, live)
    _write_yaml(after_path, after or manifest or _cronjob())
    _write_yaml(manifest_path, manifest or _cronjob())
    pvc_path.write_text(
        json.dumps(
            {
                "apiVersion": "v1",
                "kind": "PersistentVolumeClaim",
                "metadata": {"name": "market-environment-data", "namespace": "a-stock"},
                "spec": {
                    "accessModes": ["ReadWriteOnce"],
                    "volumeName": "a-stock-market-environment-data",
                },
                "status": {"phase": pvc_phase},
            }
        ),
        encoding="utf-8",
    )
    _write_fake_kubectl(kubectl)
    if sudo:
        _write_fake_sudo(sudo_bin)
    _write_tool(timedatectl, "FAKE_HOST_TIMEZONE")
    _write_tool(systemctl, "FAKE_CONTROLLER_ENVIRONMENT")

    command = ["bash", str(SCRIPT), "--manifest", str(manifest_path)]
    if apply:
        command.append("--apply")
    environment = {
        **os.environ,
        "KUBECTL_BIN": str(kubectl),
        "TIMEDATECTL_BIN": str(timedatectl),
        "SYSTEMCTL_BIN": str(systemctl),
        "FAKE_HOST_TIMEZONE": host_timezone,
        "FAKE_CONTROLLER_ENVIRONMENT": controller_environment,
        "FAKE_KUBECTL_LOG": str(log_path),
        "FAKE_APPLY_MARKER": str(marker_path),
        "FAKE_CRONJOB": str(live_path) if live is not None else "",
        "FAKE_AFTER_CRONJOB": str(after_path),
        "FAKE_PVC": str(pvc_path),
        "FAKE_SUDO_LOG": str(tmp_path / "sudo.log"),
    }
    if sudo:
        environment["PATH"] = f"{tmp_path}:{environment['PATH']}"
        environment["KUBECTL_SUDO"] = "true"
        environment["KUBECONFIG"] = kubeconfig or "/etc/rancher/k3s/k3s.yaml"
    if extra_env:
        environment.update(extra_env)
    completed = subprocess.run(
        command,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()] if log_path.exists() else []
    return completed, calls


def _call_has(call: list[str], *tokens: str) -> bool:
    return all(token in call for token in tokens)


def test_override_defaults_to_read_only_validation_and_server_dry_run(tmp_path: Path) -> None:
    live = _cronjob()
    live["spec"]["schedule"] = "30 8 * * 1-5"

    completed, calls = _run_override(tmp_path, live=live)

    assert completed.returncode == 0, completed.stderr
    assert "no resource was changed" in completed.stdout
    assert any(_call_has(call, "get", "cronjob", "market-data-collection") for call in calls)
    assert any(_call_has(call, "get", "pvc", "market-environment-data") for call in calls)
    apply_calls = [call for call in calls if "apply" in call]
    assert len(apply_calls) == 1
    assert "--dry-run=server" in apply_calls[0]
    assert not any(token in {"delete", "patch", "replace", "create"} for call in calls for token in call)


def test_override_apply_is_dry_run_then_write_then_exact_readback(tmp_path: Path) -> None:
    live = _cronjob()
    live["spec"]["schedule"] = "30 8 * * 1-5"

    completed, calls = _run_override(tmp_path, live=live, apply=True)

    assert completed.returncode == 0, completed.stderr
    assert "operator override applied" in completed.stdout
    apply_calls = [call for call in calls if "apply" in call]
    assert len(apply_calls) == 2
    assert "--dry-run=server" in apply_calls[0]
    assert "--dry-run=server" not in apply_calls[1]
    cron_reads = [call for call in calls if _call_has(call, "get", "cronjob")]
    assert len(cron_reads) == 2
    assert not any("pvc" in call and "apply" in call for call in calls)


def test_override_sudo_passes_explicit_kubeconfig_through_env(tmp_path: Path) -> None:
    completed, calls = _run_override(
        tmp_path,
        live=_cronjob(),
        sudo=True,
        kubeconfig="/etc/rancher/k3s/k3s.yaml",
    )

    assert completed.returncode == 0, completed.stderr
    sudo_log = (tmp_path / "sudo.log").read_text(encoding="utf-8").splitlines()
    assert sudo_log
    assert all(line.startswith("env KUBECONFIG=/etc/rancher/k3s/k3s.yaml ") for line in sudo_log)
    assert len(calls) == 3


@pytest.mark.parametrize(
    ("host_timezone", "controller_environment", "expected"),
    [
        ("Etc/UTC", "", "host timezone must be Asia/Shanghai"),
        ("Asia/Shanghai", "TZ=Etc/UTC", "k3s controller TZ must be Asia/Shanghai or unset"),
    ],
)
def test_override_rejects_unverified_controller_timezone_before_cluster_access(
    tmp_path: Path,
    host_timezone: str,
    controller_environment: str,
    expected: str,
) -> None:
    completed, calls = _run_override(
        tmp_path,
        live=_cronjob(),
        host_timezone=host_timezone,
        controller_environment=controller_environment,
    )

    assert completed.returncode != 0
    assert expected in completed.stderr
    assert calls == []


def test_override_refuses_to_create_a_missing_exact_cronjob(tmp_path: Path) -> None:
    completed, calls = _run_override(tmp_path, live=None)

    assert completed.returncode != 0
    assert "does not exist; refusing to create it" in completed.stderr
    assert len(calls) == 1
    assert _call_has(calls[0], "get", "cronjob", "market-data-collection")


def test_override_rejects_helm_owned_cronjob_before_pvc_or_apply(tmp_path: Path) -> None:
    live = _cronjob()
    live["metadata"].setdefault("labels", {})["app.kubernetes.io/managed-by"] = "Helm"
    live["metadata"].setdefault("annotations", {})["meta.helm.sh/release-name"] = "a-stock"

    completed, calls = _run_override(tmp_path, live=live)

    assert completed.returncode != 0
    assert "Helm-owned" in completed.stderr or "Helm ownership" in completed.stderr
    assert len(calls) == 1
    assert not any("pvc" in call or "apply" in call for call in calls)


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda item: item["spec"].update({"suspend": True}), "unsupported shape/drift"),
        (
            lambda item: item["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0].update(
                {"image": "localhost/a-stock-market-environment:latest"}
            ),
            "unsupported shape/drift",
        ),
        (
            lambda item: item["spec"].update({"timeZone": "Asia/Shanghai"}),
            "unsupported shape/drift",
        ),
    ],
    ids=["suspended", "image", "native-timezone-field"],
)
def test_override_rejects_live_shape_drift_before_apply(tmp_path: Path, mutate, expected: str) -> None:
    live = copy.deepcopy(_cronjob())
    mutate(live)

    completed, calls = _run_override(tmp_path, live=live)

    assert completed.returncode != 0
    assert expected in completed.stderr
    assert len(calls) == 1
    assert not any("apply" in call for call in calls)


def test_override_rejects_unbound_pvc_before_server_dry_run(tmp_path: Path) -> None:
    completed, calls = _run_override(tmp_path, live=_cronjob(), pvc_phase="Pending")

    assert completed.returncode != 0
    assert "PVC is not Bound or has drifted" in completed.stderr
    assert not any("apply" in call for call in calls)


def test_override_rejects_manifest_image_drift_before_cluster_access(tmp_path: Path) -> None:
    manifest = _cronjob()
    manifest["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["image"] = (
        "localhost/a-stock-market-environment:latest"
    )

    completed, calls = _run_override(tmp_path, live=_cronjob(), manifest=manifest)

    assert completed.returncode != 0
    assert "manifest validation failed" in completed.stderr
    assert calls == []


def test_override_ignores_attempts_to_repoint_frozen_image_or_claim(tmp_path: Path) -> None:
    manifest = _cronjob()
    container = manifest["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    container["image"] = "localhost/a-stock-market-environment:latest"
    manifest["spec"]["jobTemplate"]["spec"]["template"]["spec"]["volumes"][0][
        "persistentVolumeClaim"
    ]["claimName"] = "a-stock-data"

    completed, calls = _run_override(
        tmp_path,
        live=_cronjob(),
        manifest=manifest,
        extra_env={
            "OPERATOR_OVERRIDE_IMAGE": "localhost/a-stock-market-environment:latest",
            "OPERATOR_OVERRIDE_CLAIM": "a-stock-data",
            "OPERATOR_OVERRIDE_NAMESPACE": "other",
        },
    )

    assert completed.returncode != 0
    assert "manifest validation failed" in completed.stderr
    assert calls == []


def test_override_fails_when_apply_readback_does_not_match_schedule(tmp_path: Path) -> None:
    after = _cronjob()
    after["spec"]["schedule"] = "30 8 * * 1-5"

    completed, calls = _run_override(tmp_path, live=_cronjob(), apply=True, after=after)

    assert completed.returncode != 0
    assert "post-apply schedule" in completed.stderr
    assert len([call for call in calls if "apply" in call]) == 2
