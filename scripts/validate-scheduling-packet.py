#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml


TRACKED_LIVE_KINDS = {
    "Service": "v1",
    "Deployment": "apps/v1",
    "CronJob": "batch/v1",
}


def fail(message: str) -> None:
    raise SystemExit(message)


def load_documents(stream: Any) -> list[dict[str, Any]]:
    try:
        documents = [item for item in yaml.safe_load_all(stream) if item is not None]
    except yaml.YAMLError as exc:
        fail(f"invalid YAML: {exc}")
    if not all(isinstance(item, dict) for item in documents):
        fail("every rendered document must be a YAML mapping")
    return documents


def load_path(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open(encoding="utf-8") as stream:
            return load_documents(stream)
    except OSError as exc:
        fail(f"could not read {path}: {exc}")


def load_json(stream: Any, description: str) -> dict[str, Any]:
    try:
        payload = json.load(stream)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        fail(f"invalid {description} JSON: {exc}")
    if not isinstance(payload, dict):
        fail(f"{description} JSON must be an object")
    return payload


def load_json_path(path: Path, description: str) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as stream:
            return load_json(stream, description)
    except OSError as exc:
        fail(f"could not read {description} file {path}: {exc}")


def cronjob_for(
    documents: list[dict[str, Any]], release_name: str, namespace: str
) -> dict[str, Any] | None:
    cronjobs = [item for item in documents if item.get("kind") == "CronJob"]
    if len(cronjobs) > 1:
        fail("rendered packet must contain at most one CronJob")
    if not cronjobs:
        return None

    cronjob = cronjobs[0]
    metadata = cronjob.get("metadata")
    if cronjob.get("apiVersion") != "batch/v1" or not isinstance(metadata, dict):
        fail("scheduled resource must be one batch/v1 CronJob")
    if metadata.get("namespace") != namespace:
        fail(f"CronJob namespace must equal {namespace}")
    labels = metadata.get("labels")
    if not isinstance(labels, dict) or labels.get("app.kubernetes.io/instance") != release_name:
        fail(f"CronJob release label must equal {release_name}")
    name = metadata.get("name")
    if not isinstance(name, str) or not name:
        fail("CronJob metadata.name must be a non-empty string")
    return cronjob


def inspect(
    documents: list[dict[str, Any]], release_name: str, namespace: str, required_state: str
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    cronjob = cronjob_for(documents, release_name, namespace)
    if cronjob is None:
        state = "disabled"
        result = {
            "enabled": False,
            "suspend": None,
            "state": state,
            "releaseName": release_name,
            "namespace": namespace,
        }
    else:
        spec = cronjob.get("spec")
        if not isinstance(spec, dict) or type(spec.get("suspend")) is not bool:
            fail("CronJob spec.suspend must be a boolean")
        schedule = spec.get("schedule")
        if not isinstance(schedule, str) or not re.fullmatch(r"\d{1,2} \d{1,2} \* \* 1-5", schedule):
            fail("CronJob spec.schedule must be one numeric weekday trigger")
        time_zone = spec.get("timeZone")
        if time_zone is not None and time_zone != "Asia/Shanghai":
            fail("native CronJob timeZone must equal Asia/Shanghai")
        strategy = "native" if time_zone is not None else "controller"
        controller_timezone = None
        if strategy == "controller":
            if schedule == "30 8 * * 1-5":
                controller_timezone = "Etc/UTC"
            elif schedule == "30 16 * * 1-5":
                controller_timezone = "Asia/Shanghai"
            else:
                fail("controller CronJob schedule is not an approved Shanghai 16:30 mapping")
        state = "suspended" if spec["suspend"] else "active"
        result = {
            "enabled": True,
            "suspend": spec["suspend"],
            "state": state,
            "releaseName": release_name,
            "namespace": namespace,
            "name": cronjob["metadata"]["name"],
            "strategy": strategy,
            "controllerTimeZone": controller_timezone,
            "schedule": schedule,
            "timeZone": time_zone,
        }

    if required_state != "any" and state != required_state:
        fail(f"scheduling packet must be {required_state}, got {state}")
    return cronjob, result


def resource_key(document: dict[str, Any]) -> tuple[str, str, str, str]:
    metadata = document.get("metadata")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("name"), str):
        fail("every release document must have metadata.name")
    return (
        str(document.get("apiVersion", "")),
        str(document.get("kind", "")),
        str(metadata.get("namespace", "")),
        metadata["name"],
    )


def indexed(documents: list[dict[str, Any]]) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    result: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for document in documents:
        key = resource_key(document)
        if key in result:
            fail(f"duplicate rendered resource: {key}")
        result[key] = document
    return result


def compare_add_suspended(
    current: list[dict[str, Any]], desired: list[dict[str, Any]], release_name: str, namespace: str
) -> None:
    if any(item.get("kind") == "CronJob" for item in current):
        fail("suspended release requires the application CronJob to be absent")
    cronjob, _ = inspect(desired, release_name, namespace, "suspended")
    assert cronjob is not None
    desired_without_cronjob = [item for item in desired if item is not cronjob]
    if indexed(current) != indexed(desired_without_cronjob):
        fail("suspended release contains drift outside the new CronJob")


def compare_suspend_only(
    current: list[dict[str, Any]], desired: list[dict[str, Any]], release_name: str, namespace: str
) -> None:
    current_cronjob, _ = inspect(current, release_name, namespace, "suspended")
    desired_cronjob, _ = inspect(desired, release_name, namespace, "active")
    assert current_cronjob is not None and desired_cronjob is not None
    current_index = indexed(current)
    desired_index = indexed(desired)
    if current_index.keys() != desired_index.keys():
        fail("Gate C resource set differs from the suspended release")

    for key in current_index:
        before = copy.deepcopy(current_index[key])
        after = copy.deepcopy(desired_index[key])
        if key[1] == "CronJob":
            before["spec"].pop("suspend", None)
            after["spec"].pop("suspend", None)
        if before != after:
            fail(f"Gate C contains drift outside CronJob spec.suspend: {key}")


def compare_remove_cronjob(
    current: list[dict[str, Any]], desired: list[dict[str, Any]], release_name: str, namespace: str
) -> None:
    current_cronjob, _ = inspect(current, release_name, namespace, "any")
    if current_cronjob is None:
        fail("schedule rollback requires an existing application CronJob")
    inspect(desired, release_name, namespace, "disabled")
    current_without_cronjob = [item for item in current if item is not current_cronjob]
    if indexed(current_without_cronjob) != indexed(desired):
        fail("schedule rollback contains drift outside CronJob removal")


def kubernetes_json_items(
    payload: dict[str, Any], expected_kind: str, description: str
) -> list[dict[str, Any]]:
    kind = payload.get("kind")
    if kind in {"List", f"{expected_kind}List"}:
        raw_items = payload.get("items")
        if not isinstance(raw_items, list) or not all(isinstance(item, dict) for item in raw_items):
            fail(f"{description} response must contain an items list of objects")
        items = raw_items
    elif kind == expected_kind:
        items = [payload]
    else:
        fail(f"{description} response must be a {expected_kind} or {expected_kind}List")

    if any(item.get("kind") != expected_kind for item in items):
        fail(f"{description} response contains a non-{expected_kind} item")
    return items


def release_label(document: dict[str, Any]) -> Any:
    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        return None
    labels = metadata.get("labels")
    if not isinstance(labels, dict):
        return None
    return labels.get("app.kubernetes.io/instance")


def named_entries(
    document: dict[str, Any], path: tuple[str, ...], name: str
) -> list[dict[str, Any]]:
    value: Any = document
    for key in path:
        if not isinstance(value, dict):
            return []
        value = value.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict) and item.get("name") == name]


