from __future__ import annotations

import os
import re
import shlex
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
README = ROOT / "README.md"
TRUENAS_GUIDE = ROOT / "docs" / "truenas-scale-24.04-podman-k3s-deployment.md"
GENERIC_RELEASE_GUIDES = (README, TRUENAS_GUIDE, RUNBOOK)
ARCHIVED_RELEASE_GUIDES = (
    ROOT / "openspec" / "changes" / "archive" / "2026-09-05-secure-manual-collection-on-truenas" / "design.md",
)
HELM_COMMAND_AUDIT_GUIDES = (*GENERIC_RELEASE_GUIDES, *ARCHIVED_RELEASE_GUIDES)
CHART_DIR = ROOT / "deploy" / "helm" / "a-stock"
TRUENAS_DIRECT_ACCESS_VALUES = ROOT / "deploy" / "truenas" / "values-secure-manual-collection.yaml"
TRUENAS_SCHEDULED_SUSPENDED_VALUES = ROOT / "deploy" / "truenas" / "values-scheduled-suspended.yaml"
TRUENAS_SCHEDULED_ACTIVE_VALUES = ROOT / "deploy" / "truenas" / "values-scheduled-active.yaml"
TRUENAS_SCHEDULED_OFF_VALUES = ROOT / "deploy" / "truenas" / "values-scheduled-off.yaml"
HELM_BINARY = os.getenv("HELM_BINARY") or shutil.which("helm")
KUBECTL_BINARY = os.getenv("KUBECTL_BINARY") or shutil.which("kubectl")
SHELL_FENCE_LANGUAGES = ("bash", "sh", "shell")
SHELL_CONTROL_CHARACTERS = frozenset(";&|")
SHELL_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SCHEDULING_ENTRYPOINT_MODES = frozenset(
    {
        "--offline-render",
        "--read-only-discovery",
        "--server-dry-run",
        "--release-suspended",
        "--activate-schedule",
        "--disable-schedule",
    }
)


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


def _render_helm_failure_message(*arguments: str) -> str:
    first_line = _render_helm_error(*arguments).splitlines()[0]
    _, separator, message = first_line.partition("): ")
    assert separator == "): "
    return message


def _render_helm_schema_failures(*arguments: str) -> list[str]:
    return [line for line in _render_helm_error(*arguments).splitlines() if line.startswith("- at ")]


def _resource(documents: list[dict], kind: str) -> dict:
    return next(document for document in documents if document.get("kind") == kind)


def _environment(container: dict) -> dict[str, str]:
    return {item["name"]: item["value"] for item in container["env"]}


def _fenced_blocks(content: str, language: str) -> list[str]:
    lines = content.splitlines(keepends=True)
    blocks: list[str] = []
    index = 0
    opening_pattern = re.compile(r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})[ \t]*(?P<info>[^\r\n]*)")
    while index < len(lines):
        match = opening_pattern.match(lines[index])
        info_language = match.group("info").split(maxsplit=1)[0:1] if match is not None else []
        if match is None or [item.lower() for item in info_language] != [language.lower()]:
            index += 1
            continue
        fence = match.group("fence")
        closing_pattern = re.compile(
            rf"^[ \t]{{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*(?:\r?\n)?$"
        )
        body_start = index + 1
        index = body_start
        while index < len(lines) and closing_pattern.match(lines[index]) is None:
            index += 1
        if index < len(lines):
            blocks.append("".join(lines[body_start:index]))
        index += 1
    return blocks


def _shell_comment_start(line: str) -> int | None:
    single_quoted = False
    double_quoted = False
    escaped = False
    for index, character in enumerate(line):
        if escaped:
            escaped = False
            continue
        if character == "\\" and not single_quoted:
            escaped = True
            continue
        if character == "'" and not double_quoted:
            single_quoted = not single_quoted
            continue
        if character == '"' and not single_quoted:
            double_quoted = not double_quoted
            continue
        if (
            character == "#"
            and not single_quoted
            and not double_quoted
            and (index == 0 or line[index - 1].isspace() or line[index - 1] in ";|&()")
        ):
            return index
    return None


