"""LLM 统一接口，支持 OpenAI 兼容 API 和 AWS Bedrock Converse API。"""

import json
import os

import httpx
from openai import OpenAI


class LLMClient:
    def __init__(self, model: str | None = None, base_url: str | None = None, api_key: str | None = None):
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o")
        self._base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        self._api_key = api_key

        # 判断是否走 Bedrock Converse API（bearer token + Claude 模型）
        bearer = os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
        self._use_bedrock = bool(bearer and "anthropic" in self.model)

        if self._use_bedrock:
            self._bearer_token = bearer
            region = os.environ.get("AWS_REGION", "us-east-1")
            self._bedrock_endpoint = f"https://bedrock-runtime.{region}.amazonaws.com"
        else:
            self.client = OpenAI(
                base_url=self._base_url,
                api_key=self._resolve_api_key(api_key),
            )

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        if self._use_bedrock:
            return self._chat_bedrock(messages, tools)
        return self._chat_openai(messages, tools)

    # ── OpenAI 兼容路径 ──

    def _chat_openai(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        kwargs = {"model": self.model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        response = self.client.chat.completions.create(**kwargs)
        message = response.choices[0].message
        return self._serialize_openai_message(message)

    def _serialize_openai_message(self, message) -> dict:
        result = {"role": "assistant", "content": message.content}
        if message.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]
        return result

    # ── Bedrock Converse 路径 ──

    def _chat_bedrock(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        # 分离 system prompt 和对话消息
        system_prompts = []
        converse_messages = []

        for msg in messages:
            if msg["role"] == "system":
                system_prompts.append({"text": msg["content"]})
            elif msg["role"] == "user":
                converse_messages.append({
                    "role": "user",
                    "content": [{"text": msg["content"]}],
                })
            elif msg["role"] == "assistant":
                content = []
                if msg.get("content"):
                    content.append({"text": msg["content"]})
                for tc in msg.get("tool_calls", []):
                    content.append({
                        "toolUse": {
                            "toolUseId": tc["id"],
                            "name": tc["function"]["name"],
                            "input": json.loads(tc["function"]["arguments"]),
                        }
                    })
                converse_messages.append({"role": "assistant", "content": content})
            elif msg["role"] == "tool":
                # Bedrock 需要 tool results 包在 user message 里
                # 检查上一条是否已经是 toolResult 的 user message，合并进去
                tool_result = {
                    "toolResult": {
                        "toolUseId": msg["tool_call_id"],
                        "content": [{"text": msg["content"]}],
                    }
                }
                if converse_messages and converse_messages[-1].get("role") == "user" and \
                   any("toolResult" in c for c in converse_messages[-1].get("content", [])):
                    converse_messages[-1]["content"].append(tool_result)
                else:
                    converse_messages.append({
                        "role": "user",
                        "content": [tool_result],
                    })

        # 构建请求体
        body = {
            "messages": converse_messages,
            "inferenceConfig": {"maxTokens": 16384},
        }
        if system_prompts:
            body["system"] = system_prompts
        if tools:
            body["toolConfig"] = {
                "tools": [self._convert_tool_to_bedrock(t) for t in tools]
            }

        url = f"{self._bedrock_endpoint}/model/{self.model}/converse"
        resp = httpx.post(
            url,
            json=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._bearer_token}",
            },
            timeout=300,
        )
        resp.raise_for_status()
        data = resp.json()

        return self._parse_bedrock_response(data)

    def _convert_tool_to_bedrock(self, tool: dict) -> dict:
        """OpenAI tool 定义 -> Bedrock toolSpec 格式。"""
        func = tool["function"]
        return {
            "toolSpec": {
                "name": func["name"],
                "description": func.get("description", ""),
                "inputSchema": {
                    "json": func["parameters"],
                },
            }
        }

    def _parse_bedrock_response(self, data: dict) -> dict:
        """Bedrock Converse 响应 -> OpenAI 格式的 assistant message。"""
        output = data.get("output", {}).get("message", {})
        content_blocks = output.get("content", [])

        text_parts = []
        tool_calls = []

        for block in content_blocks:
            if "text" in block:
                text_parts.append(block["text"])
            elif "toolUse" in block:
                tu = block["toolUse"]
                tool_calls.append({
                    "id": tu["toolUseId"],
                    "type": "function",
                    "function": {
                        "name": tu["name"],
                        "arguments": json.dumps(tu["input"], ensure_ascii=False),
                    },
                })

        result = {"role": "assistant", "content": "\n".join(text_parts) if text_parts else None}
        if tool_calls:
            result["tool_calls"] = tool_calls
        return result

    def _resolve_api_key(self, api_key: str | None) -> str | None:
        if api_key:
            return api_key
        return os.environ.get("OPENAI_API_KEY") or os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
