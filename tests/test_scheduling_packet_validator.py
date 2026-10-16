from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate-scheduling-packet.py"
IMAGE = "localhost/a-stock-market-environment:reviewed"
DIGEST = f"sha256:{'a' * 64}"
LABELS = {"app.kubernetes.io/instance": "a-stock", "app.kubernetes.io/name": "a-stock"}


def _run(command: str, payload: str = "", *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), command, *arguments],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.mark.parametrize(
    ("version", "normalized"),
    [
        ("v1.26.6+k3s1", "1.26.6+k3s1"),
        ("v1.30.0-rc.1+build.7", "1.30.0-rc.1+build.7"),
        ("1.27.0+001", "1.27.0+001"),
    ],
)
def test_version_parser_accepts_strict_semver(version: str, normalized: str) -> None:
    completed = _run("parse-version", json.dumps({"gitVersion": version}))

    assert completed.returncode == 0
    assert completed.stdout.strip() == normalized


@pytest.mark.parametrize(
    "version",
    [
        "v01.27.0",
        "v1.027.0",
        "v1.27.00",
        "v1.27.0-.",
        "v1.27.0-rc..1",
        "v1.27.0-rc.01",
        "v1.27.0+build..1",
        "v1.27.0+build_1",
    ],
)
def test_version_parser_rejects_invalid_semver(version: str) -> None:
    completed = _run("parse-version", json.dumps({"gitVersion": version}))

    assert completed.returncode != 0
    assert "missing or invalid" in completed.stderr


def test_normalize_version_outputs_strict_version_without_v_prefix() -> None:
    completed = _run("normalize-version", "", "--version", "v1.26.6+k3s1")

    assert completed.returncode == 0
    assert completed.stdout.strip() == "1.26.6+k3s1"


def test_normalize_version_rejects_invalid_semver() -> None:
    completed = _run("normalize-version", "", "--version", "1.27.0-rc.01")

    assert completed.returncode != 0
    assert "invalid Kubernetes version" in completed.stderr


@pytest.mark.parametrize(
    "command",
    [
        "validate-activation-window",
        "validate-generic-deploy-values",
        "inspect",
        "extract-suspended",
        "compare-add-suspended",
        "compare-suspend-only",
        "compare-remove-cronjob",
    ],
)
def test_positive_scheduling_commands_are_retired(command: str) -> None:
    completed = _run(command)

    assert completed.returncode != 0
    assert "invalid choice" in completed.stderr


@pytest.mark.parametrize(
    "payload",
    [
        {"Name": f"{IMAGE}-other", "Target": {"digest": DIGEST}},
        {"Name": IMAGE, "Target": {"digest": f"sha256:{'b' * 64}"}},
        {"Name": IMAGE, "Target": DIGEST},
    ],
)
def test_containerd_image_requires_exact_name_and_target_digest(payload: dict[str, Any]) -> None:
    completed = _run(
        "verify-containerd-image",
        json.dumps(payload),
        "--image",
        IMAGE,
        "--digest",
        DIGEST,
    )

    assert completed.returncode != 0


def test_containerd_image_accepts_exact_name_and_target_digest() -> None:
    completed = _run(
        "verify-containerd-image",
        json.dumps({"Name": IMAGE, "Target": {"digest": DIGEST}}),
        "--image",
        IMAGE,
        "--digest",
        DIGEST,
    )

    assert completed.returncode == 0


