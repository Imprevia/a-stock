"""Markdown and structured-source parsing for the local knowledge index."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

import yaml

from .config import KnowledgeConfig, SOURCE_AUTHORITY, relative_ref
from .models import Chunk, IndexBuildError, RuleCatalog, SourceFile
from .text import cjk_bigrams, extract_rule_ids, normalize_text, sha256_bytes, worst_evidence_status

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
RULE_ENTRY_RE = re.compile(r"^\s*-\s+ruleId:\s*([A-Za-z0-9-]+)\s*$")
EVIDENCE_ENTRY_RE = re.compile(r"^\s*-\s+evidenceId:\s*([^\s#]+)\s*$")
MAX_CHUNK_CHARS = 2800


def discover_source_files(config: KnowledgeConfig) -> list[SourceFile]:
    sources: list[SourceFile] = []
    for layer, path in _unique_sources(config):
        try:
            path.resolve().relative_to(config.repo_root)
        except ValueError as exc:
            raise IndexBuildError(f"{path}: controlled source resolves outside repository root") from exc
        if path.is_symlink():
            raise IndexBuildError(f"{path}: symlinked knowledge sources are not allowed")
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise IndexBuildError(f"{path}: cannot read UTF-8 source: {exc}") from exc
        sources.append(
            SourceFile(
                layer=layer,
                document_ref=relative_ref(config, path),
                path=path,
                content_sha256=sha256_bytes(raw),
                byte_size=len(raw),
                line_count=len(text.splitlines()),
            )
        )
    return sources


def _unique_sources(config: KnowledgeConfig) -> Iterable[tuple[str, Path]]:
    seen: set[Path] = set()
    for layer, path in _source_paths(config):
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        yield layer, path


def _source_paths(config: KnowledgeConfig) -> list[tuple[str, Path]]:
    from .config import source_paths

    return source_paths(config)


def parse_frontmatter(lines: list[str]) -> tuple[dict[str, Any], int]:
    if not lines or lines[0].strip() != "---":
        return {}, 0
    end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if end is None:
        raise IndexBuildError("Markdown frontmatter starts with '---' but has no closing delimiter")
    raw = yaml.safe_load("\n".join(lines[1:end])) or {}
    if not isinstance(raw, dict):
        raise IndexBuildError("Markdown frontmatter must be a mapping")
    return dict(raw), end + 1


def clean_heading(value: str) -> str:
    value = re.sub(r"\\([\\`*_{}\[\]()#+.!|>-])", r"\1", value)
    value = re.sub(r"[*_`]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def parse_markdown(source: SourceFile, evidence_by_rule: dict[str, str]) -> tuple[list[Chunk], dict[str, Any]]:
    try:
        lines = source.path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise IndexBuildError(f"{source.document_ref}: cannot read Markdown: {exc}") from exc
    frontmatter, body_start = parse_frontmatter(lines)
    heading_stack: list[str] = []
    current: list[str] = []
    current_start: int | None = None
    current_end: int | None = None
    current_heading: tuple[str, ...] = ()
    chunks: list[Chunk] = []

    def flush() -> None:
        nonlocal current, current_start, current_end
        if current_start is None or current_end is None or not any(line.strip() for line in current):
            current = []
            current_start = None
            current_end = None
            return
        chunks.extend(
            _make_markdown_chunks(
                source=source,
                lines=current,
                line_start=current_start,
                line_end=current_end,
                heading_path=current_heading,
                frontmatter=frontmatter,
                evidence_by_rule=evidence_by_rule,
            )
        )
        current = []
        current_start = None
        current_end = None

    for line_number in range(body_start, len(lines)):
        raw_line = lines[line_number]
        heading = HEADING_RE.match(raw_line)
        if heading:
            flush()
            level = len(heading.group(1))
            title = clean_heading(heading.group(2))
            heading_stack = heading_stack[: level - 1]
            heading_stack.append(title)
            current_heading = tuple(heading_stack)
            current = [raw_line]
            current_start = line_number + 1
            current_end = line_number + 1
            continue
        if not raw_line.strip():
            if current and any(line.strip() for line in current[1:]):
                flush()
            elif current:
                current.append(raw_line)
                current_end = line_number + 1
            continue
        if current_start is None:
            current_start = line_number + 1
            current = []
        current_end = line_number + 1
        current.append(raw_line)
        if len("\n".join(current)) >= MAX_CHUNK_CHARS:
            flush()
    flush()
    return chunks, frontmatter


def _make_markdown_chunks(
    source: SourceFile,
    lines: list[str],
    line_start: int,
    line_end: int,
    heading_path: tuple[str, ...],
    frontmatter: dict[str, Any],
    evidence_by_rule: dict[str, str],
) -> list[Chunk]:
    rule_ids = extract_rule_ids("\n".join(lines))
    status = _frontmatter_status(frontmatter)
    evidence_status = worst_evidence_status([evidence_by_rule.get(rule_id, "unverified") for rule_id in rule_ids])
    if not rule_ids:
        evidence_status = "unverified"
    source_text = "\n".join(lines)
    metadata = " ".join(str(value) for value in frontmatter.values() if value is not None)
    search_text = normalize_text(" ".join([source_text, " ".join(heading_path), metadata]))
    content_sha = sha256_bytes(source_text.encode("utf-8"))
    citation_id = _citation_id(
        source.layer,
        source.document_ref,
        line_start,
        line_end,
        content_sha,
    )
    return [
        Chunk(
            citation_id=citation_id,
            source_layer=source.layer,
            document_ref=source.document_ref,
            heading_path=heading_path,
            line_start=line_start,
            line_end=line_end,
            rule_ids=rule_ids,
            lifecycle_status=status,
            evidence_status=evidence_status,
            content=source_text,
            content_sha256=content_sha,
            search_text=search_text,
            cjk_text=cjk_bigrams(search_text),
            authority=SOURCE_AUTHORITY[source.layer],
        )
    ]


def _frontmatter_status(frontmatter: dict[str, Any]) -> str | None:
    for key in ("ruleStatus", "status", "lifecycle"):
        value = frontmatter.get(key)
        if value:
            return str(value)
    return None


def _citation_id(layer: str, document_ref: str, line_start: int, line_end: int, content_sha: str) -> str:
    from .text import canonical_hash

    return canonical_hash(
        {
            "layer": layer,
            "document_ref": document_ref,
            "line_start": line_start,
            "line_end": line_end,
            "content_sha256": content_sha,
        }
    )[:32]


def load_rule_catalog(config: KnowledgeConfig, sources: list[SourceFile]) -> RuleCatalog:
    """Load and validate all structured facts before an index is replaced."""

    try:
        from src.trading_system.rules.coverage import validate_coverage
        from src.trading_system.rules.registry import all_rules, load_rule_sets

        validate_coverage(config.repo_root)
        rule_sets = load_rule_sets(config.repo_root)
    except Exception as exc:
        raise IndexBuildError(f"rule registry or coverage validation failed: {exc}") from exc

    catalog = RuleCatalog()
    rule_set_raw_by_name: dict[str, dict[str, Any]] = {}
    source_by_ref = {source.document_ref: source for source in sources}
    for source in sources:
        if source.layer == "machine-rule":
            raw = _load_yaml(source.path, source.document_ref)
            if not isinstance(raw, dict) or not isinstance(raw.get("rules"), list):
                raise IndexBuildError(f"{source.document_ref}: rule set YAML must contain a rules list")
            rule_set = str(raw.get("ruleSet", ""))
            rule_set_raw_by_name[rule_set] = raw
            catalog.rule_set_sources[rule_set] = source.document_ref
            for item in raw["rules"]:
                if not isinstance(item, dict) or not item.get("ruleId"):
                    raise IndexBuildError(f"{source.document_ref}: every rule entry must contain ruleId")
                rule_id = str(item["ruleId"])
                if rule_id in catalog.rules:
                    raise IndexBuildError(f"duplicate rule ID in knowledge catalog: {rule_id}")
                catalog.rules[rule_id] = {
                    "ruleId": rule_id,
                    "ruleSet": rule_set,
                    "sourcePath": source.document_ref,
                    "raw": item,
                }

        elif source.layer == "coverage":
            raw = _load_yaml(source.path, source.document_ref)
            if not isinstance(raw, dict) or not isinstance(raw.get("entries"), list):
                raise IndexBuildError(f"{source.document_ref}: coverage YAML must contain entries")
            for item in raw["entries"]:
                if not isinstance(item, dict) or not item.get("ruleId"):
                    raise IndexBuildError(f"{source.document_ref}: every coverage entry must contain ruleId")
                rule_id = str(item["ruleId"])
                if rule_id in catalog.coverage:
                    raise IndexBuildError(f"duplicate coverage rule ID: {rule_id}")
                catalog.coverage[rule_id] = item
                document_ref = item.get("documentRef")
                if not isinstance(document_ref, str) or not _registered_document(config, document_ref):
                    raise IndexBuildError(f"{source.document_ref}: {rule_id} has missing document reference {document_ref!r}")

        elif source.layer == "evidence":
            raw = _load_yaml(source.path, source.document_ref)
            if source.document_ref == "evidence/rules/index.yaml":
                rule_sets_raw = raw.get("ruleSets", {}) if isinstance(raw, dict) else {}
                if not isinstance(rule_sets_raw, dict):
                    raise IndexBuildError(f"{source.document_ref}: ruleSets must be a mapping")
                for rule_set, summary in rule_sets_raw.items():
                    if not isinstance(summary, dict):
                        raise IndexBuildError(f"{source.document_ref}: {rule_set} evidence summary must be a mapping")
                    catalog.evidence_by_rule_set[str(rule_set)] = dict(summary)
                    catalog.evidence_sources[str(rule_set)] = source.document_ref
            else:
                records = raw if isinstance(raw, list) else [raw]
                for record in records:
                    if not isinstance(record, dict):
                        raise IndexBuildError(f"{source.document_ref}: monthly evidence record must be a mapping")
                    record = dict(record)
                    record["sourcePath"] = source.document_ref
                    catalog.monthly_records.append(record)

    # Ensure every executable rule has the structured metadata required by get_rule.
    registry = all_rules(rule_sets.values())
    for rule_id, rule in registry.items():
        if rule_id not in catalog.rules:
            raise IndexBuildError(f"{rule_id}: registry rule missing from parsed YAML catalog")
    for rule_id in catalog.coverage:
        if rule_id not in catalog.rules:
            coverage = catalog.coverage[rule_id]
            catalog.rules[rule_id] = {
                "ruleId": rule_id,
                "ruleSet": None,
                "sourcePath": coverage.get("documentRef"),
                "raw": None,
            }

    quantified_statuses: dict[str, set[str]] = {}
    for source in sources:
        if source.layer != "quantified":
            continue
        try:
            frontmatter, _ = parse_frontmatter(source.path.read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeError) as exc:
            raise IndexBuildError(f"{source.document_ref}: cannot read frontmatter: {exc}") from exc
        source_ref = frontmatter.get("sourcePath")
        if source_ref is not None and (
            not isinstance(source_ref, str) or not _registered_document(config, source_ref)
        ):
            raise IndexBuildError(f"{source.document_ref}: missing sourcePath reference {source_ref!r}")
        status = _frontmatter_status(frontmatter)
        if not status:
            continue
        ids = extract_rule_ids(source.path.read_text(encoding="utf-8"))
        for rule_id in ids:
            quantified_statuses.setdefault(rule_id, set()).add(status)

    for rule_id, statuses in quantified_statuses.items():
        machine = catalog.rules.get(rule_id, {}).get("raw")
        machine_status = machine.get("status") if isinstance(machine, dict) else None
        if machine_status and statuses != {str(machine_status)}:
            catalog.conflicts.setdefault(rule_id, []).append(
                {
                    "type": "lifecycle-status-drift",
                    "machine_rule_status": machine_status,
                    "quantified_document_statuses": sorted(statuses),
                    "warning": "量化说明层状态与 YAML 机器规则状态不同，查询时必须同时展示。",
                }
            )
    return catalog


def _registered_document(config: KnowledgeConfig, document_ref: str) -> bool:
    if "\x00" in document_ref or "\\" in document_ref:
        return False
    relative = Path(document_ref)
    if relative.is_absolute() or ".." in relative.parts:
        return False
    path = config.repo_root / relative
    try:
        path.resolve().relative_to(config.repo_root)
    except ValueError:
        return False
    return path.is_file() and not path.is_symlink()


def _load_yaml(path: Path, document_ref: str) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise IndexBuildError(f"{document_ref}: cannot parse YAML: {exc}") from exc


def build_structured_chunks(
    source: SourceFile,
    catalog: RuleCatalog,
) -> list[Chunk]:
    """Create searchable, line-addressable chunks for YAML sources."""

    raw = _load_yaml(source.path, source.document_ref)
    lines = source.path.read_text(encoding="utf-8").splitlines()
    if source.layer == "machine-rule":
        rule_set = str(raw.get("ruleSet", ""))
        starts = _line_starts(lines, RULE_ENTRY_RE)
        chunks: list[Chunk] = []
        for index, (line_start, rule_id) in enumerate(starts):
            line_end = starts[index + 1][0] - 1 if index + 1 < len(starts) else len(lines)
            item = catalog.rules[rule_id]
            chunks.append(
                _make_structured_chunk(
                    source,
                    lines,
                    line_start,
                    line_end,
                    heading_path=(rule_set, rule_id, str(item["raw"].get("title", ""))),
                    rule_ids=(rule_id,),
                    lifecycle_status=str(item["raw"].get("status")),
                    evidence_status=catalog.evidence_status(rule_set),
                    extra=item["raw"],
                )
            )
        return chunks

    if source.layer == "coverage":
        starts = _line_starts(lines, RULE_ENTRY_RE)
        chunks = []
        for index, (line_start, rule_id) in enumerate(starts):
            line_end = starts[index + 1][0] - 1 if index + 1 < len(starts) else len(lines)
            coverage = catalog.coverage[rule_id]
            rule = catalog.rules.get(rule_id, {})
            raw_rule = rule.get("raw")
            rule_set = rule.get("ruleSet")
            chunks.append(
                _make_structured_chunk(
                    source,
                    lines,
                    line_start,
                    line_end,
                    heading_path=("coverage", rule_id),
                    rule_ids=(rule_id,),
                    lifecycle_status=str(raw_rule.get("status")) if isinstance(raw_rule, dict) else "documented-only",
                    evidence_status=catalog.evidence_status(rule_set),
                    extra=coverage,
                )
            )
        return chunks

    if source.document_ref == "evidence/rules/index.yaml":
        chunks = []
        for rule_set, summary in sorted(catalog.evidence_by_rule_set.items()):
            line_start = _find_line(lines, f"{rule_set}:") or 1
            line_end = _mapping_entry_end(lines, line_start)
            chunks.append(
                _make_structured_chunk(
                    source,
                    lines,
                    line_start,
                    line_end,
                    heading_path=("evidence", rule_set),
                    rule_ids=tuple(
                        sorted(
                            rule_id
                            for rule_id, item in catalog.rules.items()
                            if item.get("ruleSet") == rule_set
                        )
                    ),
                    lifecycle_status=str(summary.get("lifecycle")) if summary.get("lifecycle") else None,
                    evidence_status=catalog.evidence_status(rule_set),
                    extra=summary,
                )
            )
        return chunks

    records = raw if isinstance(raw, list) else [raw]
    starts = _line_starts(lines, EVIDENCE_ENTRY_RE)
    chunks = []
    for index, (line_start, evidence_id) in enumerate(starts):
        line_end = starts[index + 1][0] - 1 if index + 1 < len(starts) else len(lines)
        record = next((item for item in records if str(item.get("evidenceId")) == evidence_id), {})
        chunks.append(
            _make_structured_chunk(
                source,
                lines,
                line_start,
                line_end,
                heading_path=("evidence", evidence_id),
                rule_ids=(),
                lifecycle_status=str(record.get("status")) if record.get("status") else None,
                evidence_status=str(record.get("status", "insufficient")),
                extra=record,
            )
        )
    return chunks


def _line_starts(lines: list[str], pattern: re.Pattern[str]) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    for index, line in enumerate(lines, 1):
        match = pattern.match(line)
        if match:
            result.append((index, match.group(1)))
    return result


def _find_line(lines: list[str], needle: str) -> int | None:
    for index, line in enumerate(lines, 1):
        if line.strip() == needle:
            return index
    return None


def _mapping_entry_end(lines: list[str], line_start: int) -> int:
    for index in range(line_start, len(lines)):
        line = lines[index]
        if index > line_start - 1 and line and not line.startswith((" ", "\t")):
            return index
    return len(lines)


def _make_structured_chunk(
    source: SourceFile,
    lines: list[str],
    line_start: int,
    line_end: int,
    heading_path: tuple[str, ...],
    rule_ids: tuple[str, ...],
    lifecycle_status: str | None,
    evidence_status: str,
    extra: dict[str, Any],
) -> Chunk:
    content = "\n".join(lines[line_start - 1 : line_end])
    structured = normalize_text(" ".join([content, str(extra)]))
    content_sha = sha256_bytes(content.encode("utf-8"))
    citation_id = _citation_id(source.layer, source.document_ref, line_start, line_end, content_sha)
    return Chunk(
        citation_id=citation_id,
        source_layer=source.layer,
        document_ref=source.document_ref,
        heading_path=heading_path,
        line_start=line_start,
        line_end=line_end,
        rule_ids=tuple(sorted(set(rule_ids))),
        lifecycle_status=lifecycle_status,
        evidence_status=evidence_status,
        content=content,
        content_sha256=content_sha,
        search_text=structured,
        cjk_text=cjk_bigrams(structured),
        authority=SOURCE_AUTHORITY[source.layer],
    )


def enrich_markdown_evidence(chunks: list[Chunk], catalog: RuleCatalog) -> list[Chunk]:
    enriched: list[Chunk] = []
    for chunk in chunks:
        statuses = [
            catalog.evidence_status(catalog.rules.get(rule_id, {}).get("ruleSet"))
            for rule_id in chunk.rule_ids
            if rule_id in catalog.rules
        ]
        if statuses:
            enriched.append(replace(chunk, evidence_status=worst_evidence_status(statuses)))
        else:
            enriched.append(chunk)
    return enriched
