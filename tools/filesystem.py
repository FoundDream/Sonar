"""文件系统工具：让 Agent 能探索项目结构、读取文件、搜索内容。"""

import os
import subprocess

_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".tox", ".mypy_cache", ".ruff_cache", ".pytest_cache",
    "dist", "build", ".eggs",
}

_BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".bz2",
    ".pyc", ".pyo", ".so", ".dll", ".dylib",
    ".exe", ".bin",
}

_MAX_FILE_CHARS = 6000
_MAX_TREE_DEPTH = 4
_MAX_TREE_FILES = 200


# ── Functions ────────────────────────────────────────────────────

def get_tree(path: str, max_depth: int = _MAX_TREE_DEPTH) -> dict:
    """Get project structure as a tree."""
    abs_path = os.path.abspath(path)
    if not os.path.isdir(abs_path):
        return {"error": f"不是目录: {path}"}

    lines = []
    file_count = 0

    def _walk(dir_path: str, prefix: str, depth: int):
        nonlocal file_count
        if depth > max_depth or file_count > _MAX_TREE_FILES:
            return

        try:
            entries = sorted(os.listdir(dir_path))
        except PermissionError:
            return

        dirs = [e for e in entries
                if os.path.isdir(os.path.join(dir_path, e))
                and e not in _SKIP_DIRS and not e.startswith(".")]
        files = [e for e in entries
                 if os.path.isfile(os.path.join(dir_path, e))
                 and not e.startswith(".")]

        all_items = [(f, False) for f in files] + [(d, True) for d in dirs]
        for i, (name, is_dir) in enumerate(all_items):
            if file_count > _MAX_TREE_FILES:
                lines.append(f"{prefix}... (truncated)")
                break
            is_last = i == len(all_items) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{name}{'/' if is_dir else ''}")
            if is_dir:
                extension = "    " if is_last else "│   "
                _walk(os.path.join(dir_path, name), prefix + extension, depth + 1)
            else:
                file_count += 1

    project_name = os.path.basename(abs_path)
    lines.append(f"{project_name}/")
    _walk(abs_path, "", 1)

    return {"tree": "\n".join(lines), "total_files": file_count}


def list_directory(path: str) -> dict:
    """List files in a directory with types and sizes."""
    abs_path = os.path.abspath(path)
    if not os.path.isdir(abs_path):
        return {"error": f"不是目录: {path}"}

    try:
        entries = sorted(os.listdir(abs_path))
    except PermissionError:
        return {"error": f"权限不足: {path}"}

    items = []
    for name in entries:
        if name in _SKIP_DIRS or name.startswith("."):
            continue
        full = os.path.join(abs_path, name)
        entry = {"name": name}

        if os.path.isdir(full):
            entry["type"] = "directory"
            try:
                entry["items"] = len([
                    e for e in os.listdir(full)
                    if e not in _SKIP_DIRS and not e.startswith(".")
                ])
            except PermissionError:
                entry["items"] = -1
        else:
            entry["type"] = "file"
            entry["extension"] = os.path.splitext(name)[1].lower()
            try:
                entry["size"] = os.path.getsize(full)
            except OSError:
                entry["size"] = -1
        items.append(entry)

    return {"path": abs_path, "items": items, "count": len(items)}


def read_file(path: str, max_chars: int = _MAX_FILE_CHARS) -> dict:
    """Read a file's contents with smart truncation."""
    abs_path = os.path.abspath(path)
    if not os.path.isfile(abs_path):
        return {"error": f"文件不存在: {path}"}

    ext = os.path.splitext(abs_path)[1].lower()
    if ext in _BINARY_EXTENSIONS:
        return {"error": f"二进制文件，无法读取: {path}"}

    try:
        size = os.path.getsize(abs_path)
    except OSError:
        size = 0

    try:
        with open(abs_path, encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars + 100)
    except Exception as e:
        return {"error": f"读取失败: {e}"}

    was_truncated = len(content) > max_chars
    if was_truncated:
        content = content[:max_chars]

    return {
        "path": abs_path,
        "content": content,
        "size": size,
        "was_truncated": was_truncated,
    }


def search_in_files(query: str, path: str) -> dict:
    """Search for a pattern in files under a directory."""
    abs_path = os.path.abspath(path)
    if not os.path.isdir(abs_path):
        return {"error": f"不是目录: {path}"}

    matches = []
    try:
        cmd = ["grep", "-r", "-n", "-l", "--max-count=3"]
        for skip in _SKIP_DIRS:
            cmd.extend(["--exclude-dir", skip])
        cmd.extend([query, abs_path])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        if result.returncode == 0:
            file_paths = [p for p in result.stdout.strip().split("\n") if p][:20]
            for file_path in file_paths:
                rel = os.path.relpath(file_path, abs_path)
                line_cmd = ["grep", "-n", "--max-count=3", query, file_path]
                line_result = subprocess.run(
                    line_cmd, capture_output=True, text=True, timeout=5,
                )
                match_lines = []
                if line_result.returncode == 0:
                    match_lines = [
                        ln[:200] for ln in line_result.stdout.strip().split("\n")[:3]
                    ]
                matches.append({"file": rel, "lines": match_lines})
    except subprocess.TimeoutExpired:
        return {"error": "搜索超时"}
    except Exception as e:
        return {"error": f"搜索失败: {e}"}

    return {
        "query": query,
        "path": abs_path,
        "matches": matches,
        "match_count": len(matches),
    }


# ── Tool Schemas ─────────────────────────────────────────────────

GET_TREE_TOOL = {
    "type": "function",
    "function": {
        "name": "get_tree",
        "description": "获取项目目录结构树。用于快速了解项目的文件组织方式。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "项目根目录路径"},
                "max_depth": {
                    "type": "integer",
                    "description": "最大深度（默认 4）",
                },
            },
            "required": ["path"],
        },
    },
}

LIST_DIRECTORY_TOOL = {
    "type": "function",
    "function": {
        "name": "list_directory",
        "description": "列出目录内容，包含文件类型和大小。用于探索特定目录。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目录路径"},
            },
            "required": ["path"],
        },
    },
}

READ_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "读取文件内容（自动截断到 6000 字符）。用于查看关键文件。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "max_chars": {
                    "type": "integer",
                    "description": "最大字符数（默认 6000）",
                },
            },
            "required": ["path"],
        },
    },
}

SEARCH_IN_FILES_TOOL = {
    "type": "function",
    "function": {
        "name": "search_in_files",
        "description": "在目录内搜索包含指定文本的文件。返回匹配的文件和行。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "path": {"type": "string", "description": "搜索目录"},
            },
            "required": ["query", "path"],
        },
    },
}
