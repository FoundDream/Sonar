"""审查员 Agent：审查单个概念的研究质量。"""

from agents.base import Agent
from llm.client import LLMClient
from stages.models import FieldSpec

from .prompt import VERIFIER_PROMPT
from .tools import VERIFY_TOOL


class Verifier(Agent):
    """Agent that reviews a single concept's research quality."""

    def __init__(self, llm: LLMClient, finding_schema: list[FieldSpec] | None = None):
        super().__init__(
            llm,
            name="审查员",
            system_prompt=VERIFIER_PROMPT,
            max_iterations=1,
        )
        self._finding_schema = finding_schema
        self.add_terminal_tool(VERIFY_TOOL)

    def verify(self, result: dict, article_summary: str) -> dict:
        task = self._build_review(result, article_summary)
        verdict = self.run(task)
        if not verdict:
            self._log("未正常提交审查结果，视为未通过")
            return {"pass": False, "feedback": "审查调用异常，请重新研究并改进结果质量。"}
        return verdict

    def _build_review(self, result: dict, article_summary: str) -> str:
        resources_text = ""
        for r in result.get("resources", []):
            resources_text += f"  - {r.get('title', '?')} ({r.get('url', '?')})\n"
            if r.get("description"):
                resources_text += f"    {r['description']}\n"

        if self._finding_schema:
            fields_text = ""
            for spec in self._finding_schema:
                if spec.name in ("name", "resources"):
                    continue
                value = result.get(spec.name, "(空)")
                if isinstance(value, list):
                    value = ", ".join(str(v) for v in value) if value else "(空)"
                fields_text += f"\n**{spec.description}**: {value}\n"
        else:
            fields_text = f"""
**研究员的解释**: {result.get('explanation', '(空)')}

**为什么重要**: {result.get('why_important', '(空)')}
"""

        return f"""请审查以下研究结果：

**概念**: {result.get('name', '?')}

**文章背景**: {article_summary[:400]}
{fields_text}
**推荐资料**:
{resources_text or '(无)'}

请调用 verify_result 提交审查结果。如果不通过，在 feedback 里具体说明哪里有问题、应该怎么改。"""
