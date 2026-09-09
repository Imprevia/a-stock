from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy-truenas-k3s.sh"
VALIDATOR = ROOT / "scripts" / "validate-scheduling-packet.py"
CHART = ROOT / "deploy" / "helm" / "a-stock"
BASELINE = ROOT / "deploy" / "truenas" / "values-secure-manual-collection.yaml"
SUSPENDED = ROOT / "deploy" / "truenas" / "values-scheduled-suspended.yaml"
ACTIVE = ROOT / "deploy" / "truenas" / "values-scheduled-active.yaml"
OFF = ROOT / "deploy" / "truenas" / "values-scheduled-off.yaml"
HELM = shutil.which("helm")


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
        ["python3", str(VALIDATOR), command, *arguments],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )


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
    completed = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--offline-render",
            "--baseline-values",
            str(CHART / "values.yaml"),
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
    completed = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--offline-render",
            "--baseline-values",
            str(CHART / "values.yaml"),
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
    completed = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--offline-render",
            "--baseline-values",
            str(CHART / "values.yaml"),
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
    return fake_bin, marker


def _write_env(path: Path, repo: Path, baseline: Path, overlay: Path | None) -> None:
    lines = [
        f"REPO_DIR={repo}",
        "TRUENAS_HOST=192.0.2.10",
        "TRUENAS_SSH_USER=tester",
        f"HELM_VALUES_FILE={baseline}",
        "REMOTE_IMAGE_DIR=/unreachable",
    ]
    if overlay is not None:
        lines.append(f"SCHEDULING_OVERLAY_FILE={overlay}")
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
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
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
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "must be disabled, got active" in completed.stderr
    assert not marker.exists()


