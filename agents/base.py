"""Agent 基类：统一的 LLM 工具调用循环。"""

import json
from collections.abc import Callable


class Agent:
    """LLM-powered agent with tool-calling loop.

    Usage:
        agent = Agent(llm, name="Researcher", system_prompt="...")
        agent.add_tool(SEARCH_TOOL, handler=search)
        agent.add_terminal_tool(CONCEPT_DONE_TOOL)
        result = agent.run("研究概念 X ...")
    """

    def __init__(self, llm, name: str, system_prompt: str, max_iterations: int = 10):
        self.llm = llm
        self.name = name
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations

        self._tools: list[dict] = []
        self._handlers: dict[str, Callable] = {}
        self._terminal_tools: set[str] = set()

    def add_tool(self, schema: dict, handler: Callable) -> None:
        """Register a non-terminal tool (agent continues after calling it)."""
        self._tools.append(schema)
        self._handlers[schema["function"]["name"]] = handler

    def add_terminal_tool(self, schema: dict) -> None:
        """Register a terminal tool (agent returns its arguments as the result)."""
        self._tools.append(schema)
        self._terminal_tools.add(schema["function"]["name"])

    def run(self, task: str) -> dict:
        """Run the agent loop. Returns the terminal tool's arguments."""
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task},
        ]

        best_result: dict | None = None

        for i in range(self.max_iterations):
            self._log(f"第 {i + 1} 轮")
            resp = self.llm.chat(messages, tools=self._tools)
            messages.append(resp)

            if resp.get("content"):
                self._log(f"思考: {resp['content'][:80]}...")

            if "tool_calls" not in resp:
                continue

            for tc in resp["tool_calls"]:
                name = tc["function"]["name"]
                call_id = tc["id"]

                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError as e:
                    self._log(f"JSON 解析失败: {e}")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": f"JSON 解析失败: {e}。请重新调用，确保参数是合法 JSON。",
                    })
                    continue

                # Terminal tool → validate and return
                if name in self._terminal_tools:
                    error = self.validate_result(name, args)
                    if error:
                        best_result = args
                        messages.append({
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": error,
                        })
                        self._log("结果未通过校验，要求修正")
                        continue
                    self._log(f"完成 ({name})")
                    return args

                # Non-terminal tool → execute and continue
                handler = self._handlers.get(name)
                if handler is None:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False),
                    })
                    continue

                self._log(f"工具: {name}({json.dumps(args, ensure_ascii=False)[:60]})")
                result = handler(**args)
                result_str = json.dumps(result, ensure_ascii=False)
                self._log(f"结果: {result_str[:100]}...")
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result_str,
                })

        # Timeout: try to force a result, or return best partial result
        if best_result:
            self._log("超时，使用未完全通过校验的结果")
            return best_result
        return self.on_timeout(messages)

    def validate_result(self, tool_name: str, args: dict) -> str | None:
        """Validate terminal tool result. Return error message or None if valid.

        Override in subclasses for custom validation.
        """
        return None

    def on_timeout(self, messages: list[dict]) -> dict:
        """Handle timeout. Override to force a final result.

        Default: ask the LLM to submit immediately.
        """
        self._log("超时，要求立即提交")
        messages.append({
            "role": "user",
            "content": "时间到了，请立刻调用工具提交你目前的结果。",
        })
        terminal_tools = [t for t in self._tools if t["function"]["name"] in self._terminal_tools]
        resp = self.llm.chat(messages, tools=terminal_tools or self._tools)
        if "tool_calls" in resp:
            for tc in resp["tool_calls"]:
                if tc["function"]["name"] in self._terminal_tools:
                    try:
                        return json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError:
                        pass
        return {}

    def _log(self, msg: str) -> None:
        print(f"  [{self.name}] {msg}")
