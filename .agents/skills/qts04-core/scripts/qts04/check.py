"""Deterministic checker for a QTS-04 STEP 1 human-readable article.

The checker is deliberately mechanical: it reads the JSON result and the
article text, and answers one question — may this article be shown to the
user?  It never calls a language model and never touches the network.

Three classes of checks:

1. **Number provenance** — every number that carries a unit (``%``, ``×``,
   ``亿``, ``万``, ``N 分``, ``总分 N``) must exist in the JSON, allowing the
   rounding implied by the displayed precision plus a 1% relative tolerance.
   Bare small integers (direction indexes, counts) are whitelisted; bare
   integers above the whitelist and bare decimals are also traced.
2. **Forbidden wording** — ``买入`` / ``加仓`` / ``仓位`` / ``必涨`` /
   ``已验证`` / ``目标价`` are refused, with line/column of each hit.
3. **Required items** — disclaimer, ``needs-backtest`` marker, data status,
   and one confidence level per direction.  When the result is
   ``insufficient`` the article is not asked for direction sections, but it
   must explain why no direction was produced.

Exit codes: ``0`` PASS, ``1`` FAIL, ``2`` unreadable/invalid input.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "1.0"

FORBIDDEN_WORDS = ("买入", "加仓", "仓位", "必涨", "已验证", "目标价")
SMALL_INT_LIMIT = 12
YEAR_RANGE = (1900, 2100)
RELATIVE_TOLERANCE = 0.01

STATUS_LABELS = {
    "ok": "数据完整",
    "degraded": "数据降级",
    "insufficient": "数据不足",
}
CONFIDENCE_LABELS = {
    "high": "高",
    "medium": "中",
    "low": "低",
    "insufficient": "不足",
}
# Canonical Chinese labels used only when a caller opts into label provenance.
TIER_LABELS = {
    "core": "核心题材",
    "diffuse": "扩散题材",
    "event": "事件题材",
    "pseudo": "伪题材",
}
CATALYST_LABELS = {
    "confirmed": "已证实",
    "partial": "部分证实",
    "speculative": "市场推测",
    "unknown": "原因不明",
}


def default_label_map() -> dict[str, dict[str, str]]:
    """The canonical label map; callers may override individual labels."""

    return {"tier": dict(TIER_LABELS), "catalyst": dict(CATALYST_LABELS)}

_NUMBER = r"[+-]?\d+(?:\.\d+)?"

# Masked before tokenizing so dates and rule ids never look like claims.
_MASK_PATTERNS = (
    re.compile(r"QTS-\d{2}-\d{2}-\d{2}"),
    re.compile(r"\d{4}-\d{2}-\d{2}"),
    re.compile(r"\d{4}/\d{1,2}/\d{1,2}"),
    re.compile(r"\d{1,2}:\d{2}(?::\d{2})?"),
    re.compile(r"\b\d{6}\.(?:TI|SH|SZ|BJ)\b"),
    re.compile(r"\b[A-Za-z]{1,8}\d{1,6}\b"),
    re.compile(r"\b[0-9a-f]{16}\b"),
)

_TOKEN_RE = re.compile(
    r"(?P<total>总分\s*[:：]?\s*\**\s*" + _NUMBER + r")"
    r"|(?P<pct>" + _NUMBER + r")\s*[%％]"
    r"|(?P<mult>" + _NUMBER + r")\s*[×xX]"
    r"|(?P<yi>" + _NUMBER + r")\s*亿"
    r"|(?P<wan>" + _NUMBER + r")\s*万"
    r"|(?P<points>" + _NUMBER + r")\s*分(?!位)"
    r"|(?P<plain>" + _NUMBER + r")"
)

_CONFIDENCE_RE = re.compile(r"置信(?:度)?\s*[:：]?\s*\**\s*(高|中|低|不足)")

_UNIT_CHECK_NAMES = {
    "total": "总分",
    "pct": "%",
    "mult": "×",
    "yi": "亿",
    "wan": "万",
    "points": "分",
    "plain": "无单位",
}
_SCALE = {"total": 1.0, "pct": 0.01, "mult": 1.0, "yi": 1e8, "wan": 1e4, "points": 1.0, "plain": 1.0}


@dataclass(frozen=True)
class NumberToken:
    raw: str
    kind: str
    value: float
    half_ulp: float
    line: int
    column: int


def _mask(text: str) -> str:
    """Blank out dates and rule ids while preserving offsets and line breaks."""

    for pattern in _MASK_PATTERNS:
        text = pattern.sub(lambda match: re.sub(r"[^\n]", " ", match.group(0)), text)
    return text


def _position(text: str, index: int) -> tuple[int, int]:
    line = text.count("\n", 0, index) + 1
    column = index - (text.rfind("\n", 0, index) + 1) + 1
    return line, column


def _decimals(literal: str) -> int:
    return len(literal.split(".", 1)[1]) if "." in literal else 0


def extract_numbers(text: str) -> list[NumberToken]:
    """Extract every numeric claim, keeping only those that need provenance."""

    masked = _mask(text)
    tokens: list[NumberToken] = []
    for match in _TOKEN_RE.finditer(masked):
        kind = match.lastgroup or "plain"
        raw = match.group(kind)
        literal_match = re.search(_NUMBER, raw)
        if literal_match is None:
            continue
        literal = literal_match.group(0)
        try:
            displayed = float(literal)
        except ValueError:
            continue
        decimals = _decimals(literal)
        if kind == "plain":
            if decimals == 0:
                if abs(displayed) <= SMALL_INT_LIMIT:
                    continue  # direction index / small count whitelist
                if YEAR_RANGE[0] <= abs(displayed) <= YEAR_RANGE[1]:
                    continue  # a year, not a claim
        scale = _SCALE[kind]
        value = displayed * scale
        half_ulp = 0.5 * (10 ** -decimals) * scale
        line, column = _position(masked, match.start(kind))
        tokens.append(
            NumberToken(
                raw=match.group(0).strip(),
                kind=kind,
                value=value,
                half_ulp=half_ulp,
                line=line,
                column=column,
            )
        )
    return tokens


def collect_numbers(node: Any, out: set[float] | None = None) -> set[float]:
    """Every finite number carried anywhere in the JSON result."""

    if out is None:
        out = set()
    if isinstance(node, bool) or node is None:
        return out
    if isinstance(node, (int, float)):
        number = float(node)
        if math.isfinite(number):
            out.add(number)
        return out
    if isinstance(node, Mapping):
        for value in node.values():
            collect_numbers(value, out)
        return out
    if isinstance(node, (list, tuple)):
        for value in node:
            collect_numbers(value, out)
    return out


def number_is_sourced(token: NumberToken, numbers: Iterable[float]) -> bool:
    """Display-rounded match or 1% relative match against any JSON number."""

    for candidate in numbers:
        difference = abs(candidate - token.value)
        if difference <= max(token.half_ulp, 1e-9):
            return True
        if abs(token.value) > 1e-9 and difference / abs(token.value) <= RELATIVE_TOLERANCE:
            return True
    return False


def _issue(check: str, detail: str, line: int | None = None, column: int | None = None) -> dict[str, Any]:
    return {"check": check, "detail": detail, "line": line, "column": column}


def _check_schema_version(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    version = result.get("schemaVersion")
    if not version:
        return [_issue("schemaVersion", "结果缺少 schemaVersion，拒绝按当前版本消费")]
    if str(version) != SCHEMA_VERSION:
        return [_issue("schemaVersion", f"不支持的 schemaVersion：{version}（当前 {SCHEMA_VERSION}）")]
    return []


def _check_number_provenance(article: str, result: Mapping[str, Any]) -> list[dict[str, Any]]:
    numbers = collect_numbers(result)
    issues: list[dict[str, Any]] = []
    for token in extract_numbers(article):
        if number_is_sourced(token, numbers):
            continue
        unit = _UNIT_CHECK_NAMES.get(token.kind, token.kind)
        issues.append(
            _issue(
                "numberProvenance",
                f"数字 {token.raw}（{unit}）在 JSON 中找不到出处",
                token.line,
                token.column,
            )
        )
    return issues


def _check_forbidden(article: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    hits: list[tuple[int, str]] = []
    for word in FORBIDDEN_WORDS:
        start = article.find(word)
        while start != -1:
            hits.append((start, word))
            start = article.find(word, start + len(word))
    for index, word in sorted(hits, key=lambda item: (item[0], item[1])):
        line, column = _position(article, index)
        issues.append(_issue("forbiddenWording", f"命中禁用措辞「{word}」", line, column))
    return issues


def _has_disclaimer(article: str) -> bool:
    if "免责声明" in article or "不是买点" in article:
        return True
    return "不构成" in article and ("建议" in article or "买点" in article)


def _status_mentioned(article: str, status: str) -> bool:
    if status in STATUS_LABELS:
        label = STATUS_LABELS[status]
        if label in article:
            return True
    pattern = rf"(?<![A-Za-z0-9_-]){re.escape(status)}(?![A-Za-z0-9_-])"
    return re.search(pattern, article) is not None


def _direction_names(direction: Mapping[str, Any]) -> list[str]:
    names: list[str] = []
    code = str(direction.get("thscode") or "").strip()
    name = str(direction.get("name") or "").strip()
    if code:
        names.append(code)
    if name:
        names.append(name)
    return names


def _check_direction_confidence(article: str, directions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for direction in directions:
        code = str(direction.get("thscode") or "")
        names = _direction_names(direction)
        positions = [article.find(name) for name in names if name and article.find(name) != -1]
        if not positions:
            issues.append(_issue("requiredConfidence", f"文章缺少方向 {code or '（未命名）'} 的说明"))
            continue
        start = min(positions)
        window = article[max(0, start - 200) : start + 800]
        expected = CONFIDENCE_LABELS.get(str(direction.get("confidence") or ""), "")
        found = _CONFIDENCE_RE.search(window)
        if found is None:
            issues.append(_issue("requiredConfidence", f"方向 {code} 附近未写明确信度等级"))
        elif expected and found.group(1) != expected:
            issues.append(
                _issue(
                    "requiredConfidence",
                    f"方向 {code} 的置信度写作「{found.group(1)}」，JSON 为「{expected}」",
                )
            )
    return issues


def _check_required(article: str, result: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not _has_disclaimer(article):
        issues.append(_issue("requiredDisclaimer", "缺少免责声明（需写明「不构成…建议」或「不是买点」）"))
    if "needs-backtest" not in article:
        issues.append(_issue("requiredBacktestMarker", "缺少 needs-backtest 标记"))
    status = str(result.get("status") or "")
    if not status:
        issues.append(_issue("requiredDataStatus", "JSON 缺少 status，无法核对数据状态"))
    elif not _status_mentioned(article, status):
        issues.append(_issue("requiredDataStatus", f"文章未写明数据状态（应为 {status}）"))

    directions = [item for item in result.get("directions") or [] if isinstance(item, Mapping)]
    if status == "insufficient":
        if "不产出方向" not in article and "未产出方向" not in article:
            issues.append(_issue("requiredNoDirectionReason", "数据不足时须写明「本次不产出方向」"))
        if not any(word in article for word in ("原因", "因为", "由于")):
            issues.append(_issue("requiredNoDirectionReason", "数据不足时须说明未产出方向的原因"))
    else:
        issues += _check_direction_confidence(article, directions)
    return issues


def _check_label_provenance(
    article: str,
    result: Mapping[str, Any],
    label_map: Mapping[str, Mapping[str, str]],
) -> list[dict[str, Any]]:
    """Article labels must be renderings of the JSON, not independent claims.

    Only per-line associations are checked: a theme name and a label on the
    same line must agree.  Definitions ("核心题材闸门") and negations
    ("没有核心题材") are not claims and are ignored.
    """

    issues: list[dict[str, Any]] = []
    themes = [item for item in result.get("themes") or [] if isinstance(item, Mapping)]
    tier_labels = dict(label_map.get("tier") or {})
    catalyst_labels = dict(label_map.get("catalyst") or {})
    names = [str(theme.get("name") or "").strip() for theme in themes if str(theme.get("name") or "").strip()]
    definition_words = ("闸门", "门槛", "分级", "规则", "标准", "档", "定义", "口径")
    negation_words = ("没有", "无核心", "不产出", "未产出", "暂无", "不构成", "不是")

    def is_definition(line: str) -> bool:
        return any(word in line for word in definition_words)

    def is_negated(line: str) -> bool:
        return any(word in line for word in negation_words)

    def first_label(line: str, mapping: Mapping[str, str]) -> str | None:
        for label in mapping.values():
            if label and label in line:
                return label
        return None

    lines = article.splitlines()
    for theme in themes:
        name = str(theme.get("name") or "").strip()
        if not name:
            continue
        expected_tier = tier_labels.get(str(theme.get("tier")))
        expected_catalyst = catalyst_labels.get(
            str((theme.get("catalyst") or {}).get("label"))
        )
        for index, line in enumerate(lines, 1):
            if name not in line or is_negated(line) or is_definition(line):
                continue
            found_tier = first_label(line, tier_labels)
            if found_tier and expected_tier and found_tier != expected_tier:
                issues.append(
                    _issue(
                        "labelProvenance",
                        f"{name} 的分级写作「{found_tier}」，JSON 为「{expected_tier}」",
                        index,
                    )
                )
            found_catalyst = first_label(line, catalyst_labels)
            if found_catalyst and expected_catalyst and found_catalyst != expected_catalyst:
                issues.append(
                    _issue(
                        "labelProvenance",
                        f"{name} 的催化写作「{found_catalyst}」，JSON 为「{expected_catalyst}」",
                        index,
                    )
                )

    if result.get("noCoreTheme"):
        for index, line in enumerate(lines, 1):
            if "核心题材" not in line or is_negated(line) or is_definition(line):
                continue
            names_here = any(name in line for name in names)
            explicit_claim = re.search(r"(有|存在|出现|是|为|[:：])\s*\**\s*核心题材", line) is not None
            if names_here or explicit_claim:
                issues.append(
                    _issue("labelProvenance", "JSON 声明无核心题材，文章却写了核心题材", index)
                )

    if "已证实" in article and not any(
        (theme.get("catalyst") or {}).get("label") == "confirmed" for theme in themes
    ):
        issues.append(
            _issue("labelProvenance", "文章声称「已证实」，但 JSON 中没有 confirmed 催化")
        )
    return issues


def validate(
    result: Mapping[str, Any],
    article: str,
    label_map: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """Run all checks and return a deterministic verdict mapping.

    ``label_map`` is opt-in: STEP 1 never passes it, so its three-check
    contract is unchanged; STEP 2 passes the theme label map.
    """

    issues: list[dict[str, Any]] = []
    issues += _check_schema_version(result)
    issues += _check_number_provenance(article, result)
    issues += _check_forbidden(article)
    issues += _check_required(article, result)
    if label_map is not None:
        issues += _check_label_provenance(article, result, label_map)
    issues.sort(key=lambda item: (item["line"] or 0, item["column"] or 0, item["check"], item["detail"]))

    names = ["schemaVersion", "numberProvenance", "forbiddenWording", "requiredItems"]
    if label_map is not None:
        names.append("labelProvenance")
    checks = []
    for name in names:
        matched = [
            issue for issue in issues
            if issue["check"] == name
            or (name == "requiredItems" and issue["check"].startswith("required"))
        ]
        checks.append({"name": name, "status": "fail" if matched else "pass", "issues": len(matched)})
    return {
        "status": "FAIL" if issues else "PASS",
        "checks": checks,
        "issues": issues,
        "articleCharacters": len(article),
        "numbersChecked": len(extract_numbers(article)),
        "report": {
            "schemaVersion": result.get("schemaVersion"),
            "reportId": result.get("reportId"),
            "asOf": result.get("asOf"),
            "status": result.get("status"),
            "directions": len(result.get("directions") or []),
            "themes": len(result.get("themes") or []),
        },
    }


def _read_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("result JSON 顶层必须是对象")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="QTS-04 人工报告机械校验（数字溯源 / 禁用措辞 / 必备项）；PASS 前不得呈现文章",
    )
    parser.add_argument("--result", required=True, type=Path, help="pipeline 产出的 JSON")
    parser.add_argument("--article", required=True, type=Path, help="agent 撰写、待呈现的 Markdown 文章")
    parser.add_argument(
        "--labels",
        action="store_true",
        help="启用题材分级/催化标签溯源（STEP 2 使用；STEP 1 不传）",
    )
    args = parser.parse_args(argv)

    try:
        result = _read_json(args.result)
        article = args.article.read_text(encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {"status": "ERROR", "issues": [_issue("input", str(error))]},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2

    verdict = validate(result, article, default_label_map() if args.labels else None)
    print(json.dumps(verdict, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if verdict["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())