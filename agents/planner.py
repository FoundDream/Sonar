"""规划器：根据用户目标筛选概念、生成研究提示。"""

import json

from llm.client import LLMClient

from models import AnalysisResult, ResearchPlan

# ── Prompt ────────────────────────────────────────────────────────

PLANNER_PROMPT = """\
你是 Sonar 的规划器。根据用户目标和文章分析结果，制定研究策略。

你可以做的决策：
1. 从分析出的概念中选择最相关的子集（3-8个），按学习优先级排序
2. 为每个选中的概念提供研究方向提示，引导研究员聚焦于用户目标

你不能做的事：
- 不能添加分析结果中没有的概念
- 不能改变流程步骤或报告格式
- 不能跳过概念研究阶段

决策原则：
- 如果用户目标明确，大胆裁剪不相关的概念
- 如果用户目标宽泛，保留更多概念但调整排序
- 研究提示应该具体、可执行，不要泛泛而谈

调用 create_plan 提交你的规划。
"""

# ── Tool ──────────────────────────────────────────────────────────

PLAN_TOOL = {
    "type": "function",
    "function": {
        "name": "create_plan",
        "description": "提交研究规划：选择概念子集并提供研究方向提示。",
        "parameters": {
            "type": "object",
            "properties": {
                "selected_concepts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "选中的概念列表（必须是分析结果中的概念），按学习优先级排序",
                },
                "concept_hints": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "每个概念的研究方向提示（key=概念名, value=提示文本）",
                },
                "reasoning": {
                    "type": "string",
                    "description": "简要说明你的规划逻辑",
                },
            },
            "required": ["selected_concepts", "concept_hints", "reasoning"],
        },
    },
}


# ── Agent ─────────────────────────────────────────────────────────

class Planner:
    """根据 preset/goal/analysis 生成 ResearchPlan。

    无 goal 时直接返回 preset（零 LLM 调用）。
    有 goal 时用 LLM 筛选概念、生成研究提示。
    """

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def plan(self, preset: str, goal: str, analysis: AnalysisResult) -> ResearchPlan:
        from presets import get_preset
        research_plan = get_preset(preset)
        research_plan.goal = goal

        if not goal:
            return research_plan

        planning_result = self._plan_with_llm(goal, analysis)
        if planning_result:
            research_plan.selected_concepts = planning_result["selected_concepts"]
            research_plan.concept_hints = planning_result["concept_hints"]
            print(f"[Plan] 规划完成: 选中 {len(research_plan.selected_concepts)}/{len(analysis.concepts)} 个概念")
            if planning_result.get("reasoning"):
                print(f"[Plan] 逻辑: {planning_result['reasoning'][:120]}")
        else:
            print("[Plan] LLM 规划失败，使用 preset 默认配置")

        return research_plan

    def _plan_with_llm(self, goal: str, analysis: AnalysisResult) -> dict | None:
        messages = [
            {"role": "system", "content": PLANNER_PROMPT},
            {"role": "user", "content": self._build_task(goal, analysis)},
        ]

        resp = self.llm.chat(messages, tools=[PLAN_TOOL])

        if "tool_calls" not in resp:
            return None

        for tc in resp["tool_calls"]:
            if tc["function"]["name"] == "create_plan":
                try:
                    result = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    return None

                valid = [c for c in result.get("selected_concepts", [])
                         if c in analysis.concepts]
                if not valid:
                    return None

                result["selected_concepts"] = valid
                result["concept_hints"] = {
                    k: v for k, v in result.get("concept_hints", {}).items()
                    if k in valid
                }
                return result

        return None

    @staticmethod
    def _build_task(goal: str, analysis: AnalysisResult) -> str:
        return f"""用户目标: {goal}

文章标题: {analysis.article_title}
文章摘要: {analysis.article_summary[:500]}

分析出的概念列表 ({len(analysis.concepts)} 个):
{json.dumps(analysis.concepts, ensure_ascii=False)}

请根据用户目标，从中选择最相关的概念，并为每个概念提供研究方向提示。调用 create_plan 提交。"""
