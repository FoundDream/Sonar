"""Scout Agent：探索项目结构，生成项目地图。"""

import os

from agents.base import Agent
from tools.filesystem import (
    GET_TREE_TOOL,
    LIST_DIRECTORY_TOOL,
    READ_FILE_TOOL,
    SEARCH_IN_FILES_TOOL,
    get_tree,
    list_directory,
    read_file,
    search_in_files,
)
from tools.llm import LLMClient

# ── Prompt ────────────────────────────────────────────────────────

SCOUT_PROMPT = """\
你是 Sonar 的 Scout（侦察员）。你的任务是探索一个项目，生成项目地图。

## 可用工具

1. **get_tree(path)** — 获取目录结构树，快速了解项目组织
2. **list_directory(path)** — 列出目录内容（类型、大小）
3. **read_file(path)** — 读取文件内容（截断到 6000 字符）
4. **search_in_files(query, path)** — 搜索关键词，找到相关文件

## 工作方式

1. 用 get_tree 了解整体结构
2. 读取 README 和关键文档了解项目用途
3. 有选择地读取核心源码文件了解架构
4. 调用 submit_project_map 提交项目地图

## 注意

- 不要读所有文件。聚焦于：README、主入口、配置文件、文档目录
- 代码文件只读关键的（入口、核心模块），不要逐个读
- 目标是帮用户建立全局理解，不是逐行分析
- concepts 应该列出用户理解这个项目需要知道的技术概念和领域知识
"""

# ── Tool ──────────────────────────────────────────────────────────

SUBMIT_MAP_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_project_map",
        "description": "提交项目地图：项目概述、架构、关键文件、待研究概念。",
        "parameters": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "项目名称",
                },
                "description": {
                    "type": "string",
                    "description": "项目做什么（2-3 句话）",
                },
                "architecture": {
                    "type": "string",
                    "description": "项目的高层架构（组件如何协作、数据如何流动）",
                },
                "key_files": {
                    "type": "array",
                    "description": "关键文件列表（按重要性排序，5-10 个）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "文件相对路径"},
                            "role": {"type": "string", "description": "这个文件的职责（一句话）"},
                        },
                        "required": ["path", "role"],
                    },
                },
                "concepts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "理解这个项目需要知道的核心概念/技术（5-8 个）",
                },
                "entry_points": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "建议用户从哪些文件开始阅读（2-3 个）",
                },
            },
            "required": [
                "project_name", "description", "architecture",
                "key_files", "concepts", "entry_points",
            ],
        },
    },
}


# ── Agent ─────────────────────────────────────────────────────────

class Scout(Agent):
    """Agent that explores a project directory and produces a structured map."""

    def __init__(self, llm: LLMClient):
        super().__init__(
            llm,
            name="Scout",
            system_prompt=SCOUT_PROMPT,
            max_iterations=8,
        )
        self.add_tool(GET_TREE_TOOL, handler=get_tree)
        self.add_tool(LIST_DIRECTORY_TOOL, handler=list_directory)
        self.add_tool(READ_FILE_TOOL, handler=read_file)
        self.add_tool(SEARCH_IN_FILES_TOOL, handler=search_in_files)
        self.add_terminal_tool(SUBMIT_MAP_TOOL)

    def explore(self, project_path: str, goal: str = "") -> dict:
        """Explore a project and return a project map."""
        task = self._build_task(project_path, goal)
        result = self.run(task)
        return result or {
            "project_name": os.path.basename(project_path),
            "description": "",
            "architecture": "",
            "key_files": [],
            "concepts": [],
            "entry_points": [],
        }

    @staticmethod
    def _build_task(project_path: str, goal: str) -> str:
        parts = [f"请探索以下项目并生成项目地图：\n\n项目路径: {project_path}"]
        if goal:
            parts.append(f"\n用户目标: {goal}")
            parts.append("请特别关注与用户目标相关的部分。")
        parts.append("\n先用 get_tree 查看整体结构，然后有选择地读取关键文件。")
        return "\n".join(parts)
