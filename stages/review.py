"""Review 阶段：LLM-powered 报告级质量审查。"""

from agents.reviewer import Reviewer
from llm.client import LLMClient
from stages.models import ResearchPlan, ResearchResult, ReviewResult, ReworkItem


class ReviewStage:
    """检查 Research 产出的整体质量，决定是否需要返工。"""

    def __init__(self, llm: LLMClient, plan: ResearchPlan | None = None):
        self.llm = llm
        self.plan = plan

    def run(self, research: ResearchResult) -> ReviewResult:
        agent = Reviewer(self.llm)
        task = self._build_task(research)
        result = agent.run(task)

        if not result:
            print("[Review] Agent 未返回结果，视为通过")
            return ReviewResult(passed=True)

        rework = [
            ReworkItem(concept=r["concept"], feedback=r.get("feedback", ""))
            for r in result.get("rework", [])
            if r.get("concept") in research.findings
        ]

        passed = result.get("passed", True) and len(rework) == 0

        if rework:
            print(f"[Review] {len(rework)} 个概念需要返工:")
            for item in rework:
                print(f"  - {item.concept}: {item.feedback[:80]}")
        else:
            print("[Review] 所有概念通过质量检查")

        return ReviewResult(passed=passed, rework=rework)

    def _build_task(self, research: ResearchResult) -> str:
        findings_text = ""
        for name, finding in research.findings.items():
            explanation = finding.get("explanation", "(空)")
            example = finding.get("example", "(空)")
            n_resources = len(finding.get("resources", []))
            findings_text += f"\n### {name}\n"
            findings_text += f"- 解释: {explanation[:200]}{'...' if len(explanation) > 200 else ''}\n"
            findings_text += f"- 例子: {example[:150]}{'...' if len(str(example)) > 150 else ''}\n"
            findings_text += f"- 资料数: {n_resources}\n"

        return f"""请审查以下 {len(research.findings)} 个概念的研究结果：

**文章**: {research.article_title}
**摘要**: {research.article_summary[:300]}

## 研究结果
{findings_text}

请调用 submit_review 提交审查结果。只标记真正有质量问题的概念。"""