def _logical_shell_lines(block: str) -> list[str]:
    logical_lines: list[str] = []
    pending = ""
    for physical_line in block.splitlines():
        comment_start = _shell_comment_start(physical_line)
        executable = physical_line if comment_start is None else physical_line[:comment_start]
        trailing = len(executable) - len(executable.rstrip("\\"))
        if trailing % 2 == 1:
            pending += physical_line[: len(executable) - 1]
            continue
        logical_lines.append(pending + physical_line)
        pending = ""
    if pending:
        logical_lines.append(pending)
    return logical_lines


def _shell_commands(content: str) -> list[tuple[str, ...]]:
    commands: list[tuple[str, ...]] = []
    for language in SHELL_FENCE_LANGUAGES:
        for block in _fenced_blocks(content, language):
            for line in _logical_shell_lines(block):
                lexer = shlex.shlex(line, posix=True, punctuation_chars="();&|")
                lexer.whitespace_split = True
                lexer.commenters = "#"
                current: list[str] = []
                for token in lexer:
                    if token and all(character in SHELL_CONTROL_CHARACTERS for character in token):
                        if current:
                            commands.append(tuple(current))
                            current = []
                        continue
                    current.append(token)
                if current:
                    commands.append(tuple(current))
    return commands


def _helm_invocation(command: tuple[str, ...]) -> tuple[str, tuple[str, ...]] | None:
    index = 0
    while index < len(command) and command[index] in {
        "!",
        "(",
        "if",
        "then",
        "elif",
        "else",
        "while",
        "until",
        "do",
    }:
        index += 1
    while index < len(command):
        while index < len(command) and SHELL_ASSIGNMENT.match(command[index]):
            index += 1
        if index >= len(command):
            return None
        wrapper = command[index]
        if wrapper == "sudo":
            index += 1
            sudo_value_options = {"-C", "-D", "-g", "-h", "-p", "-R", "-T", "-u"}
            while index < len(command) and command[index].startswith("-"):
                option = command[index]
                index += 1
                if option == "--":
                    break
                if option in sudo_value_options and index < len(command):
                    index += 1
            continue
        if wrapper == "env":
            index += 1
            env_value_options = {"-C", "--chdir", "-S", "--split-string", "-u", "--unset"}
            while index < len(command):
                option = command[index]
                if SHELL_ASSIGNMENT.match(option):
                    index += 1
                elif option == "--":
                    index += 1
                    break
                elif option.startswith("-"):
                    index += 1
                    if option in env_value_options and index < len(command):
                        index += 1
                else:
                    break
            continue
        if wrapper == "command":
            index += 1
            if index < len(command) and command[index] in {"-v", "-V"}:
                return None
            while index < len(command) and command[index] in {"-p", "--"}:
                index += 1
            continue
        break
    if index >= len(command) or command[index] != "helm":
        return None
    helm_arguments = command[index + 1 :]
    value_options = {
        "--burst-limit",
        "--kube-apiserver",
        "--kube-as-group",
        "--kube-as-user",
        "--kube-ca-file",
        "--kube-context",
        "--kube-token",
        "--kubeconfig",
        "--namespace",
        "--qps",
        "--registry-config",
        "--repository-cache",
        "--repository-config",
        "-n",
    }
    action_index = 0
    while action_index < len(helm_arguments):
        argument = helm_arguments[action_index]
        if argument == "--":
            action_index += 1
            break
        if argument.startswith("-"):
            action_index += 1
            if "=" not in argument and argument in value_options and action_index < len(helm_arguments):
                action_index += 1
            continue
        break
    if action_index >= len(helm_arguments):
        return None
    return (
        helm_arguments[action_index],
        (*helm_arguments[:action_index], *helm_arguments[action_index + 1 :]),
    )


def _option_values(arguments: tuple[str, ...], *options: str) -> list[str]:
    values: list[str] = []
    for index, argument in enumerate(arguments):
        if (
            argument in options
            and index + 1 < len(arguments)
            and not arguments[index + 1].startswith("-")
        ):
            values.append(arguments[index + 1])
            continue
        for option in options:
            prefix = f"{option}="
            if argument.startswith(prefix) and argument != prefix:
                values.append(argument[len(prefix) :])
                break
    return values