def metadata_value(document: dict[str, Any], key: str) -> Any:
    metadata = document.get("metadata")
    return metadata.get(key) if isinstance(metadata, dict) else None


def controller_owner(document: dict[str, Any]) -> dict[str, Any] | None:
    metadata = document.get("metadata")
    references = metadata.get("ownerReferences") if isinstance(metadata, dict) else None
    if not isinstance(references, list) or not all(isinstance(item, dict) for item in references):
        return None
    controllers = [item for item in references if item.get("controller") is True]
    return controllers[0] if len(controllers) == 1 else None


def verify_controller_owner(
    document: dict[str, Any], kind: str, name: str, uid: str, description: str
) -> None:
    owner = controller_owner(document)
    if (
        owner is None
        or owner.get("kind") != kind
        or owner.get("name") != name
        or owner.get("uid") != uid
    ):
        fail(f"{description} must be controlled by {kind} {name} with uid {uid}")


def image_id_digest(image_id: Any) -> str:
    if not isinstance(image_id, str) or not image_id:
        fail("running Dashboard imageID must be a non-empty string")
    if "@" in image_id:
        prefix, digest = image_id.rsplit("@", 1)
        if not prefix:
            fail("running Dashboard imageID has an invalid image reference")
    elif "://" in image_id:
        scheme, digest = image_id.split("://", 1)
        if not scheme or not re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*", scheme):
            fail("running Dashboard imageID has an invalid scheme")
    else:
        fail("running Dashboard imageID must contain an explicit digest reference")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*(?:[+._-][A-Za-z0-9]+)*:[A-Za-z0-9=_-]+", digest):
        fail("running Dashboard imageID contains an invalid digest")
    return digest


