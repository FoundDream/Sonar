"""Prompts and tools for the synthesize stage."""

CLASSIFY_TOOL = {
    "type": "function",
    "function": {
        "name": "classify_concepts",
        "description": "对已研究的概念进行分类、标注优先级、编排学习路径。",
        "parameters": {
            "type": "object",
            "properties": {
                "prerequisites": {
                    "type": "array",
                    "description": "前置知识列表（2-4 个，按学习顺序排列）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "概念名称（必须与已研究的概念名一致）"},
                            "priority": {
                                "type": "string",
                                "enum": ["must", "should"],
                                "description": "must=不了解就无法理解文章, should=了解了会更好",
                            },
                            "why_learn_first": {
                                "type": "string",
                                "description": "为什么要先学这个概念（一句话）",
                            },
                        },
                        "required": ["name", "priority", "why_learn_first"],
                    },
                },
                "concepts": {
                    "type": "array",
                    "description": "核心概念名称列表（3-5 个，按学习顺序排列）",
                    "items": {"type": "string"},
                },
                "learning_path": {
                    "type": "array",
                    "description": "学习路径，每步是可执行动作 + 关联概念",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step": {"type": "string", "description": "学习动作描述，如'先理解自注意力机制的工作原理'"},
                            "goal": {"type": "string", "description": "这一阶段想建立什么理解"},
                            "reason": {"type": "string", "description": "为什么这一步应该排在这里"},
                            "concepts": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "这一步关联的概念名称列表",
                            },
                        },
                        "required": ["step", "goal", "reason", "concepts"],
                    },
                },
            },
            "required": ["prerequisites", "concepts", "learning_path"],
        },
    },
}

SYNTHESIZER_PROMPT = """\
你是 Sonar 的报告编辑。

研究员已经为每个概念收集了详细的解释和学习资料。你不需要重复这些内容。

你需要做三件事：

1. 把概念分类为"前置知识"或"核心概念"
   - 前置知识：读者需要先了解的背景知识（2-4 个）
   - 核心概念：文章直接讨论的重要概念（3-5 个）

2. 为前置知识标注优先级
   - must: 不了解就无法理解文章
   - should: 了解了会更好，但不是必须

3. 编排学习路径
   - 每一步是一个可执行的学习动作，如"先理解 Transformer 的自注意力机制"
   - 每一步补充这一阶段的学习目标，以及为什么这一步排在这里
   - 每一步关联到具体的概念名称（可以关联多个）
   - 顺序必须合理：先前置，再核心，由浅入深
   - 不允许只是把概念名平铺成列表

调用 classify_concepts 提交分类结果。
"""


def build_classify_tool(section_specs: list) -> dict:
    """Build a classify tool from section specs."""
    del section_specs
    return CLASSIFY_TOOL
