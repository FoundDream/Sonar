"""Plan 阶段：根据 preset/goal/analysis 生成 ResearchPlan。

无 goal 时直接返回 preset（零 LLM 调用）。
有 goal 时用 LLM 筛选概念、生成研究提示。
"""

import json

from llm.client import LLMClient
from stages.models import AnalysisResult, ResearchPlan
from stages.prompts.plan import PLAN_TOOL, PLANNER_PROMPT


class PlanStage:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(self, preset: str, goal: str, analysis: AnalysisResult) -> ResearchPlan:
        from presets import get_preset
        plan = get_preset(preset)
        plan.goal = goal

        if not goal:
            return plan

        # Use LLM to customize the plan based on goal
        planning_result = self._plan_with_llm(goal, analysis)
        if planning_result:
            plan.selected_concepts = planning_result["selected_concepts"]
            plan.concept_hints = planning_result["concept_hints"]
            print(f"[Plan] 规划完成: 选中 {len(plan.selected_concepts)}/{len(analysis.concepts)} 个概念")
            if planning_result.get("reasoning"):
                print(f"[Plan] 逻辑: {planning_result['reasoning'][:120]}")
        else:
            print("[Plan] LLM 规划失败，使用 preset 默认配置")

        return plan

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

                # Validate: selected concepts must be subset of analysis concepts
                valid = [c for c in result.get("selected_concepts", [])
                         if c in analysis.concepts]
                if not valid:
                    return None

                result["selected_concepts"] = valid
                # Filter hints to only valid concepts
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