def verify_containerd_image(payload: dict[str, Any], image: str, digest: str) -> None:
    if payload.get("Name") != image:
        fail(f"containerd image Name must equal {image}")
    target = payload.get("Target")
    if not isinstance(target, dict) or target.get("digest") != digest:
        fail(f"containerd image Target.digest must equal {digest}")


def verify_runtime_image(
    deployments_payload: dict[str, Any],
    replicasets_payload: dict[str, Any],
    pods_payload: dict[str, Any],
    release_name: str,
    image: str,
    digest: str,
) -> None:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        fail("frozen image digest must be sha256 followed by 64 lowercase hex characters")

    deployments = kubernetes_json_items(deployments_payload, "Deployment", "Deployment")
    matching_deployments = [
        item for item in deployments if release_label(item) == release_name
    ]
    if len(matching_deployments) != 1:
        fail("expected exactly one release Dashboard Deployment")
    deployment = matching_deployments[0]
    deployment_name = metadata_value(deployment, "name")
    deployment_uid = metadata_value(deployment, "uid")
    annotations = metadata_value(deployment, "annotations")
    deployment_revision = (
        annotations.get("deployment.kubernetes.io/revision")
        if isinstance(annotations, dict)
        else None
    )
    if not isinstance(deployment_name, str) or not deployment_name:
        fail("release Dashboard Deployment metadata.name is missing")
    if not isinstance(deployment_uid, str) or not deployment_uid:
        fail("release Dashboard Deployment metadata.uid is missing")
    if not isinstance(deployment_revision, str) or not re.fullmatch(
        r"[1-9][0-9]*", deployment_revision
    ):
        fail("release Dashboard Deployment revision is missing or invalid")

    deployment_containers = named_entries(
        deployment, ("spec", "template", "spec", "containers"), "dashboard"
    )
    if len(deployment_containers) != 1 or deployment_containers[0].get("image") != image:
        fail(f"Dashboard Deployment must use frozen image {image}")

    replicasets = kubernetes_json_items(replicasets_payload, "ReplicaSet", "ReplicaSet")
    owned_replicasets: list[dict[str, Any]] = []
    for replicaset in replicasets:
        if release_label(replicaset) != release_name:
            continue
        owner = controller_owner(replicaset)
        if (
            owner is not None
            and owner.get("kind") == "Deployment"
            and owner.get("name") == deployment_name
            and owner.get("uid") == deployment_uid
        ):
            owned_replicasets.append(replicaset)

    current_replicasets = []
    for replicaset in owned_replicasets:
        rs_annotations = metadata_value(replicaset, "annotations")
        if (
            isinstance(rs_annotations, dict)
            and rs_annotations.get("deployment.kubernetes.io/revision") == deployment_revision
        ):
            current_replicasets.append(replicaset)
    if len(current_replicasets) != 1:
        fail("expected exactly one current ReplicaSet for the release Dashboard Deployment")
    current_replicaset = current_replicasets[0]
    replicaset_name = metadata_value(current_replicaset, "name")
    replicaset_uid = metadata_value(current_replicaset, "uid")
    if not isinstance(replicaset_name, str) or not replicaset_name:
        fail("current Dashboard ReplicaSet metadata.name is missing")
    if not isinstance(replicaset_uid, str) or not replicaset_uid:
        fail("current Dashboard ReplicaSet metadata.uid is missing")
    replicaset_containers = named_entries(
        current_replicaset, ("spec", "template", "spec", "containers"), "dashboard"
    )
    if len(replicaset_containers) != 1 or replicaset_containers[0].get("image") != image:
        fail(f"current Dashboard ReplicaSet must use frozen image {image}")

    pods = kubernetes_json_items(pods_payload, "Pod", "Pod")
    dashboard_pods: list[dict[str, Any]] = []
    for pod in pods:
        if release_label(pod) != release_name:
            continue
        dashboard_specs = named_entries(pod, ("spec", "containers"), "dashboard")
        dashboard_statuses = named_entries(pod, ("status", "containerStatuses"), "dashboard")
        if dashboard_specs or dashboard_statuses:
            dashboard_pods.append(pod)
            continue

        collector_specs = named_entries(pod, ("spec", "containers"), "collector")
        owner = controller_owner(pod)
        if (
            len(collector_specs) != 1
            or owner is None
            or owner.get("kind") != "Job"
            or not isinstance(owner.get("name"), str)
            or not isinstance(owner.get("uid"), str)
        ):
            fail("unexpected non-Dashboard release Pod is not a retained collector Job Pod")

    if len(dashboard_pods) != 1:
        fail("expected exactly one release Dashboard Pod")
    pod = dashboard_pods[0]
    verify_controller_owner(pod, "ReplicaSet", replicaset_name, replicaset_uid, "Dashboard Pod")

    dashboard_specs = named_entries(pod, ("spec", "containers"), "dashboard")
    if len(dashboard_specs) != 1 or dashboard_specs[0].get("image") != image:
        fail(f"Dashboard Pod spec must use frozen image {image}")
    status = pod.get("status")
    if not isinstance(status, dict) or status.get("phase") != "Running":
        fail("Dashboard Pod must be Running")
    conditions = status.get("conditions")
    ready_conditions = (
        [item for item in conditions if isinstance(item, dict) and item.get("type") == "Ready"]
        if isinstance(conditions, list)
        else []
    )
    if len(ready_conditions) != 1 or ready_conditions[0].get("status") != "True":
        fail("Dashboard Pod must have Ready=True")
    dashboard_statuses = named_entries(pod, ("status", "containerStatuses"), "dashboard")
    if len(dashboard_statuses) != 1 or dashboard_statuses[0].get("ready") is not True:
        fail("Dashboard container must be ready")
    if dashboard_statuses[0].get("image") != image:
        fail(f"running Dashboard Pod must use frozen image {image}")
    actual_digest = image_id_digest(dashboard_statuses[0].get("imageID"))
    if actual_digest != digest:
        fail(f"running Dashboard imageID digest must equal {digest}")


