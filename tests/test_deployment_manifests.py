from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
K3S_DIR = ROOT / "deploy" / "k3s"
K3S_NATIVE_OVERLAY = ROOT / "deploy" / "k3s-native-scheduled"
K3S_RENDER_POLICY = K3S_NATIVE_OVERLAY / "render-policy.yaml"
K3S_RENDER_SCRIPT = ROOT / "scripts" / "render-k3s.py"
RUNBOOK = ROOT / "docs" / "runbooks.md"
CHART_DIR = ROOT / "deploy" / "helm" / "a-stock"
TRUENAS_DIRECT_ACCESS_VALUES = ROOT / "deploy" / "truenas" / "values-secure-manual-collection.yaml"
TRUENAS_SCHEDULED_SUSPENDED_VALUES = ROOT / "deploy" / "truenas" / "values-scheduled-suspended.yaml"
TRUENAS_SCHEDULED_ACTIVE_VALUES = ROOT / "deploy" / "truenas" / "values-scheduled-active.yaml"
TRUENAS_SCHEDULED_OFF_VALUES = ROOT / "deploy" / "truenas" / "values-scheduled-off.yaml"
HELM_BINARY = os.getenv("HELM_BINARY") or shutil.which("helm")
KUBECTL_BINARY = os.getenv("KUBECTL_BINARY") or shutil.which("kubectl")


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _render_helm(*arguments: str) -> list[dict]:
    completed = subprocess.run(
        [
            str(HELM_BINARY),
            "template",
            "a-stock",
            str(CHART_DIR),
            "--namespace",
            "a-stock",
            *arguments,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return [document for document in yaml.safe_load_all(completed.stdout) if document]


def _render_helm_error(*arguments: str) -> str:
    completed = subprocess.run(
        [
            str(HELM_BINARY),
            "template",
            "a-stock",
            str(CHART_DIR),
            "--namespace",
            "a-stock",
            *arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    return completed.stderr


def _resource(documents: list[dict], kind: str) -> dict:
    return next(document for document in documents if document.get("kind") == kind)


def _environment(container: dict) -> dict[str, str]:
    return {item["name"]: item["value"] for item in container["env"]}


def test_native_kustomize_cronjob_uses_dashboard_image_pvc_and_security_boundary() -> None:
    kustomization = _load_yaml(K3S_DIR / "kustomization.yaml")
    native_kustomization = _load_yaml(K3S_NATIVE_OVERLAY / "kustomization.yaml")
    deployment = _load_yaml(K3S_DIR / "deployment.yaml")
    service = _load_yaml(K3S_DIR / "service.yaml")
    cronjob = _load_yaml(K3S_NATIVE_OVERLAY / "market-data-collection-cronjob.yaml")
    deployment_pod = deployment["spec"]["template"]["spec"]
    deployment_container = deployment_pod["containers"][0]
    cron_spec = cronjob["spec"]
    cron_pod = cron_spec["jobTemplate"]["spec"]["template"]["spec"]
    cron_container = cron_pod["containers"][0]

    assert "market-data-collection-cronjob.yaml" not in kustomization["resources"]
    assert "market-data-collection-cronjob.yaml" in native_kustomization["resources"]
    assert cron_spec["schedule"] == "30 16 * * 1-5"
    assert cron_spec["timeZone"] == "Asia/Shanghai"
    assert cron_spec["concurrencyPolicy"] == "Forbid"
    assert cron_spec["jobTemplate"]["spec"]["backoffLimit"] == 0
    assert cron_spec["jobTemplate"]["spec"]["activeDeadlineSeconds"] == 3600
    assert cron_container["image"] == deployment_container["image"]
    assert cron_pod["volumes"][0]["persistentVolumeClaim"]["claimName"] == deployment_pod["volumes"][0]["persistentVolumeClaim"]["claimName"]
    assert cron_container["command"][-2:] == ["snapshots", "scheduled-refresh"]
    assert cron_pod["automountServiceAccountToken"] is False
    assert cron_pod["securityContext"]["runAsNonRoot"] is True
    assert cron_container["securityContext"]["readOnlyRootFilesystem"] is True
    assert cron_container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert _environment(cron_container) == _environment(deployment_container)
    assert any(
        cronjob["spec"]["jobTemplate"]["spec"]["template"]["metadata"]["labels"].get(key) != value
        for key, value in service["spec"]["selector"].items()
    )


def test_helm_values_define_enabled_configurable_scheduled_collection() -> None:
    chart = _load_yaml(CHART_DIR / "Chart.yaml")
    values = _load_yaml(CHART_DIR / "values.yaml")
    scheduled = values["marketEnvironment"]["scheduledCollection"]

    assert chart["kubeVersion"] == ">=1.26.0-0"
    assert values["marketEnvironment"]["timezone"] == "Asia/Shanghai"
    assert scheduled["enabled"] is True
    assert scheduled["suspend"] is False
    assert scheduled["schedule"] == "30 16 * * 1-5"
    assert scheduled["timezoneStrategy"] == "native"
    assert scheduled["timeZone"] == "Asia/Shanghai"
    assert scheduled["controllerTimeZone"] == ""
    assert scheduled["controllerTimeZoneVerified"] is False
    assert scheduled["controllerCanaryVerified"] is False
    assert scheduled["startingDeadlineSeconds"] == 1800
    assert scheduled["activeDeadlineSeconds"] == 3600


@pytest.mark.skipif(HELM_BINARY is None, reason="helm is not installed")
def test_helm_default_render_matches_dashboard_image_pvc_and_security() -> None:
    documents = _render_helm()
    deployment = _resource(documents, "Deployment")
    service = _resource(documents, "Service")
    cronjob = _resource(documents, "CronJob")
    deployment_pod = deployment["spec"]["template"]["spec"]
    deployment_container = deployment_pod["containers"][0]
    cron_pod = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    cron_container = cron_pod["containers"][0]

    assert cronjob["spec"]["schedule"] == "30 16 * * 1-5"
    assert cronjob["spec"]["timeZone"] == "Asia/Shanghai"
    assert cronjob["spec"]["suspend"] is False
    assert cronjob["spec"]["concurrencyPolicy"] == "Forbid"
    assert cronjob["spec"]["jobTemplate"]["spec"]["backoffLimit"] == 0
    assert cron_container["image"] == deployment_container["image"]
    assert cron_pod["volumes"][0]["persistentVolumeClaim"]["claimName"] == deployment_pod["volumes"][0]["persistentVolumeClaim"]["claimName"]
    assert cron_pod["automountServiceAccountToken"] is False
    assert cron_pod["securityContext"]["runAsNonRoot"] is True
    assert cron_container["securityContext"]["readOnlyRootFilesystem"] is True
    assert _environment(cron_container) == _environment(deployment_container)
    cron_labels = cronjob["spec"]["jobTemplate"]["spec"]["template"]["metadata"]["labels"]
    assert any(cron_labels.get(key) != value for key, value in service["spec"]["selector"].items())


@pytest.mark.skipif(HELM_BINARY is None, reason="helm is not installed")
def test_helm_render_supports_disabled_suspended_and_custom_native_schedule() -> None:
    disabled = _render_helm("--set", "marketEnvironment.scheduledCollection.enabled=false")
    custom = _render_helm(
        "--set",
        "marketEnvironment.scheduledCollection.suspend=true",
        "--set-string",
        "marketEnvironment.scheduledCollection.schedule=15 17 * * 1-5",
    )

    assert all(document.get("kind") != "CronJob" for document in disabled)
    cronjob = _resource(custom, "CronJob")
    assert cronjob["spec"]["suspend"] is True
    assert cronjob["spec"]["schedule"] == "15 17 * * 1-5"
    assert cronjob["spec"]["timeZone"] == "Asia/Shanghai"


@pytest.mark.skipif(HELM_BINARY is None, reason="helm is not installed")
@pytest.mark.parametrize(
    ("controller_timezone", "schedule"),
    [("Etc/UTC", "30 8 * * 1-5"), ("Asia/Shanghai", "30 16 * * 1-5")],
)
def test_helm_render_supports_verified_controller_profiles_on_kubernetes_126(
    controller_timezone: str,
    schedule: str,
) -> None:
    documents = _render_helm(
        "--kube-version",
        "1.26.6",
        "--set",
        "marketEnvironment.scheduledCollection.timezoneStrategy=controller",
        "--set",
        f"marketEnvironment.scheduledCollection.controllerTimeZone={controller_timezone}",
        "--set",
        "marketEnvironment.scheduledCollection.controllerTimeZoneVerified=true",
        "--set",
        "marketEnvironment.scheduledCollection.suspend=true",
        "--set-string",
        f"marketEnvironment.scheduledCollection.schedule={schedule}",
    )

    cronjob = _resource(documents, "CronJob")
    assert cronjob["spec"]["schedule"] == schedule
    assert cronjob["spec"]["suspend"] is True
    assert "timeZone" not in cronjob["spec"]


@pytest.mark.skipif(HELM_BINARY is None, reason="helm is not installed")
@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (
            ("--set", "marketEnvironment.scheduledCollection.timezoneStrategy=unknown"),
            "timezoneStrategy must be native or controller",
        ),
        (
            ("--kube-version", "1.26.6"),
            "timezoneStrategy=native requires Kubernetes 1.27+",
        ),
        (
            (
                "--kube-version",
                "1.26.6",
                "--set",
                "marketEnvironment.scheduledCollection.timezoneStrategy=controller",
                "--set",
                "marketEnvironment.scheduledCollection.controllerTimeZone=Etc/UTC",
                "--set-string",
                "marketEnvironment.scheduledCollection.schedule=30 8 * * 1-5",
            ),
            "controllerTimeZoneVerified=true is required",
        ),
        (
            ("--set-string", "marketEnvironment.scheduledCollection.schedule=10 15 * * 1-5"),
            "schedule must be strictly after settlementTime",
        ),
        (
            ("--set-string", "marketEnvironment.scheduledCollection.schedule=15 17\\,18 * * 1-5"),
            "must use one numeric M H * * 1-5 trigger",
        ),
        (
            (
                "--kube-version",
                "1.26.6",
                "--set",
                "marketEnvironment.scheduledCollection.timezoneStrategy=controller",
                "--set",
                "marketEnvironment.scheduledCollection.controllerTimeZone=Etc/UTC",
                "--set",
                "marketEnvironment.scheduledCollection.controllerTimeZoneVerified=true",
                "--set",
                "marketEnvironment.scheduledCollection.suspend=true",
            ),
            "controller UTC schedule must equal 30 8 * * 1-5",
        ),
        (
            (
                "--kube-version",
                "1.26.6",
                "--set",
                "marketEnvironment.scheduledCollection.timezoneStrategy=controller",
                "--set",
                "marketEnvironment.scheduledCollection.controllerTimeZone=Asia/Shanghai",
                "--set",
                "marketEnvironment.scheduledCollection.controllerTimeZoneVerified=true",
                "--set",
                "marketEnvironment.scheduledCollection.suspend=false",
            ),
            "controllerCanaryVerified=true before suspend=false",
        ),
    ],
)
def test_helm_rejects_invalid_scheduling_profiles(arguments: tuple[str, ...], message: str) -> None:
    assert message in _render_helm_error(*arguments)


@pytest.mark.skipif(HELM_BINARY is None, reason="helm is not installed")
@pytest.mark.parametrize(
    "field",
    [
        "enabled",
        "suspend",
        "controllerTimeZoneVerified",
        "controllerCanaryVerified",
    ],
)
def test_helm_rejects_string_scheduling_booleans(field: str) -> None:
    error = _render_helm_error(
        "--set-string",
        f"marketEnvironment.scheduledCollection.{field}=false",
    )

    assert f"scheduledCollection/{field}" in error
    assert "got string, want boolean" in error


@pytest.mark.skipif(HELM_BINARY is None, reason="helm is not installed")
@pytest.mark.parametrize("enabled", ["true", "false"])
def test_helm_rejects_non_shanghai_business_timezone(enabled: str) -> None:
    error = _render_helm_error(
        "--set",
        f"marketEnvironment.scheduledCollection.enabled={enabled}",
        "--set",
        "marketEnvironment.timezone=Etc/UTC",
    )

    assert "marketEnvironment/timezone" in error
    assert "value must be 'Asia/Shanghai'" in error


@pytest.mark.skipif(HELM_BINARY is None, reason="helm is not installed")
def test_helm_render_supports_node_port_on_kubernetes_126() -> None:
    documents = _render_helm(
        "--kube-version",
        "1.26.6",
        "--set",
        "marketEnvironment.scheduledCollection.enabled=false",
        "--set",
        "ingress.enabled=false",
        "--set",
        "service.type=NodePort",
        "--set",
        "service.nodePort=32001",
    )

    service = _resource(documents, "Service")
    assert service["spec"]["type"] == "NodePort"
    assert service["spec"]["ports"][0]["nodePort"] == 32001


@pytest.mark.skipif(HELM_BINARY is None, reason="helm is not installed")
def test_truenas_direct_access_values_preserve_runtime_and_storage_invariants() -> None:
    documents = _render_helm(
        "--kube-version",
        "1.26.6",
        "--values",
        str(TRUENAS_DIRECT_ACCESS_VALUES),
    )
    deployment = _resource(documents, "Deployment")
    service = _resource(documents, "Service")
    pod = deployment["spec"]["template"]["spec"]
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    manual_refresh = [
        item for item in container["env"] if item["name"] == "MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED"
    ]

    assert deployment["spec"]["replicas"] == 1
    assert container["image"] == "localhost/a-stock-market-environment:20260905-1904b66"
    assert pod["volumes"][0]["persistentVolumeClaim"]["claimName"] == "a-stock-data"
    assert container["volumeMounts"][0] == {"name": "data", "mountPath": "/data"}
    assert _environment(container)["MARKET_ENVIRONMENT_SNAPSHOT_PATH"] == "/data/snapshots.sqlite3"
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert pod["securityContext"]["runAsUser"] == 10001
    assert pod["securityContext"]["runAsGroup"] == 10001
    assert pod["securityContext"]["fsGroup"] == 10001
    assert pod["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert service["spec"]["type"] == "NodePort"
    assert service["spec"]["ports"][0]["nodePort"] == 32001
    assert manual_refresh == [{"name": "MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", "value": "1"}]
    assert all(document.get("kind") not in {"Ingress", "CronJob", "PersistentVolumeClaim"} for document in documents)


@pytest.mark.skipif(HELM_BINARY is None, reason="helm is not installed")
def test_truenas_scheduling_overlays_only_change_reviewed_scheduling_fields() -> None:
    baseline = _render_helm(
        "--kube-version",
        "1.26.6",
        "--values",
        str(TRUENAS_DIRECT_ACCESS_VALUES),
    )
    suspended = _render_helm(
        "--kube-version",
        "1.26.6",
        "--values",
        str(TRUENAS_DIRECT_ACCESS_VALUES),
        "--values",
        str(TRUENAS_SCHEDULED_SUSPENDED_VALUES),
    )
    active = _render_helm(
        "--kube-version",
        "1.26.6",
        "--values",
        str(TRUENAS_DIRECT_ACCESS_VALUES),
        "--values",
        str(TRUENAS_SCHEDULED_ACTIVE_VALUES),
    )
    off = _render_helm(
        "--kube-version",
        "1.26.6",
        "--values",
        str(TRUENAS_DIRECT_ACCESS_VALUES),
        "--values",
        str(TRUENAS_SCHEDULED_OFF_VALUES),
    )

    baseline_non_cronjobs = [document for document in baseline if document["kind"] != "CronJob"]
    assert [document for document in suspended if document["kind"] != "CronJob"] == baseline_non_cronjobs
    assert [document for document in active if document["kind"] != "CronJob"] == baseline_non_cronjobs
    assert [document for document in off if document["kind"] != "CronJob"] == baseline_non_cronjobs

    suspended_cronjob = _resource(suspended, "CronJob")
    active_cronjob = _resource(active, "CronJob")
    assert suspended_cronjob["spec"]["schedule"] == active_cronjob["spec"]["schedule"] == "30 8 * * 1-5"
    assert suspended_cronjob["spec"]["suspend"] is True
    assert active_cronjob["spec"]["suspend"] is False
    assert "timeZone" not in suspended_cronjob["spec"]
    assert all(document["kind"] != "CronJob" for document in off)


@pytest.mark.skipif(HELM_BINARY is None, reason="helm is not installed")
def test_truenas_deploy_script_offline_render_does_not_access_a_target() -> None:
    completed = subprocess.run(
        [
            "bash",
            str(ROOT / "scripts" / "deploy-truenas-k3s.sh"),
            "--offline-render",
            "--baseline-values",
            str(TRUENAS_DIRECT_ACCESS_VALUES),
            "--scheduling-overlay",
            str(TRUENAS_SCHEDULED_SUSPENDED_VALUES),
            "--kube-version",
            "1.26.6",
            "--release-name",
            "research",
            "--namespace",
            "market-data",
        ],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "DEPLOY_ENV_FILE": "/definitely/not/present"},
    )

    assert "effectiveShanghai=16:30 weekdays" in completed.stdout
    assert "kind: CronJob" in completed.stdout
    assert "timeZone:" not in completed.stdout
    assert "name: research-a-stock-data-collection" in completed.stdout
    assert "namespace: market-data" in completed.stdout
    assert "environment file" not in completed.stderr


@pytest.mark.skipif(KUBECTL_BINARY is None, reason="kubectl is not installed")
def test_base_kustomize_renders_dashboard_without_cronjob() -> None:
    completed = subprocess.run(
        [str(KUBECTL_BINARY), "kustomize", str(K3S_DIR)],
        check=True,
        capture_output=True,
        text=True,
    )
    documents = [document for document in yaml.safe_load_all(completed.stdout) if document]
    cronjobs = [document for document in documents if document.get("kind") == "CronJob"]

    assert cronjobs == []


@pytest.mark.skipif(KUBECTL_BINARY is None, reason="kubectl is not installed")
def test_checked_native_kustomize_renders_one_data_collection_cronjob() -> None:
    completed = subprocess.run(
        [sys.executable, str(K3S_RENDER_SCRIPT), "--kube-version", "1.27.0"],
        check=True,
        capture_output=True,
        text=True,
    )
    documents = [document for document in yaml.safe_load_all(completed.stdout) if document]
    cronjobs = [document for document in documents if document.get("kind") == "CronJob"]

    assert len(cronjobs) == 1
    assert cronjobs[0]["metadata"]["name"] == "market-data-collection"
    assert cronjobs[0]["spec"]["timeZone"] == "Asia/Shanghai"
    render_policy = _load_yaml(K3S_RENDER_POLICY)
    assert render_policy == {
        "minimumKubernetesVersion": "1.27.0",
        "scheduledCollectionTimezoneStrategy": "native",
    }
    assert K3S_RENDER_POLICY.name not in _load_yaml(K3S_NATIVE_OVERLAY / "kustomization.yaml")["resources"]


def test_checked_native_kustomize_rejects_126_before_kubectl(tmp_path: Path) -> None:
    marker = tmp_path / "kubectl-called"
    fake_kubectl = tmp_path / "kubectl"
    fake_kubectl.write_text(
        f"#!/usr/bin/env sh\nprintf called > {marker}\nexit 99\n",
        encoding="utf-8",
    )
    fake_kubectl.chmod(0o755)

    completed = subprocess.run(
        [
            sys.executable,
            str(K3S_RENDER_SCRIPT),
            "--kube-version",
            "1.26.6+k3s1",
            "--kubectl",
            str(fake_kubectl),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "requires Kubernetes 1.27.0+" in completed.stderr
    assert not marker.exists()


def test_runbook_does_not_offer_unguarded_schedule_activation_commands() -> None:
    content = RUNBOOK.read_text(encoding="utf-8")
    helm_upgrades = [line for line in content.splitlines() if line.startswith("helm upgrade")]

    assert helm_upgrades
    assert all("marketEnvironment.scheduledCollection.enabled=false" in line for line in helm_upgrades)
    assert all("--reuse-values" not in line for line in helm_upgrades)
    assert "kubectl patch cronjob market-data-collection -n a-stock --type=merge -p '{\"spec\":{\"suspend\":false}}'" not in content
    assert "kubectl create job -n a-stock --from=cronjob" not in content
