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
VERSION_PATTERN = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


def version_tuple(value: str) -> tuple[int, int, int]:
    match = VERSION_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(f"invalid Kubernetes version: {value}")
    return tuple(int(match.group(name)) for name in ("major", "minor", "patch"))


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
        actual_version = version_tuple(args.kube_version)
        minimum_version = version_tuple(minimum)
    except (OSError, KeyError, TypeError, yaml.YAMLError, ValueError) as exc:
        parser.error(str(exc))

    if policy.get("scheduledCollectionTimezoneStrategy") != "native":
        parser.error("native scheduled overlay policy is invalid")
    if actual_version < minimum_version:
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