def verify_deployment_image(payload: dict[str, Any], release_name: str, image: str) -> None:
    items = payload.get("items")
    if not isinstance(items, list):
        fail("Deployment response must contain an items list")
    matching = [
        item
        for item in items
        if item.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/instance")
        == release_name
    ]
    if len(matching) != 1:
        fail("expected exactly one release Dashboard Deployment")
    containers = matching[0].get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    dashboards = [item for item in containers if item.get("name") == "dashboard"]
    if len(dashboards) != 1 or dashboards[0].get("image") != image:
        fail(f"Dashboard Deployment must use frozen image {image}")


def verify_pod_image(payload: dict[str, Any], release_name: str, image: str, digest: str) -> None:
    items = payload.get("items")
    if not isinstance(items, list):
        fail("Pod response must contain an items list")
    matching = [
        item
        for item in items
        if item.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/instance")
        == release_name
    ]
    if len(matching) != 1:
        fail("expected exactly one release Dashboard Pod")
    statuses = matching[0].get("status", {}).get("containerStatuses", [])
    dashboards = [item for item in statuses if item.get("name") == "dashboard"]
    if len(dashboards) != 1:
        fail("running Dashboard container status is missing")
    if dashboards[0].get("image") != image:
        fail(f"running Dashboard Pod must use frozen image {image}")
    if image_id_digest(dashboards[0].get("imageID")) != digest:
        fail(f"running Dashboard imageID digest must equal {digest}")


def kubectl_list_documents(stream: Any) -> list[dict[str, Any]]:
    documents = load_documents(stream)
    if len(documents) != 1 or documents[0].get("kind") != "List":
        fail("live input must be one kubectl kind: List document")
    items = documents[0].get("items")
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        fail("live kubectl List must contain an items list of objects")
    return items


def _metadata(document: dict[str, Any], description: str) -> dict[str, Any]:
    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        fail(f"{description} metadata must be an object")
    return metadata


