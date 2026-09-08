from __future__ import annotations

import copy
import json
import subprocess
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
        ["python3", str(VALIDATOR), command, *arguments],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_version_parser_accepts_prerelease_and_build_metadata() -> None:
    completed = _run("parse-version", '{"gitVersion":"v1.30.0-rc.1+build.7"}')

    assert completed.returncode == 0
    assert completed.stdout.strip() == "1.30.0-rc.1+build.7"


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
        "--image",
        IMAGE,
        "--digest",
        DIGEST,
    )


def test_runtime_image_accepts_current_dashboard_and_ignores_retained_collector(
    tmp_path: Path,
) -> None:
    completed = _run_runtime(tmp_path, _runtime_payloads())

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


def test_runtime_image_rejects_digest_substring_in_image_id(tmp_path: Path) -> None:
    payloads = _runtime_payloads()
    payloads[2]["items"][0]["status"]["containerStatuses"][0]["imageID"] = (
        f"containerd://{DIGEST}0"
    )

    completed = _run_runtime(tmp_path, payloads)

    assert completed.returncode != 0
    assert "digest must equal" in completed.stderr


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
    collector_spec = copy.deepcopy(pod_spec)
    collector_spec["restartPolicy"] = "Never"
    collector_spec["containers"][0]["name"] = "collector"
    cronjob = {
        "apiVersion": "batch/v1",
        "kind": "CronJob",
        "metadata": {"name": "a-stock-data-collection", "namespace": "a-stock", "labels": LABELS},
        "spec": {
            "schedule": "30 8 * * 1-5",
            "suspend": True,
            "concurrencyPolicy": "Forbid",
            "jobTemplate": {
                "spec": {
                    "backoffLimit": 0,
                    "template": {
                        "metadata": {"labels": LABELS},
                        "spec": collector_spec,
                    },
                }
            },
        },
    }
    return [service, deployment, cronjob]


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

    service, deployment, cronjob = live
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

    job_spec = cronjob["spec"]["jobTemplate"]["spec"]
    job_spec.update(
        {
            "completionMode": "NonIndexed",
            "completions": 1,
            "parallelism": 1,
            "suspend": False,
        }
    )
    cron_template = job_spec["template"]
    cron_template["metadata"]["creationTimestamp"] = None
    cron_template["spec"].update(
        {
            "dnsPolicy": "ClusterFirst",
            "enableServiceLinks": True,
            "schedulerName": "default-scheduler",
        }
    )
    cron_template["spec"]["containers"][0].update(
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


def _drift_image(items: list[dict[str, Any]]) -> None:
    items[1]["spec"]["template"]["spec"]["containers"][0]["image"] = f"{IMAGE}-other"


def _drift_pvc(items: list[dict[str, Any]]) -> None:
    items[2]["spec"]["jobTemplate"]["spec"]["template"]["spec"]["volumes"][0][
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
