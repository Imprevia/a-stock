#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "deploy" / "k3s-native-scheduled"
POLICY = OVERLAY / "render-policy.yaml"
SEMVER_PATTERN = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def parse_semver(value: str) -> tuple[tuple[int, int, int], tuple[str, ...]]:
    match = SEMVER_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(f"invalid Kubernetes version: {value}")
    core = tuple(int(match.group(name)) for name in ("major", "minor", "patch"))
    prerelease = tuple((match.group("prerelease") or "").split("."))
    return core, prerelease if prerelease != ("",) else ()


def compare_semver(
    left: tuple[tuple[int, int, int], tuple[str, ...]],
    right: tuple[tuple[int, int, int], tuple[str, ...]],
) -> int:
    if left[0] != right[0]:
        return -1 if left[0] < right[0] else 1
    left_prerelease, right_prerelease = left[1], right[1]
    if not left_prerelease or not right_prerelease:
        if left_prerelease == right_prerelease:
            return 0
        return -1 if left_prerelease else 1
    for left_identifier, right_identifier in zip(left_prerelease, right_prerelease):
        if left_identifier == right_identifier:
            continue
        left_numeric = left_identifier.isdigit()
        right_numeric = right_identifier.isdigit()
        if left_numeric and right_numeric:
            return -1 if int(left_identifier) < int(right_identifier) else 1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return -1 if left_identifier < right_identifier else 1
    if len(left_prerelease) == len(right_prerelease):
        return 0
    return -1 if len(left_prerelease) < len(right_prerelease) else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the Kubernetes 1.27+ native scheduled-collection overlay."
    )
    parser.add_argument("--kube-version", required=True)
    parser.add_argument("--kubectl", default="kubectl")
    args = parser.parse_args()

    try:
        policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
        minimum = policy["minimumKubernetesVersion"]
        actual_version = parse_semver(args.kube_version)
        minimum_version = parse_semver(minimum)
    except (OSError, KeyError, TypeError, yaml.YAMLError, ValueError) as exc:
        parser.error(str(exc))

    if policy.get("scheduledCollectionTimezoneStrategy") != "native":
        parser.error("native scheduled overlay policy is invalid")
    if compare_semver(actual_version, minimum_version) < 0:
        parser.error(
            f"native scheduled overlay requires Kubernetes {minimum}+; "
            f"got {args.kube_version}"
        )

    kubectl = shutil.which(args.kubectl)
    if kubectl is None:
        parser.error(f"kubectl executable not found: {args.kubectl}")
    completed = subprocess.run(
        [kubectl, "kustomize", str(OVERLAY)],
        check=False,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