def _tracked_release_resources(
    documents: list[dict[str, Any]], release_name: str, namespace: str, source: str
) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    resources: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for document in documents:
        kind = document.get("kind")
        if kind not in TRACKED_LIVE_KINDS:
            continue
        metadata = _metadata(document, f"{source} {kind}")
        labels = metadata.get("labels")
        if not isinstance(labels, dict) or labels.get("app.kubernetes.io/instance") != release_name:
            fail(f"{source} {kind} must carry release label {release_name}")
        resource_namespace = metadata.get("namespace")
        if source == "desired" and resource_namespace is None:
            resource_namespace = namespace
        if resource_namespace != namespace:
            fail(f"{source} {kind} namespace must equal {namespace}")
        name = metadata.get("name")
        if not isinstance(name, str) or not name:
            fail(f"{source} {kind} metadata.name must be a non-empty string")
        expected_api_version = TRACKED_LIVE_KINDS[kind]
        if document.get("apiVersion") != expected_api_version:
            fail(f"{source} {kind} apiVersion must equal {expected_api_version}")
        key = (expected_api_version, kind, namespace, name)
        if key in resources:
            fail(f"duplicate {source} release resource: {key}")
        resources[key] = document
    return resources


def _drop_default(live: dict[str, Any], desired: dict[str, Any], key: str, value: Any) -> None:
    if key in live and key not in desired and live[key] == value:
        live.pop(key)


def _drop_allocated(live: dict[str, Any], desired: dict[str, Any], key: str) -> None:
    if key not in desired:
        live.pop(key, None)


def _matching_named_item(items: Any, name: Any) -> dict[str, Any]:
    if not isinstance(items, list) or not isinstance(name, str):
        return {}
    matches = [item for item in items if isinstance(item, dict) and item.get("name") == name]
    return matches[0] if len(matches) == 1 else {}


def _normalize_probe(live: dict[str, Any], desired: dict[str, Any]) -> None:
    for key, value in (
        ("initialDelaySeconds", 0),
        ("timeoutSeconds", 1),
        ("periodSeconds", 10),
        ("successThreshold", 1),
        ("failureThreshold", 3),
    ):
        _drop_default(live, desired, key, value)
    live_http = live.get("httpGet")
    desired_http = desired.get("httpGet")
    if isinstance(live_http, dict):
        _drop_default(
            live_http,
            desired_http if isinstance(desired_http, dict) else {},
            "scheme",
            "HTTP",
        )


def _default_pull_policy(image: Any) -> str | None:
    if not isinstance(image, str) or not image:
        return None
    last_component = image.rsplit("/", 1)[-1]
    if ":" not in last_component or last_component.endswith(":latest"):
        return "Always"
    return "IfNotPresent"


def _normalize_container(live: dict[str, Any], desired: dict[str, Any]) -> None:
    _drop_default(live, desired, "terminationMessagePath", "/dev/termination-log")
    _drop_default(live, desired, "terminationMessagePolicy", "File")
    pull_policy = _default_pull_policy(desired.get("image"))
    if pull_policy is not None:
        _drop_default(live, desired, "imagePullPolicy", pull_policy)
    for probe_name in ("startupProbe", "readinessProbe", "livenessProbe"):
        live_probe = live.get(probe_name)
        desired_probe = desired.get(probe_name)
        if isinstance(live_probe, dict) and isinstance(desired_probe, dict):
            _normalize_probe(live_probe, desired_probe)
    live_ports = live.get("ports")
    desired_ports = desired.get("ports")
    if isinstance(live_ports, list):
        for port in live_ports:
            if not isinstance(port, dict):
                continue
            desired_port = _matching_named_item(desired_ports, port.get("name"))
            _drop_default(port, desired_port, "protocol", "TCP")
            _drop_default(port, desired_port, "hostPort", 0)


def _normalize_pod_spec(live: dict[str, Any], desired: dict[str, Any]) -> None:
    for key, value in (
        ("dnsPolicy", "ClusterFirst"),
        ("enableServiceLinks", True),
        ("restartPolicy", "Always"),
        ("schedulerName", "default-scheduler"),
        ("terminationGracePeriodSeconds", 30),
        ("serviceAccount", "default"),
        ("serviceAccountName", "default"),
    ):
        _drop_default(live, desired, key, value)
    for collection_name in ("containers", "initContainers"):
        live_containers = live.get(collection_name)
        desired_containers = desired.get(collection_name)
        if not isinstance(live_containers, list):
            continue
        for container in live_containers:
            if not isinstance(container, dict):
                continue
            desired_container = _matching_named_item(desired_containers, container.get("name"))
            _normalize_container(container, desired_container)
    live_volumes = live.get("volumes")
    desired_volumes = desired.get("volumes")
    if isinstance(live_volumes, list):
        for volume in live_volumes:
            if not isinstance(volume, dict):
                continue
            desired_volume = _matching_named_item(desired_volumes, volume.get("name"))
            live_pvc = volume.get("persistentVolumeClaim")
            desired_pvc = desired_volume.get("persistentVolumeClaim")
            if isinstance(live_pvc, dict):
                _drop_default(
                    live_pvc,
                    desired_pvc if isinstance(desired_pvc, dict) else {},
                    "readOnly",
                    False,
                )
            for source_name in ("configMap", "secret", "projected"):
                live_source = volume.get(source_name)
                desired_source = desired_volume.get(source_name)
                if isinstance(live_source, dict):
                    _drop_default(
                        live_source,
                        desired_source if isinstance(desired_source, dict) else {},
                        "defaultMode",
                        420,
                    )


