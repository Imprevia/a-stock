"""Fuyao collection gates shared by dataset collectors."""

from __future__ import annotations

from typing import Any

from ...fuyao_config import FuyaoCollectionConfig


class FuyaoCollectionPolicy:
    """Resolve cutover, fallback and shadow eligibility outside the coordinator."""

    def __init__(self, config: FuyaoCollectionConfig, capability_reports: Any) -> None:
        self.config = config
        self.capability_reports = capability_reports

    def preflight_error(self, dataset: str) -> str | None:
        if dataset == "sectors":
            return None
        return self._cutover_error(dataset)

    def is_enabled(self, dataset: str) -> bool:
        if dataset == "activeDirection":
            return False
        if dataset not in self.config.datasets:
            return False
        config = self.config.for_dataset(dataset)
        if not config.enabled:
            return False
        if dataset in {"core", "breadth"} and config.approved_revision == "fuyao-market-v1":
            return False
        report = self.capability_reports.get_capability_report(
            "fuyao",
            dataset,
            config.approved_revision,
        )
        return bool(
            report
            and report.status == "eligible"
            and report.revision == config.approved_revision
        )

    def gate_warning(self, dataset: str) -> str:
        config = self.config.datasets.get(dataset)
        if config is None or not config.enabled:
            return f"扶摇 {dataset} 未启用"
        report = self.capability_reports.get_capability_report(
            "fuyao",
            dataset,
            config.approved_revision,
        )
        if report is None:
            latest = self.capability_reports.get_capability_report("fuyao", dataset)
            if latest is not None:
                return (
                    f"扶摇 {dataset} capability revision 不匹配：批准 {config.approved_revision}，"
                    f"实际 {latest.revision}"
                )
            return (
                f"扶摇 {dataset} 未通过 capability revision 门禁："
                f"缺少批准报告 {config.approved_revision}"
            )
        if report.status != "eligible":
            return f"扶摇 {dataset} 未通过 capability revision 门禁：状态为 {report.status}"
        if report.revision != config.approved_revision:
            return (
                f"扶摇 {dataset} capability revision 不匹配：批准 {config.approved_revision}，"
                f"实际 {report.revision}"
            )
        return f"扶摇 {dataset} 未通过 capability revision 门禁"

    def shadow_enabled(self, dataset: str) -> bool:
        if dataset == "activeDirection":
            return False
        config = self.config.datasets.get(dataset)
        return bool(config and config.shadow_enabled)

    def revision(self, dataset: str) -> str:
        config = self.config.datasets.get(dataset)
        return (
            config.approved_revision
            if config and config.approved_revision
            else "fuyao-market-v2"
        )

    def _cutover_error(self, dataset: str) -> str | None:
        if dataset in {"limits", "activeDirection"} or dataset not in self.config.datasets:
            return None
        config = self.config.for_dataset(dataset)
        if not config.enabled:
            return None
        if dataset in {"core", "breadth"} and config.approved_revision == "fuyao-market-v1":
            return (
                f"扶摇 {dataset} 不接受过时 capability revision fuyao-market-v1；"
                "需要 fuyao-market-v2"
            )
        report = self.capability_reports.get_capability_report(
            "fuyao",
            dataset,
            config.approved_revision,
        )
        if report is None:
            latest = self.capability_reports.get_capability_report("fuyao", dataset)
            if latest is not None:
                return (
                    f"扶摇 {dataset} capability revision 不匹配：批准 {config.approved_revision}，"
                    f"实际 {latest.revision}"
                )
            return (
                f"扶摇 {dataset} 未通过 capability revision 门禁："
                f"缺少批准报告 {config.approved_revision}"
            )
        if report.status != "eligible":
            return f"扶摇 {dataset} 未通过 capability revision 门禁：状态为 {report.status}"
        if report.revision != config.approved_revision:
            return (
                f"扶摇 {dataset} capability revision 不匹配：批准 {config.approved_revision}，"
                f"实际 {report.revision}"
            )
        return None


__all__ = ["FuyaoCollectionPolicy"]
