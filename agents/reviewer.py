"""报告审查员 Agent：LLM-powered 报告级质量审查。"""

from llm.client import LLMClient

from agents.base import Agent
from models import ResearchResult, ReviewResult, ReworkItem

# ── Prompt ────────────────────────────────────────────────────────

REVIEWER_PROMPT = """\
你是 Sonar 的报告级质量审查员。你的任务是审查所有概念的研究结果，找出需要返工的概念。

你需要检查：

1. **解释质量**：每个概念的 explanation 是否通俗易懂、有足够深度？
   - 不合格：空白、过于简短（< 50字）、或只是复述概念名
   - 合格：读者读完能真正理解这个概念

2. **完整性**：每个概念是否有例子（example）帮助理解？
   - 不合格：example 为空或过于笼统
   - 合格：有具体的、有助于理解的例子

3. **资源质量**：每个概念是否有至少 1 条学习资料？
   - 不合格：resources 为空
   - 合格：有 1-2 条来源可信的资料

只标记真正有问题的概念。大多数概念应该能通过。

调用 submit_review 提交审查结果。
"""

# ── Tool ──────────────────────────────────────────────────────────

REVIEW_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_review",
        "description": "提交审查结果：标记需要返工的概念。",
        "parameters": {
            "type": "object",
            "properties": {
                "passed": {
                    "type": "boolean",
                    "description": "true=所有概念都通过, false=有概念需要返工",
                },
                "rework": {
                    "type": "array",
                    "description": "需要返工的概念列表（如果 passed=true 则为空数组）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "concept": {
                                "type": "string",
                                "description": "概念名称（必须与研究结果中的名称一致）",
                            },
                            "feedback": {
                                "type": "string",
                                "description": "具体问题和改进建议（会转发给研究员）",
                            },
                        },
                        "required": ["concept", "feedback"],
                    },
                },
            },
            "required": ["passed", "rework"],
        },
    },
}


# ── Agent ─────────────────────────────────────────────────────────

class Reviewer(Agent):
    """LLM-powered agent that reviews all research findings holistically."""

    def __init__(self, llm: LLMClient):
        super().__init__(
            llm,
            name="Reviewer",
            system_prompt=REVIEWER_PROMPT,
            max_iterations=1,
        )
        self.add_terminal_tool(REVIEW_TOOL)

    def review(self, research: ResearchResult) -> ReviewResult:
        """Review research findings and return a ReviewResult."""
        task = self._build_task(research)
        result = self.run(task)

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
