"""Prompts and tools for the plan stage."""

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