def _normalize_pod_template(live: dict[str, Any], desired: dict[str, Any]) -> None:
    live_metadata = live.get("metadata")
    desired_metadata = desired.get("metadata")
    if isinstance(live_metadata, dict):
        _drop_default(
            live_metadata,
            desired_metadata if isinstance(desired_metadata, dict) else {},
            "creationTimestamp",
            None,
        )
    live_spec = live.get("spec")
    desired_spec = desired.get("spec")
    if isinstance(live_spec, dict):
        _normalize_pod_spec(live_spec, desired_spec if isinstance(desired_spec, dict) else {})


def _normalize_service(live: dict[str, Any], desired: dict[str, Any]) -> None:
    live_spec = live.get("spec")
    desired_spec = desired.get("spec")
    if not isinstance(live_spec, dict):
        return
    if not isinstance(desired_spec, dict):
        desired_spec = {}
    for key in ("clusterIP", "clusterIPs", "healthCheckNodePort", "ipFamilies"):
        _drop_allocated(live_spec, desired_spec, key)
    for key, value in (
        ("allocateLoadBalancerNodePorts", True),
        ("externalTrafficPolicy", "Cluster"),
        ("internalTrafficPolicy", "Cluster"),
        ("ipFamilyPolicy", "SingleStack"),
        ("publishNotReadyAddresses", False),
        ("sessionAffinity", "None"),
        ("type", "ClusterIP"),
    ):
        _drop_default(live_spec, desired_spec, key, value)
    live_ports = live_spec.get("ports")
    desired_ports = desired_spec.get("ports")
    if isinstance(live_ports, list):
        for port in live_ports:
            if not isinstance(port, dict):
                continue
            desired_port = _matching_named_item(desired_ports, port.get("name"))
            _drop_default(port, desired_port, "protocol", "TCP")
            _drop_allocated(port, desired_port, "nodePort")


def _normalize_deployment(live: dict[str, Any], desired: dict[str, Any]) -> None:
    live_spec = live.get("spec")
    desired_spec = desired.get("spec")
    if not isinstance(live_spec, dict):
        return
    if not isinstance(desired_spec, dict):
        desired_spec = {}
    for key, value in (
        ("minReadySeconds", 0),
        ("paused", False),
        ("progressDeadlineSeconds", 600),
        ("replicas", 1),
        ("revisionHistoryLimit", 10),
    ):
        _drop_default(live_spec, desired_spec, key, value)
    live_strategy = live_spec.get("strategy")
    desired_strategy = desired_spec.get("strategy")
    if isinstance(live_strategy, dict):
        desired_strategy = desired_strategy if isinstance(desired_strategy, dict) else {}
        _drop_default(live_strategy, desired_strategy, "type", "RollingUpdate")
        live_rolling = live_strategy.get("rollingUpdate")
        desired_rolling = desired_strategy.get("rollingUpdate")
        if isinstance(live_rolling, dict):
            desired_rolling = desired_rolling if isinstance(desired_rolling, dict) else {}
            _drop_default(live_rolling, desired_rolling, "maxSurge", "25%")
            _drop_default(live_rolling, desired_rolling, "maxUnavailable", "25%")
    live_template = live_spec.get("template")
    desired_template = desired_spec.get("template")
    if isinstance(live_template, dict):
        _normalize_pod_template(
            live_template, desired_template if isinstance(desired_template, dict) else {}
        )


