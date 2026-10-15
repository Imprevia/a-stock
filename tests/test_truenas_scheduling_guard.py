from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy-truenas-k3s.sh"
VALIDATOR = ROOT / "scripts" / "validate-scheduling-packet.py"
CHART = ROOT / "deploy" / "helm" / "a-stock"
BASELINE = ROOT / "deploy" / "truenas" / "values-secure-manual-collection.yaml"
COMPONENT_FIXTURE = ROOT / "tests" / "fixtures" / "truenas_component_baseline.yaml"
SUSPENDED = ROOT / "deploy" / "truenas" / "values-scheduled-suspended.yaml"
ACTIVE = ROOT / "deploy" / "truenas" / "values-scheduled-active.yaml"
OFF = ROOT / "deploy" / "truenas" / "values-scheduled-off.yaml"
SECTORS_OFF = ROOT / "deploy" / "truenas" / "values-fuyao-sectors-off.yaml"
SECTORS_ENABLED = ROOT / "deploy" / "truenas" / "values-fuyao-sectors-enabled.yaml"
HELM = shutil.which("helm")

def _values_with_database_secret(tmp_path: Path) -> Path:
    values = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))
    values["database"]["existingSecret"] = "a-stock-postgresql"
    path = tmp_path / "values-with-database-secret.yaml"
    path.write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
    return path

def _write_native_overlay(path: Path, *, schedule: str = "30 16 * * 1-5") -> None:
    path.write_text(
        "marketEnvironment:\n"
        "  scheduledCollection:\n"
        "    enabled: true\n"
        "    suspend: true\n"
        "    timezoneStrategy: native\n"
        f"    schedule: \"{schedule}\"\n",
        encoding="utf-8",
    )

def _run_validator(command: str, payload: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), command, *arguments],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )


def _bash_path(path: Path) -> str:
    """Write a path into a sourced Bash env file without Windows escapes."""
    if os.name == "nt":
        return str(path).replace("\\", "/")
    return str(path)

@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ('{"gitVersion":"v1.26.6+k3s1"}', "1.26.6+k3s1"),
        ('{\n  "platform": "linux/amd64",\n  "gitVersion": "v1.27.3"\n}', "1.27.3"),
        ('{"minor":"28","gitVersion":"1.28.0-rc.1","major":"1"}', "1.28.0-rc.1"),
    ],
)
def test_version_parser_accepts_realistic_kubernetes_json(payload: str, expected: str) -> None:
    completed = _run_validator("parse-version", payload)

    assert completed.returncode == 0
    assert completed.stdout.strip() == expected