def _render(chart: Path, baseline: Path, overlay: Path, state: str) -> str:
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


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_release_comparators_allow_only_add_suspended_and_suspend_flip(tmp_path: Path) -> None:
    disabled = _render(CHART, BASELINE, OFF, "disabled")
    suspended = _render(CHART, BASELINE, SUSPENDED, "suspended")
    active = _render(CHART, BASELINE, ACTIVE, "active")
    disabled_path = tmp_path / "disabled.yaml"
    suspended_path = tmp_path / "suspended.yaml"
    active_path = tmp_path / "active.yaml"
    disabled_path.write_text(disabled, encoding="utf-8")
    suspended_path.write_text(suspended, encoding="utf-8")
    active_path.write_text(active, encoding="utf-8")

    add_result = subprocess.run(
        [
            "python3",
            str(VALIDATOR),
            "compare-add-suspended",
            "--release-name",
            "a-stock",
            "--namespace",
            "a-stock",
            "--current",
            str(disabled_path),
            "--desired",
            str(suspended_path),
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
            "a-stock",
            "--namespace",
            "a-stock",
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
            "a-stock",
            "--namespace",
            "a-stock",
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
    (repo / "deploy" / "truenas").mkdir(parents=True)
    shutil.copytree(CHART, repo / "deploy" / "helm" / "a-stock")
    shutil.copy2(SCRIPT, repo / "scripts" / SCRIPT.name)
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
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
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
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
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
    env_file = tmp_path / "deploy.env"
    _write_env(env_file, ROOT, CHART / "values.yaml", overlay)

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
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
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
    outcome: str = "off",
    release_present: bool = True,
) -> tuple[subprocess.CompletedProcess[str], str, dict]:
    repo, baseline, suspended, active, off, _ = _prepare_reviewed_repo(tmp_path)
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

    fake_bin = tmp_path / "generic-bin"
    fake_bin.mkdir()
    calls = tmp_path / "generic-calls"
    released = tmp_path / "generic-released"
    post_read_failed = tmp_path / "generic-post-read-failed"
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
        f"      off) cp {off_state} {live_state}; touch {released} ;;\n"
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
        f"if [[ \"$1\" == get && \"$2\" == cronjob ]]; then cat {live_state}; exit 0; fi\n"
        "if [[ \"$1\" == patch && \"$2\" == cronjob ]]; then\n"
        f"  cp {suspended_state} {live_state}\n"
        "  exit 0\n"
        "fi\n"
        f"if [[ \"$*\" == *\"get deployment\"* && -f {released} && \"$GENERIC_UPGRADE_OUTCOME\" == post-read-active && ! -f {post_read_failed} ]]; then touch {post_read_failed}; exit 96; fi\n"
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
    ssh_wrapper = fake_bin / "ssh"
    ssh_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'ssh %s\\n' \"$*\" >> {calls}\n"
        "if [[ \"$GENERIC_UPGRADE_OUTCOME\" == pre-write-active && \"$*\" == *\"images import\"* ]]; then\n"
        f"  cp {active_state} {live_state}\n"
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
            "exit 0\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)

    kubeconfig = tmp_path / "generic-kubeconfig"
    kubeconfig.write_text("fixture", encoding="utf-8")
    env_file = tmp_path / "generic.env"
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
                "",
            ]
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        ["bash", str(repo / "scripts" / SCRIPT.name), "--env-file", str(env_file)],
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "REAL_HELM": HELM or "helm",
            "GENERIC_UPGRADE_OUTCOME": outcome,
            "GENERIC_RELEASE_PRESENT": str(release_present).lower(),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    call_log = calls.read_text(encoding="utf-8") if calls.exists() else ""
    return completed, call_log, json.loads(live_state.read_text(encoding="utf-8"))


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
    assert live["items"] == []
    assert "patch cronjob" not in calls


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
            "research",
            "--namespace",
            "market-data",
        ],
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
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


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
def test_server_dry_run_submits_only_exact_suspended_cronjob(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "deploy" / "truenas").mkdir(parents=True)
    shutil.copytree(CHART, repo / "deploy" / "helm" / "a-stock")
    shutil.copy2(SCRIPT, repo / "scripts" / SCRIPT.name)
    shutil.copy2(VALIDATOR, repo / "scripts" / VALIDATOR.name)
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
            "research",
            str(repo / "deploy" / "helm" / "a-stock"),
            "--namespace",
            "market-data",
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
                "SERVER_DRY_RUN_AUTHORIZED=true",
                "GATE_B_AUTHORIZATION_REF=reviewed-gate-b-packet",
                f"REVIEWED_GIT_HEAD={reviewed_head}",
                f"REVIEWED_CHART_SHA256={_chart_hash(repo)}",
                f"REVIEWED_BASELINE_SHA256={hashlib.sha256(baseline.read_bytes()).hexdigest()}",
                f"REVIEWED_OVERLAY_SHA256={hashlib.sha256(suspended.read_bytes()).hexdigest()}",
                f"REVIEWED_RENDER_SHA256={hashlib.sha256(rendered.encode()).hexdigest()}",
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
            "research",
            "--namespace",
            "market-data",
        ],
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "REAL_HELM": HELM,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    arguments = kubectl_args.read_text(encoding="utf-8")
    assert arguments == "create --namespace market-data --dry-run=server --validate=true -f -\n"
    assert "apply" not in target_calls.read_text(encoding="utf-8")
    documents = [item for item in yaml.safe_load_all(submitted.read_text(encoding="utf-8")) if item]
    assert len(documents) == 1
    cronjob = documents[0]
    assert cronjob["apiVersion"] == "batch/v1"
    assert cronjob["kind"] == "CronJob"
    assert cronjob["metadata"]["name"] == "research-a-stock-data-collection"
    assert cronjob["metadata"]["namespace"] == "market-data"
    assert cronjob["spec"]["suspend"] is True


