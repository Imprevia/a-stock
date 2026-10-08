from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "deploy" / "helm" / "a-stock"
HELM = os.getenv("HELM_BINARY") or shutil.which("helm")


def _render(*arguments: str) -> list[dict[str, Any]]:
    completed = subprocess.run(
        [
            str(HELM),
            "template",
            "a-stock",
            str(CHART),
            "--namespace",
            "a-stock",
            "--set",
            "database.existingSecret=a-stock-postgresql",
            *arguments,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return [
        document
        for document in yaml.safe_load_all(completed.stdout)
        if isinstance(document, dict)
    ]


def _resource(documents: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    return next(document for document in documents if document.get("kind") == kind)


def _environment(container: dict[str, Any]) -> dict[str, Any]:
    return {
        item["name"]: item.get("value", item.get("valueFrom"))
        for item in container["env"]
    }


def test_enhanced_container_layers_only_static_scrapling_profile() -> None:
    default = (ROOT / "Dockerfile").read_text(encoding="utf-8").lower()
    enhanced = (ROOT / "Dockerfile.scrapling").read_text(encoding="utf-8").lower()

    assert "requirements-scrapling.txt" not in default
    assert "arg base_image=" in enhanced
    assert "from ${base_image}" in enhanced
    assert "requirements-scrapling.txt" in enhanced
    assert "user 10001:10001" in enhanced
    for forbidden in (
        "scrapling install",
        "playwright install",
        "patchright install",
        "chromium",
        "google-chrome",
    ):
        assert forbidden not in default
        assert forbidden not in enhanced


def test_helm_scrapling_profile_is_disabled_and_empty_by_default() -> None:
    values = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))
    scrapling = values["marketEnvironment"]["scrapling"]

    assert scrapling == {
        "enabled": False,
        "image": {
            "repository": "a-stock-market-environment-scrapling",
            "pullPolicy": "IfNotPresent",
            "tag": "latest",
        },
        "allowlist": [],
    }
    scheduled = values["marketEnvironment"]["scheduledCollection"]
    assert scheduled["enabled"] is False
    assert scheduled["suspend"] is True


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_default_helm_render_uses_base_image_without_secret_or_cronjob() -> None:
    documents = _render()
    deployment = _resource(documents, "Deployment")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    environment = _environment(container)

    assert container["image"] == "a-stock-market-environment:latest"
    assert environment["MARKET_ENVIRONMENT_SCRAPLING_ENABLED"] == "0"
    assert environment["MARKET_ENVIRONMENT_SCRAPLING_ALLOWLIST"] == "[]"
    assert all(document.get("kind") != "CronJob" for document in documents)
    assert all(document.get("kind") != "Secret" for document in documents)


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_enhanced_helm_render_is_explicit_empty_and_still_suspended() -> None:
    documents = _render(
        "--kube-version",
        "1.27.0",
        "--set",
        "marketEnvironment.scrapling.enabled=true",
        "--set",
        "marketEnvironment.scrapling.image.repository=registry.local/a-stock-enhanced",
        "--set",
        "marketEnvironment.scrapling.image.tag=reviewed",
        "--set",
        "marketEnvironment.scheduledCollection.enabled=true",
        "--set",
        "marketEnvironment.scheduledCollection.suspend=true",
    )
    deployment = _resource(documents, "Deployment")
    cronjob = _resource(documents, "CronJob")
    containers = (
        deployment["spec"]["template"]["spec"]["containers"][0],
        cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0],
    )

    assert cronjob["spec"]["suspend"] is True
    assert all(document.get("kind") != "Secret" for document in documents)
    for container in containers:
        environment = _environment(container)
        assert container["image"] == "registry.local/a-stock-enhanced:reviewed"
        assert environment["MARKET_ENVIRONMENT_SCRAPLING_ENABLED"] == "1"
        assert environment["MARKET_ENVIRONMENT_SCRAPLING_ALLOWLIST"] == "[]"
        assert container["resources"] == {
            "requests": {"cpu": "100m", "memory": "256Mi"},
            "limits": {"cpu": "1", "memory": "1Gi"},
        }
        assert {mount["mountPath"] for mount in container["volumeMounts"]} >= {"/tmp"}

    rendered = yaml.safe_dump_all(documents, sort_keys=True).lower()
    assert "chromium" not in rendered
    assert "playwright" not in rendered
    assert "patchright" not in rendered


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (
            ("--set-string", "marketEnvironment.scrapling.enabled=false"),
            "got string, want boolean",
        ),
        (
            (
                "--set",
                "marketEnvironment.scrapling.allowlist[0].host=*",
                "--set",
                "marketEnvironment.scrapling.allowlist[0].sourceId=source",
            ),
            "does not match pattern",
        ),
    ],
)
def test_helm_scrapling_profile_rejects_ambiguous_configuration(
    arguments: tuple[str, ...], expected: str
) -> None:
    completed = subprocess.run(
        [str(HELM), "template", "a-stock", str(CHART), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert expected in completed.stderr
