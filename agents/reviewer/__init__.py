"""报告审查员 Agent：LLM-powered 报告级质量审查。"""

from agents.base import Agent
from llm.client import LLMClient

from .prompt import REVIEWER_PROMPT
from .tools import REVIEW_TOOL


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
