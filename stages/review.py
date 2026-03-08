"""Review 阶段：校验研究产出的整体质量，标记需要返工的概念。"""

from report.schema import format_issues, validate_finding
from stages.models import ResearchPlan, ResearchResult, ReviewResult, ReworkItem


class ReviewStage:
    """检查 Research 产出的整体质量，决定是否需要返工。"""

    def __init__(self, plan: ResearchPlan | None = None):
        self.plan = plan

    def run(self, research: ResearchResult) -> ReviewResult:
        schema = self.plan.finding_schema if self.plan else None
        rework: list[ReworkItem] = []

        for name, finding in research.findings.items():
            issues = self._check_finding(finding, schema)
            if issues:
                rework.append(ReworkItem(concept=name, feedback=issues))

        if rework:
            print(f"[Review] {len(rework)} 个概念需要返工:")
            for item in rework:
                print(f"  - {item.concept}: {item.feedback[:80]}")
        else:
            print("[Review] 所有概念通过质量检查")

        return ReviewResult(passed=len(rework) == 0, rework=rework)

    @staticmethod
    def _check_finding(finding: dict, schema: list | None) -> str:
        """Check a single finding, return feedback string if issues found."""
        if schema:
            issues = validate_finding(finding, schema)
        else:
            from report.schema import validate_concept
            issues = validate_concept(finding)

        errors = [i for i in issues if i.severity == "error"]
        if not errors:
            return ""
        return format_issues(errors)
