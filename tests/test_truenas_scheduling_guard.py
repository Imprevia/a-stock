from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy-truenas-k3s.sh"
VALIDATOR = ROOT / "scripts" / "validate-scheduling-packet.py"
BASELINE = ROOT / "deploy" / "truenas" / "values-secure-manual-collection.yaml"
COMPONENT_FIXTURE = ROOT / "tests" / "fixtures" / "truenas_component_baseline.yaml"
DEPLOY_ENV_EXAMPLE = ROOT / "deploy" / "truenas" / "deploy.env.example"
REAL_HELM = shutil.which("helm")
REAL_GIT = shutil.which("git")


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _cronjob(name: str, variant: str) -> str:
    labels = (
        {"unrelated.example/owner": "drifted"}
        if variant == "label-drift"
        else {"app.kubernetes.io/instance": "a-stock"}
    )
    return yaml.safe_dump(
        {
            "apiVersion": "batch/v1",
            "kind": "CronJob",
            "metadata": {
                "name": name,
                "namespace": "a-stock",
                "labels": labels,
            },
            "spec": {"suspend": variant == "suspended"},
        },
        sort_keys=False,
    )


def _job(
    name: str = "a-stock-schema-migration",
    *,
    failed: int = 0,
    succeeded: int = 0,
    active: int = 0,
) -> dict[str, object]:
    terminal_type = "Failed" if failed else "Complete"
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": name,
            "namespace": "a-stock",
            "uid": f"{name}-uid",
        },
        "status": {
            "active": active,
            "failed": failed,
            "succeeded": succeeded,
            "conditions": (
                [{"type": terminal_type, "status": "True", "reason": "fixture"}]
                if not active
                else []
            ),
        },
    }


