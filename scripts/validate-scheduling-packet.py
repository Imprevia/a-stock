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
}
MANUAL_REFRESH_LIVE_KINDS = {
    **TRACKED_LIVE_KINDS,
    "StatefulSet": "apps/v1",
    "PersistentVolumeClaim": "v1",
}
SECTORS_ENABLED_ENV = "MARKET_ENVIRONMENT_FUYAO_SECTORS_ENABLED"
SECTORS_REVISION_ENV = "MARKET_ENVIRONMENT_FUYAO_SECTORS_APPROVED_REVISION"
MANUAL_REFRESH_ENV = "MARKET_ENVIRONMENT_MANUAL_REFRESH_ENABLED"
SECTORS_DISABLED_ENVS = (
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
SEMVER_PATTERN = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


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


def parse_semver(value: Any) -> tuple[tuple[int, int, int], tuple[str, ...]]:
    if not isinstance(value, str):
        fail(f"invalid Kubernetes version: {value}")
    match = SEMVER_PATTERN.fullmatch(value)
    if match is None:
        fail(f"invalid Kubernetes version: {value}")
    core = tuple(int(match.group(name)) for name in ("major", "minor", "patch"))
    prerelease = tuple((match.group("prerelease") or "").split("."))
    return core, prerelease if prerelease != ("",) else ()


def normalize_semver(value: Any) -> str:
    parse_semver(value)
    return value.removeprefix("v")


def require_no_cronjobs(
    documents: list[dict[str, Any]], description: str
) -> None:
    cronjob_names = [
        str((item.get("metadata") or {}).get("name", "<unnamed>"))
        for item in documents
        if item.get("kind") == "CronJob"
    ]
    if cronjob_names:
        fail(
            f"{description} must not contain a CronJob: "
            + ", ".join(cronjob_names)
        )


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


def without_helm_hooks(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        document
        for document in documents
        if not isinstance((document.get("metadata") or {}).get("annotations"), dict)
        or "helm.sh/hook" not in (document.get("metadata") or {}).get("annotations", {})
    ]


def helm_hooks(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        document
        for document in documents
        if isinstance((document.get("metadata") or {}).get("annotations"), dict)
        and "helm.sh/hook" in (document.get("metadata") or {}).get("annotations", {})
    ]


def dump_documents(documents: list[dict[str, Any]]) -> None:
    yaml.safe_dump_all(documents, sys.stdout, sort_keys=False)


def _validate_resource_namespaces(
    documents: list[dict[str, Any]], namespace: str, description: str
) -> None:
    for document in documents:
        metadata = document.get("metadata")
        actual = metadata.get("namespace") if isinstance(metadata, dict) else None
        if actual not in {None, "", namespace}:
            fail(f"{description} resource namespace must be {namespace}, got {actual}")


def _validate_reviewed_hooks(
    documents: list[dict[str, Any]], release_name: str, expected_image: str
) -> list[dict[str, Any]]:
    hooks = helm_hooks(documents)
    if not hooks:
        return hooks
    if len(hooks) != 1:
        fail("sectors packet may contain only the reviewed schema migration hook")
    hook = hooks[0]
    metadata = hook.get("metadata") or {}
    annotations = metadata.get("annotations") or {}
    labels = metadata.get("labels") or {}
    containers = (((hook.get("spec") or {}).get("template") or {}).get("spec") or {}).get(
        "containers", []
    )
    migration = [
        item for item in containers if isinstance(item, dict) and item.get("name") == "schema-migration"
    ]
    if (
        hook.get("kind") != "Job"
        or release_label(hook) != release_name
        or labels.get("app.kubernetes.io/component") != "database-migration"
        or annotations.get("helm.sh/hook") != "post-install,post-upgrade"
        or annotations.get("helm.sh/hook-weight") != "-5"
        or annotations.get("helm.sh/hook-delete-policy")
        != "before-hook-creation,hook-succeeded"
        or len(migration) != 1
        or migration[0].get("image") != expected_image
        or migration[0].get("command") != ["alembic", "upgrade", "head"]
    ):
        fail("sectors packet contains an unreviewed Helm hook")
    environment = _environment_index(migration[0], "schema migration hook")
    _required_secret_reference(
        environment, "MARKET_ENVIRONMENT_DATABASE_URL", "schema migration database URL"
    )
    return hooks


def _dashboard_deployment(
    documents: list[dict[str, Any]], release_name: str, description: str
) -> dict[str, Any]:
    deployments = [
        document
        for document in documents
        if document.get("kind") == "Deployment" and release_label(document) == release_name
    ]
    if len(deployments) != 1:
        fail(f"{description} must contain exactly one release Dashboard Deployment")
    return deployments[0]


def _dashboard_container(deployment: dict[str, Any], description: str) -> dict[str, Any]:
    containers = named_entries(
        deployment, ("spec", "template", "spec", "containers"), "dashboard"
    )
    if len(containers) != 1:
        fail(f"{description} must contain exactly one dashboard container")
    return containers[0]


def _environment_index(container: dict[str, Any], description: str) -> dict[str, dict[str, Any]]:
    environment = container.get("env")
    if not isinstance(environment, list) or not all(isinstance(item, dict) for item in environment):
        fail(f"{description} env must be a list of objects")
    result: dict[str, dict[str, Any]] = {}
    for item in environment:
        name = item.get("name")
        if not isinstance(name, str) or not name:
            fail(f"{description} env names must be non-empty strings")
        if name in result:
            fail(f"{description} contains duplicate env name {name}")
        result[name] = item
    return result


def _normalize_omitted_empty_environment_value(
    live_item: dict[str, Any], desired_item: dict[str, Any]
) -> None:
    if (
        desired_item.get("value") == ""
        and "value" not in live_item
        and "valueFrom" not in live_item
    ):
        # Kubernetes 1.26 can omit an explicitly empty env value on read-back.
        live_item["value"] = ""


def _required_secret_reference(
    environment: dict[str, dict[str, Any]], name: str, description: str
) -> dict[str, Any]:
    item = environment.get(name)
    value_from = item.get("valueFrom") if isinstance(item, dict) else None
    secret_ref = value_from.get("secretKeyRef") if isinstance(value_from, dict) else None
    if (
        not isinstance(secret_ref, dict)
        or not isinstance(secret_ref.get("name"), str)
        or not secret_ref["name"]
        or not isinstance(secret_ref.get("key"), str)
        or not secret_ref["key"]
        or "value" in item
    ):
        fail(f"{description} must use a named Secret key reference")
    return secret_ref


def _validate_sectors_environment(
    environment: dict[str, dict[str, Any]], required_enabled: str, description: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    enabled = environment.get(SECTORS_ENABLED_ENV)
    if not isinstance(enabled, dict) or enabled != {
        "name": SECTORS_ENABLED_ENV,
        "value": required_enabled,
    }:
        fail(f"{SECTORS_ENABLED_ENV} must equal {required_enabled}")
    revision = environment.get(SECTORS_REVISION_ENV)
    if not isinstance(revision, dict) or revision != {
        "name": SECTORS_REVISION_ENV,
        "value": "fuyao-market-v2",
    }:
        fail(f"{SECTORS_REVISION_ENV} must equal fuyao-market-v2")
    for name in SECTORS_DISABLED_ENVS:
        item = environment.get(name)
        if not isinstance(item, dict) or item != {"name": name, "value": "0"}:
            fail(f"{name} must equal 0")
    database_ref = _required_secret_reference(
        environment, "MARKET_ENVIRONMENT_DATABASE_URL", f"{description} database URL"
    )
    provider_ref = _required_secret_reference(
        environment, "MARKET_ENVIRONMENT_FUYAO_API_KEY", f"{description} Fuyao API key"
    )
    if database_ref["name"] == provider_ref["name"]:
        fail("database and Fuyao credentials must use independent Secrets")
    return database_ref, provider_ref


def validate_sectors_packet(
    documents: list[dict[str, Any]],
    release_name: str,
    namespace: str,
    required_enabled: str,
) -> dict[str, Any]:
    if required_enabled not in {"0", "1"}:
        fail("required sectors enabled value must be 0 or 1")
    require_no_cronjobs(documents, "sectors packet")
    _validate_resource_namespaces(documents, namespace, "sectors packet")
    release_documents = without_helm_hooks(documents)
    deployment = _dashboard_deployment(release_documents, release_name, "sectors packet")
    spec = deployment.get("spec")
    if not isinstance(spec, dict) or spec.get("replicas") != 1:
        fail("sectors packet Dashboard Deployment must have exactly one replica")
    container = _dashboard_container(deployment, "sectors packet Dashboard Deployment")
    image = container.get("image")
    if not isinstance(image, str) or not image:
        fail("sectors packet Dashboard image must be non-empty")
    _validate_reviewed_hooks(documents, release_name, image)
    environment = _environment_index(container, "sectors packet Dashboard")
    database_ref, provider_ref = _validate_sectors_environment(
        environment, required_enabled, "runtime"
    )
    return {
        "deployment": metadata_value(deployment, "name"),
        "image": image,
        "databaseSecret": database_ref["name"],
        "providerSecret": provider_ref["name"],
        "sectorsEnabled": required_enabled,
    }


def compare_sectors_config_only(
    current: list[dict[str, Any]],
    desired: list[dict[str, Any]],
    release_name: str,
    namespace: str,
    expected_image: str,
    expected_from: str,
    expected_to: str,
) -> None:
    current_summary = validate_sectors_packet(
        current, release_name, namespace, expected_from
    )
    desired_summary = validate_sectors_packet(
        desired, release_name, namespace, expected_to
    )
    if current_summary["image"] != expected_image or desired_summary["image"] != expected_image:
        fail(f"config-only rollout must preserve frozen image {expected_image}")

    current_index = indexed(without_helm_hooks(current))
    desired_index = indexed(without_helm_hooks(desired))
    current_hooks = helm_hooks(current)
    desired_hooks = helm_hooks(desired)
    if current_hooks and desired_hooks and indexed(current_hooks) != indexed(desired_hooks):
        fail("config-only rollout contains Helm hook drift")
    if current_index.keys() != desired_index.keys():
        fail("config-only rollout must preserve the complete release resource set")

    deployment_keys = [key for key in current_index if key[1] == "Deployment"]
    if len(deployment_keys) != 1:
        fail("config-only rollout must contain exactly one Deployment")
    deployment_key = deployment_keys[0]
    for key in current_index:
        if key != deployment_key and current_index[key] != desired_index[key]:
            fail(f"config-only rollout contains non-Deployment drift: {key}")

    before = copy.deepcopy(current_index[deployment_key])
    after = copy.deepcopy(desired_index[deployment_key])
    before_container = _dashboard_container(before, "current Dashboard Deployment")
    after_container = _dashboard_container(after, "desired Dashboard Deployment")
    before_environment = _environment_index(before_container, "current Dashboard")
    after_environment = _environment_index(after_container, "desired Dashboard")
    if before_environment.keys() != after_environment.keys():
        fail("config-only rollout must not add or remove environment variables")
    for name in before_environment:
        if name == SECTORS_ENABLED_ENV:
            continue
        if before_environment[name] != after_environment[name]:
            fail(f"config-only rollout contains unrelated environment drift: {name}")
    before_container.pop("env")
    after_container.pop("env")
    if before != after:
        fail("config-only rollout contains Deployment drift outside dashboard env")


def validate_manual_refresh_packet(
    documents: list[dict[str, Any]],
    release_name: str,
    namespace: str,
    expected_image: str,
    required_value: str,
) -> dict[str, Any]:
    if required_value not in {"0", "1"}:
        fail("required manual refresh value must be 0 or 1")
    require_no_cronjobs(documents, "manual-refresh packet")
    _validate_resource_namespaces(documents, namespace, "manual-refresh packet")
    deployment = _dashboard_deployment(
        without_helm_hooks(documents), release_name, "manual-refresh packet"
    )
    spec = deployment.get("spec")
    if not isinstance(spec, dict) or spec.get("replicas") != 1:
        fail("manual-refresh packet Dashboard Deployment must have exactly one replica")
    container = _dashboard_container(
        deployment, "manual-refresh packet Dashboard Deployment"
    )
    if container.get("image") != expected_image:
        fail(f"manual-refresh packet must preserve frozen image {expected_image}")
    _validate_reviewed_hooks(documents, release_name, expected_image)
    environment = _environment_index(container, "manual-refresh packet Dashboard")
    if environment.get(MANUAL_REFRESH_ENV) != {
        "name": MANUAL_REFRESH_ENV,
        "value": required_value,
    }:
        fail(f"{MANUAL_REFRESH_ENV} must be literal {required_value}")
    return {
        "deployment": metadata_value(deployment, "name"),
        "image": expected_image,
        "manualRefreshEnabled": required_value,
    }


def compare_manual_refresh_only(
    current: list[dict[str, Any]],
    desired: list[dict[str, Any]],
    release_name: str,
    namespace: str,
    expected_image: str,
) -> None:
    validate_manual_refresh_packet(
        current, release_name, namespace, expected_image, "1"
    )
    validate_manual_refresh_packet(
        desired, release_name, namespace, expected_image, "0"
    )
    current_hooks = helm_hooks(current)
    desired_hooks = helm_hooks(desired)
    if indexed(current_hooks) != indexed(desired_hooks):
        fail("manual-refresh rollout contains Helm hook drift")

    current_index = indexed(without_helm_hooks(current))
    desired_index = indexed(without_helm_hooks(desired))
    if current_index.keys() != desired_index.keys():
        fail("manual-refresh rollout must preserve the complete release resource set")

    deployment_keys = [key for key in current_index if key[1] == "Deployment"]
    if len(deployment_keys) != 1:
        fail("manual-refresh rollout must contain exactly one Deployment")
    deployment_key = deployment_keys[0]
    for key in current_index:
        if key != deployment_key and current_index[key] != desired_index[key]:
            fail(f"manual-refresh rollout contains non-Deployment drift: {key}")

    before = copy.deepcopy(current_index[deployment_key])
    after = copy.deepcopy(desired_index[deployment_key])
    before_container = _dashboard_container(before, "current Dashboard Deployment")
    after_container = _dashboard_container(after, "desired Dashboard Deployment")
    before_environment = _environment_index(before_container, "current Dashboard")
    after_environment = _environment_index(after_container, "desired Dashboard")
    if before_environment.keys() != after_environment.keys():
        fail("manual-refresh rollout must not add or remove environment variables")
    for name in before_environment:
        if name == MANUAL_REFRESH_ENV:
            continue
        if before_environment[name] != after_environment[name]:
            fail(f"manual-refresh rollout contains unrelated environment drift: {name}")
    for container in (before_container, after_container):
        for item in container["env"]:
            if item.get("name") == MANUAL_REFRESH_ENV:
                item["value"] = "__reviewed_manual_refresh_transition__"
    if before != after:
        fail("manual-refresh rollout contains Deployment drift outside the reviewed value")


def compare_release_exact(
    current: list[dict[str, Any]], desired: list[dict[str, Any]]
) -> None:
    current_hooks = helm_hooks(current)
    desired_hooks = helm_hooks(desired)
    if indexed(current_hooks) != indexed(desired_hooks):
        fail("stored release contains Helm hook drift")
    if indexed(without_helm_hooks(current)) != indexed(without_helm_hooks(desired)):
        fail("stored release manifest differs from the reviewed packet")


def compare_hooks_exact(
    current: list[dict[str, Any]], desired: list[dict[str, Any]]
) -> None:
    current_hooks = helm_hooks(current)
    desired_hooks = helm_hooks(desired)
    if len(current_hooks) != len(current):
        fail("stored Helm hooks response contains a non-hook resource")
    if len(desired_hooks) != len(desired):
        fail("reviewed Helm hooks packet contains a non-hook resource")
    if indexed(current_hooks) != indexed(desired_hooks):
        fail("stored Helm hooks differ from the reviewed packet")


def select_disabled_promotion_pod(
    payload: dict[str, Any],
    deployments_payload: dict[str, Any],
    replicasets_payload: dict[str, Any],
    desired: list[dict[str, Any]],
    release_name: str,
    namespace: str,
    expected_image: str,
    digest: str,
    required_enabled: str = "0",
) -> str:
    if required_enabled not in {"0", "1"}:
        fail("required sectors enabled value must be 0 or 1")
    verify_runtime_image(
        deployments_payload,
        replicasets_payload,
        payload,
        release_name,
        namespace,
        expected_image,
        digest,
    )
    pods = kubernetes_json_items(payload, "Pod", "Pod")
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for pod in pods:
        if release_label(pod) != release_name:
            continue
        dashboards = named_entries(pod, ("spec", "containers"), "dashboard")
        if dashboards:
            if len(dashboards) != 1:
                fail("promotion Pod must contain exactly one dashboard container")
            candidates.append((pod, dashboards[0]))
    if len(candidates) != 1:
        fail("promotion requires exactly one release Dashboard Pod")
    pod, dashboard = candidates[0]
    metadata = pod.get("metadata")
    if (
        not isinstance(metadata, dict)
        or metadata.get("namespace") != namespace
        or metadata.get("deletionTimestamp") is not None
    ):
        fail(f"promotion Dashboard Pod must be live in namespace {namespace}")
    status = pod.get("status")
    ready_conditions = (
        [item for item in status.get("conditions", []) if isinstance(item, dict) and item.get("type") == "Ready"]
        if isinstance(status, dict)
        else []
    )
    statuses = named_entries(pod, ("status", "containerStatuses"), "dashboard")
    if (
        not isinstance(status, dict)
        or status.get("phase") != "Running"
        or len(ready_conditions) != 1
        or ready_conditions[0].get("status") != "True"
        or len(statuses) != 1
        or statuses[0].get("ready") is not True
    ):
        fail("promotion Dashboard Pod must be Running and Ready")
    if dashboard.get("image") != expected_image:
        fail(f"promotion Dashboard Pod must use frozen image {expected_image}")
    environment = _environment_index(dashboard, "promotion Dashboard Pod")
    _validate_sectors_environment(environment, required_enabled, "promotion runtime")
    desired_deployment = _dashboard_deployment(
        without_helm_hooks(desired), release_name, "reviewed promotion packet"
    )
    desired_environment = _environment_index(
        _dashboard_container(desired_deployment, "reviewed promotion packet"),
        "reviewed promotion packet",
    )
    normalized_environment = copy.deepcopy(environment)
    for name, live_item in normalized_environment.items():
        desired_item = desired_environment.get(name)
        if isinstance(desired_item, dict):
            _normalize_omitted_empty_environment_value(live_item, desired_item)
    if normalized_environment != desired_environment:
        fail("promotion Dashboard Pod environment differs from the reviewed packet")
    name = metadata_value(pod, "name")
    if not isinstance(name, str) or not name:
        fail("promotion Dashboard Pod metadata.name is missing")
    return name


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
    elif re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        digest = image_id
    else:
        fail("running Dashboard imageID must contain an explicit digest reference")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        fail("running Dashboard imageID contains an invalid digest")
    return digest


def image_repository(image: Any) -> str:
    if not isinstance(image, str) or not image:
        fail("image reference must be a non-empty string")
    reference = image.split("@", 1)[0]
    slash = reference.rfind("/")
    colon = reference.rfind(":")
    return reference[:colon] if colon > slash else reference


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
    namespace: str,
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
    deployment_metadata = deployment.get("metadata")
    if (
        not isinstance(deployment_metadata, dict)
        or deployment_metadata.get("namespace") != namespace
        or deployment_metadata.get("deletionTimestamp") is not None
    ):
        fail(f"release Dashboard Deployment must be live in namespace {namespace}")
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
    replicaset_metadata = current_replicaset.get("metadata")
    if (
        not isinstance(replicaset_metadata, dict)
        or replicaset_metadata.get("namespace") != namespace
        or replicaset_metadata.get("deletionTimestamp") is not None
    ):
        fail(f"current Dashboard ReplicaSet must be live in namespace {namespace}")
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

        owner = controller_owner(pod)
        labels = metadata_value(pod, "labels")
        postgresql_specs = named_entries(pod, ("spec", "containers"), "postgresql")
        postgresql_statuses = named_entries(
            pod, ("status", "containerStatuses"), "postgresql"
        )
        if (
            isinstance(labels, dict)
            and labels.get("app.kubernetes.io/component") == "postgresql"
        ):
            status = pod.get("status") or {}
            if (
                len(postgresql_specs) != 1
                or len(postgresql_statuses) != 1
                or postgresql_statuses[0].get("ready") is not True
                or status.get("phase") != "Running"
                or owner is None
                or owner.get("kind") != "StatefulSet"
                or owner.get("name") != f"{release_name}-postgresql"
                or not isinstance(owner.get("uid"), str)
            ):
                fail("release PostgreSQL Pod is not a ready StatefulSet-owned database Pod")
            continue

        collector_specs = named_entries(pod, ("spec", "containers"), "collector")
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
    pod_metadata = pod.get("metadata")
    if (
        not isinstance(pod_metadata, dict)
        or pod_metadata.get("namespace") != namespace
        or pod_metadata.get("deletionTimestamp") is not None
    ):
        fail(f"Dashboard Pod must be live in namespace {namespace}")
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
    runtime_image = dashboard_statuses[0].get("image")
    if image_repository(runtime_image) != image_repository(image):
        fail(f"running Dashboard Pod must use the frozen image repository {image_repository(image)}")
    # CRI imageID is commonly the image config digest, while containerd's
    # named image target is the manifest digest. Both are valid sha256 values
    # but are not interchangeable. The exact tag is already bound above and
    # verify-containerd-image separately binds that tag to the reviewed
    # manifest digest, so only require a well-formed runtime imageID here.
    image_id_digest(dashboard_statuses[0].get("imageID"))


def verify_manual_refresh_runtime(
    deployments_payload: dict[str, Any],
    replicasets_payload: dict[str, Any],
    pods_payload: dict[str, Any],
    desired: list[dict[str, Any]],
    release_name: str,
    namespace: str,
    image: str,
    digest: str,
    required_value: str,
) -> str:
    verify_runtime_image(
        deployments_payload,
        replicasets_payload,
        pods_payload,
        release_name,
        namespace,
        image,
        digest,
    )
    validate_manual_refresh_packet(
        desired, release_name, namespace, image, required_value
    )
    pods = kubernetes_json_items(pods_payload, "Pod", "Pod")
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for pod in pods:
        if release_label(pod) != release_name:
            continue
        dashboards = named_entries(pod, ("spec", "containers"), "dashboard")
        if dashboards:
            if len(dashboards) != 1:
                fail("manual-refresh Pod must contain exactly one dashboard container")
            candidates.append((pod, dashboards[0]))
    if len(candidates) != 1:
        fail("manual-refresh verification requires exactly one release Dashboard Pod")
    pod, dashboard = candidates[0]
    runtime_environment = _environment_index(
        dashboard, "manual-refresh Dashboard Pod"
    )
    if runtime_environment.get(MANUAL_REFRESH_ENV) != {
        "name": MANUAL_REFRESH_ENV,
        "value": required_value,
    }:
        fail(f"runtime {MANUAL_REFRESH_ENV} must be literal {required_value}")
    desired_deployment = _dashboard_deployment(
        without_helm_hooks(desired), release_name, "reviewed manual-refresh packet"
    )
    desired_environment = _environment_index(
        _dashboard_container(
            desired_deployment, "reviewed manual-refresh packet Deployment"
        ),
        "reviewed manual-refresh packet",
    )
    normalized_environment = copy.deepcopy(runtime_environment)
    for name, live_item in normalized_environment.items():
        desired_item = desired_environment.get(name)
        if isinstance(desired_item, dict):
            _normalize_omitted_empty_environment_value(live_item, desired_item)
    if normalized_environment != desired_environment:
        fail("manual-refresh Dashboard Pod environment differs from the reviewed packet")
    pod_name = metadata_value(pod, "name")
    if not isinstance(pod_name, str) or not pod_name:
        fail("manual-refresh Dashboard Pod metadata.name is missing")
    return pod_name


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
    if image_repository(dashboards[0].get("image")) != image_repository(image):
        fail(f"running Dashboard Pod must use the frozen image repository {image_repository(image)}")
    image_id_digest(dashboards[0].get("imageID"))


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
    documents: list[dict[str, Any]],
    release_name: str,
    namespace: str,
    source: str,
    tracked_kinds: dict[str, str] | None = None,
) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    tracked_kinds = TRACKED_LIVE_KINDS if tracked_kinds is None else tracked_kinds
    resources: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for document in documents:
        kind = document.get("kind")
        if kind not in tracked_kinds:
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
        expected_api_version = tracked_kinds[kind]
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
    live_env = live.get("env")
    desired_env = desired.get("env")
    if isinstance(live_env, list) and isinstance(desired_env, list):
        for live_item in live_env:
            if not isinstance(live_item, dict):
                continue
            desired_item = _matching_named_item(desired_env, live_item.get("name"))
            _normalize_omitted_empty_environment_value(live_item, desired_item)
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


def _normalize_statefulset(live: dict[str, Any], desired: dict[str, Any]) -> None:
    live_spec = live.get("spec")
    desired_spec = desired.get("spec")
    if not isinstance(live_spec, dict):
        return
    if not isinstance(desired_spec, dict):
        desired_spec = {}
    for key, value in (
        ("podManagementPolicy", "OrderedReady"),
        ("replicas", 1),
        ("revisionHistoryLimit", 10),
    ):
        _drop_default(live_spec, desired_spec, key, value)
    live_strategy = live_spec.get("updateStrategy")
    desired_strategy = desired_spec.get("updateStrategy")
    if isinstance(live_strategy, dict):
        desired_strategy = desired_strategy if isinstance(desired_strategy, dict) else {}
        _drop_default(live_strategy, desired_strategy, "type", "RollingUpdate")
        live_rolling = live_strategy.get("rollingUpdate")
        desired_rolling = desired_strategy.get("rollingUpdate")
        if isinstance(live_rolling, dict):
            desired_rolling = desired_rolling if isinstance(desired_rolling, dict) else {}
            _drop_default(live_rolling, desired_rolling, "partition", 0)
            if not live_rolling and "rollingUpdate" not in desired_strategy:
                live_strategy.pop("rollingUpdate")
        if not live_strategy and "updateStrategy" not in desired_spec:
            live_spec.pop("updateStrategy")
    retention = live_spec.get("persistentVolumeClaimRetentionPolicy")
    desired_retention = desired_spec.get("persistentVolumeClaimRetentionPolicy")
    if isinstance(retention, dict):
        desired_retention = desired_retention if isinstance(desired_retention, dict) else {}
        _drop_default(retention, desired_retention, "whenDeleted", "Retain")
        _drop_default(retention, desired_retention, "whenScaled", "Retain")
        if not retention and "persistentVolumeClaimRetentionPolicy" not in desired_spec:
            live_spec.pop("persistentVolumeClaimRetentionPolicy")
    live_template = live_spec.get("template")
    desired_template = desired_spec.get("template")
    if isinstance(live_template, dict):
        _normalize_pod_template(
            live_template, desired_template if isinstance(desired_template, dict) else {}
        )


def _normalize_persistent_volume_claim(
    live: dict[str, Any], desired: dict[str, Any]
) -> None:
    live_metadata = _metadata(live, "live PersistentVolumeClaim")
    desired_metadata = _metadata(desired, "desired PersistentVolumeClaim")
    if "finalizers" not in desired_metadata and live_metadata.get("finalizers") == [
        "kubernetes.io/pvc-protection"
    ]:
        live_metadata.pop("finalizers")
    live_annotations = live_metadata.get("annotations")
    desired_annotations = desired_metadata.get("annotations")
    if isinstance(live_annotations, dict):
        desired_annotations = (
            desired_annotations if isinstance(desired_annotations, dict) else {}
        )
        for key in (
            "pv.kubernetes.io/bind-completed",
            "pv.kubernetes.io/bound-by-controller",
            "volume.beta.kubernetes.io/storage-provisioner",
            "volume.kubernetes.io/selected-node",
            "volume.kubernetes.io/storage-provisioner",
        ):
            if key not in desired_annotations:
                live_annotations.pop(key, None)
    live_spec = live.get("spec")
    desired_spec = desired.get("spec")
    if not isinstance(live_spec, dict):
        return
    if not isinstance(desired_spec, dict):
        desired_spec = {}
    _drop_allocated(live_spec, desired_spec, "volumeName")
    _drop_default(live_spec, desired_spec, "volumeMode", "Filesystem")


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
    elif kind == "StatefulSet":
        _normalize_statefulset(normalized_live, normalized_desired)
    elif kind == "PersistentVolumeClaim":
        _normalize_persistent_volume_claim(normalized_live, normalized_desired)
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
        fail("live Service/Deployment resource set differs from desired")
    for key in live_resources:
        normalized_live, normalized_desired = _normalize_live_desired_pair(
            live_resources[key], desired_resources[key], release_name, namespace
        )
        if normalized_live != normalized_desired:
            fail(f"live declarative state differs from desired for {key}")


def compare_manual_refresh_live_desired(
    live: list[dict[str, Any]],
    desired: list[dict[str, Any]],
    release_name: str,
    namespace: str,
) -> None:
    desired_non_hooks = without_helm_hooks(desired)
    for source, documents in (("live", live), ("desired", desired_non_hooks)):
        for document in documents:
            kind = document.get("kind")
            if kind not in MANUAL_REFRESH_LIVE_KINDS:
                fail(f"{source} manual-refresh resource kind is not tracked: {kind}")
            metadata = _metadata(document, f"{source} manual-refresh {kind}")
            deletion_timestamp = metadata.get("deletionTimestamp")
            if source == "live" and deletion_timestamp is not None and deletion_timestamp != "":
                fail(f"live manual-refresh {kind} is terminating")
    live_resources = _tracked_release_resources(
        live,
        release_name,
        namespace,
        "live",
        MANUAL_REFRESH_LIVE_KINDS,
    )
    desired_resources = _tracked_release_resources(
        desired_non_hooks,
        release_name,
        namespace,
        "desired",
        MANUAL_REFRESH_LIVE_KINDS,
    )
    if live_resources.keys() != desired_resources.keys():
        fail("manual-refresh live release resource set differs from desired")
    for key in live_resources:
        normalized_live, normalized_desired = _normalize_live_desired_pair(
            live_resources[key], desired_resources[key], release_name, namespace
        )
        if normalized_live != normalized_desired:
            fail(f"manual-refresh live declarative state differs from desired for {key}")


def parse_server_version(payload: Any) -> str:
    if not isinstance(payload, dict):
        fail("Kubernetes /version response must be an object")
    value = payload.get("gitVersion")
    if not isinstance(value, str) or SEMVER_PATTERN.fullmatch(value) is None:
        fail("Kubernetes /version gitVersion is missing or invalid")
    return value.removeprefix("v")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("parse-version")
    normalize_version = subparsers.add_parser("normalize-version")
    normalize_version.add_argument("--version", required=True)
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
    runtime.add_argument("--namespace", required=True)
    runtime.add_argument("--image", required=True)
    runtime.add_argument("--digest", required=True)

    live_desired = subparsers.add_parser("compare-live-desired")
    live_desired.add_argument("--desired", type=Path, required=True)
    live_desired.add_argument("--release-name", required=True)
    live_desired.add_argument("--namespace", required=True)

    manual_live_desired = subparsers.add_parser("compare-manual-refresh-live-desired")
    manual_live_desired.add_argument("--desired", type=Path, required=True)
    manual_live_desired.add_argument("--release-name", required=True)
    manual_live_desired.add_argument("--namespace", required=True)

    extract_helm = subparsers.add_parser("extract-helm-documents")
    extract_helm.add_argument("--part", choices=("release", "hooks"), required=True)

    sectors_packet = subparsers.add_parser("validate-sectors-packet")
    sectors_packet.add_argument("--release-name", required=True)
    sectors_packet.add_argument("--namespace", required=True)
    sectors_packet.add_argument("--require-enabled", choices=("0", "1"), required=True)

    sectors_config = subparsers.add_parser("compare-sectors-config-only")
    sectors_config.add_argument("--current", type=Path, required=True)
    sectors_config.add_argument("--desired", type=Path, required=True)
    sectors_config.add_argument("--release-name", required=True)
    sectors_config.add_argument("--namespace", required=True)
    sectors_config.add_argument("--image", required=True)
    sectors_config.add_argument("--from-enabled", choices=("0", "1"), required=True)
    sectors_config.add_argument("--to-enabled", choices=("0", "1"), required=True)

    manual_packet = subparsers.add_parser("validate-manual-refresh-packet")
    manual_packet.add_argument("--release-name", required=True)
    manual_packet.add_argument("--namespace", required=True)
    manual_packet.add_argument("--image", required=True)
    manual_packet.add_argument("--require-value", choices=("0", "1"), required=True)

    manual_config = subparsers.add_parser("compare-manual-refresh-only")
    manual_config.add_argument("--current", type=Path, required=True)
    manual_config.add_argument("--desired", type=Path, required=True)
    manual_config.add_argument("--release-name", required=True)
    manual_config.add_argument("--namespace", required=True)
    manual_config.add_argument("--image", required=True)

    manual_runtime = subparsers.add_parser("verify-manual-refresh-runtime")
    manual_runtime.add_argument("--deployments", type=Path, required=True)
    manual_runtime.add_argument("--replicasets", type=Path, required=True)
    manual_runtime.add_argument("--pods", type=Path, required=True)
    manual_runtime.add_argument("--desired", type=Path, required=True)
    manual_runtime.add_argument("--release-name", required=True)
    manual_runtime.add_argument("--namespace", required=True)
    manual_runtime.add_argument("--image", required=True)
    manual_runtime.add_argument("--digest", required=True)
    manual_runtime.add_argument("--require-value", choices=("0", "1"), required=True)

    release_exact = subparsers.add_parser("compare-release-exact")
    release_exact.add_argument("--current", type=Path, required=True)
    release_exact.add_argument("--desired", type=Path, required=True)

    hooks_exact = subparsers.add_parser("compare-hooks-exact")
    hooks_exact.add_argument("--current", type=Path, required=True)
    hooks_exact.add_argument("--desired", type=Path, required=True)

    promotion_pod = subparsers.add_parser("select-disabled-promotion-pod")
    promotion_pod.add_argument("--release-name", required=True)
    promotion_pod.add_argument("--namespace", required=True)
    promotion_pod.add_argument("--image", required=True)
    promotion_pod.add_argument("--digest", required=True)
    promotion_pod.add_argument("--deployments", type=Path, required=True)
    promotion_pod.add_argument("--replicasets", type=Path, required=True)
    promotion_pod.add_argument("--desired", type=Path, required=True)
    promotion_pod.add_argument("--require-enabled", choices=("0", "1"), default="0")

    args = parser.parse_args()
    if args.command == "parse-version":
        try:
            payload = json.load(sys.stdin)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            fail(f"invalid Kubernetes /version JSON: {exc}")
        print(parse_server_version(payload))
    elif args.command == "normalize-version":
        print(normalize_semver(args.version))
    elif args.command == "verify-runtime-image":
        verify_runtime_image(
            load_json_path(args.deployments, "Deployment"),
            load_json_path(args.replicasets, "ReplicaSet"),
            load_json_path(args.pods, "Pod"),
            args.release_name,
            args.namespace,
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
    elif args.command == "compare-manual-refresh-live-desired":
        compare_manual_refresh_live_desired(
            kubectl_list_documents(sys.stdin),
            load_path(args.desired),
            args.release_name,
            args.namespace,
        )
    elif args.command == "extract-helm-documents":
        documents = load_documents(sys.stdin)
        dump_documents(
            without_helm_hooks(documents)
            if args.part == "release"
            else helm_hooks(documents)
        )
    elif args.command == "validate-sectors-packet":
        result = validate_sectors_packet(
            load_documents(sys.stdin),
            args.release_name,
            args.namespace,
            args.require_enabled,
        )
        json.dump(result, sys.stdout, sort_keys=True, separators=(",", ":"))
        sys.stdout.write("\n")
    elif args.command == "compare-sectors-config-only":
        if args.from_enabled == args.to_enabled:
            fail("config-only rollout must change the sectors enabled flag")
        compare_sectors_config_only(
            load_path(args.current),
            load_path(args.desired),
            args.release_name,
            args.namespace,
            args.image,
            args.from_enabled,
            args.to_enabled,
        )
    elif args.command == "validate-manual-refresh-packet":
        result = validate_manual_refresh_packet(
            load_documents(sys.stdin),
            args.release_name,
            args.namespace,
            args.image,
            args.require_value,
        )
        json.dump(result, sys.stdout, sort_keys=True, separators=(",", ":"))
        sys.stdout.write("\n")
    elif args.command == "compare-manual-refresh-only":
        compare_manual_refresh_only(
            load_path(args.current),
            load_path(args.desired),
            args.release_name,
            args.namespace,
            args.image,
        )
    elif args.command == "verify-manual-refresh-runtime":
        print(
            verify_manual_refresh_runtime(
                load_json_path(args.deployments, "Deployment"),
                load_json_path(args.replicasets, "ReplicaSet"),
                load_json_path(args.pods, "Pod"),
                load_path(args.desired),
                args.release_name,
                args.namespace,
                args.image,
                args.digest,
                args.require_value,
            )
        )
    elif args.command == "compare-release-exact":
        compare_release_exact(load_path(args.current), load_path(args.desired))
    elif args.command == "compare-hooks-exact":
        compare_hooks_exact(load_path(args.current), load_path(args.desired))
    elif args.command == "select-disabled-promotion-pod":
        print(
            select_disabled_promotion_pod(
                load_json(sys.stdin, "Pod"),
                load_json_path(args.deployments, "Deployment"),
                load_json_path(args.replicasets, "ReplicaSet"),
                load_path(args.desired),
                args.release_name,
                args.namespace,
                args.image,
                args.digest,
                args.require_enabled,
            )
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
