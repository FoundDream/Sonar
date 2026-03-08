"""DirectoryFetcher — 处理项目目录输入。"""

import os

from fetchers.base import BaseFetcher, FetchError
from models import FetchResult
from tools.extract import smart_truncate

_MAX_README_CHARS = 8000
_README_NAMES = ["README.md", "README", "README.txt", "README.rst", "readme.md"]


class DirectoryFetcher(BaseFetcher):
    def can_handle(self, source: str) -> bool:
        if source.startswith(("http://", "https://")):
            return False
        return os.path.isdir(source)

    def fetch(self, source: str) -> FetchResult:
        abs_path = os.path.abspath(source)
        print(f"\n--- 读取项目目录: {abs_path} ---")
        project_name = os.path.basename(abs_path)

        readme_content = self._find_readme(abs_path)
        tree_summary = self._build_tree(abs_path)

        content = ""
        if readme_content:
            content = smart_truncate(readme_content, _MAX_README_CHARS, preserve_ends=True)
        if tree_summary:
            content = f"{content}\n\n---\n\n## 项目文件结构\n\n```\n{tree_summary}\n```"

        if not content.strip():
            raise FetchError(f"目录 {abs_path} 中未找到可读文档")

        result = FetchResult(
            url=abs_path,
            title=project_name,
            content=content,
            word_count=len(content),
            was_truncated=len(readme_content) > _MAX_README_CHARS if readme_content else False,
            method="directory",
            source_type="directory",
        )
        print(f"[读取] 项目: {project_name} ({len(content)} 字)")
        return result

    @staticmethod
    def _find_readme(abs_path: str) -> str:
        for name in _README_NAMES:
            readme_path = os.path.join(abs_path, name)
            if os.path.isfile(readme_path):
                try:
                    with open(readme_path, encoding="utf-8") as f:
                        print(f"[读取] 找到 {name}")
                        return f.read()
                except Exception:
                    continue

        # Fallback: look for docs
        for doc_name in ["docs/index.md", "doc/README.md", "OVERVIEW.md"]:
            doc_path = os.path.join(abs_path, doc_name)
            if os.path.isfile(doc_path):
                try:
                    with open(doc_path, encoding="utf-8") as f:
                        print(f"[读取] 找到 {doc_name}")
                        return f.read()
                except Exception:
                    continue
        return ""

    @staticmethod
    def _build_tree(path: str, max_depth: int = 3, max_files: int = 100) -> str:
        _skip = {
            ".git", "__pycache__", "node_modules", ".venv", "venv",
            ".tox", ".mypy_cache", ".ruff_cache", ".pytest_cache",
            "dist", "build", ".eggs",
        }
        lines = []
        count = 0

        def _walk(dir_path: str, prefix: str, depth: int):
            nonlocal count
            if depth > max_depth or count > max_files:
                return
            try:
                entries = sorted(os.listdir(dir_path))
            except PermissionError:
                return

            dirs = [
                e for e in entries
                if os.path.isdir(os.path.join(dir_path, e))
                and e not in _skip and not e.startswith(".")
            ]
            files = [
                e for e in entries
                if os.path.isfile(os.path.join(dir_path, e))
                and not e.startswith(".")
            ]
            for f in files:
                if count > max_files:
                    break
                lines.append(f"{prefix}{f}")
                count += 1
            for d in dirs:
                lines.append(f"{prefix}{d}/")
                _walk(os.path.join(dir_path, d), prefix + "  ", depth + 1)

        _walk(path, "", 1)
        return "\n".join(lines)