def _runtime_payloads() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": "a-stock",
            "namespace": "a-stock",
            "uid": "deployment-current",
            "labels": LABELS,
            "annotations": {"deployment.kubernetes.io/revision": "2"},
        },
        "spec": {"template": {"spec": {"containers": [{"name": "dashboard", "image": IMAGE}]}}},
    }
    current_replicaset = {
        "apiVersion": "apps/v1",
        "kind": "ReplicaSet",
        "metadata": {
            "name": "a-stock-current",
            "namespace": "a-stock",
            "uid": "replicaset-current",
            "labels": LABELS,
            "annotations": {"deployment.kubernetes.io/revision": "2"},
            "ownerReferences": [
                {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "name": "a-stock",
                    "uid": "deployment-current",
                    "controller": True,
                }
            ],
        },
        "spec": {"template": {"spec": {"containers": [{"name": "dashboard", "image": IMAGE}]}}},
    }
    dashboard_pod = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "a-stock-current-abc",
            "namespace": "a-stock",
            "uid": "pod-current",
            "labels": LABELS,
            "ownerReferences": [
                {
                    "apiVersion": "apps/v1",
                    "kind": "ReplicaSet",
                    "name": "a-stock-current",
                    "uid": "replicaset-current",
                    "controller": True,
                }
            ],
        },
        "spec": {"containers": [{"name": "dashboard", "image": IMAGE}]},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}],
            "containerStatuses": [
                {
                    "name": "dashboard",
                    "image": IMAGE,
                    "imageID": f"containerd://{DIGEST}",
                    "ready": True,
                }
            ],
        },
    }
    retained_collector_pod = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "a-stock-data-collection-old",
            "namespace": "a-stock",
            "uid": "collector-pod",
            "labels": LABELS,
            "ownerReferences": [
                {
                    "apiVersion": "batch/v1",
                    "kind": "Job",
                    "name": "a-stock-data-collection-old",
                    "uid": "collector-job",
                    "controller": True,
                }
            ],
        },
        "spec": {"containers": [{"name": "collector", "image": IMAGE}]},
        "status": {"phase": "Succeeded"},
    }
    return (
        {"apiVersion": "apps/v1", "kind": "DeploymentList", "items": [deployment]},
        {
            "apiVersion": "apps/v1",
            "kind": "ReplicaSetList",
            "items": [current_replicaset],
        },
        {
            "apiVersion": "v1",
            "kind": "PodList",
            "items": [dashboard_pod, retained_collector_pod],
        },
    )


def _run_runtime(
    tmp_path: Path,
    payloads: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
) -> subprocess.CompletedProcess[str]:
    deployments_path = tmp_path / "deployments.json"
    replicasets_path = tmp_path / "replicasets.json"
    pods_path = tmp_path / "pods.json"
    _write_json(deployments_path, payloads[0])
    _write_json(replicasets_path, payloads[1])
    _write_json(pods_path, payloads[2])
    return _run(
        "verify-runtime-image",
        "",
        "--deployments",
        str(deployments_path),
        "--replicasets",
        str(replicasets_path),
        "--pods",
        str(pods_path),
        "--release-name",
        "a-stock",
        "--namespace",
        "a-stock",
        "--image",
        IMAGE,
        "--digest",
        DIGEST,
    )


def _promotion_environment() -> list[dict[str, Any]]:
    disabled = (
        "MARKET_ENVIRONMENT_SCRAPLING_ENABLED",
        "MARKET_ENVIRONMENT_FUYAO_CORE_ENABLED",
        "MARKET_ENVIRONMENT_FUYAO_CORE_SHADOW_ENABLED",
        "MARKET_ENVIRONMENT_FUYAO_BREADTH_ENABLED",
        "MARKET_ENVIRONMENT_FUYAO_BREADTH_SHADOW_ENABLED",
        "MARKET_ENVIRONMENT_FUYAO_SECTORS_SHADOW_ENABLED",
        "MARKET_ENVIRONMENT_FUYAO_ACTIVE_DIRECTION_ENABLED",
        "MARKET_ENVIRONMENT_FUYAO_ACTIVE_DIRECTION_SHADOW_ENABLED",
        "MARKET_ENVIRONMENT_EASTMONEY_SECTOR_ENRICHMENT_ENABLED",
    )
    return [
        {"name": "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED", "value": "0"},
        {
            "name": "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION",
            "value": "fuyao-market-v2",
        },
        *({"name": name, "value": "0"} for name in disabled),
        {
            "name": "MARKET_ENVIRONMENT_DATABASE_URL",
            "valueFrom": {
                "secretKeyRef": {"name": "a-stock-postgresql", "key": "database-url"}
            },
        },
        {
            "name": "MARKET_ENVIRONMENT_FUYAO_API_KEY",
            "valueFrom": {
                "secretKeyRef": {"name": "a-stock-market-provider", "key": "fuyao-api-key"}
            },
        },
        {"name": "EMPTY_OPTIONAL", "value": ""},
        {"name": "NONEMPTY_OPTIONAL", "value": "configured"},
    ]


def _promotion_environment_item(
    environment: list[dict[str, Any]], name: str
) -> dict[str, Any]:
    return next(item for item in environment if item.get("name") == name)