def _has_flag(arguments: tuple[str, ...], flag: str) -> bool:
    return any(argument == flag or argument.startswith(f"{flag}=") for argument in arguments)


def _effective_set_values(arguments: tuple[str, ...]) -> dict[str, str]:
    effective: dict[str, str] = {}
    for value in _option_values(arguments, "--set"):
        for assignment in value.split(","):
            key, separator, assigned_value = assignment.partition("=")
            if separator:
                effective[key] = assigned_value
    return effective


def _effective_bool_flag(arguments: tuple[str, ...], flag: str) -> bool | None:
    effective: bool | None = None
    for argument in arguments:
        if argument == flag:
            effective = True
        elif argument == f"{flag}=true":
            effective = True
        elif argument.startswith(f"{flag}="):
            effective = False
    return effective


def _helm_write_violations(content: str) -> tuple[int, list[str]]:
    write_count = 0
    violations: list[str] = []
    for command in _shell_commands(content):
        invocation = _helm_invocation(command)
        if invocation is None:
            continue
        action, arguments = invocation
        rendered_command = shlex.join(command)

        if _has_flag(arguments, "--reuse-values"):
            violations.append(f"{rendered_command}: --reuse-values is forbidden")
        if action in {"rollback", "uninstall"}:
            violations.append(f"{rendered_command}: helm {action} is forbidden")
            continue
        if action not in {"install", "upgrade"}:
            continue

        write_count += 1
        set_values = _effective_set_values(arguments)
        for key, required_value in (
            ("marketEnvironment.scheduledCollection.enabled", "false"),
            ("marketEnvironment.scheduledCollection.suspend", "true"),
        ):
            if set_values.get(key) != required_value:
                violations.append(f"{rendered_command}: missing effective --set {key}={required_value}")
        if not _option_values(arguments, "--values", "-f"):
            violations.append(f"{rendered_command}: missing complete values file")
        if _effective_bool_flag(arguments, "--atomic") is not True:
            violations.append(f"{rendered_command}: missing --atomic")

    return write_count, violations


