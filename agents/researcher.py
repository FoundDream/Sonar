"""研究员 Agent：搜索资料并研究单个概念。"""

from agents.base import Agent
from models import FieldSpec
from report.schema import format_issues, validate_concept, validate_finding
from tools.fetch import FETCH_RESOURCE_TOOL, fetch_resource
from tools.llm import LLMClient
from tools.search import SEARCH_TOOL, search

# ── Prompt ────────────────────────────────────────────────────────

RESEARCHER_PROMPT = """\
你是 Sonar 的研究员。你的任务是帮助读者理解文章中的关键概念。

你面向的读者是想理解这篇文章的人，假设他们聪明但不熟悉该领域。

## 可用工具

1. **search(query)** — 搜索关键词，返回 AI 摘要 + 5 条结果。
   每条含 snippet（600字）、domain、published_date、relevance_score。
2. **fetch_resource(url)** — 抓取网页正文（截断到 2000 字）。消耗一轮迭代，谨慎使用。
3. **concept_done(...)** — 提交研究结果。

## 工作方式

1. 用 search 搜索 1-2 次，利用 snippet 和 relevance_score 判断资料质量
2. 优先选择可靠域名的资料（官方文档、知名博客、教育机构网站、高质量学术来源）
3. 参考 published_date 优先选择较新的资料
4. 只在 snippet 不足以判断质量时才用 fetch_resource 查看详情
5. 搜索 2-3 次后，调用 concept_done 提交结构化结果。
   如果收到审查反馈（status: needs_revision），根据反馈补充搜索后再次提交

## 资料来源要求

优先选择（按优先级排序）：
1. 官方文档、项目主页（如 github.com, pytorch.org, openai.com）
2. 原作者的博客或文章
3. 知名技术博客（如 lilianweng.github.io, jalammar.github.io, distill.pub）
4. 教育机构资料（如 .edu 域名、Stanford/MIT 课程页）
5. 学术来源（arxiv.org, ACM, IEEE, 会议论文）

避免选择：
- 新闻聚合站（如 QQ 新闻、百家号、搜狐号）
- 内容农场和转载站
- 域名看不出可信来源的网站
- 被分析的原文章本身（不要把原文推荐为学习资料）

如果搜索结果中没有高质量来源，宁可只推荐 1 条好的，也不要凑数。

## 注意事项

- 解释要通俗易懂，用例子和类比帮助读者建立直觉
- 除了解释"是什么"，还要说明它在本文里扮演什么角色
- methodology 和 key_findings 是补充信息，适用时填写，不适用可留空
- 所有资料链接必须来自搜索结果，不要编造
- 每个概念只推荐 1-2 条最高质量的学习资料，少而精
"""

# ── Tools ─────────────────────────────────────────────────────────

EMPTY_FINDING = {
    "name": "",
    "explanation": "",
    "why_important": "",
    "article_role": "",
    "example": "",
    "analogy": "",
    "resources": [],
}

CONCEPT_DONE_TOOL = {
    "type": "function",
    "function": {
        "name": "concept_done",
        "description": "提交单个概念的研究结果。包含概念的解释和推荐学习资料（1-2条精选）。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "概念名称"},
                "explanation": {"type": "string", "description": "概念的通俗解释，不限字数，写清楚为止"},
                "why_important": {"type": "string", "description": "为什么理解这个概念对读懂文章很重要"},
                "article_role": {"type": "string", "description": "这个概念在本文中具体扮演什么角色"},
                "example": {"type": "string", "description": "用一个简短例子帮助读者理解这个概念"},
                "analogy": {"type": "string", "description": "可选：用一个类比帮助建立直觉；如果不需要可留空"},
                "resources": {
                    "type": "array",
                    "description": "精选 1-2 条最好的学习资料",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "url": {"type": "string"},
                            "description": {"type": "string", "description": "简短描述这个资料讲了什么"},
                        },
                        "required": ["title", "url"],
                    },
                },
            },
            "required": ["name", "explanation", "why_important", "article_role", "example", "analogy", "resources"],
        },
    },
}