def _run_promotion_pod_selection(
    tmp_path: Path,
    *,
    desired_environment: list[dict[str, Any]],
    live_environment: list[dict[str, Any]],
) -> subprocess.CompletedProcess[str]:
    deployments, replicasets, pods = _runtime_payloads()
    pods["items"][0]["spec"]["containers"][0]["env"] = live_environment
    desired = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "a-stock", "namespace": "a-stock", "labels": LABELS},
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": "dashboard",
                            "image": IMAGE,
                            "env": desired_environment,
                        }
                    ]
                }
            }
        },
    }
    deployments_path = tmp_path / "promotion-deployments.json"
    replicasets_path = tmp_path / "promotion-replicasets.json"
    desired_path = tmp_path / "promotion-desired.yaml"
    _write_json(deployments_path, deployments)
    _write_json(replicasets_path, replicasets)
    desired_path.write_text(yaml.safe_dump(desired), encoding="utf-8")
    return _run(
        "select-disabled-promotion-pod",
        json.dumps(pods),
        "--deployments",
        str(deployments_path),
        "--replicasets",
        str(replicasets_path),
        "--desired",
        str(desired_path),
        "--release-name",
        "a-stock",
        "--namespace",
        "a-stock",
        "--image",
        IMAGE,
        "--digest",
        DIGEST,
    )


def test_promotion_pod_accepts_api_server_omitted_empty_env_value(
    tmp_path: Path,
) -> None:
    desired_environment = _promotion_environment()
    live_environment = copy.deepcopy(desired_environment)
    _promotion_environment_item(live_environment, "EMPTY_OPTIONAL").pop("value")

    completed = _run_promotion_pod_selection(
        tmp_path,
        desired_environment=desired_environment,
        live_environment=live_environment,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "a-stock-current-abc"


def _omit_nonempty_promotion_value(environment: list[dict[str, Any]]) -> None:
    _promotion_environment_item(environment, "NONEMPTY_OPTIONAL").pop("value")


def _drift_promotion_secret_reference(environment: list[dict[str, Any]]) -> None:
    provider = _promotion_environment_item(
        environment, "MARKET_ENVIRONMENT_FUYAO_API_KEY"
    )
    provider["valueFrom"]["secretKeyRef"]["key"] = "other-key"


def _add_promotion_environment_variable(environment: list[dict[str, Any]]) -> None:
    environment.append({"name": "UNREVIEWED_EXTRA", "value": "1"})


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(_omit_nonempty_promotion_value, id="nonempty-value"),
        pytest.param(_drift_promotion_secret_reference, id="secret-reference"),
        pytest.param(_add_promotion_environment_variable, id="variable-set"),
    ],
)
def test_promotion_pod_rejects_real_environment_drift(
    tmp_path: Path,
    mutation: Callable[[list[dict[str, Any]]], None],
) -> None:
    desired_environment = _promotion_environment()
    live_environment = copy.deepcopy(desired_environment)
    mutation(live_environment)

    completed = _run_promotion_pod_selection(
        tmp_path,
        desired_environment=desired_environment,
        live_environment=live_environment,
    )

    assert completed.returncode != 0
    assert "environment differs from the reviewed packet" in completed.stderr


def test_runtime_image_accepts_current_dashboard_and_ignores_retained_collector(
    tmp_path: Path,
) -> None:
    completed = _run_runtime(tmp_path, _runtime_payloads())

    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    ("payload_index", "description"),
    [(0, "Deployment"), (1, "ReplicaSet"), (2, "Pod")],
)
@pytest.mark.parametrize("mutation", ["namespace", "deleting"])
def test_runtime_image_rejects_wrong_namespace_or_deleting_runtime_resource(
    tmp_path: Path, payload_index: int, description: str, mutation: str
) -> None:
    payloads = _runtime_payloads()
    resource = payloads[payload_index]["items"][0]
    if mutation == "namespace":
        resource["metadata"]["namespace"] = "wrong"
    else:
        resource["metadata"]["deletionTimestamp"] = "2026-10-09T00:00:00Z"

    completed = _run_runtime(tmp_path, payloads)

    assert completed.returncode != 0
    assert description in completed.stderr


def test_runtime_image_accepts_ready_release_postgresql_pod(tmp_path: Path) -> None:
    payloads = _runtime_payloads()
    payloads[2]["items"].append(
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": "a-stock-postgresql-0",
                "uid": "postgresql-pod",
                "labels": {**LABELS, "app.kubernetes.io/component": "postgresql"},
                "ownerReferences": [
                    {
                        "apiVersion": "apps/v1",
                        "kind": "StatefulSet",
                        "name": "a-stock-postgresql",
                        "uid": "postgresql-statefulset",
                        "controller": True,
                    }
                ],
            },
            "spec": {"containers": [{"name": "postgresql", "image": "postgres:16.4"}]},
            "status": {
                "phase": "Running",
                "containerStatuses": [{"name": "postgresql", "ready": True}],
            },
        }
    )

    completed = _run_runtime(tmp_path, payloads)

    assert completed.returncode == 0, completed.stderr


