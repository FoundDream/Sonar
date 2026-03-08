"""报告审查员 Agent 的工具定义。"""

REVIEW_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_review",
        "description": "提交审查结果：标记需要返工的概念。",
        "parameters": {
            "type": "object",
            "properties": {
                "passed": {
                    "type": "boolean",
                    "description": "true=所有概念都通过, false=有概念需要返工",
                },
                "rework": {
                    "type": "array",
                    "description": "需要返工的概念列表（如果 passed=true 则为空数组）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "concept": {
                                "type": "string",
                                "description": "概念名称（必须与研究结果中的名称一致）",
                            },
                            "feedback": {
                                "type": "string",
                                "description": "具体问题和改进建议（会转发给研究员）",
                            },
                        },
                        "required": ["concept", "feedback"],
                    },
                },
            },
            "required": ["passed", "rework"],
        },
    },
}
