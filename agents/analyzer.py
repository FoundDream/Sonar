"""分析器：LLM 分析文章，提取摘要、速览、核心概念。"""

import json

from llm.client import LLMClient

from models import AnalysisResult, FetchResult

# ── Prompt ────────────────────────────────────────────────────────

ANALYZE_PROMPT = """\
请分析以下文章，返回 JSON 格式的结果：

标题: {title}

正文:
{content}

请返回严格的 JSON（不要 markdown 代码块），包含：

1. "overview": 文章速览，包含：
   - "topic": 一句话概括文章主题（不超过 30 字）
   - "target_audience": 适合什么样的读者（如"有深度学习基础的工程师"）
   - "difficulty": 阅读难度，只能是 "beginner" / "intermediate" / "advanced"
   - "recommendation": 阅读建议，只能是以下之一：
     "deep_read"（可以直接深读）/ "skim_first"（建议先略读）/
     "learn_prerequisites"（建议先补前置知识）

2. "summary": 文章核心内容摘要（120-220字）

3. "article_analysis": 对文章本身的结构化拆解，包含：
   - "main_thesis": 文章最核心的论点（一句话）
   - "key_insights": 关键洞见列表（2-4 个），每项包含：
     - "title": 洞见标题
     - "detail": 具体展开（2-4句）
     - "why_it_matters": 这条洞见为什么重要
   - "supporting_points": 支撑论点列表（2-4 个），每项包含：
     - "claim": 作者的一个重要主张
     - "evidence": 文章用什么论据、例子或推理支撑它
   - "author_takeaway": 作者最终想让读者记住什么

4. "concepts": 核心概念名称列表（5-8个字符串），包括前置知识和核心概念

示例：
{{
  "overview": {{
    "topic": "用LLM构建自主智能体",
    "target_audience": "有NLP基础的工程师",
    "difficulty": "advanced",
    "recommendation": "learn_prerequisites"
  }},
  "summary": "这篇文章讲述了...",
  "article_analysis": {{
    "main_thesis": "作者认为...",
    "key_insights": [
      {{"title": "洞见A", "detail": "作者指出...", "why_it_matters": "它解释了..."}},
      {{"title": "洞见B", "detail": "文章进一步说明...", "why_it_matters": "它决定了..."}}
    ],
    "supporting_points": [
      {{"claim": "主张A", "evidence": "作者通过...支撑"}},
      {{"claim": "主张B", "evidence": "文章用...说明"}}
    ],
    "author_takeaway": "最终作者想强调..."
  }},
  "concepts": ["概念A", "概念B", "概念C"]
}}"""


# ── Agent ─────────────────────────────────────────────────────────

class Analyzer:
    """分析文章内容，提取结构化信息。"""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def analyze(self, fetch_result: FetchResult) -> AnalysisResult | dict:
        """分析文章，返回 AnalysisResult 或 error dict。"""
        print("\n--- 分析文章 ---")
        analysis = self._call_llm(fetch_result)

        result = AnalysisResult(
            url=fetch_result.url,
            article_title=fetch_result.title,
            article_summary=analysis.get("summary", ""),
            overview=analysis.get("overview", {}),
            article_analysis=analysis.get("article_analysis", {}),
            concepts=analysis.get("concepts", []),
        )

        if result.overview:
            difficulty = result.overview.get("difficulty", "?")
            recommendation = result.overview.get("recommendation", "?")
            print(f"[分析] 难度: {difficulty}, 建议: {recommendation}")
        print(f"[分析] 摘要: {result.article_summary[:80]}...")
        if result.article_analysis.get("main_thesis"):
            print(f"[分析] 核心论点: {result.article_analysis['main_thesis'][:80]}...")
        print(f"[分析] 识别到 {len(result.concepts)} 个核心概念: {', '.join(result.concepts)}")

        if not result.concepts:
            return {"error": "未能从文章中识别出核心概念"}

        return result

    def _call_llm(self, fetch_result: FetchResult) -> dict:
        messages = [
            {"role": "system", "content": "你是一个学术文章分析助手。"},
            {"role": "user", "content": ANALYZE_PROMPT.format(
                title=fetch_result.title,
                content=fetch_result.content,
            )},
        ]
        resp = self.llm.chat(messages)
        content = resp.get("content", "")

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}") + 1
            if start != -1 and end > start:
                try:
                    return json.loads(content[start:end])
                except json.JSONDecodeError:
                    pass
        return {"overview": {}, "summary": content[:500], "article_analysis": {}, "concepts": []}
