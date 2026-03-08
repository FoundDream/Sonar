"""审查员 Agent 的工具定义。"""

VERIFY_TOOL = {
    "type": "function",
    "function": {
        "name": "verify_result",
        "description": "提交对研究结果的审查判定。",
        "parameters": {
            "type": "object",
            "properties": {
                "pass": {
                    "type": "boolean",
                    "description": "true=通过, false=不通过需要重新研究",
                },
                "feedback": {
                    "type": "string",
                    "description": "如果不通过，给研究员的具体修改建议（会直接转发给研究员作为重新研究的提示）",
                },
            },
            "required": ["pass", "feedback"],
        },
    },
}
