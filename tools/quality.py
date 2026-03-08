"""内容质量检查：统一入口，小模型优先、LLM 兜底。"""

import json

_MIN_CONTENT_LEN = 100

_CONTENT_CHECK_TOOL = {
    "type": "function",
    "function": {
        "name": "content_check",
        "description": "判断抓取到的内容是否可用",
        "parameters": {
            "type": "object",
            "properties": {
                "usable": {
                    "type": "boolean",
                    "description": "内容是否可用于分析",
                },
                "reason": {
                    "type": "string",
                    "description": "简述判断理由",
                },
            },
            "required": ["usable", "reason"],
        },
    },
}

_CHECK_PROMPT = """\
你是内容质量检查员。根据抓取到的内容片段，判断这是否是有实质内容的文章或文档。

以下情况判为不可用:
- 错误页面（404、403、500 等）
- 付费墙（只有摘要，提示订阅/付费才能阅读全文）
- 登录墙（需要登录才能查看内容）
- 纯导航/索引页，无实质正文
- Cookie 同意页或重定向中间页

只要有实质性的正文内容就判为可用，即使内容不完整或有少量噪声。
调用 content_check 提交判断。"""


def _llm_check(content: str, llm) -> bool:
    """用 LLM 判断内容是否可用。"""
    preview = content[:500]
    messages = [
        {"role": "system", "content": _CHECK_PROMPT},
        {"role": "user", "content": f"内容片段:\n{preview}"},
    ]
    try:
        resp = llm.chat(messages, tools=[_CONTENT_CHECK_TOOL])
        if "tool_calls" in resp:
            for tc in resp["tool_calls"]:
                if tc["function"]["name"] == "content_check":
                    result = json.loads(tc["function"]["arguments"])
                    usable = result.get("usable", True)
                    if not usable:
                        print(f"  [质量] LLM: 不可用 — {result.get('reason', '')[:60]}")
                    return usable
    except Exception as e:
        print(f"  [质量] LLM 检查失败({e})，放行")
    return True


def make_quality_checker(llm=None):
    """构造质量检查函数：小模型优先、LLM 兜底 → 都没有放行。

    返回 Callable[[str], bool]。
    """
    # 尝试加载小模型
    local_check = None
    try:
        from tools.classify import check_content_quality
        local_check = check_content_quality
    except ImportError:
        pass

    def checker(content: str) -> bool:
        if len(content.strip()) < _MIN_CONTENT_LEN:
            print(f"  [质量] 内容过短({len(content.strip())}字)")
            return False

        if local_check:
            result = local_check(content)
            if not result["usable"]:
                print(f"  [质量] 小模型: {result['quality']} (score={result['score']:.2f})")
            return result["usable"]

        if llm:
            return _llm_check(content, llm)

        return True

    return checker
