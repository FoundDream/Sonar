"""Fetch 阶段：抓取文章内容 + LLM 内容质量验证。

未来可切换为本地模型验证（tools/classify.py），等 NVIDIA 模型下载后替换。
"""

import json

from llm.client import LLMClient
from stages.models import FetchResult
from tools.fetch import fetch_article

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


class FetchStage:
    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm

    def run(self, url: str) -> FetchResult | dict:
        """抓取文章，LLM 验证内容质量。"""
        print("\n--- 抓取文章 ---")
        result = fetch_article(url)
        if "error" in result:
            return {"error": f"抓取失败: {result['error']}"}

        # LLM 内容质量验证
        if self.llm:
            check = self._validate_content(result)
            if check and not check.get("usable", True):
                reason = check.get("reason", "内容不可用")
                print(f"[抓取] 内容验证未通过: {reason}")
                return {"error": f"内容不可用: {reason}"}

        fetch_result = FetchResult(
            url=url,
            title=result.get("title", ""),
            content=result.get("content", ""),
            author=result.get("author", ""),
            date=result.get("date", ""),
            description=result.get("description", ""),
            word_count=result.get("word_count", 0),
            was_truncated=result.get("was_truncated", False),
        )
        print(f"[抓取] 标题: {fetch_result.title}")
        return fetch_result

    def _validate_content(self, result: dict) -> dict | None:
        """LLM 快速验证。只传前 500 字，省 token。"""
        content_preview = result.get("content", "")[:500]
        title = result.get("title", "")

        messages = [
            {"role": "system", "content": _CHECK_PROMPT},
            {"role": "user", "content": f"标题: {title}\n\n内容片段:\n{content_preview}"},
        ]

        try:
            resp = self.llm.chat(messages, tools=[_CONTENT_CHECK_TOOL])
            if "tool_calls" in resp:
                for tc in resp["tool_calls"]:
                    if tc["function"]["name"] == "content_check":
                        return json.loads(tc["function"]["arguments"])
        except Exception as e:
            print(f"  [验证] LLM 验证失败({e})，跳过")

        return None