@pytest.mark.skipif(HELM is None, reason="helm is not installed")
@pytest.mark.parametrize(
    (
        "operation",
        "current_name",
        "selected_name",
        "authorization",
        "failure_mode",
        "expected_success",
    ),
    [
        (
            "--release-suspended",
            "values-scheduled-off.yaml",
            "values-scheduled-suspended.yaml",
            "SUSPENDED_RELEASE_AUTHORIZED=true\nGATE_B_AUTHORIZATION_REF=reviewed-gate-b-packet",
            None,
            True,
        ),
        (
            "--activate-schedule",
            "values-scheduled-suspended.yaml",
            "values-scheduled-active.yaml",
            "SCHEDULE_ACTIVATION_AUTHORIZED=true\nGATE_C_AUTHORIZATION_REF=reviewed-gate-c-decision\nGATE_C_CATCH_UP_MODE=next-schedule",
            None,
            True,
        ),
        (
            "--disable-schedule",
            "values-scheduled-suspended.yaml",
            "values-scheduled-off.yaml",
            "SCHEDULE_ROLLBACK_AUTHORIZED=true",
            None,
            True,
        ),
        (
            "--activate-schedule",
            "values-scheduled-suspended.yaml",
            "values-scheduled-active.yaml",
            "SCHEDULE_ACTIVATION_AUTHORIZED=true\nGATE_C_AUTHORIZATION_REF=reviewed-gate-c-decision\nGATE_C_CATCH_UP_MODE=next-schedule",
            "pre-live-drift",
            False,
        ),
        (
            "--activate-schedule",
            "values-scheduled-suspended.yaml",
            "values-scheduled-active.yaml",
            "SCHEDULE_ACTIVATION_AUTHORIZED=true\nGATE_C_AUTHORIZATION_REF=reviewed-gate-c-decision\nGATE_C_CATCH_UP_MODE=next-schedule",
            "post-live-drift",
            False,
        ),
        (
            "--activate-schedule",
            "values-scheduled-suspended.yaml",
            "values-scheduled-active.yaml",
            "SCHEDULE_ACTIVATION_AUTHORIZED=true\nGATE_C_AUTHORIZATION_REF=reviewed-gate-c-decision\nGATE_C_CATCH_UP_MODE=next-schedule",
            "activation-window-failure",
            False,
        ),
        (
            "--activate-schedule",
            "values-scheduled-suspended.yaml",
            "values-scheduled-active.yaml",
            "SCHEDULE_ACTIVATION_AUTHORIZED=true\nGATE_C_AUTHORIZATION_REF=reviewed-gate-c-decision\nGATE_C_CATCH_UP_MODE=next-schedule",
            "post-live-capture-failure",
            False,
        ),
        (
            "--activate-schedule",
            "values-scheduled-suspended.yaml",
            "values-scheduled-active.yaml",
            "SCHEDULE_ACTIVATION_AUTHORIZED=true\nGATE_C_AUTHORIZATION_REF=reviewed-gate-c-decision\nGATE_C_CATCH_UP_MODE=next-schedule",
            "signal-after-helm",
            False,
        ),
        (
            "--activate-schedule",
            "values-scheduled-suspended.yaml",
            "values-scheduled-active.yaml",
            "SCHEDULE_ACTIVATION_AUTHORIZED=true\nGATE_C_AUTHORIZATION_REF=reviewed-gate-c-decision\nGATE_C_CATCH_UP_MODE=next-schedule",
            "pre-write-activation-window-failure",
            False,
        ),
        (
            "--activate-schedule",
            "values-scheduled-suspended.yaml",
            "values-scheduled-active.yaml",
            "SCHEDULE_ACTIVATION_AUTHORIZED=true\nGATE_C_AUTHORIZATION_REF=reviewed-gate-c-decision\nGATE_C_CATCH_UP_MODE=next-schedule",
            "helm-failure",
            False,
        ),
        (
            "--activate-schedule",
            "values-scheduled-suspended.yaml",
            "values-scheduled-active.yaml",
            "SCHEDULE_ACTIVATION_AUTHORIZED=true\nGATE_C_AUTHORIZATION_REF=reviewed-gate-c-decision\nGATE_C_CATCH_UP_MODE=next-schedule",
            "final-get-failure",
            False,
        ),
    ],
    ids=(
        "release-suspended",
        "activate",
        "disable",
        "pre-live-drift",
        "post-live-drift",
        "activation-window-failure",
        "post-live-capture-failure",
        "signal-after-helm",
        "pre-write-activation-window-failure",
        "helm-failure",
        "final-get-failure",
    ),
)
def test_reviewed_release_modes_are_atomic_and_fail_closed(
    tmp_path: Path,
    operation: str,
    current_name: str,
    selected_name: str,
    authorization: str,
    failure_mode: str | None,
    expected_success: bool,
) -> None:
    repo, baseline, suspended, active, off, head = _prepare_reviewed_repo(tmp_path)
    overlays = {path.name: path for path in (suspended, active, off)}
    current_render = _render_reviewed(repo, baseline, overlays[current_name])
    desired_render = _render_reviewed(repo, baseline, overlays[selected_name])
    selected = overlays[selected_name]
    selected_sha256 = hashlib.sha256(selected.read_bytes()).hexdigest()
    digest = f"sha256:{'a' * 64}"
    image = "localhost/a-stock-market-environment:20260905-1904b66"

    fake_bin = tmp_path / "release-bin"
    fake_bin.mkdir()
    target_calls = tmp_path / "release-calls"
    activation_window_counter = tmp_path / "activation-window-count"
    current_manifest = tmp_path / "current.yaml"
    current_manifest.write_text(current_render, encoding="utf-8")
    current_live_payload = yaml.safe_load(_live_list(current_render, "market-data"))
    if failure_mode == "pre-live-drift":
        service = next(item for item in current_live_payload["items"] if item["kind"] == "Service")
        service["spec"]["ports"][0]["nodePort"] = 32002
    current_live = tmp_path / "current-live.yaml"
    current_live.write_text(yaml.safe_dump(current_live_payload, sort_keys=False), encoding="utf-8")
    desired_live_payload = yaml.safe_load(_live_list(desired_render, "market-data"))
    if failure_mode == "post-live-drift":
        cronjob = next(item for item in desired_live_payload["items"] if item["kind"] == "CronJob")
        cronjob["spec"]["suspend"] = True
    desired_live = tmp_path / "desired-live.yaml"
    desired_live.write_text(yaml.safe_dump(desired_live_payload, sort_keys=False), encoding="utf-8")
    deployed_manifest = tmp_path / "deployed.yaml"
    deployed_overlay = tmp_path / "deployed-overlay.yaml"
    released = tmp_path / "released"
    deployments, replicasets, pods = _runtime_payloads(current_render, "research", digest)
    deployments_json = tmp_path / "deployments.json"
    replicasets_json = tmp_path / "replicasets.json"
    pods_json = tmp_path / "pods.json"
    deployments_json.write_text(json.dumps(deployments), encoding="utf-8")
    replicasets_json.write_text(json.dumps(replicasets), encoding="utf-8")
    pods_json.write_text(json.dumps(pods), encoding="utf-8")
    helm_wrapper = fake_bin / "helm"
    helm_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        "case \"$1\" in\n"
        "  lint|template) exec \"$REAL_HELM\" \"$@\" ;;\n"
        f"  get) cat {current_manifest}; exit 0 ;;\n"
        "  upgrade)\n"
        f"    printf 'helm-upgrade %s\\n' \"$*\" >> {target_calls}\n"
        "    if [[ \"${FAIL_HELM_UPGRADE:-false}\" == true ]]; then exit 95; fi\n"
        "    release_name=\"$2\"\n"
        "    chart_path=\"$3\"\n"
        "    shift 3\n"
        "    template_args=()\n"
        "    values_seen=0\n"
        "    while (($#)); do\n"
        "      case \"$1\" in\n"
        "        --atomic|--wait) shift ;;\n"
        "        --timeout) shift 2 ;;\n"
        "        --values)\n"
        "          values_seen=$((values_seen + 1))\n"
        f"          if [[ $values_seen -eq 2 ]]; then cp \"$2\" {deployed_overlay}; fi\n"
        "          template_args+=(\"$1\" \"$2\")\n"
        "          shift 2 ;;\n"
        "        *) template_args+=(\"$1\"); shift ;;\n"
        "      esac\n"
        "    done\n"
        f"    printf '\\ninvalid: [concurrent-change\\n' >> {selected}\n"
        f"    \"$REAL_HELM\" template \"$release_name\" \"$chart_path\" --kube-version 1.26.6+k3s1 \"${{template_args[@]}}\" > {deployed_manifest}\n"
        f"    touch {released}\n"
        "    if [[ \"${SIGNAL_AFTER_HELM:-false}\" == true ]]; then kill -TERM \"$PPID\"; sleep 0.1; fi\n"
        "    ;;\n"
        "  *) exit 98 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    helm_wrapper.chmod(0o755)
    ssh_wrapper = fake_bin / "ssh"
    ssh_wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'ssh %s\\n' \"$*\" >> {target_calls}\n"
        f"if [[ \"$*\" == *\"images info\"* ]]; then printf '%s' '{json.dumps({'Name': image, 'Target': {'digest': digest}})}'; fi\n"
        "exit 0\n",
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
        "if [[ \"$*\" == *\"get --raw /version\"* ]]; then printf '{\"gitVersion\": \"v1.26.6+k3s1\"}'; exit 0; fi\n"
        f"if [[ \"$*\" == *\"get deployment,service,cronjob\"* ]]; then if [[ -f {released} ]]; then if [[ \"${{FAIL_POST_LIVE_CAPTURE:-false}}\" == true ]]; then exit 96; fi; cat {desired_live}; else cat {current_live}; fi; exit 0; fi\n"
        f"if [[ \"$*\" == *\"get deployment\"* ]]; then cat {deployments_json}; exit 0; fi\n"
        f"if [[ \"$*\" == *\"get replicasets\"* ]]; then cat {replicasets_json}; exit 0; fi\n"
        f"if [[ \"$*\" == *\"get pods\"* ]]; then cat {pods_json}; exit 0; fi\n"
        f"if [[ \"$*\" == *\"get cronjob\"* ]]; then if [[ \"${{FAIL_FINAL_CRONJOB_GET:-false}}\" == true ]]; then exit 94; fi; cat {desired_live}; exit 0; fi\n"
        "if [[ \"$*\" == *\"patch cronjob\"* ]]; then exit 0; fi\n"
        "exit 99\n",
        encoding="utf-8",
    )
    kubectl_wrapper.chmod(0o755)

    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("fixture", encoding="utf-8")
    env_file = tmp_path / "release.env"
    env_file.write_text(
        "\n".join(
            [
                f"REPO_DIR={repo}",
                "TRUENAS_HOST=192.0.2.10",
                "TRUENAS_SSH_USER=tester",
                f"KUBECONFIG={kubeconfig}",
                f"HELM_VALUES_FILE={baseline}",
                f"SCHEDULING_OVERLAY_FILE={selected}",
                authorization,
                f"REVIEWED_GIT_HEAD={head}",
                f"REVIEWED_CHART_SHA256={_chart_hash(repo)}",
                f"REVIEWED_BASELINE_SHA256={hashlib.sha256(baseline.read_bytes()).hexdigest()}",
                f"REVIEWED_OVERLAY_SHA256={hashlib.sha256(selected.read_bytes()).hexdigest()}",
                f"REVIEWED_RENDER_SHA256={hashlib.sha256(desired_render.encode()).hexdigest()}",
                "FROZEN_IMAGE_REPOSITORY=localhost/a-stock-market-environment",
                "FROZEN_IMAGE_TAG=20260905-1904b66",
                f"FROZEN_IMAGE_DIGEST={digest}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    activation_window_fail_on_call = {
        "activation-window-failure": 1,
        "pre-write-activation-window-failure": 2,
    }.get(failure_mode, 0)

    completed = subprocess.run(
        [
            "bash",
            str(repo / "scripts" / SCRIPT.name),
            "--env-file",
            str(env_file),
            operation,
            "--kube-version",
            "1.26.6+k3s1",
            "--release-name",
            "research",
            "--namespace",
            "market-data",
        ],
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "REAL_HELM": HELM,
            "FAKE_ACTIVATION_WINDOW_COUNTER": str(activation_window_counter),
            "FAKE_ACTIVATION_WINDOW_FAIL_ON_CALL": str(activation_window_fail_on_call),
            "FAIL_POST_LIVE_CAPTURE": str(
                failure_mode == "post-live-capture-failure"
            ).lower(),
            "FAIL_HELM_UPGRADE": str(failure_mode == "helm-failure").lower(),
            "FAIL_FINAL_CRONJOB_GET": str(failure_mode == "final-get-failure").lower(),
            "SIGNAL_AFTER_HELM": str(failure_mode == "signal-after-helm").lower(),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    calls = target_calls.read_text(encoding="utf-8") if target_calls.exists() else ""
    activation_window_calls = (
        int(activation_window_counter.read_text(encoding="utf-8"))
        if activation_window_counter.exists()
        else 0
    )
    expected_activation_window_calls = (
        0
        if operation != "--activate-schedule"
        else 1
        if failure_mode in {"activation-window-failure", "pre-live-drift"}
        else 2
    )
    assert activation_window_calls == expected_activation_window_calls
    exact_suspend_call = (
        "kubectl patch cronjob research-a-stock-data-collection --namespace market-data "
        '--type=merge --patch {"spec":{"suspend":true}}'
    )
    if not expected_success:
        assert completed.returncode != 0
        if failure_mode == "activation-window-failure":
            assert "Gate C preflight activation window validation failed" in completed.stderr
            assert "helm-upgrade" not in calls
            assert "ssh " not in calls and "kubectl " not in calls
        elif failure_mode == "pre-write-activation-window-failure":
            assert "Gate C pre-write activation window validation failed" in completed.stderr
            assert "ssh " in calls and "kubectl " in calls
            assert "helm-upgrade" not in calls
            assert "patch cronjob" not in calls
        elif failure_mode == "pre-live-drift":
            assert "live declarative state differs" in completed.stderr
            assert "helm-upgrade" not in calls
        elif failure_mode == "post-live-capture-failure":
            assert "activation did not complete safely" in completed.stderr
            assert calls.splitlines().count(exact_suspend_call) == 1
        elif failure_mode == "helm-failure":
            assert "Helm atomic rollback was requested" in completed.stderr
            assert "activation did not complete safely" in completed.stderr
            assert "helm-upgrade" in calls
            assert calls.splitlines().count(exact_suspend_call) == 1
        elif failure_mode == "final-get-failure":
            assert completed.returncode == 94
            assert "activation did not complete safely" in completed.stderr
            assert "helm-upgrade" in calls
            assert calls.splitlines().count(exact_suspend_call) == 1
        elif failure_mode == "signal-after-helm":
            assert completed.returncode == 143
            assert "activation did not complete safely" in completed.stderr
            assert calls.splitlines().count(exact_suspend_call) == 1
        else:
            assert "postcondition failed" in completed.stderr
            assert calls.splitlines().count(exact_suspend_call) == 1
        return

    assert completed.returncode == 0, completed.stderr
    assert "helm-upgrade" in calls
    assert "research" in calls and "--namespace market-data" in calls
    assert "image.repository=localhost/a-stock-market-environment" in calls
    assert "image.tag=20260905-1904b66" in calls
    assert "--atomic" in calls
    if operation == "--activate-schedule":
        assert "Gate C activation window (preflight):" in completed.stdout
        assert "Gate C activation window (pre-write):" in completed.stdout
    assert str(repo / "deploy" / "helm" / "a-stock") not in next(
        line for line in calls.splitlines() if line.startswith("helm-upgrade")
    )
    assert hashlib.sha256(deployed_overlay.read_bytes()).hexdigest() == selected_sha256
    assert hashlib.sha256(deployed_manifest.read_bytes()).hexdigest() == hashlib.sha256(
        desired_render.encode()
    ).hexdigest()
    assert "podman" not in calls and "scp" not in calls
