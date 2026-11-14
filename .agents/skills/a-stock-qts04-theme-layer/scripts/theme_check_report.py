"""STEP 2 checker wrapper: always enables tier/catalyst label provenance."""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
_CORE = SKILL_DIR.parent / "qts04-core" / "scripts"
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from qts04.check import main as _core_main  # noqa: E402
from qts04.check import validate as _core_validate  # noqa: E402

from theme_report import label_map  # noqa: E402


def validate(result, article):
    return _core_validate(result, article, label_map())


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--labels" not in args:
        args.append("--labels")
    return _core_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