def test_runtime_image_rejects_two_dashboard_pods(tmp_path: Path) -> None:
    payloads = _runtime_payloads()
    duplicate = copy.deepcopy(payloads[2]["items"][0])
    duplicate["metadata"]["name"] = "a-stock-current-def"
    duplicate["metadata"]["uid"] = "pod-second"
    payloads[2]["items"].append(duplicate)

    completed = _run_runtime(tmp_path, payloads)

    assert completed.returncode != 0
    assert "exactly one" in completed.stderr


def test_runtime_image_rejects_pod_from_old_replicaset(tmp_path: Path) -> None:
    payloads = _runtime_payloads()
    old_replicaset = copy.deepcopy(payloads[1]["items"][0])
    old_replicaset["metadata"]["name"] = "a-stock-old"
    old_replicaset["metadata"]["uid"] = "replicaset-old"
    old_replicaset["metadata"]["annotations"]["deployment.kubernetes.io/revision"] = "1"
    payloads[1]["items"].append(old_replicaset)
    pod_owner = payloads[2]["items"][0]["metadata"]["ownerReferences"][0]
    pod_owner["name"] = "a-stock-old"
    pod_owner["uid"] = "replicaset-old"

    completed = _run_runtime(tmp_path, payloads)

    assert completed.returncode != 0
    assert "controlled by ReplicaSet a-stock-current" in completed.stderr


def test_runtime_image_accepts_distinct_valid_config_digest(tmp_path: Path) -> None:
    payloads = _runtime_payloads()
    payloads[2]["items"][0]["status"]["containerStatuses"][0]["imageID"] = (
        "containerd://sha256:" + "b" * 64
    )

    completed = _run_runtime(tmp_path, payloads)

    assert completed.returncode == 0, completed.stderr


def test_runtime_image_accepts_cri_alias_for_same_image_repository(tmp_path: Path) -> None:
    payloads = _runtime_payloads()
    payloads[2]["items"][0]["status"]["containerStatuses"][0]["image"] = (
        "localhost/a-stock-market-environment:previous-tag"
    )

    completed = _run_runtime(tmp_path, payloads)

    assert completed.returncode == 0, completed.stderr


def test_runtime_image_accepts_bare_sha256_image_id(tmp_path: Path) -> None:
    payloads = _runtime_payloads()
    payloads[2]["items"][0]["status"]["containerStatuses"][0]["imageID"] = (
        "sha256:" + "b" * 64
    )

    completed = _run_runtime(tmp_path, payloads)

    assert completed.returncode == 0, completed.stderr


def test_runtime_image_rejects_invalid_image_id_digest(tmp_path: Path) -> None:
    payloads = _runtime_payloads()
    payloads[2]["items"][0]["status"]["containerStatuses"][0]["imageID"] = (
        f"containerd://{DIGEST}0"
    )

    completed = _run_runtime(tmp_path, payloads)

    assert completed.returncode != 0
    assert "invalid digest" in completed.stderr


def _desired_resources() -> list[dict[str, Any]]:
    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": "a-stock", "labels": LABELS},
        "spec": {
            "type": "NodePort",
            "selector": LABELS,
            "ports": [
                {
                    "name": "http",
                    "port": 80,
                    "targetPort": "http",
                    "protocol": "TCP",
                    "nodePort": 32001,
                }
            ],
        },
    }
    pod_spec = {
        "automountServiceAccountToken": False,
        "terminationGracePeriodSeconds": 30,
        "securityContext": {"runAsNonRoot": True, "runAsUser": 10001},
        "containers": [
            {
                "name": "dashboard",
                "image": IMAGE,
                "imagePullPolicy": "IfNotPresent",
                "securityContext": {
                    "allowPrivilegeEscalation": False,
                    "readOnlyRootFilesystem": True,
                },
                "volumeMounts": [{"name": "data", "mountPath": "/data"}],
            }
        ],
        "volumes": [
            {"name": "data", "persistentVolumeClaim": {"claimName": "a-stock-data"}},
            {"name": "tmp", "emptyDir": {}},
        ],
    }
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "a-stock", "labels": LABELS},
        "spec": {
            "replicas": 1,
            "strategy": {"type": "Recreate"},
            "selector": {"matchLabels": LABELS},
            "template": {"metadata": {"labels": LABELS}, "spec": pod_spec},
        },
    }
    return [service, deployment]