def _is_generic_deploy_entrypoint(command: tuple[str, ...]) -> bool:
    return (
        command[:2] == ("bash", "scripts/deploy-truenas-k3s.sh")
        and not SCHEDULING_ENTRYPOINT_MODES.intersection(command[2:])
    )


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
    assert cron_spec["startingDeadlineSeconds"] == 1800
    assert cron_spec["successfulJobsHistoryLimit"] == 3
    assert cron_spec["failedJobsHistoryLimit"] == 3
    assert cron_spec["jobTemplate"]["spec"]["backoffLimit"] == 0
    assert cron_spec["jobTemplate"]["spec"]["activeDeadlineSeconds"] == 3600
    assert cron_container["image"] == deployment_container["image"]
    assert cron_pod["volumes"][0]["persistentVolumeClaim"]["claimName"] == deployment_pod["volumes"][0]["persistentVolumeClaim"]["claimName"]
    assert cron_container["volumeMounts"][0] == deployment_container["volumeMounts"][0]
    assert cron_container["command"] == [
        "python",
        "-m",
        "src.market_environment.cli",
        "snapshots",
        "scheduled-refresh",
    ]
    assert cron_pod["automountServiceAccountToken"] is False
    assert cron_pod["securityContext"] == deployment_pod["securityContext"]
    assert cron_pod["securityContext"]["runAsNonRoot"] is True
    assert cron_pod["securityContext"]["runAsUser"] == 10001
    assert cron_pod["securityContext"]["runAsGroup"] == 10001
    assert cron_pod["securityContext"]["fsGroup"] == 10001
    assert cron_pod["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}
    assert cron_container["securityContext"] == deployment_container["securityContext"]
    assert cron_container["securityContext"]["allowPrivilegeEscalation"] is False
    assert cron_container["securityContext"]["readOnlyRootFilesystem"] is True
    assert cron_container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert _environment(cron_container) == _environment(deployment_container)
    assert _environment(cron_container)["MARKET_ENVIRONMENT_SNAPSHOT_PATH"] == "/data/snapshots.sqlite3"
    assert any(
        cronjob["spec"]["jobTemplate"]["spec"]["template"]["metadata"]["labels"].get(key) != value
        for key, value in service["spec"]["selector"].items()
    )


def test_helm_values_define_fail_closed_configurable_scheduled_collection() -> None:
    chart = _load_yaml(CHART_DIR / "Chart.yaml")
    values = _load_yaml(CHART_DIR / "values.yaml")
    scheduled = values["marketEnvironment"]["scheduledCollection"]

    assert chart["kubeVersion"] == ">=1.26.0-0"
    assert values["marketEnvironment"]["timezone"] == "Asia/Shanghai"
    assert scheduled["enabled"] is False
    assert scheduled["suspend"] is True
    assert scheduled["schedule"] == "30 16 * * 1-5"
    assert scheduled["timezoneStrategy"] == "native"
    assert scheduled["timeZone"] == "Asia/Shanghai"
    assert scheduled["controllerTimeZone"] == ""
    assert scheduled["controllerTimeZoneVerified"] is False
    assert scheduled["controllerCanaryVerified"] is False
    assert scheduled["startingDeadlineSeconds"] == 1800
    assert scheduled["activeDeadlineSeconds"] == 3600


@pytest.mark.skipif(HELM_BINARY is None, reason="helm is not installed")
def test_helm_default_render_keeps_dashboard_and_omits_cronjob() -> None:
    documents = _render_helm()

    assert _resource(documents, "Deployment")
    assert _resource(documents, "Service")
    assert all(document.get("kind") != "CronJob" for document in documents)


@pytest.mark.skipif(HELM_BINARY is None, reason="helm is not installed")
def test_helm_render_supports_disabled_suspended_and_custom_native_schedule() -> None:
    disabled = _render_helm("--set", "marketEnvironment.scheduledCollection.enabled=false")
    custom = _render_helm(
        "--kube-version",
        "1.27.0",
        "--set",
        "marketEnvironment.scheduledCollection.enabled=true",
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
        "marketEnvironment.scheduledCollection.enabled=true",
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
    ("kube_version", "profile_arguments", "expected_schedule", "expected_timezone"),
    [
        (
            "1.26.6",
            (
                "--set",
                "marketEnvironment.scheduledCollection.timezoneStrategy=controller",
                "--set",
                "marketEnvironment.scheduledCollection.controllerTimeZone=Etc/UTC",
                "--set",
                "marketEnvironment.scheduledCollection.controllerTimeZoneVerified=true",
                "--set-string",
                "marketEnvironment.scheduledCollection.schedule=30 8 * * 1-5",
            ),
            "30 8 * * 1-5",
            None,
        ),
        (
            "1.26.6",
            (
                "--set",
                "marketEnvironment.scheduledCollection.timezoneStrategy=controller",
                "--set",
                "marketEnvironment.scheduledCollection.controllerTimeZone=Asia/Shanghai",
                "--set",
                "marketEnvironment.scheduledCollection.controllerTimeZoneVerified=true",
            ),
            "30 16 * * 1-5",
            None,
        ),
        (
            "1.27.0",
            ("--set", "marketEnvironment.scheduledCollection.timezoneStrategy=native"),
            "30 16 * * 1-5",
            "Asia/Shanghai",
        ),
    ],
    ids=["controller-utc-126", "controller-shanghai-126", "native-127"],
)
@pytest.mark.parametrize(
    ("state_arguments", "expected_suspend"),
    [
        (("--set", "marketEnvironment.scheduledCollection.enabled=false"), None),
        (
            (
                "--set",
                "marketEnvironment.scheduledCollection.enabled=true",
                "--set",
                "marketEnvironment.scheduledCollection.suspend=true",
            ),
            True,
        ),
        (
            (
                "--set",
                "marketEnvironment.scheduledCollection.enabled=true",
                "--set",
                "marketEnvironment.scheduledCollection.suspend=false",
                "--set",
                "marketEnvironment.scheduledCollection.controllerCanaryVerified=true",
            ),
            False,
        ),
    ],
    ids=["disabled", "suspended", "active"],
)
def test_helm_render_matrix_covers_every_profile_and_state(
    kube_version: str,
    profile_arguments: tuple[str, ...],
    expected_schedule: str,
    expected_timezone: str | None,
    state_arguments: tuple[str, ...],
    expected_suspend: bool | None,
) -> None:
    documents = _render_helm(
        "--kube-version",
        kube_version,
        *profile_arguments,
        *state_arguments,
    )

    cronjobs = [document for document in documents if document.get("kind") == "CronJob"]
    if expected_suspend is None:
        assert cronjobs == []
        return

    assert len(cronjobs) == 1
    cronjob = cronjobs[0]
    assert cronjob["spec"]["schedule"] == expected_schedule
    assert cronjob["spec"]["suspend"] is expected_suspend
    if expected_timezone is None:
        assert "timeZone" not in cronjob["spec"]
    else:
        assert cronjob["spec"]["timeZone"] == expected_timezone


@pytest.mark.skipif(HELM_BINARY is None, reason="helm is not installed")
@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (
            ("--set", "persistence.enabled=false"),
            "marketEnvironment.scheduledCollection.enabled requires persistence.enabled=true",
        ),
        (
            ("--set", "marketEnvironment.scheduledCollection.timezoneStrategy=unknown"),
            "marketEnvironment.scheduledCollection.timezoneStrategy must be native or controller",
        ),
        (
            ("--kube-version", "1.26.6"),
            "marketEnvironment.scheduledCollection.timezoneStrategy=native requires Kubernetes 1.27+",
        ),
        (
            (
                "--set",
                "marketEnvironment.scheduledCollection.timezoneStrategy=native",
                "--set",
                "marketEnvironment.scheduledCollection.timeZone=Etc/UTC",
            ),
            "marketEnvironment.scheduledCollection.native strategy requires timeZone=Asia/Shanghai",
        ),
        (
            (
                "--kube-version",
                "1.27.0",
                "--set",
                "marketEnvironment.scheduledCollection.timezoneStrategy=controller",
            ),
            "marketEnvironment.scheduledCollection.timezoneStrategy=controller is limited to Kubernetes 1.26",
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
            "marketEnvironment.scheduledCollection.controllerTimeZoneVerified=true is required for controller strategy",
        ),
        (
            ("--set-string", "marketEnvironment.settlementTime=1510"),
            "marketEnvironment.settlementTime must use numeric H:M",
        ),
        (
            ("--set-string", "marketEnvironment.scheduledCollection.schedule=60 16 * * 1-5"),
            "marketEnvironment.scheduledCollection.schedule and settlementTime must contain valid clock values",
        ),
        (
            ("--set-string", "marketEnvironment.scheduledCollection.schedule=09 15 * * 1-5"),
            "marketEnvironment.scheduledCollection.schedule must be strictly after settlementTime",
        ),
        (
            ("--set-string", "marketEnvironment.scheduledCollection.schedule=10 15 * * 1-5"),
            "marketEnvironment.scheduledCollection.schedule must be strictly after settlementTime",
        ),
        (
            ("--set-string", "marketEnvironment.scheduledCollection.schedule=15\\,45 17 * * 1-5"),
            "marketEnvironment.scheduledCollection.schedule must use one numeric M H * * 1-5 trigger",
        ),
        (
            ("--set-string", "marketEnvironment.scheduledCollection.schedule=15-45 17 * * 1-5"),
            "marketEnvironment.scheduledCollection.schedule must use one numeric M H * * 1-5 trigger",
        ),
        (
            ("--set-string", "marketEnvironment.scheduledCollection.schedule=*/15 17 * * 1-5"),
            "marketEnvironment.scheduledCollection.schedule must use one numeric M H * * 1-5 trigger",
        ),
        (
            ("--set-string", "marketEnvironment.scheduledCollection.schedule=15 17\\,18 * * 1-5"),
            "marketEnvironment.scheduledCollection.schedule must use one numeric M H * * 1-5 trigger",
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
                "--set",
                "marketEnvironment.settlementTime=15:00",
                "--set-string",
                "marketEnvironment.scheduledCollection.schedule=30 8 * * 1-5",
            ),
            "marketEnvironment.scheduledCollection.controller strategy requires settlementTime=15:10 for Shanghai 16:30 equivalence",
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
            "marketEnvironment.scheduledCollection.controller UTC schedule must equal 30 8 * * 1-5 for Shanghai 16:30",
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
                "marketEnvironment.scheduledCollection.suspend=true",
                "--set-string",
                "marketEnvironment.scheduledCollection.schedule=30 8 * * 1-5",
            ),
            "marketEnvironment.scheduledCollection.controller Shanghai schedule must equal 30 16 * * 1-5",
        ),
        (
            (
                "--kube-version",
                "1.26.6",
                "--set",
                "marketEnvironment.scheduledCollection.timezoneStrategy=controller",
                "--set",
                "marketEnvironment.scheduledCollection.controllerTimeZone=Europe/London",
                "--set",
                "marketEnvironment.scheduledCollection.controllerTimeZoneVerified=true",
                "--set",
                "marketEnvironment.scheduledCollection.suspend=true",
            ),
            "marketEnvironment.scheduledCollection.controllerTimeZone must be Etc/UTC or Asia/Shanghai",
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
            "marketEnvironment.scheduledCollection.controller strategy requires controllerCanaryVerified=true before suspend=false",
        ),
    ],
)
def test_helm_rejects_invalid_scheduling_profiles(arguments: tuple[str, ...], message: str) -> None:
    assert _render_helm_failure_message(
        "--set", "marketEnvironment.scheduledCollection.enabled=true", *arguments
    ) == message


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
    assert _render_helm_schema_failures(
        "--set-string", f"marketEnvironment.scheduledCollection.{field}=false"
    ) == [f"- at '/marketEnvironment/scheduledCollection/{field}': got string, want boolean"]