@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        "{}",
        '{"gitVersion": 126}',
        '{"gitVersion": "v1.26"}',
    ],
)
def test_version_parser_rejects_malformed_or_missing_git_version(payload: str) -> None:
    completed = _run_validator("parse-version", payload)

    assert completed.returncode != 0
    assert "version" in completed.stderr.lower()

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_native_offline_render_exits_without_loading_environment(tmp_path: Path) -> None:
    overlay = tmp_path / "native-suspended.yaml"
    _write_native_overlay(overlay)
    baseline = _values_with_database_secret(tmp_path)
    completed = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--offline-render",
            "--baseline-values",
            str(baseline),
            "--scheduling-overlay",
            str(overlay),
            "--kube-version",
            "1.27.0",
        ],
        env={**os.environ, "DEPLOY_ENV_FILE": "/definitely/not/present"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "strategy=native" in completed.stdout
    assert "effectiveShanghai=16:30" in completed.stdout
    assert "environment file" not in completed.stderr

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_native_offline_render_rejects_kubernetes_prerelease_boundary(tmp_path: Path) -> None:
    overlay = tmp_path / "native-suspended.yaml"
    _write_native_overlay(overlay)
    baseline = _values_with_database_secret(tmp_path)
    completed = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--offline-render",
            "--baseline-values",
            str(baseline),
            "--scheduling-overlay",
            str(overlay),
            "--kube-version",
            "1.27.0-rc.1",
        ],
        env={**os.environ, "DEPLOY_ENV_FILE": "/definitely/not/present"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "requires Kubernetes 1.27.0 stable or later" in completed.stderr
    assert "offline scheduling packet validation failed" in completed.stderr
    assert "environment file" not in completed.stderr

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_invalid_offline_cron_stops_before_environment_or_target_access(tmp_path: Path) -> None:
    overlay = tmp_path / "invalid-schedule.yaml"
    _write_native_overlay(overlay, schedule="invalid")
    baseline = _values_with_database_secret(tmp_path)
    completed = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--offline-render",
            "--baseline-values",
            str(baseline),
            "--scheduling-overlay",
            str(overlay),
            "--kube-version",
            "1.27.0",
        ],
        env={**os.environ, "DEPLOY_ENV_FILE": "/definitely/not/present"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "offline scheduling render failed" in completed.stderr
    assert "environment file" not in completed.stderr

def _write_target_spies(tmp_path: Path) -> tuple[Path, Path]:
    marker = tmp_path / "target-calls"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in ("ssh", "kubectl", "nc", "podman", "curl", "scp"):
        executable = fake_bin / name
        executable.write_text(
            f"#!/usr/bin/env bash\nprintf '%s\\n' {name} >> {marker!s}\nexit 97\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
    helm = fake_bin / "helm"
    helm.write_text(
        "#!/usr/bin/env bash\n"
        "case \"$1\" in\n"
        f"  lint|template) exec {HELM or '/definitely/missing/helm'} \"$@\" ;;\n"
        f"  *) printf 'helm %s\\n' \"$*\" >> {marker!s}; exit 97 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    helm.chmod(0o755)
    return fake_bin, marker

def _write_env(path: Path, repo: Path, baseline: Path, overlay: Path | None) -> None:
    lines = [
        f"REPO_DIR={_bash_path(repo)}",
        "TRUENAS_HOST=192.0.2.10",
        "TRUENAS_SSH_USER=tester",
        f"HELM_VALUES_FILE={_bash_path(baseline)}",
        "REMOTE_IMAGE_DIR=/unreachable",
    ]
    if overlay is not None:
        lines.append(f"SCHEDULING_OVERLAY_FILE={_bash_path(overlay)}")
    path.write_text("\n".join([*lines, ""]), encoding="utf-8")

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_active_packet_is_rejected_before_server_dry_run_target_access(tmp_path: Path) -> None:
    fake_bin, marker = _write_target_spies(tmp_path)
    env_file = tmp_path / "deploy.env"
    _write_env(env_file, ROOT, BASELINE, ACTIVE)
    completed = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--env-file",
            str(env_file),
            "--server-dry-run",
            "--kube-version",
            "1.26.6",
        ],
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "must be suspended, got active" in completed.stderr
    assert not marker.exists()

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_ordinary_deploy_rejects_enabled_schedule_before_target_access(tmp_path: Path) -> None:
    fake_bin, marker = _write_target_spies(tmp_path)
    active_values = tmp_path / "active-native.yaml"
    active_values.write_text(
        "marketEnvironment:\n"
        "  scheduledCollection:\n"
        "    enabled: true\n"
        "    suspend: false\n"
        "    timezoneStrategy: native\n",
        encoding="utf-8",
    )
    env_file = tmp_path / "deploy.env"
    _write_env(env_file, ROOT, active_values, None)
    completed = subprocess.run(
        ["bash", str(SCRIPT), "--env-file", str(env_file)],
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "enabled=false and scheduledCollection.suspend=true" in completed.stderr
    assert not marker.exists()

def test_ordinary_deploy_rejects_disabled_unsuspended_values_before_render_or_access(
    tmp_path: Path,
) -> None:
    fake_bin, marker = _write_target_spies(tmp_path)
    helm = fake_bin / "helm"
    helm.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' helm >> {marker!s}\nexit 97\n",
        encoding="utf-8",
    )
    helm.chmod(0o755)
    unsafe_values = tmp_path / "disabled-unsuspended.yaml"
    unsafe_values.write_text(
        "marketEnvironment:\n"
        "  scheduledCollection:\n"
        "    enabled: false\n"
        "    suspend: false\n",
        encoding="utf-8",
    )
    env_file = tmp_path / "deploy.env"
    _write_env(env_file, ROOT, unsafe_values, None)

    completed = subprocess.run(
        ["bash", str(SCRIPT), "--env-file", str(env_file)],
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "enabled=false and scheduledCollection.suspend=true" in completed.stderr
    assert "before Helm rendering" in completed.stderr
    assert not marker.exists()

def test_ordinary_deploy_rejects_disabled_unsuspended_env_before_render_or_access(
    tmp_path: Path,
) -> None:
    fake_bin, marker = _write_target_spies(tmp_path)
    helm = fake_bin / "helm"
    helm.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' helm >> {marker!s}\nexit 97\n",
        encoding="utf-8",
    )
    helm.chmod(0o755)
    env_file = tmp_path / "deploy.env"
    env_file.write_text(
        f"REPO_DIR={_bash_path(ROOT)}\n"
        "TRUENAS_HOST=192.0.2.10\n"
        "TRUENAS_SSH_USER=tester\n"
        "HELM_VALUES_FILE=\n"
        "REMOTE_IMAGE_DIR=/unreachable\n"
        "SCHEDULED_COLLECTION_ENABLED=false\n"
        "SCHEDULED_COLLECTION_SUSPEND=false\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        ["bash", str(SCRIPT), "--env-file", str(env_file)],
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "enabled=false and scheduledCollection.suspend=true" in completed.stderr
    assert "before Helm rendering" in completed.stderr
    assert not marker.exists()

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_ordinary_deploy_revalidates_frozen_values_before_render_or_access(
    tmp_path: Path,
) -> None:
    repo, tracked_baseline, _, _, _, reviewed_head = _prepare_reviewed_repo(tmp_path)
    baseline = tmp_path / "external-baseline.yaml"
    shutil.copy2(tracked_baseline, baseline)
    fake_bin, target_marker = _write_target_spies(tmp_path)
    helm_calls = tmp_path / "helm-calls"
    drifted = tmp_path / "baseline-drifted"
    helm = fake_bin / "helm"
    helm.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$1\" >> {helm_calls!s}\n"
        f"if [[ \"$1\" == lint && ! -e {drifted!s} ]]; then\n"
        f"  sed -i 's/    suspend: true/    suspend: false/' {baseline!s}\n"
        f"  touch {drifted!s}\n"
        "fi\n"
        "exec \"$REAL_HELM\" \"$@\"\n",
        encoding="utf-8",
    )
    helm.chmod(0o755)
    env_file = tmp_path / "deploy.env"
    _write_env(env_file, repo, baseline, None)
    with env_file.open("a", encoding="utf-8") as stream:
        stream.write(f"REVIEWED_GIT_HEAD={reviewed_head}\n")

    completed = subprocess.run(
        ["bash", str(repo / "scripts" / SCRIPT.name), "--env-file", str(env_file)],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "REAL_HELM": HELM,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "frozen ordinary deployment packet requires" in completed.stderr
    assert helm_calls.read_text(encoding="utf-8").splitlines() == ["lint", "template"]
    assert not target_marker.exists()

def _render(chart: Path, baseline: Path, overlay: Path, state: str) -> str:
    assert HELM is not None
    return subprocess.run(
        [
            HELM,
            "template",
            "research",
            str(chart),
            "--namespace",
            "market-data",
            "--kube-version",
            "1.26.6",
            "--values",
            str(baseline),
            "--values",
            str(overlay),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _render_sector_profile(
    values: Path,
    *,
    chart: Path = CHART,
    image_repository: str = "registry.local/frozen",
    image_tag: str = "reviewed-20261009",
) -> str:
    assert HELM is not None
    return subprocess.run(
        [
            HELM,
            "template",
            "a-stock",
            str(chart),
            "--namespace",
            "a-stock",
            "--kube-version",
            "1.26.6+k3s1",
            "--values",
            str(values),
            "--set",
            f"image.repository={image_repository}",
            "--set",
            f"image.tag={image_tag}",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.rstrip("\n") + "\n"


def _write_documents(path: Path, documents: list[dict]) -> None:
    path.write_text(yaml.safe_dump_all(documents, sort_keys=False), encoding="utf-8")


def _manual_refresh_render(value: str, *, values: Path = SECTORS_OFF) -> str:
    documents = [item for item in yaml.safe_load_all(_render_sector_profile(values)) if item]
    deployment = next(item for item in documents if item.get("kind") == "Deployment")
    dashboard = deployment["spec"]["template"]["spec"]["containers"][0]
    manual = [
        item
        for item in dashboard["env"]
        if item.get("name") == "MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED"
    ]
    assert len(manual) == 1
    manual[0] = {
        "name": "MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED",
        "value": value,
    }
    dashboard["env"] = [
        manual[0]
        if item.get("name") == "MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED"
        else item
        for item in dashboard["env"]
    ]
    return yaml.safe_dump_all(documents, sort_keys=False)


def _sector_runtime_payloads(rendered: str) -> tuple[dict, dict, dict]:
    deployment = next(
        item
        for item in yaml.safe_load_all(rendered)
        if item and item.get("kind") == "Deployment"
    )
    deployment = copy.deepcopy(deployment)
    deployment["metadata"].update(
        {
            "namespace": "a-stock",
            "uid": "deployment-reviewed",
            "annotations": {"deployment.kubernetes.io/revision": "7"},
        }
    )
    dashboard = copy.deepcopy(deployment["spec"]["template"]["spec"]["containers"][0])
    labels = {"app.kubernetes.io/instance": "a-stock"}
    replicaset = {
        "apiVersion": "apps/v1",
        "kind": "ReplicaSet",
        "metadata": {
            "name": "a-stock-reviewed-7",
            "namespace": "a-stock",
            "uid": "replicaset-reviewed",
            "labels": labels,
            "annotations": {"deployment.kubernetes.io/revision": "7"},
            "ownerReferences": [
                {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "name": deployment["metadata"]["name"],
                    "uid": "deployment-reviewed",
                    "controller": True,
                }
            ],
        },
        "spec": {"template": {"spec": {"containers": [copy.deepcopy(dashboard)]}}},
    }
    pods = {
        "apiVersion": "v1",
        "kind": "PodList",
        "items": [
            {
                "apiVersion": "v1",
                "kind": "Pod",
                "metadata": {
                    "name": "a-stock-dashboard-reviewed",
                    "namespace": "a-stock",
                    "uid": "pod-reviewed",
                    "labels": labels,
                    "ownerReferences": [
                        {
                            "apiVersion": "apps/v1",
                            "kind": "ReplicaSet",
                            "name": "a-stock-reviewed-7",
                            "uid": "replicaset-reviewed",
                            "controller": True,
                        }
                    ],
                },
                "spec": {"containers": [dashboard]},
                "status": {
                    "phase": "Running",
                    "conditions": [{"type": "Ready", "status": "True"}],
                    "containerStatuses": [
                        {
                            "name": "dashboard",
                            "image": dashboard["image"],
                            "imageID": f"containerd://sha256:{'e' * 64}",
                            "ready": True,
                        }
                    ],
                },
            }
        ],
    }
    return (
        {"apiVersion": "apps/v1", "kind": "DeploymentList", "items": [deployment]},
        {"apiVersion": "apps/v1", "kind": "ReplicaSetList", "items": [replicaset]},
        pods,
    )


def _run_promotion_pod_selector(
    tmp_path: Path, payloads: tuple[dict, dict, dict]
) -> subprocess.CompletedProcess[str]:
    deployments, replicasets, pods = payloads
    deployments_path = tmp_path / "deployments.json"
    replicasets_path = tmp_path / "replicasets.json"
    desired_path = tmp_path / "reviewed-off.yaml"
    deployments_path.write_text(json.dumps(deployments), encoding="utf-8")
    replicasets_path.write_text(json.dumps(replicasets), encoding="utf-8")
    desired_path.write_text(_render_sector_profile(SECTORS_OFF), encoding="utf-8")
    return _run_validator(
        "select-disabled-promotion-pod",
        json.dumps(pods),
        "--release-name",
        "a-stock",
        "--namespace",
        "a-stock",
        "--image",
        "registry.local/frozen:reviewed-20261009",
        "--digest",
        f"sha256:{'d' * 64}",
        "--deployments",
        str(deployments_path),
        "--replicasets",
        str(replicasets_path),
        "--desired",
        str(desired_path),
    )


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize(
    ("values", "enabled"),
    [(SECTORS_OFF, "0"), (SECTORS_ENABLED, "1")],
    ids=["off", "enabled"],
)
def test_reviewed_sectors_packet_validator_accepts_profiles(values: Path, enabled: str) -> None:
    rendered = _render_sector_profile(values)

    completed = _run_validator(
        "validate-sectors-packet",
        rendered,
        "--release-name",
        "a-stock",
        "--namespace",
        "a-stock",
        "--require-enabled",
        enabled,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "databaseSecret": "a-stock-postgresql",
        "deployment": "a-stock",
        "image": "registry.local/frozen:reviewed-20261009",
        "providerSecret": "a-stock-market-provider",
        "sectorsEnabled": enabled,
    }


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_sectors_config_only_comparator_accepts_only_bidirectional_flag_flip(
    tmp_path: Path,
) -> None:
    off = tmp_path / "off.yaml"
    enabled = tmp_path / "enabled.yaml"
    off.write_text(_render_sector_profile(SECTORS_OFF), encoding="utf-8")
    enabled.write_text(_render_sector_profile(SECTORS_ENABLED), encoding="utf-8")

    for current, desired, before, after in (
        (off, enabled, "0", "1"),
        (enabled, off, "1", "0"),
    ):
        completed = _run_validator(
            "compare-sectors-config-only",
            "",
            "--current",
            str(current),
            "--desired",
            str(desired),
            "--release-name",
            "a-stock",
            "--namespace",
            "a-stock",
            "--image",
            "registry.local/frozen:reviewed-20261009",
            "--from-enabled",
            before,
            "--to-enabled",
            after,
        )
        assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize(
    "drift",
    [
        "image",
        "revision",
        "database-secret",
        "provider-secret",
        "replicas",
        "service",
        "pvc",
        "environment",
        "topology",
        "namespace",
        "resource-set",
        "hook",
    ],
)
def test_sectors_config_only_comparator_rejects_unrelated_drift(
    tmp_path: Path, drift: str
) -> None:
    off_documents = [item for item in yaml.safe_load_all(_render_sector_profile(SECTORS_OFF)) if item]
    enabled_documents = [
        item for item in yaml.safe_load_all(_render_sector_profile(SECTORS_ENABLED)) if item
    ]
    deployment = next(item for item in enabled_documents if item["kind"] == "Deployment")
    dashboard = deployment["spec"]["template"]["spec"]["containers"][0]
    environment = {item["name"]: item for item in dashboard["env"]}
    if drift == "image":
        dashboard["image"] = "registry.local/drift:reviewed-20261009"
    elif drift == "revision":
        environment["MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION"]["value"] = "other"
    elif drift == "database-secret":
        environment["MARKET_ENVIRONMENT_DATABASE_URL"]["valueFrom"]["secretKeyRef"]["name"] = (
            "other-database"
        )
    elif drift == "provider-secret":
        environment["MARKET_ENVIRONMENT_FUYAO_API_KEY"]["valueFrom"]["secretKeyRef"]["name"] = (
            "other-provider"
        )
    elif drift == "replicas":
        deployment["spec"]["replicas"] = 2
    elif drift == "service":
        service = next(item for item in enabled_documents if item["kind"] == "Service")
        service["spec"]["ports"][0]["port"] = 81
    elif drift == "pvc":
        pvc = next(item for item in enabled_documents if item["kind"] == "PersistentVolumeClaim")
        pvc["spec"]["resources"]["requests"]["storage"] = "6Gi"
    elif drift == "environment":
        environment["MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED"]["value"] = "0"
    elif drift == "topology":
        deployment["spec"]["template"]["spec"]["automountServiceAccountToken"] = True
    elif drift == "namespace":
        deployment["metadata"]["namespace"] = "wrong"
    elif drift == "resource-set":
        enabled_documents.append(
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {
                    "name": "unexpected",
                    "namespace": "a-stock",
                    "labels": {"app.kubernetes.io/instance": "a-stock"},
                },
            }
        )
    else:
        enabled_documents.append(
            {
                "apiVersion": "batch/v1",
                "kind": "Job",
                "metadata": {
                    "name": "unreviewed-hook",
                    "namespace": "a-stock",
                    "labels": {"app.kubernetes.io/instance": "a-stock"},
                    "annotations": {"helm.sh/hook": "pre-upgrade"},
                },
                "spec": {},
            }
        )
    off = tmp_path / "off.yaml"
    enabled = tmp_path / "enabled.yaml"
    _write_documents(off, off_documents)
    _write_documents(enabled, enabled_documents)

    completed = _run_validator(
        "compare-sectors-config-only",
        "",
        "--current",
        str(off),
        "--desired",
        str(enabled),
        "--release-name",
        "a-stock",
        "--namespace",
        "a-stock",
        "--image",
        "registry.local/frozen:reviewed-20261009",
        "--from-enabled",
        "0",
        "--to-enabled",
        "1",
    )

    assert completed.returncode != 0


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_sectors_config_only_comparator_rejects_noop_transition(tmp_path: Path) -> None:
    off = tmp_path / "off.yaml"
    off.write_text(_render_sector_profile(SECTORS_OFF), encoding="utf-8")

    completed = _run_validator(
        "compare-sectors-config-only",
        "",
        "--current",
        str(off),
        "--desired",
        str(off),
        "--release-name",
        "a-stock",
        "--namespace",
        "a-stock",
        "--image",
        "registry.local/frozen:reviewed-20261009",
        "--from-enabled",
        "0",
        "--to-enabled",
        "0",
    )

    assert completed.returncode != 0
    assert "must change the sectors enabled flag" in completed.stderr


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_manual_refresh_comparator_accepts_only_literal_one_to_zero(
    tmp_path: Path,
) -> None:
    current = tmp_path / "manual-on.yaml"
    desired = tmp_path / "manual-off.yaml"
    current.write_text(_manual_refresh_render("1"), encoding="utf-8")
    desired.write_text(_manual_refresh_render("0"), encoding="utf-8")

    completed = _run_validator(
        "compare-manual-refresh-only",
        "",
        "--current",
        str(current),
        "--desired",
        str(desired),
        "--release-name",
        "a-stock",
        "--namespace",
        "a-stock",
        "--image",
        "registry.local/frozen:reviewed-20261009",
    )

    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize(
    "drift",
    [
        "noop",
        "value-from",
        "duplicate",
        "missing",
        "image",
        "other-env",
        "replicas",
        "service",
        "resource-set",
        "cronjob",
        "hook",
    ],
)
def test_manual_refresh_comparator_rejects_every_unreviewed_drift(
    tmp_path: Path, drift: str
) -> None:
    current_documents = [
        item for item in yaml.safe_load_all(_manual_refresh_render("1")) if item
    ]
    desired_documents = [
        item for item in yaml.safe_load_all(_manual_refresh_render("0")) if item
    ]
    deployment = next(item for item in desired_documents if item["kind"] == "Deployment")
    dashboard = deployment["spec"]["template"]["spec"]["containers"][0]
    manual_index = next(
        index
        for index, item in enumerate(dashboard["env"])
        if item["name"] == "MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED"
    )
    if drift == "noop":
        dashboard["env"][manual_index]["value"] = "1"
    elif drift == "value-from":
        dashboard["env"][manual_index] = {
            "name": "MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED",
            "valueFrom": {"secretKeyRef": {"name": "wrong", "key": "enabled"}},
        }
    elif drift == "duplicate":
        dashboard["env"].append(copy.deepcopy(dashboard["env"][manual_index]))
    elif drift == "missing":
        dashboard["env"].pop(manual_index)
    elif drift == "image":
        dashboard["image"] = "registry.local/drift:reviewed-20261009"
    elif drift == "other-env":
        next(
            item
            for item in dashboard["env"]
            if item["name"] == "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED"
        )["value"] = "1"
    elif drift == "replicas":
        deployment["spec"]["replicas"] = 2
    elif drift == "service":
        service = next(item for item in desired_documents if item["kind"] == "Service")
        service["spec"]["ports"][0]["port"] = 81
    elif drift == "resource-set":
        desired_documents.append(
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {
                    "name": "unexpected",
                    "namespace": "a-stock",
                    "labels": {"app.kubernetes.io/instance": "a-stock"},
                },
            }
        )
    elif drift == "cronjob":
        desired_documents.append(
            {
                "apiVersion": "batch/v1",
                "kind": "CronJob",
                "metadata": {
                    "name": "a-stock-data-collection",
                    "namespace": "a-stock",
                    "labels": {"app.kubernetes.io/instance": "a-stock"},
                },
                "spec": {"suspend": True},
            }
        )
    else:
        hook = next(
            item
            for item in desired_documents
            if "helm.sh/hook" in ((item.get("metadata") or {}).get("annotations") or {})
        )
        hook["spec"]["template"]["spec"]["containers"][0]["command"] = [
            "sh",
            "-c",
            "false",
        ]
    current = tmp_path / "manual-on.yaml"
    desired = tmp_path / "manual-off.yaml"
    _write_documents(current, current_documents)
    _write_documents(desired, desired_documents)

    completed = _run_validator(
        "compare-manual-refresh-only",
        "",
        "--current",
        str(current),
        "--desired",
        str(desired),
        "--release-name",
        "a-stock",
        "--namespace",
        "a-stock",
        "--image",
        "registry.local/frozen:reviewed-20261009",
    )

    assert completed.returncode != 0


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_manual_refresh_runtime_verifier_requires_reviewed_ready_pod_environment(
    tmp_path: Path,
) -> None:
    reviewed = _manual_refresh_render("0")
    deployments, replicasets, pods = _sector_runtime_payloads(reviewed)
    deployments_path = tmp_path / "deployments.json"
    replicasets_path = tmp_path / "replicasets.json"
    pods_path = tmp_path / "pods.json"
    desired_path = tmp_path / "manual-off.yaml"
    deployments_path.write_text(json.dumps(deployments), encoding="utf-8")
    replicasets_path.write_text(json.dumps(replicasets), encoding="utf-8")
    pods_path.write_text(json.dumps(pods), encoding="utf-8")
    desired_path.write_text(reviewed, encoding="utf-8")

    completed = _run_validator(
        "verify-manual-refresh-runtime",
        "",
        "--deployments",
        str(deployments_path),
        "--replicasets",
        str(replicasets_path),
        "--pods",
        str(pods_path),
        "--desired",
        str(desired_path),
        "--release-name",
        "a-stock",
        "--namespace",
        "a-stock",
        "--image",
        "registry.local/frozen:reviewed-20261009",
        "--digest",
        f"sha256:{'d' * 64}",
        "--require-value",
        "0",
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "a-stock-dashboard-reviewed"

    dashboard = pods["items"][0]["spec"]["containers"][0]
    next(
        item
        for item in dashboard["env"]
        if item["name"] == "MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED"
    )["value"] = "1"
    pods_path.write_text(json.dumps(pods), encoding="utf-8")
    rejected = _run_validator(
        "verify-manual-refresh-runtime",
        "",
        "--deployments",
        str(deployments_path),
        "--replicasets",
        str(replicasets_path),
        "--pods",
        str(pods_path),
        "--desired",
        str(desired_path),
        "--release-name",
        "a-stock",
        "--namespace",
        "a-stock",
        "--image",
        "registry.local/frozen:reviewed-20261009",
        "--digest",
        f"sha256:{'d' * 64}",
        "--require-value",
        "0",
    )
    assert rejected.returncode != 0
    assert "must be literal 0" in rejected.stderr


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_compare_release_exact_rejects_hook_drift(tmp_path: Path) -> None:
    reviewed = [item for item in yaml.safe_load_all(_render_sector_profile(SECTORS_OFF)) if item]
    drifted = copy.deepcopy(reviewed)
    hook = next(
        item
        for item in drifted
        if "helm.sh/hook" in ((item.get("metadata") or {}).get("annotations") or {})
    )
    hook["spec"]["template"]["spec"]["containers"][0]["command"] = ["sh", "-c", "false"]
    reviewed_path = tmp_path / "reviewed.yaml"
    drifted_path = tmp_path / "drifted.yaml"
    _write_documents(reviewed_path, reviewed)
    _write_documents(drifted_path, drifted)

    completed = _run_validator(
        "compare-release-exact",
        "",
        "--current",
        str(drifted_path),
        "--desired",
        str(reviewed_path),
    )

    assert completed.returncode != 0
    assert "hook drift" in completed.stderr


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_hook_comparators_require_exact_and_reject_single_sided_hooks(
    tmp_path: Path,
) -> None:
    current = [item for item in yaml.safe_load_all(_manual_refresh_render("1")) if item]
    desired = [item for item in yaml.safe_load_all(_manual_refresh_render("0")) if item]
    hooks = [
        item
        for item in desired
        if "helm.sh/hook" in ((item.get("metadata") or {}).get("annotations") or {})
    ]
    hooks_path = tmp_path / "hooks.yaml"
    _write_documents(hooks_path, hooks)
    exact = _run_validator(
        "compare-hooks-exact",
        "",
        "--current",
        str(hooks_path),
        "--desired",
        str(hooks_path),
    )
    assert exact.returncode == 0, exact.stderr

    for missing_side in ("current", "desired"):
        current_documents = copy.deepcopy(current)
        desired_documents = copy.deepcopy(desired)
        if missing_side == "current":
            current_documents = [
                item
                for item in current_documents
                if "helm.sh/hook"
                not in ((item.get("metadata") or {}).get("annotations") or {})
            ]
        else:
            desired_documents = [
                item
                for item in desired_documents
                if "helm.sh/hook"
                not in ((item.get("metadata") or {}).get("annotations") or {})
            ]
        current_path = tmp_path / f"current-{missing_side}.yaml"
        desired_path = tmp_path / f"desired-{missing_side}.yaml"
        _write_documents(current_path, current_documents)
        _write_documents(desired_path, desired_documents)

        manual = _run_validator(
            "compare-manual-refresh-only",
            "",
            "--current",
            str(current_path),
            "--desired",
            str(desired_path),
            "--release-name",
            "a-stock",
            "--namespace",
            "a-stock",
            "--image",
            "registry.local/frozen:reviewed-20261009",
        )
        release = _run_validator(
            "compare-release-exact",
            "",
            "--current",
            str(current_path),
            "--desired",
            str(desired_path),
        )

        assert manual.returncode != 0
        assert "hook drift" in manual.stderr
        assert release.returncode != 0
        assert "hook drift" in release.stderr


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_manual_live_comparator_normalizes_statefulset_and_pvc_server_fields(
    tmp_path: Path,
) -> None:
    desired = [
        item
        for item in yaml.safe_load_all(_manual_refresh_render("1"))
        if item
        and "helm.sh/hook"
        not in ((item.get("metadata") or {}).get("annotations") or {})
    ]
    live = copy.deepcopy(desired)
    for item in live:
        metadata = item.setdefault("metadata", {})
        metadata.update(
            {
                "namespace": "a-stock",
                "uid": f"uid-{metadata['name']}",
                "resourceVersion": "42",
                "generation": 3,
                "creationTimestamp": "2026-10-15T00:00:00Z",
            }
        )
        item["status"] = {}
        if item["kind"] == "StatefulSet":
            item["spec"].update(
                {
                    "podManagementPolicy": "OrderedReady",
                    "revisionHistoryLimit": 10,
                    "updateStrategy": {
                        "type": "RollingUpdate",
                        "rollingUpdate": {"partition": 0},
                    },
                    "persistentVolumeClaimRetentionPolicy": {
                        "whenDeleted": "Retain",
                        "whenScaled": "Retain",
                    },
                }
            )
            item["spec"]["template"]["spec"].update(
                {
                    "dnsPolicy": "ClusterFirst",
                    "enableServiceLinks": True,
                    "restartPolicy": "Always",
                    "schedulerName": "default-scheduler",
                    "terminationGracePeriodSeconds": 30,
                    "serviceAccount": "default",
                    "serviceAccountName": "default",
                }
            )
        if item["kind"] == "PersistentVolumeClaim":
            metadata["finalizers"] = ["kubernetes.io/pvc-protection"]
            metadata.setdefault("annotations", {}).update(
                {
                    "pv.kubernetes.io/bind-completed": "yes",
                    "pv.kubernetes.io/bound-by-controller": "yes",
                    "volume.kubernetes.io/storage-provisioner": "rancher.io/local-path",
                }
            )
            item["spec"].update(
                {"volumeName": "pv-reviewed", "volumeMode": "Filesystem"}
            )

    desired_path = tmp_path / "manual-live-desired.yaml"
    _write_documents(desired_path, desired)
    payload = yaml.safe_dump(
        {"apiVersion": "v1", "kind": "List", "items": live}, sort_keys=False
    )
    completed = _run_validator(
        "compare-manual-refresh-live-desired",
        payload,
        "--desired",
        str(desired_path),
        "--release-name",
        "a-stock",
        "--namespace",
        "a-stock",
    )

    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize(
    "failure",
    [
        "duplicate",
        "not-ready",
        "image",
        "enabled",
        "database-secret",
        "namespace",
        "owner",
        "image-id",
        "disabled-env",
        "provider-secret",
        "extra-env",
        "deleting",
    ],
)
def test_promotion_pod_selector_rejects_unsafe_runtime(
    tmp_path: Path, failure: str
) -> None:
    payloads = _sector_runtime_payloads(_render_sector_profile(SECTORS_OFF))
    pod = payloads[2]["items"][0]
    dashboard = pod["spec"]["containers"][0]
    if failure == "duplicate":
        duplicate = copy.deepcopy(pod)
        duplicate["metadata"]["name"] = "a-stock-dashboard-duplicate"
        payloads[2]["items"].append(duplicate)
    elif failure == "not-ready":
        pod["status"]["conditions"][0]["status"] = "False"
    elif failure == "image":
        dashboard["image"] = "registry.local/drift:reviewed-20261009"
    elif failure == "enabled":
        next(
            item
            for item in dashboard["env"]
            if item["name"] == "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED"
        )["value"] = "1"
    elif failure == "database-secret":
        dashboard["env"] = [
            item
            for item in dashboard["env"]
            if item["name"] != "MARKET_ENVIRONMENT_DATABASE_URL"
        ]
    elif failure == "namespace":
        pod["metadata"]["namespace"] = "wrong"
    elif failure == "owner":
        pod["metadata"]["ownerReferences"][0]["uid"] = "wrong"
    elif failure == "image-id":
        pod["status"]["containerStatuses"][0]["imageID"] = "invalid"
    elif failure == "disabled-env":
        next(
            item
            for item in dashboard["env"]
            if item["name"] == "MARKET_ENVIRONMENT_FUYAO_CORE_ENABLED"
        )["value"] = "1"
    elif failure == "provider-secret":
        dashboard["env"] = [
            item
            for item in dashboard["env"]
            if item["name"] != "MARKET_ENVIRONMENT_FUYAO_API_KEY"
        ]
    elif failure == "extra-env":
        dashboard["env"].append({"name": "UNREVIEWED_RUNTIME_FLAG", "value": "1"})
    else:
        pod["metadata"]["deletionTimestamp"] = "2026-10-09T00:00:00Z"

    completed = _run_promotion_pod_selector(tmp_path, payloads)

    assert completed.returncode != 0


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_promotion_pod_selector_returns_exact_ready_disabled_pod(tmp_path: Path) -> None:
    payloads = _sector_runtime_payloads(_render_sector_profile(SECTORS_OFF))

    completed = _run_promotion_pod_selector(tmp_path, payloads)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "a-stock-dashboard-reviewed"


def _run_sectors_pod_selector_with_required(
    tmp_path: Path,
    payloads: tuple[dict, dict, dict],
    *,
    required_enabled: str,
    desired_path: Path,
) -> subprocess.CompletedProcess[str]:
    deployments, replicasets, pods = payloads
    deployments_path = tmp_path / "deployments.json"
    replicasets_path = tmp_path / "replicasets.json"
    deployments_path.write_text(json.dumps(deployments), encoding="utf-8")
    replicasets_path.write_text(json.dumps(replicasets), encoding="utf-8")
    return _run_validator(
        "select-disabled-promotion-pod",
        json.dumps(pods),
        "--release-name",
        "a-stock",
        "--namespace",
        "a-stock",
        "--image",
        "registry.local/frozen:reviewed-20261009",
        "--digest",
        f"sha256:{'d' * 64}",
        "--deployments",
        str(deployments_path),
        "--replicasets",
        str(replicasets_path),
        "--desired",
        str(desired_path),
        "--require-enabled",
        required_enabled,
    )


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_sectors_pod_selector_accepts_enabled_runtime_against_enabled_render(
    tmp_path: Path,
) -> None:
    enabled_render = _render_sector_profile(SECTORS_ENABLED)
    payloads = _sector_runtime_payloads(enabled_render)
    pod = payloads[2]["items"][0]
    dashboard = pod["spec"]["containers"][0]
    for item in dashboard["env"]:
        if item["name"] == "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED":
            item["value"] = "1"
    deployments = payloads[0]["items"]
    for item in deployments:
        for env in item["spec"]["template"]["spec"]["containers"][0]["env"]:
            if env["name"] == "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED":
                env["value"] = "1"
    desired = tmp_path / "enabled.yaml"
    desired.write_text(enabled_render, encoding="utf-8")

    completed = _run_sectors_pod_selector_with_required(
        tmp_path,
        payloads,
        required_enabled="1",
        desired_path=desired,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "a-stock-dashboard-reviewed"


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_sectors_pod_selector_rejects_enabled_runtime_against_off_render(
    tmp_path: Path,
) -> None:
    off_render = _render_sector_profile(SECTORS_OFF)
    payloads = _sector_runtime_payloads(off_render)
    pod = payloads[2]["items"][0]
    dashboard = pod["spec"]["containers"][0]
    for item in dashboard["env"]:
        if item["name"] == "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED":
            item["value"] = "1"
    deployments = payloads[0]["items"]
    for item in deployments:
        for env in item["spec"]["template"]["spec"]["containers"][0]["env"]:
            if env["name"] == "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED":
                env["value"] = "1"
    desired = tmp_path / "off.yaml"
    desired.write_text(off_render, encoding="utf-8")

    completed = _run_sectors_pod_selector_with_required(
        tmp_path,
        payloads,
        required_enabled="1",
        desired_path=desired,
    )

    assert completed.returncode != 0
    assert "differs from the reviewed packet" in completed.stderr


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_select_runtime_sectors_pod_picks_reviewed_render_per_required_enabled() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    required_check = 'if [[ "$required_enabled" == "1" ]]; then'
    assert required_check in source
    off_marker = "REVIEWED_OFF_RENDER"
    enabled_marker = "REVIEWED_ENABLED_RENDER"
    # Both renders must be selectable, and the enabled branch must appear in
    # the file so the selector can pick the matching render for required_enabled=1.
    assert off_marker in source
    assert enabled_marker in source
    assert source.index(required_check) < source.index(enabled_marker)


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_release_comparators_allow_only_add_suspended_and_suspend_flip(tmp_path: Path) -> None:
    disabled = _render(CHART, BASELINE, OFF, "disabled")
    suspended = _render(CHART, BASELINE, SUSPENDED, "suspended")
    active = _render(CHART, BASELINE, ACTIVE, "active")
    disabled_path = tmp_path / "disabled.yaml"
    suspended_desired_path = tmp_path / "suspended-desired.yaml"
    suspended_path = tmp_path / "suspended.yaml"
    active_path = tmp_path / "active.yaml"
    without_hooks = lambda payload: "---\n".join(
        yaml.safe_dump(document, sort_keys=False)
        for document in yaml.safe_load_all(payload)
        if document is not None
        and "helm.sh/hook" not in ((document.get("metadata") or {}).get("annotations") or {})
    )
    disabled_path.write_text(without_hooks(disabled), encoding="utf-8")
    suspended_desired_path.write_text(suspended, encoding="utf-8")
    suspended_path.write_text(without_hooks(suspended), encoding="utf-8")
    active_path.write_text(active, encoding="utf-8")

    add_result = subprocess.run(
        [
            "python3",
            str(VALIDATOR),
            "compare-add-suspended",
            "--release-name",
            "research",
            "--namespace",
            "market-data",
            "--current",
            str(disabled_path),
            "--desired",
            str(suspended_desired_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    activation_result = subprocess.run(
        [
            "python3",
            str(VALIDATOR),
            "compare-suspend-only",
            "--release-name",
            "research",
            "--namespace",
            "market-data",
            "--current",
            str(suspended_path),
            "--desired",
            str(active_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert add_result.returncode == 0, add_result.stderr
    assert activation_result.returncode == 0, activation_result.stderr

    changed = active.replace(
        'image: "localhost/a-stock-market-environment:20260905-1904b66"',
        'image: "localhost/a-stock-market-environment:drift"',
        1,
    )
    changed_path = tmp_path / "changed.yaml"
    changed_path.write_text(changed, encoding="utf-8")
    rejected = subprocess.run(
        [
            "python3",
            str(VALIDATOR),
            "compare-suspend-only",
            "--release-name",
            "research",
            "--namespace",
            "market-data",
            "--current",
            str(suspended_path),
            "--desired",
            str(changed_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert "drift outside CronJob spec.suspend" in rejected.stderr

def _chart_hash(repo: Path) -> str:
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", "deploy/helm/a-stock"],
        cwd=repo,
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    lines = bytearray()
    for raw_path in sorted(path for path in tracked if path):
        relative = raw_path.decode()
        digest = hashlib.sha256((repo / relative).read_bytes()).hexdigest()
        lines.extend(f"{digest}  {relative}\n".encode())
    return hashlib.sha256(lines).hexdigest()

def _prepare_reviewed_repo(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path, str]:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "tests" / "fixtures").mkdir(parents=True)
    (repo / "deploy" / "truenas").mkdir(parents=True)
    shutil.copytree(CHART, repo / "deploy" / "helm" / "a-stock")
    shutil.copy2(SCRIPT, repo / "scripts" / SCRIPT.name)
    shutil.copy2(COMPONENT_FIXTURE, repo / "tests" / "fixtures" / COMPONENT_FIXTURE.name)
    real_validator = repo / "scripts" / "validate-scheduling-packet-real.py"
    shutil.copy2(VALIDATOR, real_validator)
    (repo / "scripts" / VALIDATOR.name).write_text(
        "from __future__ import annotations\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "if len(sys.argv) > 1 and sys.argv[1] == 'validate-activation-window':\n"
        "    counter = Path(os.environ['FAKE_ACTIVATION_WINDOW_COUNTER'])\n"
        "    call_count = int(counter.read_text()) + 1 if counter.exists() else 1\n"
        "    counter.write_text(str(call_count))\n"
        "    fail_on_call = int(os.environ.get('FAKE_ACTIVATION_WINDOW_FAIL_ON_CALL', '0'))\n"
        "    if call_count == fail_on_call:\n"
        "        raise SystemExit('outside the authorized activation window')\n"
        "    print(os.environ.get('FAKE_ACTIVATION_WINDOW_OUTPUT', "
        "'{\"allowed\":true,\"mode\":\"test\"}'))\n"
        "    raise SystemExit(0)\n"
        "real = Path(__file__).with_name('validate-scheduling-packet-real.py')\n"
        "os.execv(sys.executable, [sys.executable, str(real), *sys.argv[1:]])\n",
        encoding="utf-8",
    )
    copied_values = []
    for source in (BASELINE, SUSPENDED, ACTIVE, OFF):
        destination = repo / "deploy" / "truenas" / source.name
        shutil.copy2(source, destination)
        copied_values.append(destination)
    shutil.copy2(ROOT / "Dockerfile", repo / "Dockerfile")

    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=repo, check=True, capture_output=True)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo, check=True, capture_output=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    return repo, *copied_values, head

def test_git_update_is_rejected_before_any_target_or_update_command(tmp_path: Path) -> None:
    fake_bin, marker = _write_target_spies(tmp_path)
    env_file = tmp_path / "deploy.env"
    _write_env(env_file, ROOT, BASELINE, None)
    with env_file.open("a", encoding="utf-8") as stream:
        stream.write("GIT_UPDATE=true\n")

    completed = subprocess.run(
        ["bash", str(SCRIPT), "--env-file", str(env_file)],
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "GIT_UPDATE=true is unsupported" in completed.stderr
    assert not marker.exists()

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_invalid_kubernetes_semver_is_rejected_before_target_access(tmp_path: Path) -> None:
    fake_bin, marker = _write_target_spies(tmp_path)
    env_file = tmp_path / "deploy.env"
    _write_env(env_file, ROOT, BASELINE, SUSPENDED)

    completed = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--env-file",
            str(env_file),
            "--server-dry-run",
            "--kube-version",
            "1.26.6-.",
        ],
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "invalid Kubernetes version" in completed.stderr
    assert not marker.exists()

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_native_kubernetes_prerelease_is_rejected_before_target_access(tmp_path: Path) -> None:
    fake_bin, marker = _write_target_spies(tmp_path)
    overlay = tmp_path / "native-suspended.yaml"
    _write_native_overlay(overlay)
    baseline = _values_with_database_secret(tmp_path)
    env_file = tmp_path / "deploy.env"
    _write_env(env_file, ROOT, baseline, overlay)

    completed = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--env-file",
            str(env_file),
            "--server-dry-run",
            "--kube-version",
            "1.27.0-rc.1",
        ],
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "requires Kubernetes 1.27.0 stable or later" in completed.stderr
    assert "operation server-dry-run rejected the final scheduling state" in completed.stderr
    assert not marker.exists()

def _cronjob_list(rendered: str) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "List",
        "items": [
            document
            for document in yaml.safe_load_all(rendered)
            if document and document.get("kind") == "CronJob"
        ],
    }

def _run_generic_deploy(
    tmp_path: Path,
    *,
    stored_overlay: Path,
    live_overlay: Path,
    component: str = "all",
    outcome: str = "off",
    release_present: bool = True,
    live_label_drift: bool = False,
    reviewed_head_state: str = "valid",
    dirty_tree: bool = False,
    preset_digest: str | None = None,
    digest_drift_call: int | None = None,
    deploy_tmp_root: Path | None = None,
    image_size_output: str = "1048576",
    archive_available_kib: int = 4 * 1024 * 1024,
    tmpdir: Path | None = None,
    tmpdir_available_kib: int | None = None,
    scp_exit_code: int = 0,
) -> tuple[subprocess.CompletedProcess[str], str, dict]:
    repo, baseline, suspended, active, off, head = _prepare_reviewed_repo(tmp_path)
    overlays = {path.name: path for path in (suspended, active, off)}
    stored_manifest = tmp_path / "generic-stored.yaml"
    stored_manifest.write_text(
        _render_reviewed(
            repo,
            baseline,
            overlays[stored_overlay.name],
            release_name="a-stock",
            namespace="a-stock",
        ),
        encoding="utf-8",
    )
    live_state = tmp_path / "generic-live.json"
    live_state.write_text(
        json.dumps(
            _cronjob_list(
                _render_reviewed(
                    repo,
                    baseline,
                    overlays[live_overlay.name],
                    release_name="a-stock",
                    namespace="a-stock",
                )
            )
        ),
        encoding="utf-8",
    )
    if live_label_drift:
        payload = json.loads(live_state.read_text(encoding="utf-8"))
        for item in payload["items"]:
            item["metadata"]["labels"].pop("app.kubernetes.io/instance", None)
        live_state.write_text(json.dumps(payload), encoding="utf-8")
    off_state = tmp_path / "generic-off.json"
    off_state.write_text(
        json.dumps(
            _cronjob_list(
                _render_reviewed(
                    repo, baseline, off, release_name="a-stock", namespace="a-stock"
                )
            )
        ),
        encoding="utf-8",
    )
    suspended_state = tmp_path / "generic-suspended.json"
    suspended_state.write_text(
        json.dumps(
            _cronjob_list(
                _render_reviewed(
                    repo,
                    baseline,
                    suspended,
                    release_name="a-stock",
                    namespace="a-stock",
                )
            )
        ),
        encoding="utf-8",
    )
    active_state = tmp_path / "generic-active.json"
    active_state.write_text(
        json.dumps(
            _cronjob_list(
                _render_reviewed(
                    repo, baseline, active, release_name="a-stock", namespace="a-stock"
                )
            )
        ),
        encoding="utf-8",
    )
    runtime_render = _render_reviewed(
        repo, baseline, off, release_name="a-stock", namespace="a-stock"
    ).replace("20260905-1904b66", "test-generic")
    runtime_payloads = _runtime_payloads(
        runtime_render, "a-stock", f"sha256:{'c' * 64}"
    )
    for payload in runtime_payloads:
        for item in payload["items"]:
            item.setdefault("metadata", {})["namespace"] = "a-stock"
    runtime_deployments = tmp_path / "generic-runtime-deployments.json"
    runtime_replicasets = tmp_path / "generic-runtime-replicasets.json"
    runtime_pods = tmp_path / "generic-runtime-pods.json"
    runtime_deployments.write_text(json.dumps(runtime_payloads[0]), encoding="utf-8")
    runtime_replicasets.write_text(json.dumps(runtime_payloads[1]), encoding="utf-8")
    runtime_pods.write_text(json.dumps(runtime_payloads[2]), encoding="utf-8")
    drifted_runtime_pods = copy.deepcopy(runtime_payloads[2])
    drifted_runtime_pods["items"][0]["metadata"]["ownerReferences"][0]["uid"] = (
        "wrong-replicaset"
    )
    drifted_runtime_pods_path = tmp_path / "generic-runtime-pods-drifted.json"
    drifted_runtime_pods_path.write_text(
        json.dumps(drifted_runtime_pods), encoding="utf-8"
    )

    fake_bin = tmp_path / "generic-bin"
    fake_bin.mkdir()
    calls = tmp_path / "generic-calls"
    released = tmp_path / "generic-released"
    post_read_failed = tmp_path / "generic-post-read-failed"
    digest_calls = tmp_path / "generic-digest-calls"
    helm_wrapper = fake_bin / "helm"
    helm_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'helm %s\\n' \"$*\" >> {calls}\n"
        "case \"$1\" in\n"
        "  lint|template) exec \"$REAL_HELM\" \"$@\" ;;\n"
        "  list) if [[ \"$GENERIC_RELEASE_PRESENT\" == true ]]; then printf '[{\"name\":\"a-stock\"}]\\n'; else printf '[]\\n'; fi ;;\n"
        f"  get) [[ \"$GENERIC_RELEASE_PRESENT\" == true ]] || exit 96; cat {stored_manifest} ;;\n"
        "  upgrade)\n"
        "    case \"$GENERIC_UPGRADE_OUTCOME\" in\n"
        f"      fail-active) cp {active_state} {live_state}; exit 95 ;;\n"
        f"      signal-active) cp {active_state} {live_state}; touch {released}; kill -TERM \"$PPID\"; sleep 0.1 ;;\n"
        f"      post-read-active|rollout-active|postcondition-active) cp {active_state} {live_state}; touch {released} ;;\n"
        f"      off|chart-drift|runtime-drift|prewrite-digest-drift|import-digest-missing|import-digest-mismatch) cp {off_state} {live_state}; touch {released} ;;\n"
        "      *) exit 98 ;;\n"
        "    esac\n"
        "    ;;\n"
        "  *) exit 97 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    helm_wrapper.chmod(0o755)

    kubectl_wrapper = fake_bin / "kubectl"
    kubectl_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'kubectl %s\\n' \"$*\" >> {calls}\n"
        "if [[ \"$*\" == *\"get nodes\"* ]]; then printf amd64; exit 0; fi\n"
        "if [[ \"$*\" == *\"get --raw /version\"* ]]; then printf '{\"gitVersion\":\"v1.26.6+k3s1\"}'; exit 0; fi\n"
        "if [[ \"$1\" == get && \"$2\" == cronjob ]]; then\n"
        "  if [[ \"$*\" == *\" -l app.kubernetes.io/instance=\"* ]]; then\n"
        "    if [[ \"$GENERIC_LIVE_LABEL_DRIFT\" == true ]]; then printf '{\"apiVersion\":\"v1\",\"kind\":\"List\",\"items\":[]}'; else "
        f"cat {live_state}; fi\n"
        "  else\n"
        "    [[ \"$3\" == a-stock-data-collection ]] || exit 92\n"
        f"    python3 -c 'import json,sys; p=json.load(open(sys.argv[1])); print(json.dumps(p[\"items\"][0])) if p[\"items\"] else None' {live_state}\n"
        "  fi\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"$1\" == get && \"$2\" == pvc ]]; then printf '{\"metadata\":{\"name\":\"a-stock-postgresql-data\"},\"spec\":{\"accessModes\":[\"ReadWriteOnce\"]},\"status\":{\"phase\":\"Bound\"}}'; exit 0; fi\n"
        "if [[ \"$1\" == get && \"$2\" == statefulset ]]; then printf '{\"spec\":{\"replicas\":1},\"status\":{\"readyReplicas\":1}}'; exit 0; fi\n"
        "if [[ \"$1\" == patch && \"$2\" == cronjob ]]; then\n"
        "  [[ \"$3\" == a-stock-data-collection && \"$*\" == *\"--namespace a-stock\"* && \"$*\" == *\"--patch {\\\"spec\\\":{\\\"suspend\\\":true}}\"* ]] || exit 91\n"
        f"  cp {suspended_state} {live_state}\n"
        "  exit 0\n"
        "fi\n"
        f"if [[ \"$*\" == *\"get deployment\"* && -f {released} && \"$GENERIC_UPGRADE_OUTCOME\" == post-read-active && ! -f {post_read_failed} ]]; then touch {post_read_failed}; exit 96; fi\n"
        f"if [[ \"$*\" == *\"get deployment --namespace\"* && \"$*\" == *\"-o json\"* ]]; then cat {runtime_deployments}; exit 0; fi\n"
        f"if [[ \"$*\" == *\"get replicasets --namespace\"* && \"$*\" == *\"-o json\"* ]]; then cat {runtime_replicasets}; exit 0; fi\n"
        f"if [[ \"$*\" == *\"get pods --namespace\"* && \"$*\" == *\"-o json\"* ]]; then if [[ \"$GENERIC_UPGRADE_OUTCOME\" == runtime-drift && -f {released} ]]; then cat {drifted_runtime_pods_path}; else cat {runtime_pods}; fi; exit 0; fi\n"
        "if [[ \"$*\" == *\"get deployment\"* ]]; then printf a-stock; exit 0; fi\n"
        "if [[ \"$*\" == *\"rollout status\"* ]]; then [[ \"$GENERIC_UPGRADE_OUTCOME\" != rollout-active ]] || exit 93; exit 0; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    kubectl_wrapper.chmod(0o755)

    podman_wrapper = fake_bin / "podman"
    podman_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'podman %s\\n' \"$*\" >> {calls}\n"
        "if [[ \"$1 $2\" == \"image inspect\" ]]; then printf '%s\\n' \"$PODMAN_IMAGE_SIZE_OUTPUT\"; exit 0; fi\n"
        "if [[ \"$1\" == save ]]; then\n"
        "  while (($#)); do\n"
        "    if [[ \"$1\" == --output ]]; then : > \"$2\"; exit 0; fi\n"
        "    shift\n"
        "  done\n"
        "  exit 99\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    podman_wrapper.chmod(0o755)
    df_wrapper = fake_bin / "df"
    df_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        "target=\"${@: -1}\"\n"
        "available=\"$ARCHIVE_AVAILABLE_KIB\"\n"
        "if [[ -n \"${ARCHIVE_LOW_SPACE_PATH:-}\" && \"$target\" == \"$ARCHIVE_LOW_SPACE_PATH\"* ]]; then available=\"$ARCHIVE_LOW_SPACE_KIB\"; fi\n"
        "printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\n'\n"
        "printf 'fixture 8388608 0 %s 0%% /fixture\\n' \"$available\"\n",
        encoding="utf-8",
    )
    df_wrapper.chmod(0o755)
    ssh_wrapper = fake_bin / "ssh"
    ssh_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'ssh %s\\n' \"$*\" >> {calls}\n"
        "if [[ \"$GENERIC_UPGRADE_OUTCOME\" == pre-write-active && \"$*\" == *\"images import\"* ]]; then\n"
        f"  cp {active_state} {live_state}\n"
        "fi\n"
        "if [[ \"$GENERIC_UPGRADE_OUTCOME\" == chart-drift && \"$*\" == *\"images import\"* ]]; then\n"
        f"  printf '\\n{{{{ fail \"SOURCE_CHART_DRIFT\" }}}}\\n' >> {repo / 'deploy' / 'helm' / 'a-stock' / 'templates' / 'market-data-collection-cronjob.yaml'}\n"
        "fi\n"
        "if [[ \"$*\" == *\"images ls\"* && \"$*\" == *\"Target\"* ]]; then\n"
        f"  printf '{{\"Name\":\"localhost/a-stock-market-environment:test-generic\",\"Target\":{{\"digest\":\"sha256:{'d' * 64}\"}}}}\\n'\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"$*\" == *\"images ls\"* ]]; then\n"
        f"  count=0; if [[ -f {digest_calls} ]]; then count=$(cat {digest_calls}); fi; count=$((count + 1)); printf '%s' \"$count\" > {digest_calls}\n"
        "  if [[ \"$GENERIC_UPGRADE_OUTCOME\" == import-digest-missing && \"$count\" == 1 ]]; then exit 1; fi\n"
        "  if [[ \"$GENERIC_DIGEST_DRIFT_CALL\" -gt 0 && \"$count\" -eq \"$GENERIC_DIGEST_DRIFT_CALL\" ]]; then\n"
        f"    printf 'sha256:{'e' * 64}\\n'\n"
        "  else\n"
        f"    printf 'sha256:{'d' * 64}\\n'\n"
        "  fi\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    ssh_wrapper.chmod(0o755)
    for name in ("nc", "scp", "curl"):
        executable = fake_bin / name
        executable.write_text(
            "#!/usr/bin/env bash\n"
            f"printf '{name} %s\\n' \"$*\" >> {calls}\n"
            + ("exit \"$SCP_EXIT_CODE\"\n" if name == "scp" else "exit 0\n"),
            encoding="utf-8",
        )
        executable.chmod(0o755)

    kubeconfig = tmp_path / "generic-kubeconfig"
    kubeconfig.write_text("fixture", encoding="utf-8")
    env_file = tmp_path / "generic.env"
    reviewed_head_lines: list[str] = []
    if reviewed_head_state == "valid":
        reviewed_head_lines.append(f"REVIEWED_GIT_HEAD={head}")
    elif reviewed_head_state == "mismatch":
        reviewed_head_lines.append(f"REVIEWED_GIT_HEAD={'0' * 40}")
    elif reviewed_head_state == "invalid":
        reviewed_head_lines.append("REVIEWED_GIT_HEAD=ABC123")
    elif reviewed_head_state != "missing":
        raise AssertionError(f"unsupported reviewed_head_state: {reviewed_head_state}")
    if preset_digest is not None:
        reviewed_head_lines.append(f"FROZEN_IMAGE_DIGEST={preset_digest}")
    env_file.write_text(
        "\n".join(
            [
                f"REPO_DIR={repo}",
                "TRUENAS_HOST=192.0.2.10",
                "TRUENAS_SSH_USER=tester",
                "REMOTE_IMAGE_DIR=/unreachable",
                f"KUBECONFIG={kubeconfig}",
                f"HELM_VALUES_FILE={baseline}",
                "IMAGE_TAG=test-generic",
                *reviewed_head_lines,
                *(
                    [f"DEPLOY_TMP_ROOT={_bash_path(deploy_tmp_root)}"]
                    if deploy_tmp_root is not None
                    else []
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )
    if dirty_tree:
        (repo / "unreviewed.txt").write_text("dirty\n", encoding="utf-8")
    command = ["bash", str(repo / "scripts" / SCRIPT.name), "--env-file", str(env_file)]
    if component != "all":
        command.extend(["--component", component])
    completed = subprocess.run(
        command,
        env={
            **os.environ,
            **({"TMPDIR": _bash_path(tmpdir)} if tmpdir is not None else {}),
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "REAL_HELM": HELM or "helm",
            "GENERIC_UPGRADE_OUTCOME": outcome,
            "GENERIC_DIGEST_DRIFT_CALL": str(
                digest_drift_call
                if digest_drift_call is not None
                else (2 if outcome == "prewrite-digest-drift" else 0)
            ),
            "GENERIC_RELEASE_PRESENT": str(release_present).lower(),
            "GENERIC_LIVE_LABEL_DRIFT": str(live_label_drift).lower(),
            "PODMAN_IMAGE_SIZE_OUTPUT": image_size_output,
            "ARCHIVE_AVAILABLE_KIB": str(archive_available_kib),
            "ARCHIVE_LOW_SPACE_PATH": _bash_path(tmpdir) if tmpdir is not None else "",
            "ARCHIVE_LOW_SPACE_KIB": str(
                tmpdir_available_kib
                if tmpdir_available_kib is not None
                else archive_available_kib
            ),
            "SCP_EXIT_CODE": str(scp_exit_code),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    call_log = calls.read_text(encoding="utf-8") if calls.exists() else ""
    return completed, call_log, json.loads(live_state.read_text(encoding="utf-8"))


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize("component", ["all", "service"])
@pytest.mark.parametrize(
    ("reviewed_head_state", "dirty_tree"),
    [
        ("missing", False),
        ("mismatch", False),
        ("invalid", False),
        ("valid", True),
    ],
    ids=["missing-head", "mismatched-head", "invalid-head", "dirty-tree"],
)
def test_generic_all_service_rejects_unreviewed_source_before_target_access(
    tmp_path: Path,
    component: str,
    reviewed_head_state: str,
    dirty_tree: bool,
) -> None:
    completed, calls, _ = _run_generic_deploy(
        tmp_path,
        stored_overlay=OFF,
        live_overlay=OFF,
        component=component,
        reviewed_head_state=reviewed_head_state,
        dirty_tree=dirty_tree,
    )

    assert completed.returncode != 0
    if dirty_tree:
        assert "clean working tree" in completed.stderr
    elif reviewed_head_state == "invalid":
        assert "full lowercase commit SHA" in completed.stderr
    else:
        assert "REVIEWED_GIT_HEAD" in completed.stderr or "reviewed Git HEAD" in completed.stderr
    target_prefixes = ("ssh ", "kubectl ", "podman ", "scp ", "curl ", "nc ")
    assert not any(line.startswith(target_prefixes) for line in calls.splitlines())


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize(
    ("outcome", "preset_digest", "error"),
    [
        ("import-digest-missing", None, "could not resolve one exact"),
        (
            "import-digest-mismatch",
            f"sha256:{'a' * 64}",
            "imported image digest drift",
        ),
    ],
)
@pytest.mark.parametrize("component", ["all", "service"])
def test_generic_all_service_rejects_import_digest_failure_before_helm_write(
    tmp_path: Path,
    outcome: str,
    preset_digest: str | None,
    error: str,
    component: str,
) -> None:
    completed, calls, _ = _run_generic_deploy(
        tmp_path,
        stored_overlay=OFF,
        live_overlay=OFF,
        component=component,
        outcome=outcome,
        preset_digest=preset_digest,
    )

    assert completed.returncode != 0
    assert error in completed.stderr
    assert "images import" in calls
    assert "helm upgrade" not in calls


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize(
    ("component", "digest_drift_call", "completed_components"),
    [
        ("service", 2, []),
        ("all", 2, []),
        ("all", 3, ["database"]),
        ("all", 4, ["database", "service"]),
    ],
    ids=[
        "service-before-write",
        "all-before-database",
        "all-before-service",
        "all-before-final",
    ],
)
def test_generic_deploy_rejects_manifest_digest_drift_before_each_helm_write(
    tmp_path: Path,
    component: str,
    digest_drift_call: int,
    completed_components: list[str],
) -> None:
    completed, calls, _ = _run_generic_deploy(
        tmp_path,
        stored_overlay=OFF,
        live_overlay=OFF,
        component=component,
        digest_drift_call=digest_drift_call,
    )

    assert completed.returncode != 0
    assert "digest" in (completed.stdout + completed.stderr).lower()
    digest_captures = [
        line
        for line in calls.splitlines()
        if line.startswith("ssh ") and "images ls" in line and "matches += 1" in line
    ]
    upgrades = [line for line in calls.splitlines() if line.startswith("helm upgrade ")]
    assert len(digest_captures) == digest_drift_call
    assert len(upgrades) == len(completed_components)
    for upgrade, completed_component in zip(upgrades, completed_components, strict=True):
        assert f"--set component={completed_component}" in upgrade
    assert not any("--set component=all" in upgrade for upgrade in upgrades)


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_generic_service_rejects_runtime_owner_drift_after_rollout(tmp_path: Path) -> None:
    completed, calls, _ = _run_generic_deploy(
        tmp_path,
        stored_overlay=OFF,
        live_overlay=OFF,
        component="service",
        outcome="runtime-drift",
    )

    assert completed.returncode != 0
    assert sum(line.startswith("helm upgrade ") for line in calls.splitlines()) == 1
    assert "frozen_image_runtime_unproven" in completed.stdout
    assert "controlled by ReplicaSet" in completed.stderr

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize("blocked_overlay", [ACTIVE, SUSPENDED], ids=["active", "suspended"])
@pytest.mark.parametrize("blocked_source", ["stored", "live"])
def test_generic_deploy_requires_reviewed_disable_for_existing_schedule(
    tmp_path: Path, blocked_overlay: Path, blocked_source: str
) -> None:
    stored_overlay = blocked_overlay if blocked_source == "stored" else OFF
    completed, calls, _ = _run_generic_deploy(
        tmp_path,
        stored_overlay=stored_overlay,
        live_overlay=blocked_overlay,
    )

    assert completed.returncode != 0
    assert f"{blocked_source} Helm release scheduling" in completed.stderr or (
        blocked_source == "live" and "live release scheduling" in completed.stderr
    )
    assert "reviewed --disable-schedule mode first" in completed.stderr
    assert "helm upgrade" not in calls
    assert "podman build" not in calls

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_generic_deploy_rechecks_live_schedule_immediately_before_helm(tmp_path: Path) -> None:
    completed, calls, _ = _run_generic_deploy(
        tmp_path,
        stored_overlay=OFF,
        live_overlay=OFF,
        outcome="pre-write-active",
    )

    assert completed.returncode != 0
    assert "live release scheduling to be off/absent" in completed.stderr
    assert "reviewed --disable-schedule mode first" in completed.stderr
    assert calls.count("helm list --all --namespace a-stock") == 2
    assert "podman build" in calls
    assert "helm upgrade" not in calls

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_generic_deploy_exact_name_lookup_cannot_miss_label_drift(tmp_path: Path) -> None:
    completed, calls, _ = _run_generic_deploy(
        tmp_path,
        stored_overlay=OFF,
        live_overlay=ACTIVE,
        live_label_drift=True,
    )

    assert completed.returncode != 0
    assert "CronJob release label must equal a-stock" in completed.stderr
    assert "live release scheduling to be off/absent" in completed.stderr
    assert "kubectl get cronjob a-stock-data-collection --namespace a-stock" in calls
    assert " -l app.kubernetes.io/instance=" not in calls
    assert "podman build" not in calls
    assert "helm upgrade" not in calls

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_generic_deploy_uses_frozen_chart_after_source_drift(tmp_path: Path) -> None:
    completed, calls, live = _run_generic_deploy(
        tmp_path,
        stored_overlay=OFF,
        live_overlay=OFF,
        outcome="chart-drift",
    )

    assert completed.returncode == 0, completed.stderr
    upgrade = next(line for line in calls.splitlines() if line.startswith("helm upgrade"))
    assert "/release-packet/chart" in upgrade
    assert "/repo/deploy/helm/a-stock" not in upgrade
    assert live["items"] == []

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize(
    ("outcome", "expected_returncode"),
    [
        ("fail-active", 95),
        ("signal-active", 143),
        ("post-read-active", 96),
        ("rollout-active", 93),
        ("postcondition-active", 1),
    ],
)
def test_generic_deploy_failure_never_leaves_atomic_restored_schedule_active(
    tmp_path: Path, outcome: str, expected_returncode: int
) -> None:
    completed, calls, live = _run_generic_deploy(
        tmp_path,
        stored_overlay=OFF,
        live_overlay=OFF,
        outcome=outcome,
    )

    assert completed.returncode == expected_returncode
    assert completed.stdout.count(
        "generic deployment precondition: stored and live scheduling are off/absent"
    ) == 2
    assert "helm upgrade" in calls
    assert "--atomic" in next(line for line in calls.splitlines() if line.startswith("helm upgrade"))
    assert calls.count("kubectl patch cronjob a-stock-data-collection") == 1
    upgrade_index = calls.splitlines().index(
        next(line for line in calls.splitlines() if line.startswith("helm upgrade"))
    )
    assert sum(
        line.startswith("kubectl get cronjob")
        for line in calls.splitlines()[upgrade_index + 1 :]
    ) >= 2
    cronjob = live["items"][0]
    assert cronjob["spec"]["suspend"] is True
    assert "generic deployment failure recovery: scheduling is suspended" in completed.stdout

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_generic_deploy_success_proves_schedule_remains_absent(tmp_path: Path) -> None:
    completed, calls, live = _run_generic_deploy(
        tmp_path,
        stored_overlay=OFF,
        live_overlay=OFF,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.count(
        "generic deployment precondition: stored and live scheduling are off/absent"
    ) == 2
    assert calls.count("helm list --all --namespace a-stock") == 2
    digest_captures = [
        line
        for line in calls.splitlines()
        if line.startswith("ssh ") and "images ls" in line and "matches += 1" in line
    ]
    upgrades = [line for line in calls.splitlines() if line.startswith("helm upgrade ")]
    assert len(digest_captures) == 4
    assert len(upgrades) == 3
    for upgrade, component in zip(
        upgrades, ["database", "service", "all"], strict=True
    ):
        assert f"--set component={component}" in upgrade
    assert live["items"] == []
    assert "patch cronjob" not in calls


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_generic_deploy_uses_and_cleans_explicit_archive_temp_root(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive-root"
    archive_root.mkdir()
    completed, calls, _ = _run_generic_deploy(
        tmp_path,
        stored_overlay=OFF,
        live_overlay=OFF,
        deploy_tmp_root=archive_root,
    )

    assert completed.returncode == 0, completed.stderr
    assert f"image archive workspace: root={archive_root.resolve()}" in completed.stdout
    save_call = next(line for line in calls.splitlines() if line.startswith("podman save"))
    assert f"--output {archive_root.resolve()}/a-stock-deploy-image." in save_call
    assert list(archive_root.iterdir()) == []


@pytest.mark.skipif(
    HELM is None or not Path("/dev/shm").is_dir(),
    reason="helm or /dev/shm is unavailable",
)
def test_generic_deploy_falls_back_from_small_tmpdir_to_dev_shm(tmp_path: Path) -> None:
    control_tmpdir = tmp_path / "control-tmp"
    control_tmpdir.mkdir()
    completed, calls, _ = _run_generic_deploy(
        tmp_path,
        stored_overlay=OFF,
        live_overlay=OFF,
        tmpdir=control_tmpdir,
        tmpdir_available_kib=1,
    )

    assert completed.returncode == 0, completed.stderr
    assert "image archive workspace: root=/dev/shm" in completed.stdout
    save_call = next(line for line in calls.splitlines() if line.startswith("podman save"))
    archive_path = Path(save_call.split("--output ", 1)[1].split(" ", 1)[0])
    assert archive_path.parent.parent == Path("/dev/shm")
    assert not archive_path.parent.exists()
    assert list(control_tmpdir.iterdir()) == []


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_generic_deploy_cleans_archive_workspace_when_scp_fails(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive-root"
    archive_root.mkdir()
    completed, calls, _ = _run_generic_deploy(
        tmp_path,
        stored_overlay=OFF,
        live_overlay=OFF,
        deploy_tmp_root=archive_root,
        scp_exit_code=88,
    )

    assert completed.returncode == 88
    save_call = next(line for line in calls.splitlines() if line.startswith("podman save"))
    archive_path = Path(save_call.split("--output ", 1)[1].split(" ", 1)[0])
    assert not archive_path.parent.exists()
    assert "images import" not in calls
    assert "helm upgrade" not in calls


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_generic_deploy_rejects_insufficient_explicit_archive_space_before_save(
    tmp_path: Path,
) -> None:
    archive_root = tmp_path / "archive-root"
    archive_root.mkdir()
    completed, calls, _ = _run_generic_deploy(
        tmp_path,
        stored_overlay=OFF,
        live_overlay=OFF,
        deploy_tmp_root=archive_root,
        archive_available_kib=1,
    )

    assert completed.returncode != 0
    assert "image archive requires" in completed.stderr
    assert "Set DEPLOY_TMP_ROOT" in completed.stderr
    assert "podman build" in calls
    assert "podman image inspect" in calls
    assert "podman save" not in calls
    assert "scp " not in calls
    assert "images import" not in calls
    assert "helm upgrade" not in calls


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize("image_size_output", ["", "0", "abc", "0123"])
def test_generic_deploy_rejects_invalid_image_size_before_save(
    tmp_path: Path, image_size_output: str
) -> None:
    archive_root = tmp_path / "archive-root"
    archive_root.mkdir()
    completed, calls, _ = _run_generic_deploy(
        tmp_path,
        stored_overlay=OFF,
        live_overlay=OFF,
        deploy_tmp_root=archive_root,
        image_size_output=image_size_output,
    )

    assert completed.returncode != 0
    assert "could not determine a positive local image size" in completed.stderr
    assert "podman save" not in calls
    assert "scp " not in calls
    assert "helm upgrade" not in calls


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_generic_deploy_local_smoke_supplies_required_database_setting(tmp_path: Path) -> None:
    completed, calls, _ = _run_generic_deploy(
        tmp_path,
        stored_overlay=OFF,
        live_overlay=OFF,
    )

    assert completed.returncode == 0, completed.stderr
    podman_run = next(line for line in calls.splitlines() if line.startswith("podman run"))
    assert (
        "--env MARKET_ENVIRONMENT_DATABASE_URL="
        "postgresql+psycopg://smoke:smoke@127.0.0.1:1/smoke"
    ) in podman_run


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_generic_deploy_allows_new_release_only_when_live_schedule_is_absent(
    tmp_path: Path,
) -> None:
    completed, calls, live = _run_generic_deploy(
        tmp_path,
        stored_overlay=OFF,
        live_overlay=OFF,
        release_present=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert calls.count("helm list --all --namespace a-stock") == 2
    assert "helm get manifest" not in calls
    assert "helm upgrade --install" in calls
    assert live["items"] == []

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize("live_overlay", [ACTIVE, SUSPENDED], ids=["active", "suspended"])
def test_generic_deploy_rejects_live_schedule_for_new_release(
    tmp_path: Path, live_overlay: Path
) -> None:
    completed, calls, _ = _run_generic_deploy(
        tmp_path,
        stored_overlay=OFF,
        live_overlay=live_overlay,
        release_present=False,
    )

    assert completed.returncode != 0
    assert "live release scheduling to be off/absent" in completed.stderr
    assert "reviewed --disable-schedule mode first" in completed.stderr
    assert "helm get manifest" not in calls
    assert "podman build" not in calls
    assert "helm upgrade" not in calls

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_read_only_discovery_uses_live_version_without_render_hash(tmp_path: Path) -> None:
    repo, _, _, _, _, head = _prepare_reviewed_repo(tmp_path)
    fake_bin = tmp_path / "read-only-bin"
    fake_bin.mkdir()
    calls = tmp_path / "read-only-calls"
    for name, body in {
        "helm": (
            "case \"$1\" in\n"
            "  history) printf 'revision 7\\n' ;;\n"
            "  get) printf 'marketEnvironment: {}\\n' ;;\n"
            "  *) exit 98 ;;\n"
            "esac\n"
        ),
        "ssh": "exit 0\n",
        "nc": "exit 0\n",
        "podman": f"printf podman >> {calls}\nexit 97\n",
        "kubectl": (
            "if [[ \"$*\" == *\"get nodes\"* ]]; then printf amd64; exit 0; fi\n"
            "if [[ \"$*\" == *\"get --raw /version\"* ]]; then "
            "printf '{\"gitVersion\":\"v1.26.6+k3s1\"}'; exit 0; fi\n"
            "printf '{}\\n'\n"
        ),
    }.items():
        executable = fake_bin / name
        executable.write_text(
            f"#!/usr/bin/env bash\nprintf '{name} %s\\n' \"$*\" >> {calls}\n{body}",
            encoding="utf-8",
        )
        executable.chmod(0o755)

    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("fixture", encoding="utf-8")
    env_file = tmp_path / "read-only.env"
    env_file.write_text(
        "\n".join(
            [
                f"REPO_DIR={repo}",
                "TRUENAS_HOST=192.0.2.10",
                "TRUENAS_SSH_USER=tester",
                f"KUBECONFIG={kubeconfig}",
                f"REVIEWED_GIT_HEAD={head}",
                f"REVIEWED_CHART_SHA256={_chart_hash(repo)}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            "bash",
            str(repo / "scripts" / SCRIPT.name),
            "--env-file",
            str(env_file),
            "--read-only-discovery",
            "--release-name",
            "a-stock",
            "--namespace",
            "a-stock",
        ],
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Kubernetes 1.26.6+k3s1" in completed.stdout
    assert "podman" not in calls.read_text(encoding="utf-8")

def _render_reviewed(
    repo: Path,
    baseline: Path,
    overlay: Path,
    *,
    release_name: str = "research",
    namespace: str = "market-data",
) -> str:
    assert HELM is not None
    return subprocess.run(
        [
            HELM,
            "template",
            release_name,
            str(repo / "deploy" / "helm" / "a-stock"),
            "--namespace",
            namespace,
            "--kube-version",
            "1.26.6+k3s1",
            "--values",
            str(baseline),
            "--values",
            str(overlay),
            "--set",
            "image.repository=localhost/a-stock-market-environment",
            "--set",
            "image.tag=20260905-1904b66",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.rstrip("\n") + "\n"
def _live_list(rendered: str, namespace: str) -> str:
    items = [item for item in yaml.safe_load_all(rendered) if item]
    for item in items:
        item.setdefault("metadata", {})["namespace"] = namespace
    return yaml.safe_dump(
        {"apiVersion": "v1", "kind": "List", "items": items},
        sort_keys=False,
    )

def _runtime_payloads(rendered: str, release: str, digest: str) -> tuple[dict, dict, dict]:
    documents = [item for item in yaml.safe_load_all(rendered) if item]
    deployment = next(item for item in documents if item["kind"] == "Deployment")
    image = deployment["spec"]["template"]["spec"]["containers"][0]["image"]
    deployment["metadata"].update(
        {
            "uid": "deployment-current",
            "annotations": {"deployment.kubernetes.io/revision": "2"},
        }
    )
    labels = {"app.kubernetes.io/instance": release}
    replicaset = {
        "apiVersion": "apps/v1",
        "kind": "ReplicaSet",
        "metadata": {
            "name": "research-a-stock-current",
            "uid": "replicaset-current",
            "labels": labels,
            "annotations": {"deployment.kubernetes.io/revision": "2"},
            "ownerReferences": [
                {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "name": deployment["metadata"]["name"],
                    "uid": "deployment-current",
                    "controller": True,
                }
            ],
        },
        "spec": {"template": {"spec": {"containers": [{"name": "dashboard", "image": image}]}}},
    }
    dashboard_pod = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "research-a-stock-current-pod",
            "uid": "dashboard-pod",
            "labels": labels,
            "ownerReferences": [
                {
                    "apiVersion": "apps/v1",
                    "kind": "ReplicaSet",
                    "name": replicaset["metadata"]["name"],
                    "uid": "replicaset-current",
                    "controller": True,
                }
            ],
        },
        "spec": {"containers": [{"name": "dashboard", "image": image}]},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}],
            "containerStatuses": [
                {
                    "name": "dashboard",
                    "image": image,
                    "imageID": f"containerd://{digest}",
                    "ready": True,
                }
            ],
        },
    }
    retained_collector_pod = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "research-a-stock-data-collection-old",
            "uid": "collector-pod",
            "labels": labels,
            "ownerReferences": [
                {
                    "apiVersion": "batch/v1",
                    "kind": "Job",
                    "name": "research-a-stock-data-collection-old",
                    "uid": "collector-job",
                    "controller": True,
                }
            ],
        },
        "spec": {"containers": [{"name": "collector", "image": image}]},
        "status": {"phase": "Succeeded"},
    }
    return (
        {"apiVersion": "apps/v1", "kind": "DeploymentList", "items": [deployment]},
        {"apiVersion": "apps/v1", "kind": "ReplicaSetList", "items": [replicaset]},
        {"apiVersion": "v1", "kind": "PodList", "items": [dashboard_pod, retained_collector_pod]},
    )


def _run_disable_schedule_with_job_evidence(
    tmp_path: Path,
    *,
    outcome: str = "success",
) -> tuple[subprocess.CompletedProcess[str], str]:
    repo, baseline, suspended, _, off, _ = _prepare_reviewed_repo(tmp_path)
    digest = f"sha256:{'d' * 64}"
    image_repository = "localhost/a-stock-market-environment"
    image_tag = "20260905-1904b66"
    suspended_render = _render_reviewed(
        repo, baseline, suspended, release_name="a-stock", namespace="a-stock"
    )
    off_render = _render_reviewed(
        repo, baseline, off, release_name="a-stock", namespace="a-stock"
    )

    def live_release(rendered: str) -> str:
        items = []
        for document in yaml.safe_load_all(rendered):
            if not document or document.get("kind") not in {
                "Deployment",
                "Service",
                "CronJob",
            }:
                continue
            document = copy.deepcopy(document)
            document.setdefault("metadata", {})["namespace"] = "a-stock"
            items.append(document)
        return yaml.safe_dump(
            {"apiVersion": "v1", "kind": "List", "items": items},
            sort_keys=False,
        )

    current_manifest = tmp_path / "disable-current.yaml"
    current_manifest.write_text(suspended_render, encoding="utf-8")
    live_before = tmp_path / "disable-live-before.yaml"
    live_before.write_text(live_release(suspended_render), encoding="utf-8")
    live_after = tmp_path / "disable-live-after.yaml"
    live_after.write_text(live_release(off_render), encoding="utf-8")
    retained_cronjob = tmp_path / "disable-retained-cronjob.yaml"
    retained = next(
        document
        for document in yaml.safe_load_all(suspended_render)
        if document and document.get("kind") == "CronJob"
    )
    retained.setdefault("metadata", {})["namespace"] = "a-stock"
    retained_cronjob.write_text(yaml.safe_dump(retained, sort_keys=False), encoding="utf-8")

    runtime_payloads = _runtime_payloads(suspended_render, "a-stock", digest)
    runtime_paths = []
    for name, payload in zip(("deployments", "replicasets", "pods"), runtime_payloads):
        for item in payload["items"]:
            item.setdefault("metadata", {})["namespace"] = "a-stock"
        path = tmp_path / f"disable-{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        runtime_paths.append(path)
    deployments, replicasets, pods = runtime_paths

    jobs_before = {
        "apiVersion": "batch/v1",
        "kind": "JobList",
        "items": [
            {
                "metadata": {
                    "name": "completed-audit",
                    "namespace": "a-stock",
                    "uid": "job-complete-uid",
                },
                "status": {
                    "active": 0,
                    "failed": 0,
                    "succeeded": 1,
                    "conditions": [
                        {
                            "type": "Complete",
                            "status": "True",
                            "reason": "CompletionsReached",
                            "message": "Job completed",
                            "lastTransitionTime": "2026-10-14T08:31:00Z",
                        }
                    ],
                },
            },
            {
                "metadata": {
                    "name": "failed-audit",
                    "namespace": "a-stock",
                    "uid": "job-failed-uid",
                },
                "status": {
                    "active": 0,
                    "failed": 1,
                    "succeeded": 0,
                    "conditions": [
                        {
                            "type": "Failed",
                            "status": "True",
                            "reason": "BackoffLimitExceeded",
                            "message": "Job reached the backoff limit",
                            "lastTransitionTime": "2026-10-14T08:42:00Z",
                        }
                    ],
                },
            },
        ],
    }
    if outcome == "empty-jobs":
        jobs_before["items"] = []
    if outcome == "prewrite-nonterminal":
        jobs_before["items"][0]["status"] = {
            "active": 0,
            "failed": 0,
            "succeeded": 0,
            "conditions": [{"type": "Complete", "status": "False"}],
        }
    jobs_after = copy.deepcopy(jobs_before)
    if outcome == "post-missing":
        jobs_after["items"].pop()
    elif outcome == "post-new":
        jobs_after["items"].append(
            {
                "metadata": {
                    "name": "new-audit",
                    "namespace": "a-stock",
                    "uid": "job-new-uid",
                },
                "status": {
                    "active": 0,
                    "failed": 0,
                    "succeeded": 1,
                    "conditions": [{"type": "Complete", "status": "True"}],
                },
            }
        )
    elif outcome in {"predelete-uid", "post-uid"}:
        jobs_after["items"][0]["metadata"]["uid"] = "job-replaced-uid"
    elif outcome == "post-counts":
        jobs_after["items"][0]["status"]["succeeded"] = 2
    elif outcome == "post-terminal":
        jobs_after["items"][1]["status"]["conditions"][0]["reason"] = (
            "DeadlineExceeded"
        )
    elif outcome not in {
        "success",
        "empty-jobs",
        "cronjob-absent-after-helm",
        "prewrite-nonterminal",
        "predelete-read-failure",
        "delete-failure",
    }:
        raise AssertionError(f"unsupported disable-schedule outcome: {outcome}")

    jobs_before_path = tmp_path / "disable-jobs-before.json"
    jobs_before_path.write_text(json.dumps(jobs_before), encoding="utf-8")
    jobs_after_path = tmp_path / "disable-jobs-after.json"
    jobs_after_path.write_text(json.dumps(jobs_after), encoding="utf-8")

    fake_bin = tmp_path / "disable-bin"
    fake_bin.mkdir()
    calls = tmp_path / "disable-calls.log"
    cronjob_deleted = tmp_path / "disable-cronjob-deleted"
    helm_upgraded = tmp_path / "disable-helm-upgraded"

    helm_wrapper = fake_bin / "helm"
    helm_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'helm %s\\n' \"$*\" >> {calls}\n"
        "case \"$1\" in\n"
        "  lint|template) exec \"$REAL_HELM\" \"$@\" ;;\n"
        f"  get) [[ \"$2\" == manifest ]] || exit 81; cat {current_manifest} ;;\n"
        "  upgrade)\n"
        "    [[ \" $* \" == *\" --no-hooks \"* ]] || exit 89\n"
        f"    touch {helm_upgraded} ;;\n"
        "  *) exit 82 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    helm_wrapper.chmod(0o755)

    kubectl_wrapper = fake_bin / "kubectl"
    kubectl_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'kubectl %s\\n' \"$*\" >> {calls}\n"
        "args=\"$*\"\n"
        "if [[ \"$args\" == *\"get nodes\"* ]]; then printf amd64; exit 0; fi\n"
        "if [[ \"$args\" == *\"get --raw /version\"* ]]; then printf '{\"gitVersion\":\"v1.26.6+k3s1\"}'; exit 0; fi\n"
        f"if [[ \"$args\" == *\"get deployment,service,cronjob\"* ]]; then if [[ -f {cronjob_deleted} || ( -f {helm_upgraded} && \"$DISABLE_OUTCOME\" == cronjob-absent-after-helm ) ]]; then cat {live_after}; else cat {live_before}; fi; exit 0; fi\n"
        f"if [[ \"$args\" == *\"get deployment --namespace\"* && \"$args\" == *\"-o json\"* ]]; then cat {deployments}; exit 0; fi\n"
        f"if [[ \"$args\" == *\"get replicasets --namespace\"* ]]; then cat {replicasets}; exit 0; fi\n"
        f"if [[ \"$args\" == *\"get pods --namespace\"* ]]; then cat {pods}; exit 0; fi\n"
        f"if [[ \"$args\" == *\"get jobs --namespace\"* ]]; then if [[ -f {helm_upgraded} && \"$DISABLE_OUTCOME\" == predelete-read-failure ]]; then exit 90; elif [[ -f {cronjob_deleted} || ( -f {helm_upgraded} && \"$DISABLE_OUTCOME\" == predelete-uid ) ]]; then cat {jobs_after_path}; else cat {jobs_before_path}; fi; exit 0; fi\n"
        f"if [[ \"$1\" == get && \"$2\" == cronjob && \"$3\" == a-stock-data-collection ]]; then if [[ ! -f {cronjob_deleted} && ! ( -f {helm_upgraded} && \"$DISABLE_OUTCOME\" == cronjob-absent-after-helm ) ]]; then cat {retained_cronjob}; fi; exit 0; fi\n"
        "if [[ \"$1\" == delete && \"$2\" == cronjob ]]; then\n"
        "  [[ \"$3\" == a-stock-data-collection ]] || exit 83\n"
        "  [[ \" $* \" == *\" --namespace a-stock \"* ]] || exit 84\n"
        "  [[ \" $* \" == *\" --cascade=orphan \"* ]] || exit 85\n"
        "  [[ \" $* \" == *\" --wait=true \"* ]] || exit 86\n"
        "  [[ \"$DISABLE_OUTCOME\" != delete-failure ]] || exit 87\n"
        f"  touch {cronjob_deleted}; exit 0\n"
        "fi\n"
        "exit 88\n",
        encoding="utf-8",
    )
    kubectl_wrapper.chmod(0o755)

    ssh_wrapper = fake_bin / "ssh"
    ssh_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'ssh %s\\n' \"$*\" >> {calls}\n"
        "if [[ \"$*\" == *\"images ls\"* ]]; then\n"
        f"  printf '{{\"Name\":\"{image_repository}:{image_tag}\",\"Target\":{{\"digest\":\"{digest}\"}}}}\\n'\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    ssh_wrapper.chmod(0o755)

    kubeconfig = tmp_path / "disable-kubeconfig"
    kubeconfig.write_text("fixture\n", encoding="utf-8")
    env_file = tmp_path / "disable.env"
    env_file.write_text(
        "\n".join(
            [
                f"REPO_DIR={repo}",
                "TRUENAS_HOST=192.0.2.10",
                "TRUENAS_SSH_USER=tester",
                f"KUBECONFIG={kubeconfig}",
                f"HELM_VALUES_FILE={baseline}",
                f"SCHEDULING_OVERLAY_FILE={off}",
                f"FROZEN_IMAGE_REPOSITORY={image_repository}",
                f"FROZEN_IMAGE_TAG={image_tag}",
                f"FROZEN_IMAGE_DIGEST={digest}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            "bash",
            str(repo / "scripts" / SCRIPT.name),
            "--env-file",
            str(env_file),
            "--disable-schedule",
            "--baseline-values",
            str(baseline),
            "--scheduling-overlay",
            str(off),
            "--kube-version",
            "1.26.6+k3s1",
            "--release-name",
            "a-stock",
            "--namespace",
            "a-stock",
        ],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "REAL_HELM": HELM or "helm",
            "DISABLE_OUTCOME": outcome,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return completed, calls.read_text(encoding="utf-8")


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_disable_schedule_orphans_cronjob_and_preserves_namespace_job_evidence(
    tmp_path: Path,
) -> None:
    completed, calls = _run_disable_schedule_with_job_evidence(tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert calls.count("helm upgrade ") == 1
    assert "--no-hooks" in next(
        line for line in calls.splitlines() if line.startswith("helm upgrade ")
    )
    assert calls.count("kubectl get jobs --namespace a-stock -o json") == 3
    deletes = [line for line in calls.splitlines() if line.startswith("kubectl delete cronjob ")]
    assert deletes == [
        "kubectl delete cronjob a-stock-data-collection --namespace a-stock "
        "--cascade=orphan --wait=true"
    ]
    assert completed.stdout.count("namespace terminal Job evidence is unchanged") == 2
    assert "disable-schedule completed" in completed.stdout


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize(
    ("outcome", "expected_deletes"),
    [("empty-jobs", 1), ("cronjob-absent-after-helm", 0)],
    ids=["empty-job-set", "cronjob-already-absent"],
)
def test_disable_schedule_accepts_safe_empty_or_already_absent_state(
    tmp_path: Path,
    outcome: str,
    expected_deletes: int,
) -> None:
    completed, calls = _run_disable_schedule_with_job_evidence(
        tmp_path, outcome=outcome
    )

    assert completed.returncode == 0, completed.stderr
    assert calls.count("helm upgrade ") == 1
    assert calls.count("kubectl delete cronjob ") == expected_deletes
    assert calls.count("kubectl get jobs --namespace a-stock -o json") == 3


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_disable_schedule_rejects_nonterminal_job_before_helm_write(
    tmp_path: Path,
) -> None:
    completed, calls = _run_disable_schedule_with_job_evidence(
        tmp_path, outcome="prewrite-nonterminal"
    )

    assert completed.returncode != 0
    assert calls.count("kubectl get jobs --namespace a-stock -o json") == 1
    assert "helm upgrade " not in calls
    assert "kubectl delete cronjob " not in calls
    assert "requires every namespace Job to be terminal before Helm write" in completed.stderr


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_disable_schedule_fails_closed_when_orphan_delete_fails(tmp_path: Path) -> None:
    completed, calls = _run_disable_schedule_with_job_evidence(
        tmp_path, outcome="delete-failure"
    )

    assert completed.returncode != 0
    assert calls.count("helm upgrade ") == 1
    assert calls.count("kubectl get jobs --namespace a-stock -o json") == 2
    assert calls.count("kubectl delete cronjob ") == 1
    assert "--cascade=orphan --wait=true" in calls
    assert "failed to delete exact CronJob" in completed.stderr


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_disable_schedule_rejects_job_drift_before_orphan_delete(
    tmp_path: Path,
) -> None:
    completed, calls = _run_disable_schedule_with_job_evidence(
        tmp_path, outcome="predelete-uid"
    )

    assert completed.returncode != 0
    assert calls.count("helm upgrade ") == 1
    assert calls.count("kubectl get jobs --namespace a-stock -o json") == 2
    assert "kubectl delete cronjob " not in calls
    assert "namespace terminal Job evidence drifted before CronJob deletion" in completed.stderr


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_disable_schedule_fails_closed_when_predelete_job_read_fails(
    tmp_path: Path,
) -> None:
    completed, calls = _run_disable_schedule_with_job_evidence(
        tmp_path, outcome="predelete-read-failure"
    )

    assert completed.returncode != 0
    assert calls.count("helm upgrade ") == 1
    assert calls.count("kubectl get jobs --namespace a-stock -o json") == 2
    assert "kubectl delete cronjob " not in calls
    assert "namespace terminal Job evidence drifted before CronJob deletion" in completed.stderr


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize(
    "outcome",
    ["post-missing", "post-new", "post-uid", "post-counts", "post-terminal"],
    ids=["missing", "new", "uid", "counts", "terminal-condition"],
)
def test_disable_schedule_rejects_namespace_job_evidence_drift_after_orphan_delete(
    tmp_path: Path,
    outcome: str,
) -> None:
    completed, calls = _run_disable_schedule_with_job_evidence(
        tmp_path, outcome=outcome
    )

    assert completed.returncode != 0
    assert calls.count("helm upgrade ") == 1
    assert calls.count("kubectl delete cronjob ") == 1
    assert calls.count("kubectl get jobs --namespace a-stock -o json") == 3
    assert "namespace terminal Job evidence changed" in completed.stderr

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_server_dry_run_submits_only_exact_suspended_cronjob(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "tests" / "fixtures").mkdir(parents=True)
    (repo / "deploy" / "truenas").mkdir(parents=True)
    shutil.copytree(CHART, repo / "deploy" / "helm" / "a-stock")
    shutil.copy2(SCRIPT, repo / "scripts" / SCRIPT.name)
    shutil.copy2(VALIDATOR, repo / "scripts" / VALIDATOR.name)
    shutil.copy2(COMPONENT_FIXTURE, repo / "tests" / "fixtures" / COMPONENT_FIXTURE.name)
    shutil.copy2(BASELINE, repo / "deploy" / "truenas" / BASELINE.name)
    shutil.copy2(SUSPENDED, repo / "deploy" / "truenas" / SUSPENDED.name)
    shutil.copy2(ROOT / "Dockerfile", repo / "Dockerfile")

    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=repo, check=True, capture_output=True)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo, check=True, capture_output=True)

    baseline = repo / "deploy" / "truenas" / BASELINE.name
    suspended = repo / "deploy" / "truenas" / SUSPENDED.name
    rendered = subprocess.run(
        [
            HELM,
            "template",
            "a-stock",
            str(repo / "deploy" / "helm" / "a-stock"),
            "--namespace",
            "a-stock",
            "--kube-version",
            "1.26.6+k3s1",
            "--values",
            str(baseline),
            "--values",
            str(suspended),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.rstrip("\n") + "\n"
    reviewed_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    fake_bin = tmp_path / "target-bin"
    fake_bin.mkdir()
    kubectl_args = tmp_path / "kubectl-args"
    submitted = tmp_path / "submitted.yaml"
    target_calls = tmp_path / "target-calls"
    helm_wrapper = fake_bin / "helm"
    helm_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        "case \"$1\" in\n"
        "  lint|template) exec \"$REAL_HELM\" \"$@\" ;;\n"
        f"  *) printf 'helm %s\\n' \"$*\" >> {target_calls}; exit 98 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    helm_wrapper.chmod(0o755)
    ssh_wrapper = fake_bin / "ssh"
    ssh_wrapper.write_text(
        f"#!/usr/bin/env bash\nprintf 'ssh %s\\n' \"$*\" >> {target_calls}\nexit 0\n",
        encoding="utf-8",
    )
    ssh_wrapper.chmod(0o755)
    nc_wrapper = fake_bin / "nc"
    nc_wrapper.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    nc_wrapper.chmod(0o755)
    kubectl_wrapper = fake_bin / "kubectl"
    kubectl_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'kubectl %s\\n' \"$*\" >> {target_calls}\n"
        "if [[ \"$*\" == *\"get nodes\"* ]]; then printf amd64; exit 0; fi\n"
        "if [[ \"$*\" == *\"get --raw /version\"* ]]; then printf '{\\n  \"minor\": \"26\",\\n  \"gitVersion\": \"v1.26.6+k3s1\",\\n  \"major\": \"1\"\\n}'; exit 0; fi\n"
        "if [[ \"$*\" == *\"auth can-i create cronjobs.batch\"* ]]; then printf 'yes\\n'; exit 0; fi\n"
        f"if [[ \"$1\" == create ]]; then printf '%s\\n' \"$*\" > {kubectl_args}; cat > {submitted}; printf 'cronjob.batch dry-run\\n'; exit 0; fi\n"
        "exit 99\n",
        encoding="utf-8",
    )
    kubectl_wrapper.chmod(0o755)

    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("fixture", encoding="utf-8")
    env_file = tmp_path / "deploy.env"
    env_file.write_text(
        "\n".join(
            [
                f"REPO_DIR={repo}",
                "TRUENAS_HOST=192.0.2.10",
                "TRUENAS_SSH_USER=tester",
                f"KUBECONFIG={kubeconfig}",
                f"HELM_VALUES_FILE={baseline}",
                f"SCHEDULING_OVERLAY_FILE={suspended}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "bash",
            str(repo / "scripts" / SCRIPT.name),
            "--env-file",
            str(env_file),
            "--server-dry-run",
            "--kube-version",
            "1.26.6+k3s1",
            "--release-name",
            "a-stock",
            "--namespace",
            "a-stock",
        ],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "REAL_HELM": HELM,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    arguments = kubectl_args.read_text(encoding="utf-8")
    assert arguments == "create --namespace a-stock --dry-run=server --validate=true -f -\n"
    assert "apply" not in target_calls.read_text(encoding="utf-8")
    documents = [item for item in yaml.safe_load_all(submitted.read_text(encoding="utf-8")) if item]
    assert len(documents) == 1
    cronjob = documents[0]
    assert cronjob["apiVersion"] == "batch/v1"
    assert cronjob["kind"] == "CronJob"
    assert cronjob["metadata"]["name"] == "a-stock-data-collection"
    assert cronjob["metadata"]["namespace"] == "a-stock"
    assert cronjob["spec"]["suspend"] is True

def _component_fake_repo(
    tmp_path: Path,
    *,
    baseline_name: str = "values-secure-manual-collection.yaml",
) -> tuple[Path, Path, Path, dict[str, Path]]:
    """Copy chart + script + values into an isolated reviewed repo so a test
    can drive the component entry point with fake ssh/kubectl/helm/podman
    stubs without touching the real checkout.
    """
    repo = tmp_path / "component-repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "tests" / "fixtures").mkdir(parents=True)
    (repo / "deploy" / "truenas").mkdir(parents=True)
    shutil.copytree(CHART, repo / "deploy" / "helm" / "a-stock")
    shutil.copy2(SCRIPT, repo / "scripts" / SCRIPT.name)
    shutil.copy2(VALIDATOR, repo / "scripts" / VALIDATOR.name)
    shutil.copy2(COMPONENT_FIXTURE, repo / "tests" / "fixtures" / COMPONENT_FIXTURE.name)
    shutil.copy2(ROOT / "Dockerfile", repo / "Dockerfile")
    sources = {
        path.name: path
        for path in (BASELINE, SUSPENDED, ACTIVE, OFF, SECTORS_OFF, SECTORS_ENABLED)
    }
    copied: dict[str, Path] = {}
    for source in sources.values():
        destination = repo / "deploy" / "truenas" / source.name
        shutil.copy2(source, destination)
        copied[source.name] = destination
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=repo, check=True, capture_output=True)
    return repo, repo / "scripts" / SCRIPT.name, copied[baseline_name], copied


def _controlled_sector_packet(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, Path, dict[str, str]]:
    repo, script, _, values = _component_fake_repo(tmp_path)
    off = values[SECTORS_OFF.name]
    enabled = values[SECTORS_ENABLED.name]
    image_repository = "registry.local/frozen"
    image_tag = "reviewed-20261009"
    off_render = _render_sector_profile(
        off,
        chart=repo / "deploy" / "helm" / "a-stock",
        image_repository=image_repository,
        image_tag=image_tag,
    )
    enabled_render = _render_sector_profile(
        enabled,
        chart=repo / "deploy" / "helm" / "a-stock",
        image_repository=image_repository,
        image_tag=image_tag,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    reviewed = {
        "REVIEWED_GIT_HEAD": head,
        "REVIEWED_CHART_SHA256": _chart_hash(repo),
        "REVIEWED_OFF_VALUES_SHA256": hashlib.sha256(off.read_bytes()).hexdigest(),
        "REVIEWED_ENABLED_VALUES_SHA256": hashlib.sha256(enabled.read_bytes()).hexdigest(),
        "REVIEWED_OFF_RENDER_SHA256": hashlib.sha256(off_render.encode()).hexdigest(),
        "REVIEWED_ENABLED_RENDER_SHA256": hashlib.sha256(enabled_render.encode()).hexdigest(),
        "FROZEN_IMAGE_REPOSITORY": image_repository,
        "FROZEN_IMAGE_TAG": image_tag,
        "FROZEN_IMAGE_DIGEST": f"sha256:{'d' * 64}",
        "FROZEN_IMAGE_SOURCE_GIT_HEAD": head,
        "EXPECTED_REPAIR_HELM_REVISION": "91",
    }
    env_file = tmp_path / "controlled-sectors.env"
    env_file.write_text(
        "\n".join(
            [
                f"REPO_DIR={repo}",
                "TRUENAS_HOST=192.0.2.10",
                "TRUENAS_SSH_USER=tester",
                *[f"{name}={value}" for name, value in reviewed.items()],
                "",
            ]
        ),
        encoding="utf-8",
    )
    return repo, script, env_file, off, enabled, reviewed


def _run_controlled_sector_entry(
    script: Path,
    env_file: Path,
    off: Path,
    enabled: Path,
    fake_bin: Path,
    operation: str = "--enable-sectors-config",
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            str(script),
            "--env-file",
            str(env_file),
            operation,
            "--off-values",
            str(off),
            "--enabled-values",
            str(enabled),
            "--kube-version",
            "1.26.6+k3s1",
            "--release-name",
            "a-stock",
            "--namespace",
            "a-stock",
        ],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "REAL_HELM": HELM or "helm",
        },
        capture_output=True,
        text=True,
        check=False,
    )


def _controlled_manual_refresh_packet(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, str, str]:
    repo, script, _, values = _component_fake_repo(tmp_path)
    current_values = values[SECTORS_OFF.name]
    manual_off_values = repo / "deploy" / "truenas" / "manual-off.yaml"
    manual_off_values.write_text(
        current_values.read_text(encoding="utf-8").replace(
            "  - name: MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED\n    value: \"1\"",
            "  - name: MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED\n    value: \"0\"",
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "manual off fixture"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    current_render = _render_sector_profile(
        current_values,
        chart=repo / "deploy" / "helm" / "a-stock",
    )
    desired_render = _render_sector_profile(
        manual_off_values,
        chart=repo / "deploy" / "helm" / "a-stock",
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    env_file = tmp_path / "controlled-manual-refresh.env"
    env_file.write_text(
        "\n".join(
            [
                f"REPO_DIR={repo}",
                "TRUENAS_HOST=192.0.2.10",
                "TRUENAS_SSH_USER=tester",
                f"REVIEWED_GIT_HEAD={head}",
                f"REVIEWED_CHART_SHA256={_chart_hash(repo)}",
                "REVIEWED_MANUAL_OFF_VALUES_SHA256="
                f"{hashlib.sha256(manual_off_values.read_bytes()).hexdigest()}",
                "REVIEWED_MANUAL_OFF_RENDER_SHA256="
                f"{hashlib.sha256(desired_render.encode()).hexdigest()}",
                "FROZEN_IMAGE_REPOSITORY=registry.local/frozen",
                "FROZEN_IMAGE_TAG=reviewed-20261009",
                f"FROZEN_IMAGE_DIGEST=sha256:{'d' * 64}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return repo, script, env_file, manual_off_values, current_render, desired_render


def _run_controlled_manual_refresh_entry(
    script: Path,
    env_file: Path,
    manual_off_values: Path,
    fake_bin: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            str(script),
            "--env-file",
            str(env_file),
            "--disable-manual-refresh",
            "--baseline-values",
            str(manual_off_values),
            "--kube-version",
            "1.26.6+k3s1",
            "--release-name",
            "a-stock",
            "--namespace",
            "a-stock",
        ],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "REAL_HELM": HELM or "helm",
        },
        capture_output=True,
        text=True,
        check=False,
    )


def _repair_target_stubs(
    tmp_path: Path,
    *,
    reviewed_off_render: str,
    stored_manifest: str = "",
    release_revision: int = 91,
    release_status: str = "deployed",
    chart_name: str | None = None,
    chart_version: str | None = None,
    stored_component: str = "schedule",
    stored_hooks: str = "",
    post_stored_hooks: str | None = None,
) -> tuple[Path, Path]:
    fake_bin = tmp_path / "repair-bin"
    fake_bin.mkdir()
    calls = tmp_path / "repair-calls.log"
    state = tmp_path / "repair-upgraded"
    full_manifest = tmp_path / "repair-full.yaml"
    current_manifest = tmp_path / "repair-current.yaml"
    live_manifest = tmp_path / "repair-live.yaml"
    deployments_path = tmp_path / "repair-deployments.json"
    replicasets_path = tmp_path / "repair-replicasets.json"
    pods_path = tmp_path / "repair-pods.json"
    pvc_path = tmp_path / "repair-postgresql-pvc.json"
    statefulset_path = tmp_path / "repair-postgresql-statefulset.json"
    release_metadata_path = tmp_path / "repair-release-metadata.json"
    post_release_metadata_path = tmp_path / "repair-post-release-metadata.json"
    release_values_path = tmp_path / "repair-release-values.json"
    post_release_values_path = tmp_path / "repair-post-release-values.json"
    release_hooks_path = tmp_path / "repair-release-hooks.yaml"
    post_release_hooks_path = tmp_path / "repair-post-release-hooks.yaml"

    full_manifest.write_text(reviewed_off_render, encoding="utf-8")
    current_manifest.write_text(stored_manifest, encoding="utf-8")
    live_documents = []
    for document in yaml.safe_load_all(reviewed_off_render):
        if not document or document.get("kind") not in {"Deployment", "Service", "CronJob"}:
            continue
        document = copy.deepcopy(document)
        document.setdefault("metadata", {})["namespace"] = "a-stock"
        live_documents.append(document)
    live_manifest.write_text(
        yaml.safe_dump(
            {"apiVersion": "v1", "kind": "List", "items": live_documents},
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    deployments, replicasets, pods = _sector_runtime_payloads(reviewed_off_render)
    deployments_path.write_text(json.dumps(deployments), encoding="utf-8")
    replicasets_path.write_text(json.dumps(replicasets), encoding="utf-8")
    pods_path.write_text(json.dumps(pods), encoding="utf-8")
    pvc_path.write_text(
        json.dumps(
            {
                "metadata": {"name": "a-stock-postgresql-data", "namespace": "a-stock"},
                "spec": {"accessModes": ["ReadWriteOnce"], "volumeName": "pv-postgresql"},
                "status": {"phase": "Bound"},
            }
        ),
        encoding="utf-8",
    )
    statefulset_path.write_text(
        json.dumps(
            {
                "metadata": {"name": "a-stock-postgresql", "namespace": "a-stock"},
                "spec": {"replicas": 1},
                "status": {"readyReplicas": 1},
            }
        ),
        encoding="utf-8",
    )
    release_values = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))
    overlay_values = yaml.safe_load(SECTORS_OFF.read_text(encoding="utf-8"))

    def merge(target: dict, source: dict) -> None:
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                merge(target[key], value)
            else:
                target[key] = value

    merge(release_values, overlay_values)
    release_values["component"] = stored_component
    release_values["image"]["repository"] = "registry.local/frozen"
    release_values["image"]["tag"] = "reviewed-20261009"
    release_values_path.write_text(json.dumps(release_values), encoding="utf-8")
    post_release_values = copy.deepcopy(release_values)
    post_release_values["component"] = "all"
    post_release_values_path.write_text(
        json.dumps(post_release_values), encoding="utf-8"
    )
    release_hooks_path.write_text(stored_hooks, encoding="utf-8")
    reviewed_hooks = [
        document
        for document in yaml.safe_load_all(reviewed_off_render)
        if document
        and "helm.sh/hook"
        in ((document.get("metadata") or {}).get("annotations") or {})
    ]
    post_release_hooks_path.write_text(
        post_stored_hooks
        if post_stored_hooks is not None
        else yaml.safe_dump_all(reviewed_hooks, explicit_start=True, sort_keys=False),
        encoding="utf-8",
    )
    chart_metadata = yaml.safe_load((CHART / "Chart.yaml").read_text(encoding="utf-8"))

    def write_release_metadata(path: Path, *, revision: int, status: str) -> None:
        path.write_text(
            json.dumps(
                {
                    "name": "a-stock",
                    "chart": chart_name or chart_metadata["name"],
                    "version": chart_version or chart_metadata["version"],
                    "appVersion": chart_metadata["appVersion"],
                    "namespace": "a-stock",
                    "revision": revision,
                    "status": status,
                }
            ),
            encoding="utf-8",
        )

    write_release_metadata(
        release_metadata_path, revision=release_revision, status=release_status
    )
    write_release_metadata(post_release_metadata_path, revision=92, status="deployed")

    helm_wrapper = fake_bin / "helm"
    helm_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'helm %s\\n' \"$*\" >> {calls}\n"
        "case \"$1\" in\n"
        "  lint|template) exec \"$REAL_HELM\" \"$@\" ;;\n"
        "  list) printf '[{\"name\":\"a-stock\"}]\\n' ;;\n"
        f"  get) if [[ \"$2\" == metadata ]]; then if [[ -f {state} ]]; then cat {post_release_metadata_path}; else cat {release_metadata_path}; fi; elif [[ \"$2\" == values ]]; then if [[ -f {state} ]]; then cat {post_release_values_path}; else cat {release_values_path}; fi; elif [[ \"$2\" == hooks ]]; then if [[ -f {state} ]]; then cat {post_release_hooks_path}; else cat {release_hooks_path}; fi; elif [[ -f {state} ]]; then cat {full_manifest}; else cat {current_manifest}; fi ;;\n"
        "  upgrade)\n"
        "    [[ \" $* \" == *\" --no-hooks \"* ]] || exit 81\n"
        "    [[ \" $* \" == *\" --set component=all \"* ]] || exit 82\n"
        "    [[ \" $* \" != *\" --install \"* ]] || exit 83\n"
        f"    touch {state} ;;\n"
        "  *) exit 84 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    helm_wrapper.chmod(0o755)

    kubectl_wrapper = fake_bin / "kubectl"
    kubectl_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'kubectl %s\\n' \"$*\" >> {calls}\n"
        "args=\"$*\"\n"
        "if [[ \"$args\" == *\"get nodes\"* ]]; then printf amd64; exit 0; fi\n"
        "if [[ \"$args\" == *\"get --raw /version\"* ]]; then printf '{\"gitVersion\":\"v1.26.6+k3s1\"}'; exit 0; fi\n"
        f"if [[ \"$args\" == *\"get deployment,service,cronjob\"* ]]; then cat {live_manifest}; exit 0; fi\n"
        f"if [[ \"$args\" == *\"get deployment --namespace\"* && \"$args\" == *\"-o json\"* ]]; then cat {deployments_path}; exit 0; fi\n"
        f"if [[ \"$args\" == *\"get replicasets --namespace\"* ]]; then cat {replicasets_path}; exit 0; fi\n"
        f"if [[ \"$args\" == *\"get pods --namespace\"* ]]; then cat {pods_path}; exit 0; fi\n"
        "if [[ \"$args\" == *\"get jobs --namespace\"* ]]; then printf '{\"items\":[]}'; exit 0; fi\n"
        "if [[ \"$args\" == *\"get cronjob \"* ]]; then exit 0; fi\n"
        "if [[ \"$args\" == *\"get secret \"* ]]; then printf 'secret-uid|11'; exit 0; fi\n"
        "if [[ \"$args\" == *\"get pvc \"* && \"$args\" == *\"jsonpath\"* ]]; then printf 'pvc-uid|12|pv-reviewed|Bound|5Gi'; exit 0; fi\n"
        f"if [[ \"$args\" == *\"get pvc a-stock-postgresql-data\"* && \"$args\" == *\"-o json\"* ]]; then cat {pvc_path}; exit 0; fi\n"
        f"if [[ \"$args\" == *\"get statefulset a-stock-postgresql\"* ]]; then cat {statefulset_path}; exit 0; fi\n"
        "if [[ \"$args\" == *\"get deployment\"* && \"$args\" == *\"jsonpath\"* ]]; then printf a-stock; exit 0; fi\n"
        "if [[ \"$args\" == *\"rollout status deployment/a-stock\"* ]]; then exit 0; fi\n"
        "exit 85\n",
        encoding="utf-8",
    )
    kubectl_wrapper.chmod(0o755)

    ssh_wrapper = fake_bin / "ssh"
    ssh_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'ssh %s\\n' \"$*\" >> {calls}\n"
        "if [[ \"$*\" == *\"images ls\"* ]]; then\n"
        f"  printf '{{\"Name\":\"registry.local/frozen:reviewed-20261009\",\"Target\":{{\"digest\":\"sha256:{'d' * 64}\"}}}}\\n'\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    ssh_wrapper.chmod(0o755)
    for name in ("nc", "podman", "scp", "curl"):
        executable = fake_bin / name
        executable.write_text(
            "#!/usr/bin/env bash\n"
            f"printf '{name} %s\\n' \"$*\" >> {calls}\n"
            + ("exit 0\n" if name == "nc" else "exit 86\n"),
            encoding="utf-8",
        )
        executable.chmod(0o755)
    return fake_bin, calls


def _manual_refresh_target_stubs(
    tmp_path: Path,
    *,
    current_render: str,
    desired_render: str,
    job_state: str = "terminal",
    hook_drift: str | None = None,
    live_drift: str | None = None,
) -> tuple[Path, Path]:
    fake_bin = tmp_path / "manual-refresh-bin"
    fake_bin.mkdir()
    calls = tmp_path / "manual-refresh-calls.log"
    state = tmp_path / "manual-refresh-upgraded"

    def release_manifest(rendered: str) -> str:
        return yaml.safe_dump_all(
            [
                item
                for item in yaml.safe_load_all(rendered)
                if item
                and "helm.sh/hook"
                not in ((item.get("metadata") or {}).get("annotations") or {})
            ],
            sort_keys=False,
        )

    def hook_manifest(rendered: str, *, drift: bool = False) -> str:
        documents = [
            copy.deepcopy(item)
            for item in yaml.safe_load_all(rendered)
            if item
            and "helm.sh/hook"
            in ((item.get("metadata") or {}).get("annotations") or {})
        ]
        if drift:
            documents[0]["spec"]["template"]["spec"]["containers"][0]["command"] = [
                "sh",
                "-c",
                "false",
            ]
        return yaml.safe_dump_all(documents, sort_keys=False)

    def live_manifest(rendered: str, *, drift: str | None = None) -> str:
        documents = []
        for item in yaml.safe_load_all(rendered):
            if not item or item.get("kind") not in {
                "Deployment",
                "Service",
                "CronJob",
                "StatefulSet",
                "PersistentVolumeClaim",
            }:
                continue
            item = copy.deepcopy(item)
            item.setdefault("metadata", {})["namespace"] = "a-stock"
            if drift == "statefulset" and item.get("kind") == "StatefulSet":
                item["spec"]["replicas"] = 2
            if drift == "pvc" and item.get("kind") == "PersistentVolumeClaim":
                item["spec"]["resources"]["requests"]["storage"] = "9Gi"
            if drift == "terminating-deployment" and item.get("kind") == "Deployment":
                item["metadata"]["deletionTimestamp"] = "2026-10-15T01:02:03Z"
            documents.append(item)
        return yaml.safe_dump(
            {"apiVersion": "v1", "kind": "List", "items": documents},
            sort_keys=False,
        )

    current_manifest_path = tmp_path / "manual-current.yaml"
    desired_manifest_path = tmp_path / "manual-desired.yaml"
    current_hooks_path = tmp_path / "manual-current-hooks.yaml"
    desired_hooks_path = tmp_path / "manual-desired-hooks.yaml"
    current_live_path = tmp_path / "manual-current-live.yaml"
    desired_live_path = tmp_path / "manual-desired-live.yaml"
    current_manifest_path.write_text(release_manifest(current_render), encoding="utf-8")
    desired_manifest_path.write_text(release_manifest(desired_render), encoding="utf-8")
    current_hooks_path.write_text(
        hook_manifest(current_render, drift=hook_drift == "before"),
        encoding="utf-8",
    )
    desired_hooks_path.write_text(
        hook_manifest(desired_render, drift=hook_drift == "after"),
        encoding="utf-8",
    )
    current_live_path.write_text(
        live_manifest(current_render, drift=live_drift), encoding="utf-8"
    )
    desired_live_path.write_text(live_manifest(desired_render), encoding="utf-8")

    current_runtime = _sector_runtime_payloads(current_render)
    desired_runtime = _sector_runtime_payloads(desired_render)
    runtime_paths: list[tuple[Path, Path]] = []
    for name, current_payload, desired_payload in zip(
        ("deployments", "replicasets", "pods"), current_runtime, desired_runtime
    ):
        current_path = tmp_path / f"manual-current-{name}.json"
        desired_path = tmp_path / f"manual-desired-{name}.json"
        current_path.write_text(json.dumps(current_payload), encoding="utf-8")
        desired_path.write_text(json.dumps(desired_payload), encoding="utf-8")
        runtime_paths.append((current_path, desired_path))
    (current_deployments, desired_deployments), (
        current_replicasets,
        desired_replicasets,
    ), (current_pods, desired_pods) = runtime_paths

    pvc_path = tmp_path / "manual-postgresql-pvc.json"
    pvc_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "name": "a-stock-postgresql-data",
                    "namespace": "a-stock",
                },
                "spec": {
                    "accessModes": ["ReadWriteOnce"],
                    "volumeName": "pv-postgresql",
                },
                "status": {"phase": "Bound"},
            }
        ),
        encoding="utf-8",
    )
    statefulset_path = tmp_path / "manual-postgresql-statefulset.json"
    statefulset_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "name": "a-stock-postgresql",
                    "namespace": "a-stock",
                },
                "spec": {"replicas": 1},
                "status": {"readyReplicas": 1},
            }
        ),
        encoding="utf-8",
    )

    helm_wrapper = fake_bin / "helm"
    helm_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'helm %s\\n' \"$*\" >> {calls}\n"
        "case \"$1\" in\n"
        "  lint|template) exec \"$REAL_HELM\" \"$@\" ;;\n"
        "  list) printf '[{\"name\":\"a-stock\"}]\\n' ;;\n"
        f"  get) if [[ \"$2\" == hooks ]]; then if [[ -f {state} ]]; then cat {desired_hooks_path}; else cat {current_hooks_path}; fi; elif [[ -f {state} ]]; then cat {desired_manifest_path}; else cat {current_manifest_path}; fi ;;\n"
        "  upgrade)\n"
        "    [[ \" $* \" == *\" --no-hooks \"* ]] || exit 81\n"
        "    [[ \" $* \" == *\" --atomic \"* ]] || exit 82\n"
        "    [[ \" $* \" == *\" --wait \"* ]] || exit 83\n"
        "    [[ \" $* \" == *\" --set component=all \"* ]] || exit 84\n"
        "    [[ \" $* \" != *\" --install \"* ]] || exit 85\n"
        f"    touch {state} ;;\n"
        "  *) exit 86 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    helm_wrapper.chmod(0o755)

    job_payloads = {
        "terminal": {
            "items": [
                {
                    "metadata": {"name": "completed-audit"},
                    "status": {
                        "succeeded": 1,
                        "conditions": [{"type": "Complete", "status": "True"}],
                    },
                },
                {
                    "metadata": {"name": "failed-audit"},
                    "status": {
                        "failed": 1,
                        "conditions": [
                            {"type": "Failed", "status": "True", "reason": "Error"}
                        ],
                    },
                },
            ]
        },
        "active": {
            "items": [
                {
                    "metadata": {"name": "active-job"},
                    "status": {
                        "active": 1,
                        "conditions": [{"type": "Complete", "status": "False"}],
                    },
                }
            ]
        },
        "missing-conditions": {
            "items": [
                {"metadata": {"name": "missing-conditions"}, "status": {"succeeded": 1}}
            ]
        },
        "nonterminal": {
            "items": [
                {
                    "metadata": {"name": "nonterminal"},
                    "status": {
                        "conditions": [
                            {"type": "Complete", "status": "False"},
                            {"type": "FailureTarget", "status": "True"},
                        ]
                    },
                }
            ]
        },
        "failed-count": {
            "items": [
                {
                    "metadata": {"name": "failed-count"},
                    "status": {
                        "failed": 1,
                        "conditions": [{"type": "Complete", "status": "True"}],
                    },
                }
            ]
        },
        "invalid": {
            "items": [
                {
                    "metadata": {"name": "invalid-active"},
                    "status": {
                        "active": False,
                        "conditions": [{"type": "Complete", "status": "True"}],
                    },
                }
            ]
        },
    }
    jobs_payload = json.dumps(job_payloads[job_state], separators=(",", ":"))
    kubectl_wrapper = fake_bin / "kubectl"
    kubectl_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'kubectl %s\\n' \"$*\" >> {calls}\n"
        "args=\"$*\"\n"
        "if [[ \"$args\" == *\"get nodes\"* ]]; then printf amd64; exit 0; fi\n"
        "if [[ \"$args\" == *\"get --raw /version\"* ]]; then printf '{\"gitVersion\":\"v1.26.6+k3s1\"}'; exit 0; fi\n"
        f"if [[ \"$args\" == *\"get deployment,service,cronjob,statefulset,pvc\"* ]]; then if [[ -f {state} ]]; then cat {desired_live_path}; else cat {current_live_path}; fi; exit 0; fi\n"
        f"if [[ \"$args\" == *\"get deployment --namespace\"* && \"$args\" == *\"-o json\"* ]]; then if [[ -f {state} ]]; then cat {desired_deployments}; else cat {current_deployments}; fi; exit 0; fi\n"
        f"if [[ \"$args\" == *\"get replicasets --namespace\"* ]]; then if [[ -f {state} ]]; then cat {desired_replicasets}; else cat {current_replicasets}; fi; exit 0; fi\n"
        f"if [[ \"$args\" == *\"get pods --namespace\"* ]]; then if [[ -f {state} ]]; then cat {desired_pods}; else cat {current_pods}; fi; exit 0; fi\n"
        f"if [[ \"$args\" == *\"get jobs --namespace\"* ]]; then printf '{jobs_payload}'; exit 0; fi\n"
        "if [[ \"$args\" == *\"get cronjob --namespace\"* ]]; then printf 'apiVersion: v1\\nkind: List\\nitems: []\\n'; exit 0; fi\n"
        "if [[ \"$args\" == *\"get cronjob market-data-collection\"* ]]; then exit 0; fi\n"
        "if [[ \"$args\" == *\"get secret \"* ]]; then printf 'secret-uid|11'; exit 0; fi\n"
        "if [[ \"$args\" == *\"get pvc \"* && \"$args\" == *\"jsonpath\"* ]]; then printf 'pvc-uid|12|pv-reviewed|Bound|5Gi'; exit 0; fi\n"
        f"if [[ \"$args\" == *\"get pvc a-stock-postgresql-data\"* && \"$args\" == *\"-o json\"* ]]; then cat {pvc_path}; exit 0; fi\n"
        f"if [[ \"$args\" == *\"get statefulset a-stock-postgresql\"* ]]; then cat {statefulset_path}; exit 0; fi\n"
        "if [[ \"$args\" == *\"get deployment\"* && \"$args\" == *\"jsonpath\"* ]]; then printf a-stock; exit 0; fi\n"
        "if [[ \"$args\" == *\"rollout status deployment/a-stock\"* ]]; then exit 0; fi\n"
        "exit 87\n",
        encoding="utf-8",
    )
    kubectl_wrapper.chmod(0o755)

    ssh_wrapper = fake_bin / "ssh"
    ssh_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'ssh %s\\n' \"$*\" >> {calls}\n"
        "if [[ \"$*\" == *\"images ls\"* ]]; then\n"
        f"  printf '{{\"Name\":\"registry.local/frozen:reviewed-20261009\",\"Target\":{{\"digest\":\"sha256:{'d' * 64}\"}}}}\\n'\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    ssh_wrapper.chmod(0o755)
    for name in ("nc", "podman", "scp", "curl"):
        executable = fake_bin / name
        executable.write_text(
            "#!/usr/bin/env bash\n"
            f"printf '{name} %s\\n' \"$*\" >> {calls}\n"
            + ("exit 0\n" if name == "nc" else "exit 88\n"),
            encoding="utf-8",
        )
        executable.chmod(0o755)
    return fake_bin, calls


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_controlled_sectors_operation_rejects_dirty_tree_before_target_access(
    tmp_path: Path,
) -> None:
    repo, script, env_file, off, enabled, _ = _controlled_sector_packet(tmp_path)
    (repo / "unreviewed.txt").write_text("dirty\n", encoding="utf-8")
    fake_bin, marker = _write_target_spies(tmp_path)

    completed = _run_controlled_sector_entry(script, env_file, off, enabled, fake_bin)

    assert completed.returncode != 0
    assert "clean working tree" in completed.stderr
    assert not marker.exists()


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_disable_manual_refresh_rejects_dirty_tree_before_target_access(
    tmp_path: Path,
) -> None:
    repo, script, env_file, manual_off, _, _ = _controlled_manual_refresh_packet(
        tmp_path
    )
    (repo / "unreviewed.txt").write_text("dirty\n", encoding="utf-8")
    fake_bin, marker = _write_target_spies(tmp_path)

    completed = _run_controlled_manual_refresh_entry(
        script, env_file, manual_off, fake_bin
    )

    assert completed.returncode != 0
    assert "clean working tree" in completed.stderr
    assert not marker.exists()


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize(
    "variable",
    [
        "REVIEWED_GIT_HEAD",
        "REVIEWED_CHART_SHA256",
        "REVIEWED_MANUAL_OFF_VALUES_SHA256",
        "REVIEWED_MANUAL_OFF_RENDER_SHA256",
    ],
)
def test_disable_manual_refresh_rejects_reviewed_drift_before_target_access(
    tmp_path: Path, variable: str
) -> None:
    _, script, env_file, manual_off, _, _ = _controlled_manual_refresh_packet(
        tmp_path
    )
    content = env_file.read_text(encoding="utf-8")
    replacement_length = 40 if variable == "REVIEWED_GIT_HEAD" else 64
    content = "\n".join(
        f"{variable}={'0' * replacement_length}"
        if line.startswith(f"{variable}=")
        else line
        for line in content.splitlines()
    )
    env_file.write_text(content + "\n", encoding="utf-8")
    fake_bin, marker = _write_target_spies(tmp_path)

    completed = _run_controlled_manual_refresh_entry(
        script, env_file, manual_off, fake_bin
    )

    assert completed.returncode != 0
    assert "reviewed" in completed.stderr.lower()
    assert not marker.exists()


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_disable_manual_refresh_runs_one_hook_free_same_image_upgrade_with_inactive_jobs(
    tmp_path: Path,
) -> None:
    _, script, env_file, manual_off, current_render, desired_render = (
        _controlled_manual_refresh_packet(tmp_path)
    )
    kubeconfig = tmp_path / "manual-refresh-kubeconfig"
    kubeconfig.write_text("fixture\n", encoding="utf-8")
    with env_file.open("a", encoding="utf-8") as stream:
        stream.write(f"KUBECONFIG={kubeconfig}\n")
    fake_bin, calls = _manual_refresh_target_stubs(
        tmp_path,
        current_render=current_render,
        desired_render=desired_render,
    )

    completed = _run_controlled_manual_refresh_entry(
        script, env_file, manual_off, fake_bin
    )
    call_log = calls.read_text(encoding="utf-8")
    upgrades = [line for line in call_log.splitlines() if line.startswith("helm upgrade ")]

    assert completed.returncode == 0, completed.stderr
    assert len(upgrades) == 1
    assert "--set image.repository=registry.local/frozen" in upgrades[0]
    assert "--set image.tag=reviewed-20261009" in upgrades[0]
    assert "--set component=all" in upgrades[0]
    assert "--no-hooks" in upgrades[0]
    assert "--atomic" in upgrades[0]
    assert "--wait" in upgrades[0]
    assert "--install" not in upgrades[0]
    assert call_log.count("helm get hooks a-stock --namespace a-stock") == 3
    assert call_log.count("kubectl get jobs --namespace a-stock -o json") == 3
    assert "manual refresh disabled with same frozen image" in completed.stdout
    for forbidden in (
        "podman ",
        "scp ",
        "curl ",
        "kubectl exec",
        "scheduled-refresh",
        "capabilities promote",
        "images import",
    ):
        assert forbidden not in call_log


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize(
    "failure",
    [
        "manual-already-off",
        "job-active",
        "job-missing-conditions",
        "job-nonterminal",
        "job-failed-count",
        "job-invalid",
        "digest",
        "hook-before",
        "live-statefulset",
        "live-pvc",
        "live-terminating-deployment",
    ],
)
def test_disable_manual_refresh_rejects_unsafe_target_before_helm_write(
    tmp_path: Path, failure: str
) -> None:
    _, script, env_file, manual_off, current_render, desired_render = (
        _controlled_manual_refresh_packet(tmp_path)
    )
    kubeconfig = tmp_path / "manual-refresh-kubeconfig"
    kubeconfig.write_text("fixture\n", encoding="utf-8")
    with env_file.open("a", encoding="utf-8") as stream:
        stream.write(f"KUBECONFIG={kubeconfig}\n")
    if failure == "digest":
        env_file.write_text(
            env_file.read_text(encoding="utf-8").replace(
                f"FROZEN_IMAGE_DIGEST=sha256:{'d' * 64}",
                f"FROZEN_IMAGE_DIGEST=sha256:{'a' * 64}",
            ),
            encoding="utf-8",
        )
    fake_bin, calls = _manual_refresh_target_stubs(
        tmp_path,
        current_render=desired_render if failure == "manual-already-off" else current_render,
        desired_render=desired_render,
        job_state=failure.removeprefix("job-") if failure.startswith("job-") else "terminal",
        hook_drift="before" if failure == "hook-before" else None,
        live_drift=(
            failure.removeprefix("live-") if failure.startswith("live-") else None
        ),
    )

    completed = _run_controlled_manual_refresh_entry(
        script, env_file, manual_off, fake_bin
    )
    call_log = calls.read_text(encoding="utf-8")

    assert completed.returncode != 0
    assert "helm upgrade " not in call_log


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_disable_manual_refresh_rejects_post_write_hook_drift(tmp_path: Path) -> None:
    _, script, env_file, manual_off, current_render, desired_render = (
        _controlled_manual_refresh_packet(tmp_path)
    )
    kubeconfig = tmp_path / "manual-refresh-kubeconfig"
    kubeconfig.write_text("fixture\n", encoding="utf-8")
    with env_file.open("a", encoding="utf-8") as stream:
        stream.write(f"KUBECONFIG={kubeconfig}\n")
    fake_bin, calls = _manual_refresh_target_stubs(
        tmp_path,
        current_render=current_render,
        desired_render=desired_render,
        hook_drift="after",
    )

    completed = _run_controlled_manual_refresh_entry(
        script, env_file, manual_off, fake_bin
    )
    call_log = calls.read_text(encoding="utf-8")

    assert completed.returncode != 0
    assert call_log.count("helm upgrade ") == 1
    assert "stored Helm hooks differ from the reviewed packet" in completed.stderr


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize(
    "variable",
    [
        "REVIEWED_GIT_HEAD",
        "REVIEWED_CHART_SHA256",
        "REVIEWED_OFF_VALUES_SHA256",
        "REVIEWED_ENABLED_VALUES_SHA256",
        "REVIEWED_OFF_RENDER_SHA256",
        "REVIEWED_ENABLED_RENDER_SHA256",
    ],
)
def test_controlled_sectors_operation_rejects_reviewed_identity_drift_before_target_access(
    tmp_path: Path, variable: str
) -> None:
    _, script, env_file, off, enabled, _ = _controlled_sector_packet(tmp_path)
    content = env_file.read_text(encoding="utf-8")
    content = "\n".join(
        f"{variable}={'0' * (40 if variable == 'REVIEWED_GIT_HEAD' else 64)}"
        if line.startswith(f"{variable}=")
        else line
        for line in content.splitlines()
    )
    env_file.write_text(content + "\n", encoding="utf-8")
    fake_bin, marker = _write_target_spies(tmp_path)

    completed = _run_controlled_sector_entry(script, env_file, off, enabled, fake_bin)

    assert completed.returncode != 0
    assert "reviewed" in completed.stderr.lower()
    assert not marker.exists()


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_controlled_sectors_operation_requires_complete_frozen_image_before_target_access(
    tmp_path: Path,
) -> None:
    _, script, env_file, off, enabled, _ = _controlled_sector_packet(tmp_path)
    env_file.write_text(
        env_file.read_text(encoding="utf-8").replace(
            f"FROZEN_IMAGE_DIGEST=sha256:{'d' * 64}\n", ""
        ),
        encoding="utf-8",
    )
    fake_bin, marker = _write_target_spies(tmp_path)

    completed = _run_controlled_sector_entry(script, env_file, off, enabled, fake_bin)

    assert completed.returncode != 0
    assert "requires frozen image repository, tag, and digest" in completed.stderr
    assert not marker.exists()


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_stage_sectors_off_does_not_require_digest_before_target_access(
    tmp_path: Path,
) -> None:
    _, script, env_file, off, enabled, _ = _controlled_sector_packet(tmp_path)
    content = env_file.read_text(encoding="utf-8").replace(
        f"FROZEN_IMAGE_DIGEST=sha256:{'d' * 64}\n", ""
    )
    env_file.write_text(
        content
        + "REMOTE_IMAGE_DIR=/unreachable\n"
        + "IMAGE_REPOSITORY=registry.local/frozen\n"
        + "IMAGE_TAG=reviewed-20261009\n",
        encoding="utf-8",
    )
    fake_bin, marker = _write_target_spies(tmp_path)

    completed = _run_controlled_sector_entry(
        script, env_file, off, enabled, fake_bin, operation="--stage-sectors-off"
    )

    assert completed.returncode == 97
    assert "requires frozen image repository, tag, and digest" not in completed.stderr
    assert marker.read_text(encoding="utf-8").splitlines() == ["ssh"]


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_controlled_sectors_operation_rejects_profile_drift_before_target_access(
    tmp_path: Path,
) -> None:
    _, script, env_file, off, enabled, _ = _controlled_sector_packet(tmp_path)
    enabled.write_text(
        enabled.read_text(encoding="utf-8").replace(
            "  - name: MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED\n    value: \"1\"",
            "  - name: MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED\n    value: \"0\"",
        ),
        encoding="utf-8",
    )
    fake_bin, marker = _write_target_spies(tmp_path)

    completed = _run_controlled_sector_entry(script, env_file, off, enabled, fake_bin)

    assert completed.returncode != 0
    assert "differ outside the enabled flag" in completed.stderr
    assert not marker.exists()


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_controlled_promotion_rejects_report_hash_drift_before_kubectl_exec(
    tmp_path: Path,
) -> None:
    _, script, env_file, off, enabled, _ = _controlled_sector_packet(tmp_path)
    report = tmp_path / "reviewed-report.json"
    report.write_text('{"provider":"fuyao","reports":[]}\n', encoding="utf-8")
    with env_file.open("a", encoding="utf-8") as stream:
        stream.write(f"REVIEWED_REPORT_SHA256={'0' * 64}\n")
    fake_bin, marker = _write_target_spies(tmp_path)

    completed = subprocess.run(
        [
            "bash",
            str(script),
            "--env-file",
            str(env_file),
            "--promote-sectors-capability",
            "--off-values",
            str(off),
            "--enabled-values",
            str(enabled),
            "--report",
            str(report),
            "--kube-version",
            "1.26.6+k3s1",
        ],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "REAL_HELM": HELM,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "reviewed capability report SHA-256 drift" in completed.stderr
    assert not marker.exists()


def test_controlled_sectors_commands_are_narrow_and_hook_free() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    controlled = source.split(
        'if [[ "$OPERATION" == repair-sectors-off-release || '
        '"$OPERATION" == promote-sectors-capability || '
        '"$OPERATION" == enable-sectors-config || '
        '"$OPERATION" == disable-sectors-config ]]; then',
        1,
    )[1].split('if [[ "$OPERATION" == deploy ]]; then', 1)[0]
    promotion = controlled.split("PROMOTION_ARGS=(", 1)[1].split("exit 0", 1)[0]
    repair = controlled.split(
        'if [[ "$OPERATION" == repair-sectors-off-release ]]; then', 1
    )[1].split("exit 0", 1)[0]
    config = controlled.split('log "applying hook-free same-image sectors config', 1)[1]

    assert "kubectl exec -i --namespace" in promotion
    assert "-c dashboard --" in promotion
    assert "capabilities promote" in promotion
    assert "--input - --provider fuyao --dataset sectors --revision fuyao-market-v2" in promotion
    assert controlled.index("compare-release-exact") < controlled.index("kubectl exec -i")
    assert controlled.index("compare-live-desired") < controlled.index("kubectl exec -i")
    assert "kubectl cp" not in promotion
    assert "sh -c" not in promotion
    assert "helm upgrade \"$RELEASE_NAME\"" in config
    assert "--set component=all" in config
    assert "--no-hooks" in config
    assert "--atomic" in config
    assert "--wait" in config
    assert "--install" not in config
    assert 'helm upgrade "$RELEASE_NAME"' in repair
    assert "--set component=all" in repair
    assert "--no-hooks" in repair
    assert "--install" not in repair
    assert "compare-release-exact" in repair
    assert "compare-live-desired" in repair
    assert "verify_live_database_contract" in repair
    assert "capabilities promote" not in repair
    assert "scheduled-refresh" not in repair
    assert "kubectl exec" not in repair
    for forbidden in ("podman build", "podman save", "scp ", "images import", "kubectl cp"):
        assert forbidden not in controlled


def test_disable_manual_refresh_command_is_narrow_hook_free_and_fail_closed() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    controlled = source.split(
        'if [[ "$CONTROLLED_MANUAL_REFRESH_OPERATION" == true ]]; then\n'
        '  FROZEN_IMAGE=',
        1,
    )[1].split(
        'if [[ "$OPERATION" == repair-sectors-off-release',
        1,
    )[0]

    assert 'compare-manual-refresh-only' in controlled
    assert 'compare-release-exact' in controlled
    assert 'compare-hooks-exact' in controlled
    assert controlled.count('helm get hooks "$RELEASE_NAME"') == 3
    assert 'compare-manual-refresh-live-desired' in controlled
    assert 'kubectl get deployment,service,cronjob,statefulset,pvc' in controlled
    assert 'verify_live_database_contract' in controlled
    assert 'verify_frozen_runtime_image' in controlled
    assert 'verify_manual_refresh_runtime "$REVIEWED_MANUAL_OFF_RENDER" 0' in controlled
    assert 'require_all_application_cronjobs_absent' in controlled
    assert 'require_terminal_namespace_jobs' in controlled
    assert 'require_no_active_namespace_jobs' not in controlled
    assert 'require_namespace_jobs_absent' not in controlled
    assert 'capture_preserved_resource_identities' in controlled
    assert 'helm upgrade "$RELEASE_NAME"' in controlled
    assert '--no-hooks' in controlled
    assert '--atomic' in controlled
    assert '--wait' in controlled
    assert '--install' not in controlled
    for forbidden in (
        "podman build",
        "podman save",
        "scp ",
        "images import",
        "kubectl exec",
        "capabilities promote",
        "scheduled-refresh",
        "alembic upgrade",
    ):
        assert forbidden not in controlled


def test_disabled_all_component_stage_stops_after_complete_release_convergence() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "component=all complete Helm release manifest consolidated" in source
    assert '&& ( "$COMPONENT_NAME" == "schedule" || "$COMPONENT_NAME" == "all" )' not in source
    assert 'if [[ -z "$FAILED_COMPONENT" && "$COMPONENT_NAME" == "schedule" ]]; then' in source
    assert "schedule phase=skipped reason=baseline_disabled complete_release_converged" in source


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_repair_sectors_off_restores_only_complete_release_without_image_or_data_work(
    tmp_path: Path,
) -> None:
    repo, script, env_file, off, enabled, _ = _controlled_sector_packet(tmp_path)
    reviewed_off_render = _render_sector_profile(
        off,
        chart=repo / "deploy" / "helm" / "a-stock",
        image_repository="registry.local/frozen",
        image_tag="reviewed-20261009",
    )
    fake_bin, calls = _repair_target_stubs(
        tmp_path, reviewed_off_render=reviewed_off_render
    )
    kubeconfig = tmp_path / "repair-kubeconfig"
    kubeconfig.write_text("fixture\n", encoding="utf-8")
    with env_file.open("a", encoding="utf-8") as stream:
        stream.write(f"KUBECONFIG={kubeconfig}\n")

    completed = _run_controlled_sector_entry(
        script,
        env_file,
        off,
        enabled,
        fake_bin,
        operation="--repair-sectors-off-release",
    )
    call_log = calls.read_text(encoding="utf-8")

    assert completed.returncode == 0, completed.stderr
    upgrade_calls = [line for line in call_log.splitlines() if line.startswith("helm upgrade ")]
    metadata_calls = [
        line for line in call_log.splitlines() if line.startswith("helm get metadata ")
    ]
    values_calls = [
        line for line in call_log.splitlines() if line.startswith("helm get values ")
    ]
    hooks_calls = [
        line for line in call_log.splitlines() if line.startswith("helm get hooks ")
    ]
    assert len(upgrade_calls) == 1
    assert len(metadata_calls) == 3
    assert len(values_calls) == 3
    assert len(hooks_calls) == 3
    assert "--set image.repository=registry.local/frozen" in upgrade_calls[0]
    assert "--set image.tag=reviewed-20261009" in upgrade_calls[0]
    assert "--set component=all" in upgrade_calls[0]
    assert "--no-hooks" in upgrade_calls[0]
    assert "--install" not in upgrade_calls[0]
    assert "--atomic" not in upgrade_calls[0]
    assert "complete sectors-off release repaired" in completed.stdout
    for forbidden in (
        "podman ",
        "scp ",
        "curl ",
        "kubectl exec",
        "capabilities promote",
        "scheduled-refresh",
        "images import",
    ):
        assert forbidden not in call_log


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_repair_sectors_off_rejects_post_upgrade_hook_drift(
    tmp_path: Path,
) -> None:
    repo, script, env_file, off, enabled, _ = _controlled_sector_packet(tmp_path)
    reviewed_off_render = _render_sector_profile(
        off,
        chart=repo / "deploy" / "helm" / "a-stock",
        image_repository="registry.local/frozen",
        image_tag="reviewed-20261009",
    )
    fake_bin, calls = _repair_target_stubs(
        tmp_path,
        reviewed_off_render=reviewed_off_render,
        post_stored_hooks=(
            "apiVersion: batch/v1\n"
            "kind: Job\n"
            "metadata:\n"
            "  name: unreviewed-hook\n"
            "  annotations:\n"
            "    helm.sh/hook: post-upgrade\n"
        ),
    )
    kubeconfig = tmp_path / "repair-kubeconfig"
    kubeconfig.write_text("fixture\n", encoding="utf-8")
    with env_file.open("a", encoding="utf-8") as stream:
        stream.write(f"KUBECONFIG={kubeconfig}\n")

    completed = _run_controlled_sector_entry(
        script,
        env_file,
        off,
        enabled,
        fake_bin,
        operation="--repair-sectors-off-release",
    )
    call_log = calls.read_text(encoding="utf-8")
    upgrade_calls = [
        line for line in call_log.splitlines() if line.startswith("helm upgrade ")
    ]

    assert completed.returncode != 0
    assert "postcondition requires the next deployed complete-off revision" in completed.stderr
    assert len(upgrade_calls) == 1
    assert "--no-hooks" in upgrade_calls[0]
    assert "--atomic" not in upgrade_calls[0]
    for forbidden in (
        "podman ",
        "scp ",
        "kubectl exec",
        "capabilities promote",
        "scheduled-refresh",
        "images import",
    ):
        assert forbidden not in call_log


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize(
    "stub_overrides",
    [
        pytest.param({"release_revision": 90}, id="revision-drift"),
        pytest.param({"release_status": "failed"}, id="status-drift"),
        pytest.param({"chart_name": "unexpected-chart"}, id="chart-name-drift"),
        pytest.param({"chart_version": "0.0.0-drift"}, id="chart-version-drift"),
        pytest.param({"stored_component": "all"}, id="stored-values-drift"),
        pytest.param(
            {"stored_hooks": "apiVersion: batch/v1\nkind: Job\n"},
            id="stored-hooks-drift",
        ),
    ],
)
def test_repair_sectors_off_rejects_release_identity_drift_before_helm_write(
    tmp_path: Path,
    stub_overrides: dict[str, object],
) -> None:
    repo, script, env_file, off, enabled, _ = _controlled_sector_packet(tmp_path)
    reviewed_off_render = _render_sector_profile(
        off,
        chart=repo / "deploy" / "helm" / "a-stock",
        image_repository="registry.local/frozen",
        image_tag="reviewed-20261009",
    )
    fake_bin, calls = _repair_target_stubs(
        tmp_path,
        reviewed_off_render=reviewed_off_render,
        **stub_overrides,
    )
    kubeconfig = tmp_path / "repair-kubeconfig"
    kubeconfig.write_text("fixture\n", encoding="utf-8")
    with env_file.open("a", encoding="utf-8") as stream:
        stream.write(f"KUBECONFIG={kubeconfig}\n")

    completed = _run_controlled_sector_entry(
        script,
        env_file,
        off,
        enabled,
        fake_bin,
        operation="--repair-sectors-off-release",
    )
    call_log = calls.read_text(encoding="utf-8")

    assert completed.returncode != 0
    assert "requires exact deployed revision" in completed.stderr
    assert "helm upgrade " not in call_log
    for forbidden in (
        "podman ",
        "scp ",
        "kubectl exec",
        "capabilities promote",
        "scheduled-refresh",
        "images import",
    ):
        assert forbidden not in call_log


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_repair_sectors_off_rejects_nonexact_stored_manifest_before_helm_write(
    tmp_path: Path,
) -> None:
    repo, script, env_file, off, enabled, _ = _controlled_sector_packet(tmp_path)
    reviewed_off_render = _render_sector_profile(
        off,
        chart=repo / "deploy" / "helm" / "a-stock",
        image_repository="registry.local/frozen",
        image_tag="reviewed-20261009",
    )
    fake_bin, calls = _repair_target_stubs(
        tmp_path,
        reviewed_off_render=reviewed_off_render,
        stored_manifest=reviewed_off_render,
    )
    kubeconfig = tmp_path / "repair-kubeconfig"
    kubeconfig.write_text("fixture\n", encoding="utf-8")
    with env_file.open("a", encoding="utf-8") as stream:
        stream.write(f"KUBECONFIG={kubeconfig}\n")

    completed = _run_controlled_sector_entry(
        script,
        env_file,
        off,
        enabled,
        fake_bin,
        operation="--repair-sectors-off-release",
    )
    call_log = calls.read_text(encoding="utf-8")

    assert completed.returncode != 0
    assert "requires the exact reviewed schedule-only stored manifest" in completed.stderr
    assert "helm upgrade " not in call_log
    assert "podman " not in call_log
    assert "scp " not in call_log


def test_stage_sectors_off_freezes_single_import_digest_before_helm_write() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    execution = source.split('log "building $IMAGE"', 1)[1].split(
        'if [[ "$OPERATION" == read-only-discovery ]]; then', 1
    )[0]

    assert source.count("podman build \\") == 1
    assert source.count("podman save --format docker-archive") == 1
    assert source.count("images import '$ARCHIVE_NAME'") == 1
    assert execution.index("images import '$ARCHIVE_NAME'") < execution.index(
        'DISCOVERED_IMAGE_DIGEST="$(capture_containerd_image_digest "$IMAGE")"'
    )
    assert execution.index("DISCOVERED_IMAGE_DIGEST=") < execution.index(
        'deploy_step_or_exit database'
    )
    assert "could not resolve one exact containerd manifest digest after import" in execution


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_stage_sectors_off_stops_before_helm_when_imported_digest_is_unavailable(
    tmp_path: Path,
) -> None:
    repo, script, env_file, off, enabled, _ = _controlled_sector_packet(tmp_path)
    off_render = _render_sector_profile(
        off,
        chart=repo / "deploy" / "helm" / "a-stock",
        image_repository="registry.local/frozen",
        image_tag="reviewed-20261009",
    )
    stored_manifest = tmp_path / "stored-off.yaml"
    stored_manifest.write_text(off_render, encoding="utf-8")
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("fixture\n", encoding="utf-8")
    content = env_file.read_text(encoding="utf-8").replace(
        f"FROZEN_IMAGE_DIGEST=sha256:{'d' * 64}\n", ""
    )
    env_file.write_text(
        content
        + "REMOTE_IMAGE_DIR=/unreachable\n"
        + "IMAGE_REPOSITORY=registry.local/frozen\n"
        + "IMAGE_TAG=reviewed-20261009\n"
        + f"KUBECONFIG={kubeconfig}\n",
        encoding="utf-8",
    )

    fake_bin = tmp_path / "stage-bin"
    fake_bin.mkdir()
    calls = tmp_path / "stage-calls"
    helm_wrapper = fake_bin / "helm"
    helm_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'helm %s\\n' \"$*\" >> {calls}\n"
        "case \"$1\" in\n"
        "  lint|template) exec \"$REAL_HELM\" \"$@\" ;;\n"
        "  list) printf '[{\"name\":\"a-stock\"}]\\n' ;;\n"
        f"  get) cat {stored_manifest} ;;\n"
        "  upgrade) exit 93 ;;\n"
        "  *) exit 94 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    helm_wrapper.chmod(0o755)
    kubectl_wrapper = fake_bin / "kubectl"
    kubectl_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'kubectl %s\\n' \"$*\" >> {calls}\n"
        "if [[ \"$*\" == *\"get nodes\"* ]]; then printf amd64; exit 0; fi\n"
        "if [[ \"$*\" == *\"get --raw /version\"* ]]; then printf '{\"gitVersion\":\"v1.26.6+k3s1\"}'; exit 0; fi\n"
        "if [[ \"$1\" == get && \"$2\" == cronjob ]]; then exit 0; fi\n"
        "if [[ \"$1\" == get && \"$2\" == jobs ]]; then printf '{\"items\":[]}'; exit 0; fi\n"
        "if [[ \"$1\" == get && \"$2\" == secret ]]; then printf 'secret-uid|11'; exit 0; fi\n"
        "if [[ \"$1\" == get && \"$2\" == pvc ]]; then printf 'pvc-uid|12|pv-reviewed|Bound|5Gi'; exit 0; fi\n"
        "exit 95\n",
        encoding="utf-8",
    )
    kubectl_wrapper.chmod(0o755)
    podman_wrapper = fake_bin / "podman"
    podman_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'podman %s\\n' \"$*\" >> {calls}\n"
        "if [[ \"$1 $2\" == \"image inspect\" ]]; then printf '1048576\\n'; exit 0; fi\n"
        "if [[ \"$1\" == save ]]; then\n"
        "  while (($#)); do\n"
        "    if [[ \"$1\" == --output ]]; then : > \"$2\"; exit 0; fi\n"
        "    shift\n"
        "  done\n"
        "  exit 96\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    podman_wrapper.chmod(0o755)
    ssh_wrapper = fake_bin / "ssh"
    ssh_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'ssh %s\\n' \"$*\" >> {calls}\n"
        "if [[ \"$*\" == *\"matches += 1\"* ]]; then exit 91; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    ssh_wrapper.chmod(0o755)
    for name in ("nc", "scp", "curl"):
        executable = fake_bin / name
        executable.write_text(
            "#!/usr/bin/env bash\n"
            f"printf '{name} %s\\n' \"$*\" >> {calls}\n"
            "exit 0\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)

    completed = _run_controlled_sector_entry(
        script, env_file, off, enabled, fake_bin, operation="--stage-sectors-off"
    )
    call_log = calls.read_text(encoding="utf-8")

    assert completed.returncode != 0
    assert "could not resolve one exact containerd manifest digest after import" in completed.stderr
    assert call_log.count("podman build ") == 1
    assert call_log.count("podman save ") == 1
    assert call_log.count("scp ") == 1
    assert call_log.count("images import") == 1
    assert "helm upgrade" not in call_log

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize(
    "component",
    ["database", "schedule"],
    ids=["database-skips-image", "schedule-requires-frozen-image"],
)
def test_component_deploy_routes_around_image_work_without_target_access(
    tmp_path: Path, component: str
) -> None:
    repo, script, baseline, _ = _component_fake_repo(tmp_path)
    fake_bin, marker = _write_target_spies(tmp_path)
    digest = f"sha256:{'a' * 64}"
    env_file = tmp_path / f"{component}.env"
    env_file.write_text(
        "\n".join(
            [
                f"REPO_DIR={repo}",
                "TRUENAS_HOST=192.0.2.10",
                "TRUENAS_SSH_USER=tester",
                f"HELM_VALUES_FILE={baseline}",
                "IMAGE_TAG=test-component",
                "TARGET_KUBERNETES_VERSION=1.26.6",
                "DEPLOY_TMP_ROOT=relative-path-that-must-not-be-read",
                "",
            ]
        ),
        encoding="utf-8",
    )
    if component == "schedule":
        with env_file.open("a", encoding="utf-8") as stream:
            stream.write(
                "FROZEN_IMAGE_REPOSITORY=localhost/a-stock-market-environment\n"
                "FROZEN_IMAGE_TAG=20260905-1904b66\n"
                f"FROZEN_IMAGE_DIGEST={digest}\n"
                f"SCHEDULING_OVERLAY_FILE={repo / 'deploy' / 'truenas' / 'values-scheduled-suspended.yaml'}\n"
            )

    completed = subprocess.run(
        [
            "bash",
            str(script),
            "--env-file",
            str(env_file),
            "--component",
            component,
        ],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "REAL_HELM": HELM,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    # Component deploys now continue from render preflight into the guarded
    # target-write phase.  The fail-closed target spy rejects that phase while
    # proving that no image build/transfer was attempted before access.
    assert completed.returncode == 97, completed.stderr
    assert f"component summary: phase=preflight component={component}" in completed.stdout
    assert "checking SSH and non-interactive sudo" in completed.stdout
    assert marker.exists()
    assert "podman" not in marker.read_text(encoding="utf-8")
    assert "scp" not in marker.read_text(encoding="utf-8")

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_component_schedule_rejects_missing_frozen_image_without_target_access(
    tmp_path: Path,
) -> None:
    repo, script, baseline, _ = _component_fake_repo(tmp_path)
    fake_bin, marker = _write_target_spies(tmp_path)
    env_file = tmp_path / "schedule.env"
    env_file.write_text(
        "\n".join(
            [
                f"REPO_DIR={repo}",
                "TRUENAS_HOST=192.0.2.10",
                "TRUENAS_SSH_USER=tester",
                f"HELM_VALUES_FILE={baseline}",
                f"SCHEDULING_OVERLAY_FILE={repo / 'deploy' / 'truenas' / 'values-scheduled-suspended.yaml'}",
                "IMAGE_TAG=test-schedule",
                "TARGET_KUBERNETES_VERSION=1.26.6",
                "",
            ]
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "bash",
            str(script),
            "--env-file",
            str(env_file),
            "--component",
            "schedule",
        ],
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "requires FROZEN_IMAGE_REPOSITORY" in completed.stderr
    assert not marker.exists()

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize(
    "invalid_component",
    ["service-database", "all,database", ""],
    ids=["named-pair", "comma-list", "empty"],
)
def test_component_value_rejects_invalid_or_ambiguous_names(
    tmp_path: Path, invalid_component: str
) -> None:
    repo, script, baseline, _ = _component_fake_repo(tmp_path)
    env_file = tmp_path / "invalid.env"
    env_file.write_text(
        "\n".join(
            [
                f"REPO_DIR={repo}",
                "TRUENAS_HOST=192.0.2.10",
                "TRUENAS_SSH_USER=tester",
                f"HELM_VALUES_FILE={baseline}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "bash",
            str(script),
            "--env-file",
            str(env_file),
            "--component",
            invalid_component,
        ],
        env={**os.environ, "PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "--component must be one of" in completed.stderr

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_component_database_renders_only_pvc_in_offline_mode(tmp_path: Path) -> None:
    repo, _, baseline, _ = _component_fake_repo(tmp_path)
    chart_managed = tmp_path / "chart-managed.yaml"
    chart_managed.write_text(
        "replicaCount: 1\n"
        "image:\n"
        "  repository: localhost/a-stock-market-environment\n"
        "  tag: chart-managed\n"
        "  pullPolicy: IfNotPresent\n"
        "service:\n"
        "  type: ClusterIP\n"
        "  port: 80\n"
        "ingress:\n"
        "  enabled: false\n"
        "persistence:\n"
        "  enabled: true\n"
        "  storageClass: ix-storage-class\n"
        "  accessModes:\n"
        "    - ReadWriteOnce\n"
        "  size: 2Gi\n"
        "  mountPath: /data\n"
        "  keep: true\n"
        "database:\n"
        "  enabled: true\n"
        "  existingSecret: a-stock-postgresql\n"
        "  persistence:\n"
        "    enabled: true\n"
        "    storageClass: ix-storage-class\n"
        "    accessModes:\n"
        "      - ReadWriteOnce\n"
        "    size: 5Gi\n"
        "marketEnvironment:\n"
        "  timezone: Asia/Shanghai\n"
        "  snapshotPath: /data/snapshots.sqlite3\n"
        "  persistentCache: true\n"
        "  settlementTime: \"15:10\"\n"
        "  scheduledCollection:\n"
        "    enabled: false\n"
        "    suspend: true\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "bash",
            str(repo / "scripts" / SCRIPT.name),
            "--offline-render",
            "--component",
            "database",
            "--baseline-values",
            str(chart_managed),
            "--scheduling-overlay",
            str(repo / "deploy" / "truenas" / "values-scheduled-off.yaml"),
            "--kube-version",
            "1.26.6",
            "--release-name",
            "a-stock",
            "--namespace",
            "a-stock",
        ],
        env={**os.environ, "DEPLOY_ENV_FILE": "/definitely/not/present", "REAL_HELM": HELM},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    kinds = {
        line.split(":", 1)[1].strip()
        for line in completed.stdout.splitlines()
        if line.startswith("kind:")
    }
    assert kinds == {"PersistentVolumeClaim", "Service", "StatefulSet", "Job"}
    assert "name: a-stock-postgresql" in completed.stdout
    assert "name: a-stock-postgresql-data" in completed.stdout
    assert "kind: Deployment" not in completed.stdout
    assert "kind: CronJob" not in completed.stdout

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_component_database_with_existingclaim_renders_no_pvc_object(tmp_path: Path) -> None:
    repo, _, baseline, _ = _component_fake_repo(tmp_path)

    completed = subprocess.run(
        [
            "bash",
            str(repo / "scripts" / SCRIPT.name),
            "--offline-render",
            "--component",
            "database",
            "--baseline-values",
            str(baseline),
            "--scheduling-overlay",
            str(repo / "deploy" / "truenas" / "values-scheduled-off.yaml"),
            "--kube-version",
            "1.26.6",
            "--release-name",
            "a-stock",
            "--namespace",
            "a-stock",
        ],
        env={**os.environ, "DEPLOY_ENV_FILE": "/definitely/not/present", "REAL_HELM": HELM},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    kinds = {
        line.split(":", 1)[1].strip()
        for line in completed.stdout.splitlines()
        if line.startswith("kind:")
    }
    assert kinds == {"PersistentVolumeClaim", "Service", "StatefulSet", "Job"}
    assert "name: a-stock-postgresql-data" in completed.stdout

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_component_schedule_offline_render_keeps_suspended_cronjob(tmp_path: Path) -> None:
    repo, _, baseline, _ = _component_fake_repo(tmp_path)

    completed = subprocess.run(
        [
            "bash",
            str(repo / "scripts" / SCRIPT.name),
            "--offline-render",
            "--component",
            "schedule",
            "--baseline-values",
            str(baseline),
            "--scheduling-overlay",
            str(repo / "deploy" / "truenas" / "values-scheduled-suspended.yaml"),
            "--kube-version",
            "1.26.6",
            "--release-name",
            "a-stock",
            "--namespace",
            "a-stock",
        ],
        env={**os.environ, "DEPLOY_ENV_FILE": "/definitely/not/present", "REAL_HELM": HELM},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "kind: CronJob" in completed.stdout
    assert "suspend: true" in completed.stdout
    assert "kind: Deployment" not in completed.stdout
    assert "kind: Service" not in completed.stdout
    assert "kind: PersistentVolumeClaim" not in completed.stdout

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_component_schedule_deploy_preflight_renders_with_frozen_image(
    tmp_path: Path,
) -> None:
    repo, script, baseline, _ = _component_fake_repo(tmp_path)
    fake_bin, marker = _write_target_spies(tmp_path)
    digest = f"sha256:{'b' * 64}"
    frozen_repo = "registry.local/frozen"
    frozen_tag = "20260101-frozen01"
    baseline_repo = "localhost/a-stock-market-environment"
    baseline_tag = "20260905-1904b66"
    env_file = tmp_path / "schedule-frozen.env"
    env_file.write_text(
        "\n".join(
            [
                f"REPO_DIR={repo}",
                "TRUENAS_HOST=192.0.2.10",
                "TRUENAS_SSH_USER=tester",
                f"HELM_VALUES_FILE={baseline}",
                f"SCHEDULING_OVERLAY_FILE={repo / 'deploy' / 'truenas' / 'values-scheduled-suspended.yaml'}",
                "IMAGE_TAG=test-schedule",
                f"FROZEN_IMAGE_REPOSITORY={frozen_repo}",
                f"FROZEN_IMAGE_TAG={frozen_tag}",
                f"FROZEN_IMAGE_DIGEST={digest}",
                "TARGET_KUBERNETES_VERSION=1.26.6",
                "",
            ]
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "bash",
            str(script),
            "--env-file",
            str(env_file),
            "--component",
            "schedule",
        ],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "REAL_HELM": HELM,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 97, completed.stderr
    assert f"component=schedule frozen image provenance verified: {frozen_repo}:{frozen_tag}" in completed.stdout
    assert digest in completed.stdout
    assert f"component step: name=schedule phase=preflight image={frozen_repo}:{frozen_tag}" in completed.stdout
    assert "checking SSH and non-interactive sudo" in completed.stdout
    assert marker.exists()
    assert "podman" not in marker.read_text(encoding="utf-8")
    assert "scp" not in marker.read_text(encoding="utf-8")

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_component_schedule_deploy_rejects_baseline_image_when_frozen_required(
    tmp_path: Path,
) -> None:
    repo, script, baseline, _ = _component_fake_repo(tmp_path)
    fake_bin, marker = _write_target_spies(tmp_path)
    digest = f"sha256:{'c' * 64}"
    env_file = tmp_path / "schedule-mismatch.env"
    env_file.write_text(
        "\n".join(
            [
                f"REPO_DIR={repo}",
                "TRUENAS_HOST=192.0.2.10",
                "TRUENAS_SSH_USER=tester",
                f"HELM_VALUES_FILE={baseline}",
                f"SCHEDULING_OVERLAY_FILE={repo / 'deploy' / 'truenas' / 'values-scheduled-suspended.yaml'}",
                "IMAGE_TAG=should-not-be-used",
                "FROZEN_IMAGE_REPOSITORY=registry.local/frozen",
                "FROZEN_IMAGE_TAG=20260101-frozen01",
                f"FROZEN_IMAGE_DIGEST={digest}",
                "TARGET_KUBERNETES_VERSION=1.26.6",
                "",
            ]
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "bash",
            str(script),
            "--env-file",
            str(env_file),
            "--component",
            "schedule",
        ],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "REAL_HELM": HELM,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 97, completed.stderr
    assert "image=registry.local/frozen:20260101-frozen01" in completed.stdout
    assert "image=should-not-be-used" not in completed.stdout
    assert "image=localhost/a-stock-market-environment:20260905-1904b66" not in completed.stdout
    assert marker.exists()
    assert "podman" not in marker.read_text(encoding="utf-8")
    assert "scp" not in marker.read_text(encoding="utf-8")

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_component_service_deploy_preflight_uses_component_value(
    tmp_path: Path,
) -> None:
    repo, script, baseline, _ = _component_fake_repo(tmp_path)
    fake_bin, marker = _write_target_spies(tmp_path)
    env_file = tmp_path / "service.env"
    env_file.write_text(
        "\n".join(
            [
                f"REPO_DIR={repo}",
                "TRUENAS_HOST=192.0.2.10",
                "TRUENAS_SSH_USER=tester",
                f"HELM_VALUES_FILE={baseline}",
                "IMAGE_TAG=test-service",
                "TARGET_KUBERNETES_VERSION=1.26.6",
                "",
            ]
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "bash",
            str(script),
            "--env-file",
            str(env_file),
            "--component",
            "service",
        ],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "REAL_HELM": HELM,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0, completed.stderr
    assert "REMOTE_IMAGE_DIR is required" in completed.stderr
    assert not marker.exists()

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_component_service_deploy_preflight_accepts_remote_image_dir_and_blocks_target(
    tmp_path: Path,
) -> None:
    repo, script, baseline, _ = _component_fake_repo(tmp_path)
    reviewed_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    fake_bin, marker = _write_target_spies(tmp_path)
    env_file = tmp_path / "service.env"
    env_file.write_text(
        "\n".join(
            [
                f"REPO_DIR={repo}",
                "TRUENAS_HOST=192.0.2.10",
                "TRUENAS_SSH_USER=tester",
                f"HELM_VALUES_FILE={baseline}",
                "REMOTE_IMAGE_DIR=/unreachable",
                "IMAGE_TAG=test-service",
                f"REVIEWED_GIT_HEAD={reviewed_head}",
                "TARGET_KUBERNETES_VERSION=1.26.6",
                "",
            ]
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "bash",
            str(script),
            "--env-file",
            str(env_file),
            "--component",
            "service",
        ],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "REAL_HELM": HELM,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 97, completed.stderr
    assert "REMOTE_IMAGE_DIR is required" not in completed.stderr
    assert "component step: name=service phase=preflight" in completed.stdout
    assert "checking SSH and non-interactive sudo" in completed.stdout
    assert marker.exists()
    assert "podman" not in marker.read_text(encoding="utf-8")
    assert "scp" not in marker.read_text(encoding="utf-8")

@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_all_components_ordered_database_service_schedule_in_preflight(
    tmp_path: Path,
) -> None:
    """`all` deploy preflight must report the explicit database -> service ->
    schedule ordering so operators can verify dependency direction without
    running the full Helm write.
    """
    repo, script, baseline, _ = _component_fake_repo(tmp_path)
    fake_bin, marker = _write_target_spies(tmp_path)
    env_file = tmp_path / "all.env"
    env_file.write_text(
        "\n".join(
            [
                f"REPO_DIR={repo}",
                "TRUENAS_HOST=192.0.2.10",
                "TRUENAS_SSH_USER=tester",
                f"HELM_VALUES_FILE={baseline}",
                "IMAGE_TAG=test-all",
                "TARGET_KUBERNETES_VERSION=1.26.6",
                "",
            ]
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "bash",
            str(script),
            "--env-file",
            str(env_file),
            "--component",
            "all",
        ],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "REAL_HELM": HELM,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "REMOTE_IMAGE_DIR is required" in completed.stderr
    assert not marker.exists()
