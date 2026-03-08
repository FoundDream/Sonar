"""审查员 Agent：审查单个概念的研究质量。"""

from agents.base import Agent
from models import FieldSpec
from tools.llm import LLMClient

# ── Prompt ────────────────────────────────────────────────────────

VERIFIER_PROMPT = """\
你是 Sonar 的质量审查员。你的任务是审查研究员对一个概念的研究结果。

你需要检查三个方面：

1. **解释质量**：explanation 是否真正解释了这个概念？
   - 不合格：只是复述概念名、过于笼统、或者解释了别的东西
   - 合格：读者读完能理解这个概念是什么、怎么工作

2. **上下文匹配**：研究结果是否与文章主题相关？
   - 不合格：概念解释正确但角度完全偏离文章讨论的方向
   - 合格：解释的角度和文章的使用场景一致

3. **资源质量**：推荐的学习资料是否合适？
   - 不合格：资料标题/描述看起来与概念不对口，或来自不可靠来源
   - 合格：资料直接针对该概念，来源可信

调用 verify_result 提交你的审查结果。
"""

# ── Tool ──────────────────────────────────────────────────────────

VERIFY_TOOL = {
    "type": "function",
    "function": {
        "name": "verify_result",
        "description": "提交对研究结果的审查判定。",
        "parameters": {
            "type": "object",
            "properties": {
                "pass": {
                    "type": "boolean",
                    "description": "true=通过, false=不通过需要重新研究",
                },
                "feedback": {
                    "type": "string",
                    "description": "如果不通过，给研究员的具体修改建议（会直接转发给研究员作为重新研究的提示）",
                },
            },
            "required": ["pass", "feedback"],
        },
    },
}


# ── Agent ─────────────────────────────────────────────────────────

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
