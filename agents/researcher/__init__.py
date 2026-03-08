"""研究员 Agent：搜索资料并研究单个概念。"""

from agents.base import Agent
from llm.client import LLMClient
from report.schema import format_issues, validate_concept, validate_finding
from stages.models import FieldSpec
from tools.fetch import FETCH_RESOURCE_TOOL, fetch_resource
from tools.search import SEARCH_TOOL, search

from .prompt import RESEARCHER_PROMPT
from .tools import CONCEPT_DONE_TOOL, EMPTY_FINDING


class Researcher(Agent):
    """Agent that researches a single concept using search and fetch tools."""

    def __init__(self, llm: LLMClient, finding_tool: dict | None = None,
                 researcher_prompt: str | None = None,
                 finding_schema: list[FieldSpec] | None = None):
        super().__init__(
            llm,
            name="研究员",
            system_prompt=researcher_prompt or RESEARCHER_PROMPT,
            max_iterations=5,
        )
        self._finding_schema = finding_schema

        self.add_tool(SEARCH_TOOL, handler=search)
        self.add_tool(FETCH_RESOURCE_TOOL, handler=fetch_resource)
        self.add_terminal_tool(finding_tool or CONCEPT_DONE_TOOL)

    def research(self, concept: str, article_summary: str, hints: str = "") -> dict:
        """Research a concept and return the finding dict."""
        task = self._build_task(concept, article_summary, hints)
        result = self.run(task)
        return result or dict(EMPTY_FINDING, name=concept)

    def validate_result(self, tool_name: str, args: dict) -> str | None:
        if self._finding_schema:
            issues = validate_finding(args, self._finding_schema)
        else:
            issues = validate_concept(args)
        errors = [iss for iss in issues if iss.severity == "error"]
        if not errors:
            return None
        return "结果未通过质量检查，请修正后重新调用 concept_done:\n" + format_issues(errors)

    def on_timeout(self, messages: list[dict]) -> dict:
        result = super().on_timeout(messages)
        return result or dict(EMPTY_FINDING)

    @staticmethod
    def _build_task(concept: str, article_summary: str, hints: str) -> str:
        parts = [f"请研究以下概念，找到通俗易懂的学习资料：\n\n**概念**: {concept}"]
        if article_summary:
            parts.append(f"\n**文章背景**:\n{article_summary[:500]}")
        if hints:
            parts.append(f"\n**搜索建议**: {hints}")
        parts.append("\n搜索 2-3 次后，调用 concept_done 提交你的研究结果（精选 1-2 条最好的资料）。")
        return "\n".join(parts)