def _normalize_cronjob(live: dict[str, Any], desired: dict[str, Any]) -> None:
    live_spec = live.get("spec")
    desired_spec = desired.get("spec")
    if not isinstance(live_spec, dict):
        return
    if not isinstance(desired_spec, dict):
        desired_spec = {}
    for key, value in (
        ("concurrencyPolicy", "Allow"),
        ("failedJobsHistoryLimit", 1),
        ("successfulJobsHistoryLimit", 3),
        ("suspend", False),
    ):
        _drop_default(live_spec, desired_spec, key, value)
    live_job_template = live_spec.get("jobTemplate")
    desired_job_template = desired_spec.get("jobTemplate")
    if not isinstance(live_job_template, dict):
        return
    if not isinstance(desired_job_template, dict):
        desired_job_template = {}
    live_job_metadata = live_job_template.get("metadata")
    desired_job_metadata = desired_job_template.get("metadata")
    if isinstance(live_job_metadata, dict):
        _drop_default(
            live_job_metadata,
            desired_job_metadata if isinstance(desired_job_metadata, dict) else {},
            "creationTimestamp",
            None,
        )
    live_job_spec = live_job_template.get("spec")
    desired_job_spec = desired_job_template.get("spec")
    if not isinstance(live_job_spec, dict):
        return
    if not isinstance(desired_job_spec, dict):
        desired_job_spec = {}
    for key, value in (
        ("backoffLimit", 6),
        ("completionMode", "NonIndexed"),
        ("completions", 1),
        ("manualSelector", False),
        ("parallelism", 1),
        ("suspend", False),
    ):
        _drop_default(live_job_spec, desired_job_spec, key, value)
    live_template = live_job_spec.get("template")
    desired_template = desired_job_spec.get("template")
    if isinstance(live_template, dict):
        _normalize_pod_template(
            live_template, desired_template if isinstance(desired_template, dict) else {}
        )


def _prune_omitted_empty(live: Any, desired: Any) -> None:
    if isinstance(live, dict):
        desired_mapping = desired if isinstance(desired, dict) else {}
        for key in list(live):
            if key not in desired_mapping and live[key] in (None, {}, []):
                live.pop(key)
            elif key in desired_mapping:
                _prune_omitted_empty(live[key], desired_mapping[key])
    elif isinstance(live, list) and isinstance(desired, list):
        for index, value in enumerate(live[: len(desired)]):
            _prune_omitted_empty(value, desired[index])


