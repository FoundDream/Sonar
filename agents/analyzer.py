"""分析器 Agent：分析文章内容，提取摘要、速览、核心概念。"""

from agents.base import Agent
from models import AnalysisResult, FetchResult
from tools.llm import LLMClient
from tools.search import SEARCH_TOOL, search

# ── Prompt ────────────────────────────────────────────────────────

ANALYZER_PROMPT = """\
你是 Sonar 的文章分析员。你的任务是分析文章内容，提取结构化信息。

## 可用工具

1. **search(query)** — 搜索领域背景知识。当你不确定某个概念是否属于"读者背景知识"时，
   可以搜索一下该领域，帮助你判断目标读者的知识背景和文章的难度。
2. **submit_analysis(...)** — 提交分析结果（终止）

## 工作方式

1. 仔细阅读文章内容
2. 如有必要，用 search 了解该领域背景（帮助判断概念难度、目标受众）
3. 调用 submit_analysis 提交结构化分析结果
"""

# ── Tool ──────────────────────────────────────────────────────────

SUBMIT_ANALYSIS_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_analysis",
        "description": "提交文章分析结果。",
        "parameters": {
            "type": "object",
            "properties": {
                "overview": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "description": "一句话概括文章主题（不超过 30 字）"},
                        "target_audience": {"type": "string", "description": "适合什么样的读者"},
                        "difficulty": {"type": "string", "enum": ["beginner", "intermediate", "advanced"]},
                        "recommendation": {"type": "string", "enum": ["deep_read", "skim_first", "learn_prerequisites"]},
                    },
                    "required": ["topic", "target_audience", "difficulty", "recommendation"],
                },
                "summary": {"type": "string", "description": "文章核心内容摘要（120-220字）"},
                "article_analysis": {
                    "type": "object",
                    "properties": {
                        "main_thesis": {"type": "string"},
                        "key_insights": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "detail": {"type": "string"},
                                    "why_it_matters": {"type": "string"},
                                },
                                "required": ["title", "detail", "why_it_matters"],
                            },
                        },
                        "supporting_points": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "claim": {"type": "string"},
                                    "evidence": {"type": "string"},
                                },
                                "required": ["claim", "evidence"],
                            },
                        },
                        "author_takeaway": {"type": "string"},
                    },
                    "required": ["main_thesis", "key_insights", "supporting_points", "author_takeaway"],
                },
                "concepts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "核心概念名称列表（5-8个），包含前置知识和核心概念",
                },
            },
            "required": ["overview", "summary", "article_analysis", "concepts"],
        },
    },
}


# ── Agent ─────────────────────────────────────────────────────────

class Analyzer(Agent):
    """分析文章内容，提取结构化信息。"""

    def __init__(self, llm: LLMClient):
        super().__init__(llm, name="分析员", system_prompt=ANALYZER_PROMPT, max_iterations=5)
        self.add_tool(SEARCH_TOOL, handler=search)
        self.add_terminal_tool(SUBMIT_ANALYSIS_TOOL)

    def analyze(self, fetch_result: FetchResult) -> AnalysisResult | dict:
        """分析文章，返回 AnalysisResult 或 error dict。"""
        print("\n--- 分析文章 ---")
        task = f"标题: {fetch_result.title}\n\n正文:\n{fetch_result.content}"
        result = self.run(task)

        if not result or not result.get("concepts"):
            return {"error": "未能从文章中识别出核心概念"}

        analysis = AnalysisResult(
            url=fetch_result.url,
            article_title=fetch_result.title,
            article_summary=result.get("summary", ""),
            overview=result.get("overview", {}),
            article_analysis=result.get("article_analysis", {}),
            concepts=result.get("concepts", []),
        )

        if analysis.overview:
            difficulty = analysis.overview.get("difficulty", "?")
            recommendation = analysis.overview.get("recommendation", "?")
            print(f"[分析] 难度: {difficulty}, 建议: {recommendation}")
        print(f"[分析] 摘要: {analysis.article_summary[:80]}...")
        if analysis.article_analysis.get("main_thesis"):
            print(f"[分析] 核心论点: {analysis.article_analysis['main_thesis'][:80]}...")
        print(f"[分析] 识别到 {len(analysis.concepts)} 个核心概念: {', '.join(analysis.concepts)}")

        return analysis