def build_finding_tool(field_specs: list[FieldSpec]) -> dict:
    """Build a concept_done tool schema from plan-defined fields."""
    properties = {}
    required = []

    for spec in field_specs:
        if spec.name == "resources":
            properties["resources"] = {
                "type": "array",
                "description": spec.description,
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "url": {"type": "string"},
                        "description": {"type": "string", "description": "简短描述这个资料讲了什么"},
                    },
                    "required": ["title", "url"],
                },
            }
        else:
            properties[spec.name] = {
                "type": spec.type,
                "description": spec.description,
            }

        if spec.required:
            required.append(spec.name)

    return {
        "type": "function",
        "function": {
            "name": "concept_done",
            "description": "提交研究结果。",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


# ── Agent ─────────────────────────────────────────────────────────

class Researcher(Agent):
    """Agent that researches a single concept using search and fetch tools."""

    MAX_VERIFY_RETRIES = 2  # 最多被 Verifier 拒绝 2 次后接受结果

    def __init__(self, llm: LLMClient, verifier=None,
                 finding_tool: dict | None = None,
                 researcher_prompt: str | None = None,
                 finding_schema: list[FieldSpec] | None = None):
        super().__init__(
            llm,
            name="研究员",
            system_prompt=researcher_prompt or RESEARCHER_PROMPT,
            max_iterations=10,
        )
        self._finding_schema = finding_schema
        self._verifier = verifier

        # 每次 research() 调用重置
        self._summary: str = ""
        self._verify_count: int = 0
        self._stop: bool = False
        self._final_result: dict = {}

        self.add_tool(SEARCH_TOOL, handler=search)
        self.add_tool(FETCH_RESOURCE_TOOL, handler=fetch_resource)
        # concept_done 为非终止工具，由 _handle_submit 处理
        self.add_tool(finding_tool or CONCEPT_DONE_TOOL, handler=self._handle_submit)

    def _handle_submit(self, **args) -> dict:
        """concept_done 的处理器：格式校验 → 内联 Verifier → 通过/反馈。"""
        # Step 1: 格式校验
        if self._finding_schema:
            issues = validate_finding(args, self._finding_schema)
        else:
            issues = validate_concept(args)
        errors = [iss for iss in issues if iss.severity == "error"]
        if errors:
            return {"status": "rejected", "reason": "格式校验失败:\n" + format_issues(errors)}

        # Step 2: 无 Verifier 时直接接受（向后兼容）
        if self._verifier is None:
            self._stop = True
            self._final_result = args
            return {"status": "accepted"}

        # Step 3: 运行 Verifier
        self._verify_count += 1
        verdict = self._verifier.verify(args, self._summary)

        if verdict.get("pass", True):
            self._log(f"审查通过（第 {self._verify_count} 次提交）")
            self._stop = True
            self._final_result = args
            return {"status": "accepted"}

        feedback = verdict.get("feedback", "审查未通过")

        if self._verify_count >= Researcher.MAX_VERIFY_RETRIES:
            self._log(f"已达最大审查次数 ({self._verify_count})，接受当前结果")
            self._stop = True
            self._final_result = args
            return {"status": "accepted_after_max_retries"}

        self._log(f"审查未通过（第 {self._verify_count} 次），要求修改")
        return {
            "status": "needs_revision",
            "feedback": feedback,
            "instruction": "请根据反馈补充搜索后再次调用 concept_done 提交。",
        }

    def research(self, concept: str, article_summary: str, hints: str = "") -> dict:
        """Research a concept and return the finding dict."""
        self._summary = article_summary
        self._verify_count = 0
        self._stop = False
        self._final_result = {}
        task = self._build_task(concept, article_summary, hints)
        result = self.run(task)
        return self._final_result or result or dict(EMPTY_FINDING, name=concept)

    def on_timeout(self, messages: list[dict]) -> dict:
        if self._final_result:
            return self._final_result
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