def _run_guarded_deploy(
    tmp_path: Path,
    *,
    component: str = "database",
    identity: str | None = None,
    source: str = "live",
    variant: str = "active",
    failure: str = "none",
    fullname_override: str | None = None,
    namespace_jobs: list[dict[str, object]] | None = None,
    legacy_migration_enabled: bool = False,
) -> tuple[subprocess.CompletedProcess[str], list[str], list[str]]:
    assert REAL_HELM is not None
    assert REAL_GIT is not None

    values = BASELINE
    if fullname_override is not None or legacy_migration_enabled:
        payload = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))
        if fullname_override is not None:
            payload["fullnameOverride"] = fullname_override
        if legacy_migration_enabled:
            payload["database"].setdefault("migration", {}).update(
                {"enabled": True, "sourceClaim": "a-stock-data", "apply": False}
            )
        values = tmp_path / "values.yaml"
        values.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    stored_manifest = tmp_path / "stored-manifest.yaml"
    if source == "stored" and identity is not None:
        stored_manifest.write_text(_cronjob(identity, variant), encoding="utf-8")
    else:
        stored_manifest.write_text(
            "apiVersion: v1\nkind: ConfigMap\nmetadata:\n"
            "  name: retained-safe-config\n  namespace: a-stock\n",
            encoding="utf-8",
        )

    live_manifest = tmp_path / "live-cronjob.yaml"
    if source == "live" and identity is not None:
        live_manifest.write_text(_cronjob(identity, variant), encoding="utf-8")
    else:
        live_manifest.write_text("", encoding="utf-8")

    jobs_manifest = tmp_path / "jobs.json"
    jobs_manifest.write_text(
        json.dumps({"apiVersion": "v1", "kind": "List", "items": namespace_jobs or []}),
        encoding="utf-8",
    )
    failed_job_manifest = tmp_path / "failed-job.json"
    failed_job_manifest.write_text(
        json.dumps(
            {
                "apiVersion": "v1",
                "kind": "List",
                "items": [_job(failed=1)],
            }
        ),
        encoding="utf-8",
    )

    calls = tmp_path / "calls.log"
    mutations = tmp_path / "mutations.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    _write_executable(
        fake_bin / "helm",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f"printf 'helm %s\\n' \"$*\" >> {shlex.quote(str(calls))}\n"
        "case \"$1\" in\n"
        "  lint|template) exec \"$REAL_HELM\" \"$@\" ;;\n"
        "  list)\n"
        "    if [[ \"$GUARD_FAILURE\" == helm-list ]]; then exit 61; fi\n"
        "    printf '[{\"name\":\"a-stock\"}]\\n'\n"
        "    ;;\n"
        "  get)\n"
        "    if [[ \"$GUARD_FAILURE\" == helm-get ]]; then exit 62; fi\n"
        "    cat \"$STORED_MANIFEST\"\n"
        "    ;;\n"
        "  upgrade)\n"
        f"    printf 'helm-upgrade %s\\n' \"$*\" >> {shlex.quote(str(mutations))}\n"
        "    if [[ \"$GUARD_FAILURE\" == helm-upgrade-failed-job ]]; then\n"
        "      cp \"$FAILED_JOB_MANIFEST\" \"$JOBS_MANIFEST\"\n"
        "    fi\n"
        "    exit 73\n"
        "    ;;\n"
        "  *) exit 97 ;;\n"
        "esac\n",
    )

    _write_executable(
        fake_bin / "kubectl",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f"printf 'kubectl %s\\n' \"$*\" >> {shlex.quote(str(calls))}\n"
        "if [[ \"$*\" == *\"get nodes\"* ]]; then printf amd64; exit 0; fi\n"
        "if [[ \"$*\" == *\"get --raw /version\"* ]]; then\n"
        "  printf '{\"gitVersion\":\"v1.26.6+k3s1\"}'; exit 0\n"
        "fi\n"
        "if [[ \"${1:-}\" == get && \"${2:-}\" == jobs ]]; then\n"
        "  cat \"$JOBS_MANIFEST\"; exit 0\n"
        "fi\n"
        "if [[ \"${1:-}\" == get && \"${2:-}\" == cronjob ]]; then\n"
        "  name=\"${3:-}\"\n"
        "  if [[ \"$GUARD_FAILURE\" == kubectl-silent ]]; then exit 63; fi\n"
        "  if [[ \"$GUARD_FAILURE\" == kubectl-diagnostic ]]; then\n"
        "    printf 'forbidden\\n' >&2; exit 64\n"
        "  fi\n"
        "  if [[ \"$GUARD_FAILURE\" == kubectl-malformed ]]; then\n"
        "    printf 'not: [valid\\n'; exit 0\n"
        "  fi\n"
        "  if [[ -n \"$LIVE_IDENTITY\" && \"$name\" == \"$LIVE_IDENTITY\" ]]; then\n"
        "    cat \"$LIVE_MANIFEST\"\n"
        "  fi\n"
        "  exit 0\n"
        "fi\n"
        "case \" $* \" in\n"
        "  *\" apply \"*|*\" patch \"*|*\" delete \"*|*\" create \"*)\n"
        f"    printf 'kubectl-mutation %s\\n' \"$*\" >> {shlex.quote(str(mutations))}\n"
        "    exit 74\n"
        "    ;;\n"
        "esac\n"
        "exit 0\n",
    )

    _write_executable(
        fake_bin / "ssh",
        "#!/usr/bin/env bash\n"
        f"printf 'ssh %s\\n' \"$*\" >> {shlex.quote(str(calls))}\n"
        "exit 0\n",
    )
    for command in ("podman", "curl", "scp"):
        _write_executable(
            fake_bin / command,
            "#!/usr/bin/env bash\n"
            f"printf '{command} %s\\n' \"$*\" >> {shlex.quote(str(calls))}\n"
            f"printf '{command} %s\\n' \"$*\" >> {shlex.quote(str(mutations))}\n"
            "exit 75\n",
        )
    _write_executable(fake_bin / "nc", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(
        fake_bin / "git",
        "#!/usr/bin/env bash\n"
        "for argument in \"$@\"; do\n"
        "  if [[ \"$argument\" == status ]]; then exit 0; fi\n"
        "done\n"
        "exec \"$REAL_GIT\" \"$@\"\n",
    )

    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("fixture\n", encoding="utf-8")
    head = subprocess.run(
        [REAL_GIT, "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    env_file = tmp_path / "deploy.env"
    env_file.write_text(
        "\n".join(
            [
                f"REPO_DIR={ROOT}",
                "TRUENAS_HOST=192.0.2.10",
                "TRUENAS_SSH_USER=tester",
                "REMOTE_IMAGE_DIR=/fixture/images",
                "K3S_API_SSH_TUNNEL=false",
                f"KUBECONFIG={kubeconfig}",
                f"HELM_VALUES_FILE={values}",
                "IMAGE_TAG=guard-test",
                f"REVIEWED_GIT_HEAD={head}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--env-file",
            str(env_file),
            "--component",
            component,
        ],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "REAL_HELM": REAL_HELM,
            "REAL_GIT": REAL_GIT,
            "STORED_MANIFEST": str(stored_manifest),
            "LIVE_MANIFEST": str(live_manifest),
            "LIVE_IDENTITY": identity if source == "live" and identity else "",
            "JOBS_MANIFEST": str(jobs_manifest),
            "FAILED_JOB_MANIFEST": str(failed_job_manifest),
            "GUARD_FAILURE": failure,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return (
        completed,
        calls.read_text(encoding="utf-8").splitlines() if calls.exists() else [],
        mutations.read_text(encoding="utf-8").splitlines()
        if mutations.exists()
        else [],
    )


def _bash_function_source(name: str) -> str:
    script = SCRIPT.read_text(encoding="utf-8")
    start = script.index(f"{name}() {{")
    end = script.index("\n}\n", start) + len("\n}\n")
    return script[start:end]


def test_help_exposes_only_retained_components_and_no_scheduling_modes() -> None:
    completed = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "--component {all,database,service}" in completed.stdout
    for retired in (
        "schedule",
        "--offline-render",
        "--read-only-discovery",
        "--server-dry-run",
        "--release-suspended",
        "--activate-schedule",
        "--disable-schedule",
        "--scheduling-overlay",
        "--repair-sectors-off-release",
    ):
        assert retired not in completed.stdout


@pytest.mark.parametrize(
    "argument",
    [
        "--offline-render",
        "--read-only-discovery",
        "--server-dry-run",
        "--release-suspended",
        "--activate-schedule",
        "--disable-schedule",
        "--scheduling-overlay",
        "--repair-sectors-off-release",
    ],
)
def test_retired_modes_fail_before_environment_or_target_access(argument: str) -> None:
    completed = subprocess.run(
        ["bash", str(SCRIPT), argument],
        env={**os.environ, "DEPLOY_ENV_FILE": "/definitely/not/present"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert f"unknown argument: {argument}" in completed.stderr
    assert "environment file not found" not in completed.stderr


def test_retired_schedule_component_fails_before_environment_or_target_access() -> None:
    completed = subprocess.run(
        ["bash", str(SCRIPT), "--component", "schedule"],
        env={**os.environ, "DEPLOY_ENV_FILE": "/definitely/not/present"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "--component must be one of: all|database|service" in completed.stderr
    assert "environment file not found" not in completed.stderr


@pytest.mark.skipif(REAL_HELM is None or REAL_GIT is None, reason="helm/git unavailable")
@pytest.mark.parametrize(
    "identity", ["a-stock-data-collection", "market-data-collection"]
)
@pytest.mark.parametrize("source", ["stored", "live"])
@pytest.mark.parametrize("variant", ["active", "suspended", "label-drift"])
def test_each_retired_identity_is_rejected_regardless_of_state_or_labels(
    tmp_path: Path, identity: str, source: str, variant: str
) -> None:
    completed, calls, mutations = _run_guarded_deploy(
        tmp_path,
        identity=identity,
        source=source,
        variant=variant,
    )

    assert completed.returncode != 0
    assert identity in completed.stderr
    assert not mutations
    assert not any(call.startswith("helm upgrade ") for call in calls)
    assert not any(call.startswith("podman ") for call in calls)


@pytest.mark.skipif(REAL_HELM is None or REAL_GIT is None, reason="helm/git unavailable")
@pytest.mark.parametrize("component", ["all", "database", "service"])
def test_every_ordinary_component_blocks_retained_cronjob_before_build_or_write(
    tmp_path: Path, component: str
) -> None:
    completed, calls, mutations = _run_guarded_deploy(
        tmp_path,
        component=component,
        identity="a-stock-data-collection",
        source="live",
        variant="suspended",
    )

    assert completed.returncode != 0
    assert "retired CronJob a-stock-data-collection still exists" in completed.stderr
    assert not mutations
    assert not any(call.startswith("podman ") for call in calls)
    assert not any(call.startswith("helm upgrade ") for call in calls)


@pytest.mark.skipif(REAL_HELM is None or REAL_GIT is None, reason="helm/git unavailable")
@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("helm-list", "could not determine whether the target Helm release already exists"),
        ("helm-get", "could not read the existing Helm release manifest"),
        ("kubectl-silent", "API/auth/transport uncertainty"),
        ("kubectl-diagnostic", "API/auth/transport uncertainty"),
        ("kubectl-malformed", "API/auth/transport uncertainty"),
    ],
)
def test_guard_fails_closed_when_stored_or_live_read_is_uncertain(
    tmp_path: Path, failure: str, message: str
) -> None:
    completed, calls, mutations = _run_guarded_deploy(tmp_path, failure=failure)

    assert completed.returncode != 0
    assert message in completed.stderr
    assert not mutations
    assert not any(call.startswith("helm upgrade ") for call in calls)


@pytest.mark.skipif(REAL_HELM is None or REAL_GIT is None, reason="helm/git unavailable")
@pytest.mark.parametrize(
    "job",
    [
        _job(name="unrelated-complete", succeeded=1),
        _job(name="unrelated-failed", failed=1),
        _job(name="unrelated-active", active=1),
    ],
    ids=["complete", "failed", "active"],
)
def test_any_existing_namespace_job_blocks_before_helm_write(
    tmp_path: Path, job: dict[str, object]
) -> None:
    completed, calls, mutations = _run_guarded_deploy(
        tmp_path,
        namespace_jobs=[job],
    )

    assert completed.returncode != 0
    assert "Job" in completed.stderr
    assert not any(call.startswith("helm upgrade ") for call in calls)
    assert not mutations


@pytest.mark.skipif(REAL_HELM is None or REAL_GIT is None, reason="helm/git unavailable")
def test_database_component_rejects_legacy_and_schema_migration_jobs_together(
    tmp_path: Path,
) -> None:
    completed, calls, mutations = _run_guarded_deploy(
        tmp_path,
        legacy_migration_enabled=True,
    )

    assert completed.returncode != 0
    assert "exactly one" in completed.stderr
    assert "legacy SQLite migration must be disabled" in completed.stderr
    assert not any(call.startswith("helm upgrade ") for call in calls)
    assert not mutations


@pytest.mark.skipif(REAL_HELM is None or REAL_GIT is None, reason="helm/git unavailable")
def test_both_identities_absent_allows_database_deploy_to_reach_first_write(
    tmp_path: Path,
) -> None:
    completed, calls, mutations = _run_guarded_deploy(tmp_path)

    assert completed.returncode == 73
    assert completed.stdout.count("both former CronJob identities are absent") >= 2
    assert any(call.startswith("helm upgrade ") for call in calls)
    assert len(mutations) == 1
    assert mutations[0].startswith("helm-upgrade ")


def test_component_helm_write_hook_flags_are_explicit(tmp_path: Path) -> None:
    calls = tmp_path / "helm-calls.log"
    function_source = _bash_function_source("deploy_helm_upgrade_with_component")
    completed = subprocess.run(
        [
            "bash",
            "-c",
            "\n".join(
                [
                    "set -eu",
                    "log() { :; }",
                    "warn() { :; }",
                    "render_release_packet() { return 0; }",
                    'helm() { printf "%s\\n" "$*" >> "$CALLS"; }',
                    'OPERATION_CHART_DIR="/fixture/chart"',
                    'VALUES_FILE="/fixture/values.yaml"',
                    'TARGET_KUBERNETES_VERSION="1.26.6"',
                    'RELEASE_NAME="a-stock"',
                    'NAMESPACE="a-stock"',
                    'HELM_TIMEOUT="5m"',
                    function_source,
                    'deploy_helm_upgrade_with_component database "registry.local/a-stock" "candidate"',
                    'deploy_helm_upgrade_with_component service "registry.local/a-stock" "candidate"',
                ]
            ),
        ],
        env={**os.environ, "CALLS": str(calls)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    database, service = [shlex.split(line) for line in calls.read_text().splitlines()]
    assert "component=database" in database
    assert "--no-hooks" not in database
    assert "component=service" in service
    assert service.count("--no-hooks") == 1

    script = SCRIPT.read_text(encoding="utf-8")
    final_all = script.split("log 'component=all consolidating complete Helm release manifest'", 1)[1]
    final_all = final_all.split("FULL_POST_RENDER=", 1)[0]
    assert "--set component=all" in final_all
    assert final_all.count("--no-hooks") == 1


def test_automation_refresh_write_is_hook_free_and_does_not_build_or_import() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    marker = (
        'if [[ "$CONTROLLED_AUTOMATION_REFRESH_OPERATION" == true ]]; then\n'
        '  FROZEN_IMAGE='
    )
    block = script.split(marker, 1)[1].split(
        '\nfi\n\nif [[ "$CONTROLLED_MANUAL_REFRESH_OPERATION" == true ]]; then', 1
    )[0]

    assert "helm upgrade" in block
    assert block.count("--no-hooks") == 1
    assert "--atomic" in block
    assert "--wait" in block
    assert "podman " not in block
    assert "scp " not in block
    assert "images import" not in block
    assert "alembic" not in block
    assert "collection-runs/full" not in block


@pytest.mark.parametrize(
    ("counts", "expected"), [("0|0|0", 0), ("1|0|0", 1), ("0|1|0", 1), ("0|0|1", 1)]
)
def test_automation_refresh_writer_guard_requires_zero_counts(
    counts: str, expected: int
) -> None:
    function_source = _bash_function_source("require_no_active_collection_writers")
    completed = subprocess.run(
        [
            "bash",
            "-c",
            "\n".join(
                [
                    "set -eu",
                    "log() { :; }",
                    "warn() { :; }",
                    'kubectl() { printf "%s\\n" "$WRITER_COUNTS"; }',
                    'RELEASE_NAME="a-stock"',
                    'NAMESPACE="a-stock"',
                    function_source,
                    "require_no_active_collection_writers",
                ]
            ),
        ],
        env={**os.environ, "WRITER_COUNTS": counts},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == expected


def test_database_failure_stops_later_component_phases(tmp_path: Path) -> None:
    attempts = tmp_path / "component-attempts.log"
    function_source = _bash_function_source("deploy_step_or_exit")
    completed = subprocess.run(
        [
            "bash",
            "-c",
            "\n".join(
                [
                    "set -eu",
                    "log() { :; }",
                    'verify_component_prerequisites() { return 0; }',
                    'deploy_component_step() { printf "%s\\n" "$1" >> "$ATTEMPTS"; return 73; }',
                    'COMPLETED_COMPONENTS=""',
                    'FAILED_COMPONENT=""',
                    'FAILED_REASON=""',
                    function_source,
                    'deploy_step_or_exit database repository tag',
                    'COMPLETED_COMPONENTS+=" database"',
                    'deploy_step_or_exit service repository tag',
                    'printf "final-all\\n" >> "$ATTEMPTS"',
                ]
            ),
        ],
        env={**os.environ, "ATTEMPTS": str(attempts)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 73
    assert attempts.read_text(encoding="utf-8").splitlines() == ["database"]


@pytest.mark.skipif(REAL_HELM is None or REAL_GIT is None, reason="helm/git unavailable")
def test_failed_database_hook_is_retained_without_job_delete(
    tmp_path: Path,
) -> None:
    completed, calls, mutations = _run_guarded_deploy(
        tmp_path,
        failure="helm-upgrade-failed-job",
    )

    assert completed.returncode == 73
    upgrades = [call for call in calls if call.startswith("helm upgrade ")]
    assert len(upgrades) == 1
    assert "component=database" in shlex.split(upgrades[0])
    assert "--no-hooks" not in shlex.split(upgrades[0])
    assert not any("kubectl delete job" in call for call in calls)
    assert not any(mutation.startswith("kubectl-mutation ") for mutation in mutations)
    jobs = json.loads((tmp_path / "jobs.json").read_text(encoding="utf-8"))["items"]
    assert jobs == [_job(failed=1)]


@pytest.mark.skipif(REAL_HELM is None or REAL_GIT is None, reason="helm/git unavailable")
def test_release_derived_identity_uses_historical_helper_and_deduplicates_legacy_name(
    tmp_path: Path,
) -> None:
    completed, calls, mutations = _run_guarded_deploy(
        tmp_path,
        fullname_override="market",
    )

    assert completed.returncode == 73
    exact_reads = [
        call
        for call in calls
        if call.startswith("kubectl get cronjob market-data-collection ")
    ]
    assert len(exact_reads) == 2
    assert not any("a-stock-data-collection" in call for call in calls)
    assert len(mutations) == 1


def test_retired_creation_and_positive_validation_paths_are_absent() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    validator = VALIDATOR.read_text(encoding="utf-8")
    deploy_env = DEPLOY_ENV_EXAMPLE.read_text(encoding="utf-8")
    fixture = yaml.safe_load(COMPONENT_FIXTURE.read_text(encoding="utf-8"))

    for forbidden in (
        "kubectl patch cronjob",
        "kubectl delete cronjob",
        "kubectl delete job",
        "kubectl create",
        "component=schedule",
        "scheduledCollection",
        "validate-activation-window",
        "compare-add-suspended",
        "compare-suspend-only",
        "compare-remove-cronjob",
    ):
        assert forbidden not in script
    for retired_command in (
        "validate-activation-window",
        "validate-generic-deploy-values",
        "inspect",
        "extract-suspended",
        "compare-add-suspended",
        "compare-suspend-only",
        "compare-remove-cronjob",
    ):
        assert retired_command not in validator
    assert "SCHEDULED_COLLECTION_" not in deploy_env
    assert "SCHEDULING_OVERLAY" not in deploy_env
    assert "scheduling" not in fixture
