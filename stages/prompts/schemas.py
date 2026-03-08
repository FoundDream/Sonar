"""Reusable tool schemas for stage prompts."""


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


def build_finding_tool(field_specs: list) -> dict:
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