@pytest.mark.skipif(HELM_BINARY is None, reason="helm is not installed")
@pytest.mark.parametrize("enabled", ["true", "false"])
def test_helm_rejects_non_shanghai_business_timezone(enabled: str) -> None:
    assert _render_helm_schema_failures(
        "--set",
        f"marketEnvironment.scheduledCollection.enabled={enabled}",
        "--set",
        "marketEnvironment.timezone=Etc/UTC",
    ) == ["- at '/marketEnvironment/timezone': value must be 'Asia/Shanghai'"]


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


def test_truenas_disabled_profiles_explicitly_lock_both_safety_booleans() -> None:
    for path in (TRUENAS_DIRECT_ACCESS_VALUES, TRUENAS_SCHEDULED_OFF_VALUES):
        scheduled = _load_yaml(path)["marketEnvironment"]["scheduledCollection"]
        assert scheduled["enabled"] is False
        assert scheduled["suspend"] is True


@pytest.mark.skipif(HELM_BINARY is None, reason="helm is not installed")
def test_generic_overrides_disable_a_previously_active_values_stack() -> None:
    documents = _render_helm(
        "--kube-version",
        "1.26.6",
        "--values",
        str(TRUENAS_DIRECT_ACCESS_VALUES),
        "--values",
        str(TRUENAS_SCHEDULED_ACTIVE_VALUES),
        "--set",
        "marketEnvironment.scheduledCollection.enabled=false",
        "--set",
        "marketEnvironment.scheduledCollection.suspend=true",
    )

    assert all(document.get("kind") != "CronJob" for document in documents)


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

    for documents in (suspended, active):
        deployment = _resource(documents, "Deployment")
        cronjob = _resource(documents, "CronJob")
        deployment_pod = deployment["spec"]["template"]["spec"]
        deployment_container = deployment_pod["containers"][0]
        cron_pod = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        cron_container = cron_pod["containers"][0]

        assert cronjob["spec"]["concurrencyPolicy"] == "Forbid"
        assert cronjob["spec"]["startingDeadlineSeconds"] == 1800
        assert cronjob["spec"]["successfulJobsHistoryLimit"] == 3
        assert cronjob["spec"]["failedJobsHistoryLimit"] == 3
        assert cronjob["spec"]["jobTemplate"]["spec"]["backoffLimit"] == 0
        assert cronjob["spec"]["jobTemplate"]["spec"]["activeDeadlineSeconds"] == 3600
        assert cron_container["image"] == deployment_container["image"]
        assert cron_pod["volumes"][0] == deployment_pod["volumes"][0]
        assert cron_container["volumeMounts"][0] == deployment_container["volumeMounts"][0]
        assert _environment(cron_container) == _environment(deployment_container)
        assert _environment(cron_container)["MARKET_ENVIRONMENT_SNAPSHOT_PATH"] == "/data/snapshots.sqlite3"
        assert cron_pod["automountServiceAccountToken"] is False
        assert cron_pod["securityContext"] == deployment_pod["securityContext"]
        assert cron_pod["securityContext"]["runAsNonRoot"] is True
        assert cron_pod["securityContext"]["runAsUser"] == 10001
        assert cron_pod["securityContext"]["runAsGroup"] == 10001
        assert cron_pod["securityContext"]["fsGroup"] == 10001
        assert cron_pod["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}
        assert cron_container["securityContext"] == deployment_container["securityContext"]
        assert cron_container["securityContext"]["allowPrivilegeEscalation"] is False
        assert cron_container["securityContext"]["readOnlyRootFilesystem"] is True
        assert cron_container["securityContext"]["capabilities"]["drop"] == ["ALL"]
        assert cron_container["command"] == [
            "python",
            "-m",
            "src.market_environment.cli",
            "snapshots",
            "scheduled-refresh",
        ]


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


@pytest.mark.parametrize(
    "version",
    [
        "01.27.0",
        "1.027.0",
        "1.27.00",
        "1.27.0-.",
        "1.27.0-rc..1",
        "1.27.0-rc.01",
        "1.27.0+build..1",
        "1.27.0+build_1",
        "1.27.0-rc.1",
    ],
)
def test_checked_native_kustomize_rejects_invalid_or_prerelease_version_before_kubectl(
    tmp_path: Path, version: str
) -> None:
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
            version,
            "--kubectl",
            str(fake_kubectl),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert not marker.exists()


@pytest.mark.parametrize("guide", HELM_COMMAND_AUDIT_GUIDES, ids=lambda path: path.name)
def test_documented_generic_helm_writes_are_fail_closed(guide: Path) -> None:
    content = guide.read_text(encoding="utf-8")
    commands = _shell_commands(content)
    write_count, violations = _helm_write_violations(content)
    raw_retirement_commands = [
        command
        for command in commands
        if (invocation := _helm_invocation(command)) is not None
        and invocation[0] in {"rollback", "uninstall"}
    ]
    generic_entrypoints = [command for command in commands if _is_generic_deploy_entrypoint(command)]

    assert write_count == 0
    assert raw_retirement_commands == []
    if guide in GENERIC_RELEASE_GUIDES:
        assert generic_entrypoints
    assert violations == []


def test_helm_write_audit_accepts_supported_fences_and_multiline_safe_writes() -> None:
    content = (
        "```bash\n"
        "sudo helm upgrade release chart \\\n"
        "  --values values-production.yaml \\\n"
        "  --set marketEnvironment.scheduledCollection.enabled=false \\\n"
        "  --set marketEnvironment.scheduledCollection.suspend=true \\\n"
        "  --atomic\n"
        "```\n"
        "~~~~sh\n"
        "helm install release chart -f values-production.yaml "
        "--set=marketEnvironment.scheduledCollection.enabled=false "
        "--set=marketEnvironment.scheduledCollection.suspend=true --atomic=true\n"
        "~~~~\n"
        "````shell\nhelm status release\n````\n"
        "```bash title=read-only\nhelm --namespace a-stock status release\n````\n"
    )

    write_count, violations = _helm_write_violations(content)

    assert write_count == 2
    assert violations == []
    assert _fenced_blocks("````bash\nhelm rollback release 7\n```", "bash") == []


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (
            "```bash\nsudo helm upgrade release chart -f active.yaml --atomic\n```",
            "missing effective --set marketEnvironment.scheduledCollection.enabled=false",
        ),
        (
            "````sh\nhelm install release chart -f values.yaml "
            "--set marketEnvironment.scheduledCollection.enabled=false --atomic\n````",
            "missing effective --set marketEnvironment.scheduledCollection.suspend=true",
        ),
        (
            "```shell\nhelm upgrade release chart --reuse-values "
            "--set marketEnvironment.scheduledCollection.enabled=false "
            "--set marketEnvironment.scheduledCollection.suspend=true --atomic\n```",
            "--reuse-values is forbidden",
        ),
        (
            "~~~shell\nhelm rollback release 7 --namespace a-stock\n~~~",
            "helm rollback is forbidden",
        ),
        (
            "```bash\nhelm uninstall release --namespace a-stock\n```",
            "helm uninstall is forbidden",
        ),
        (
            "```bash\nhelm --namespace a-stock rollback release 7\n````",
            "helm rollback is forbidden",
        ),
        (
            "~~~shell\nsudo -n helm rollback release 7\n~~~~",
            "helm rollback is forbidden",
        ),
        (
            "```bash\nenv RELEASE=a-stock helm rollback release 7\n```",
            "helm rollback is forbidden",
        ),
        (
            "```bash title=retirement\ncommand helm uninstall release\n```",
            "helm uninstall is forbidden",
        ),
        (
            "```bash\nif true; then helm rollback release 7; fi\n```",
            "helm rollback is forbidden",
        ),
        (
            "```bash\ntrue # comment \\\nhelm rollback release 7\n```",
            "helm rollback is forbidden",
        ),
        (
            "```bash\nprintf ready | helm uninstall release\n```",
            "helm uninstall is forbidden",
        ),
        (
            "```bash\ntrue && helm upgrade release chart \\\n"
            "  --atomic; printf '%s' '--values values.yaml "
            "--set marketEnvironment.scheduledCollection.enabled=false "
            "--set marketEnvironment.scheduledCollection.suspend=true'\n```",
            "missing effective --set marketEnvironment.scheduledCollection.enabled=false",
        ),
        (
            "```bash\nhelm upgrade release chart # --values values.yaml "
            "--set marketEnvironment.scheduledCollection.enabled=false "
            "--set marketEnvironment.scheduledCollection.suspend=true --atomic\n```",
            "missing effective --set marketEnvironment.scheduledCollection.enabled=false",
        ),
        (
            "```bash\nhelm upgrade release chart -f values.yaml "
            "--set marketEnvironment.scheduledCollection.enabled=false "
            "--set marketEnvironment.scheduledCollection.suspend=true "
            "--set marketEnvironment.scheduledCollection.enabled=true --atomic\n```",
            "missing effective --set marketEnvironment.scheduledCollection.enabled=false",
        ),
        (
            "```bash\nhelm upgrade release chart -f values.yaml "
            "--set marketEnvironment.scheduledCollection.enabled=false "
            "--set marketEnvironment.scheduledCollection.suspend=true "
            "--atomic --atomic=false\n```",
            "missing --atomic",
        ),
    ],
    ids=[
        "sudo-upgrade",
        "standalone-install",
        "reuse-values",
        "rollback",
        "uninstall",
        "global-flag-before-rollback",
        "sudo-option",
        "env-wrapper",
        "command-wrapper-and-info-attrs",
        "if-then",
        "comment-backslash-does-not-continue",
        "pipe-boundary",
        "and-semicolon-boundaries",
        "inline-comment",
        "later-set-wins",
        "later-boolean-flag-wins",
    ],
)
def test_helm_write_audit_rejects_unsafe_shell_commands(content: str, expected: str) -> None:
    _, violations = _helm_write_violations(content)

    assert any(expected in violation for violation in violations)


def test_truenas_guide_values_example_is_fail_closed() -> None:
    content = TRUENAS_GUIDE.read_text(encoding="utf-8")
    values = next(
        yaml.safe_load(block)
        for block in _fenced_blocks(content, "yaml")
        if "marketEnvironment:" in block
    )
    scheduled = values["marketEnvironment"]["scheduledCollection"]

    assert scheduled["enabled"] is False
    assert scheduled["suspend"] is True


def test_runbook_does_not_offer_direct_schedule_mutations() -> None:
    content = RUNBOOK.read_text(encoding="utf-8")
    commands = _shell_commands(content)

    assert all(command[:3] != ("kubectl", "patch", "cronjob") for command in commands)
    assert "kubectl create job -n a-stock --from=cronjob" not in content