def _live_resources(desired: list[dict[str, Any]]) -> list[dict[str, Any]]:
    live = copy.deepcopy(desired)
    for item in live:
        item["metadata"]["namespace"] = "a-stock"
        item["metadata"].update(
            {
                "creationTimestamp": "2026-09-08T10:00:00Z",
                "generation": 3,
                "managedFields": [{"manager": "helm"}],
                "resourceVersion": "1234",
                "uid": f"{item['kind'].lower()}-uid",
            }
        )
        item["metadata"]["annotations"] = {
            "meta.helm.sh/release-name": "a-stock",
            "meta.helm.sh/release-namespace": "a-stock",
        }
        item["status"] = {"observed": True}

    service, deployment = live
    service["spec"].update(
        {
            "clusterIP": "10.43.0.10",
            "clusterIPs": ["10.43.0.10"],
            "externalTrafficPolicy": "Cluster",
            "internalTrafficPolicy": "Cluster",
            "ipFamilies": ["IPv4"],
            "ipFamilyPolicy": "SingleStack",
            "sessionAffinity": "None",
        }
    )
    deployment["metadata"]["annotations"]["deployment.kubernetes.io/revision"] = "2"
    deployment["spec"]["progressDeadlineSeconds"] = 600
    deployment_template = deployment["spec"]["template"]
    deployment_template["metadata"]["creationTimestamp"] = None
    deployment_template["spec"].update(
        {
            "dnsPolicy": "ClusterFirst",
            "enableServiceLinks": True,
            "restartPolicy": "Always",
            "schedulerName": "default-scheduler",
        }
    )
    deployment_template["spec"]["containers"][0].update(
        {"terminationMessagePath": "/dev/termination-log", "terminationMessagePolicy": "File"}
    )

    return live


def _run_live_compare(
    tmp_path: Path, desired: list[dict[str, Any]], live: list[dict[str, Any]]
) -> subprocess.CompletedProcess[str]:
    desired_path = tmp_path / "desired.yaml"
    desired_path.write_text(yaml.safe_dump_all(desired, sort_keys=False), encoding="utf-8")
    live_payload = yaml.safe_dump(
        {"apiVersion": "v1", "kind": "List", "items": live}, sort_keys=False
    )
    return _run(
        "compare-live-desired",
        live_payload,
        "--desired",
        str(desired_path),
        "--release-name",
        "a-stock",
        "--namespace",
        "a-stock",
    )


def test_live_compare_ignores_only_server_state_and_known_defaults(tmp_path: Path) -> None:
    desired = _desired_resources()
    completed = _run_live_compare(tmp_path, desired, _live_resources(desired))

    assert completed.returncode == 0, completed.stderr


def test_live_compare_accepts_identical_documents_without_optional_default_keys(
    tmp_path: Path,
) -> None:
    desired = _desired_resources()
    live = copy.deepcopy(desired)
    for item in live:
        item["metadata"]["namespace"] = "a-stock"

    completed = _run_live_compare(tmp_path, desired, live)

    assert completed.returncode == 0, completed.stderr


def test_live_compare_accepts_api_server_omitted_empty_env_values(tmp_path: Path) -> None:
    desired = _desired_resources()
    desired[1]["spec"]["template"]["spec"]["containers"][0]["env"] = [
        {"name": "EMPTY_OPTIONAL", "value": ""},
        {"name": "ENABLED", "value": "1"},
    ]
    live = _live_resources(desired)
    live[1]["spec"]["template"]["spec"]["containers"][0]["env"][0].pop("value")

    completed = _run_live_compare(tmp_path, desired, live)

    assert completed.returncode == 0, completed.stderr


def test_live_compare_rejects_missing_nonempty_env_value(tmp_path: Path) -> None:
    desired = _desired_resources()
    desired[1]["spec"]["template"]["spec"]["containers"][0]["env"] = [
        {"name": "REQUIRED", "value": "1"},
    ]
    live = _live_resources(desired)
    live[1]["spec"]["template"]["spec"]["containers"][0]["env"][0].pop("value")

    completed = _run_live_compare(tmp_path, desired, live)

    assert completed.returncode != 0
    assert "declarative state differs" in completed.stderr