def _normalize_live_desired_pair(
    live: dict[str, Any],
    desired: dict[str, Any],
    release_name: str,
    namespace: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized_live = copy.deepcopy(live)
    normalized_desired = copy.deepcopy(desired)
    for document, source in ((normalized_live, "live"), (normalized_desired, "desired")):
        document.pop("status", None)
        metadata = _metadata(document, f"{source} resource")
        metadata["namespace"] = metadata.get("namespace") or namespace
        for key in (
            "creationTimestamp",
            "deletionGracePeriodSeconds",
            "deletionTimestamp",
            "generation",
            "managedFields",
            "resourceVersion",
            "selfLink",
            "uid",
        ):
            metadata.pop(key, None)
        annotations = metadata.get("annotations")
        if isinstance(annotations, dict):
            helm_values = {
                "meta.helm.sh/release-name": release_name,
                "meta.helm.sh/release-namespace": namespace,
            }
            for key, expected in helm_values.items():
                if key in annotations:
                    if annotations[key] != expected:
                        fail(f"{source} resource has invalid Helm ownership annotation {key}")
                    annotations.pop(key)
            if (
                source == "live"
                and "kubectl.kubernetes.io/last-applied-configuration" in annotations
            ):
                annotations.pop("kubectl.kubernetes.io/last-applied-configuration")
            if source == "live" and document.get("kind") == "Deployment":
                revision = annotations.get("deployment.kubernetes.io/revision")
                if revision is not None:
                    if not isinstance(revision, str) or not re.fullmatch(r"[1-9][0-9]*", revision):
                        fail("live Deployment revision annotation is invalid")
                    annotations.pop("deployment.kubernetes.io/revision")

    kind = normalized_live.get("kind")
    if kind == "Service":
        _normalize_service(normalized_live, normalized_desired)
    elif kind == "Deployment":
        _normalize_deployment(normalized_live, normalized_desired)
    elif kind == "CronJob":
        _normalize_cronjob(normalized_live, normalized_desired)
    _prune_omitted_empty(normalized_live, normalized_desired)
    _prune_omitted_empty(normalized_desired, normalized_live)
    return normalized_live, normalized_desired


def compare_live_desired(
    live: list[dict[str, Any]],
    desired: list[dict[str, Any]],
    release_name: str,
    namespace: str,
) -> None:
    live_resources = _tracked_release_resources(live, release_name, namespace, "live")
    desired_resources = _tracked_release_resources(desired, release_name, namespace, "desired")
    if live_resources.keys() != desired_resources.keys():
        fail("live Service/Deployment/CronJob resource set differs from desired")
    for key in live_resources:
        normalized_live, normalized_desired = _normalize_live_desired_pair(
            live_resources[key], desired_resources[key], release_name, namespace
        )
        if normalized_live != normalized_desired:
            fail(f"live declarative state differs from desired for {key}")


def parse_server_version(payload: Any) -> str:
    if not isinstance(payload, dict):
        fail("Kubernetes /version response must be an object")
    value = payload.get("gitVersion")
    if not isinstance(value, str) or not re.fullmatch(
        r"v?\d+\.\d+\.\d+(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
        r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?",
        value,
    ):
        fail("Kubernetes /version gitVersion is missing or invalid")
    return value.removeprefix("v")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("parse-version")

    for name in ("inspect", "extract-suspended"):
        child = subparsers.add_parser(name)
        child.add_argument("--release-name", required=True)
        child.add_argument("--namespace", required=True)
        child.add_argument(
            "--require-state", choices=("any", "disabled", "suspended", "active"), default="any"
        )

    for name in ("compare-add-suspended", "compare-suspend-only", "compare-remove-cronjob"):
        child = subparsers.add_parser(name)
        child.add_argument("--release-name", required=True)
        child.add_argument("--namespace", required=True)
        child.add_argument("--current", type=Path, required=True)
        child.add_argument("--desired", type=Path, required=True)

    for name in ("verify-deployment-image", "verify-pod-image"):
        child = subparsers.add_parser(name)
        child.add_argument("--release-name", required=True)
        child.add_argument("--image", required=True)
        if name == "verify-pod-image":
            child.add_argument("--digest", required=True)

    containerd = subparsers.add_parser("verify-containerd-image")
    containerd.add_argument("--image", required=True)
    containerd.add_argument("--digest", required=True)

    runtime = subparsers.add_parser("verify-runtime-image")
    runtime.add_argument("--deployments", type=Path, required=True)
    runtime.add_argument("--replicasets", type=Path, required=True)
    runtime.add_argument("--pods", type=Path, required=True)
    runtime.add_argument("--release-name", required=True)
    runtime.add_argument("--image", required=True)
    runtime.add_argument("--digest", required=True)

    live_desired = subparsers.add_parser("compare-live-desired")
    live_desired.add_argument("--desired", type=Path, required=True)
    live_desired.add_argument("--release-name", required=True)
    live_desired.add_argument("--namespace", required=True)

    args = parser.parse_args()
    if args.command == "parse-version":
        try:
            payload = json.load(sys.stdin)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            fail(f"invalid Kubernetes /version JSON: {exc}")
        print(parse_server_version(payload))
    elif args.command in {"inspect", "extract-suspended"}:
        documents = load_documents(sys.stdin)
        cronjob, result = inspect(
            documents, args.release_name, args.namespace, args.require_state
        )
        if args.command == "inspect":
            json.dump(result, sys.stdout, sort_keys=True, separators=(",", ":"))
            sys.stdout.write("\n")
        else:
            if cronjob is None:
                fail("suspended CronJob is missing")
            yaml.safe_dump(cronjob, sys.stdout, sort_keys=False)
    elif args.command in {"compare-add-suspended", "compare-suspend-only", "compare-remove-cronjob"}:
        current = load_path(args.current)
        desired = load_path(args.desired)
        if args.command == "compare-add-suspended":
            compare_add_suspended(current, desired, args.release_name, args.namespace)
        elif args.command == "compare-suspend-only":
            compare_suspend_only(current, desired, args.release_name, args.namespace)
        else:
            compare_remove_cronjob(current, desired, args.release_name, args.namespace)
    elif args.command == "verify-runtime-image":
        verify_runtime_image(
            load_json_path(args.deployments, "Deployment"),
            load_json_path(args.replicasets, "ReplicaSet"),
            load_json_path(args.pods, "Pod"),
            args.release_name,
            args.image,
            args.digest,
        )
    elif args.command == "compare-live-desired":
        compare_live_desired(
            kubectl_list_documents(sys.stdin),
            load_path(args.desired),
            args.release_name,
            args.namespace,
        )
    else:
        payload = load_json(sys.stdin, "Kubernetes")
        if args.command == "verify-deployment-image":
            verify_deployment_image(payload, args.release_name, args.image)
        elif args.command == "verify-pod-image":
            verify_pod_image(payload, args.release_name, args.image, args.digest)
        else:
            verify_containerd_image(payload, args.image, args.digest)


if __name__ == "__main__":
    main()