def _drift_image(items: list[dict[str, Any]]) -> None:
    items[1]["spec"]["template"]["spec"]["containers"][0]["image"] = f"{IMAGE}-other"


def _drift_pvc(items: list[dict[str, Any]]) -> None:
    items[1]["spec"]["template"]["spec"]["volumes"][0][
        "persistentVolumeClaim"
    ]["claimName"] = "other-data"


def _drift_security(items: list[dict[str, Any]]) -> None:
    items[1]["spec"]["template"]["spec"]["securityContext"]["runAsNonRoot"] = False


def _drift_service_spec(items: list[dict[str, Any]]) -> None:
    items[0]["spec"]["ports"][0]["nodePort"] = 32002


@pytest.mark.parametrize(
    "mutate",
    [_drift_image, _drift_pvc, _drift_security, _drift_service_spec],
    ids=["image", "pvc", "security", "service-spec"],
)
def test_live_compare_rejects_declarative_drift(
    tmp_path: Path, mutate: Callable[[list[dict[str, Any]]], None]
) -> None:
    desired = _desired_resources()
    live = _live_resources(desired)
    mutate(live)

    completed = _run_live_compare(tmp_path, desired, live)

    assert completed.returncode != 0
    assert "declarative state differs" in completed.stderr


def test_live_compare_rejects_resource_set_change(tmp_path: Path) -> None:
    desired = _desired_resources()
    live = _live_resources(desired)
    extra_service = copy.deepcopy(live[0])
    extra_service["metadata"]["name"] = "a-stock-extra"
    live.append(extra_service)

    completed = _run_live_compare(tmp_path, desired, live)

    assert completed.returncode != 0
    assert "resource set differs" in completed.stderr


def _automation_release(value: str, *, manual: str = "0") -> list[dict[str, Any]]:
    resources = _desired_resources()
    dashboard = resources[1]["spec"]["template"]["spec"]["containers"][0]
    dashboard["env"] = [
        {"name": "MARKET_ENVIRONMENT_AUTOMATION_REFRESH_ENABLED", "value": value},
        {"name": "MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED", "value": manual},
        {"name": "UNCHANGED", "value": "reviewed"},
    ]
    return resources


def _run_automation_compare(
    tmp_path: Path,
    current: list[dict[str, Any]],
    desired: list[dict[str, Any]],
    *,
    from_value: str = "0",
    to_value: str = "1",
) -> subprocess.CompletedProcess[str]:
    current_path = tmp_path / "automation-current.yaml"
    desired_path = tmp_path / "automation-desired.yaml"
    current_path.write_text(yaml.safe_dump_all(current, sort_keys=False), encoding="utf-8")
    desired_path.write_text(yaml.safe_dump_all(desired, sort_keys=False), encoding="utf-8")
    return _run(
        "compare-automation-refresh-only",
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
        IMAGE,
        "--from-value",
        from_value,
        "--to-value",
        to_value,
    )


def test_automation_refresh_compare_accepts_only_zero_to_one(tmp_path: Path) -> None:
    completed = _run_automation_compare(
        tmp_path, _automation_release("0"), _automation_release("1")
    )

    assert completed.returncode == 0, completed.stderr


def test_automation_refresh_compare_accepts_only_one_to_zero(tmp_path: Path) -> None:
    completed = _run_automation_compare(
        tmp_path,
        _automation_release("1"),
        _automation_release("0"),
        from_value="1",
        to_value="0",
    )

    assert completed.returncode == 0, completed.stderr


def test_automation_refresh_compare_rejects_unrelated_drift(tmp_path: Path) -> None:
    current = _automation_release("0")
    desired = _automation_release("1")
    desired[1]["spec"]["template"]["spec"]["containers"][0]["env"][2][
        "value"
    ] = "drifted"

    completed = _run_automation_compare(tmp_path, current, desired)

    assert completed.returncode != 0
    assert "unrelated environment drift" in completed.stderr


def test_automation_refresh_packet_requires_manual_refresh_off() -> None:
    completed = _run(
        "validate-automation-refresh-packet",
        yaml.safe_dump_all(_automation_release("1", manual="1"), sort_keys=False),
        "--release-name",
        "a-stock",
        "--namespace",
        "a-stock",
        "--image",
        IMAGE,
        "--require-value",
        "1",
    )

    assert completed.returncode != 0
    assert "MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED must remain literal 0" in completed.stderr
