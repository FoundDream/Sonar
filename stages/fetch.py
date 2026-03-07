"""Fetch 阶段：抓取文章内容 + LLM 内容质量验证。

支持两类输入：
  - URL (http/https) → Jina / httpx / playwright 降级链
  - 本地文件 (.pdf / .md / .txt / .html) → 直接读取
"""

import json
import os

from llm.client import LLMClient
from stages.models import FetchResult
from tools.extract import smart_truncate
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

_SUPPORTED_EXTENSIONS = {".pdf", ".md", ".txt", ".html", ".htm"}
_MAX_FILE_CHARS = 8000


def is_local_file(source: str) -> bool:
    """判断输入是本地文件还是 URL。"""
    if source.startswith(("http://", "https://")):
        return False
    return os.path.isfile(source)


class FetchStage:
    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm

    def run(self, source: str) -> FetchResult | dict:
        """抓取内容。source 可以是 URL 或本地文件路径。"""
        if is_local_file(source):
            return self._fetch_local(source)
        return self._fetch_url(source)

    def _fetch_url(self, url: str) -> FetchResult | dict:
        """从 URL 抓取文章。"""
        print("\n--- 抓取文章 ---")
        result = fetch_article(url)
        if "error" in result:
            return {"error": f"抓取失败: {result['error']}"}

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
            source_type="url",
        )
        print(f"[抓取] 标题: {fetch_result.title}")
        return fetch_result

    def _fetch_local(self, path: str) -> FetchResult | dict:
        """从本地文件读取内容。"""
        print(f"\n--- 读取本地文件: {path} ---")
        abs_path = os.path.abspath(path)
        ext = os.path.splitext(abs_path)[1].lower()

        if ext not in _SUPPORTED_EXTENSIONS:
            return {"error": f"不支持的文件类型: {ext}（支持: {', '.join(sorted(_SUPPORTED_EXTENSIONS))}）"}

        if ext == ".pdf":
            return self._read_pdf(abs_path)
        if ext in (".html", ".htm"):
            return self._read_html(abs_path)
        return self._read_text(abs_path)

    def _read_pdf(self, path: str) -> FetchResult | dict:
        """读取本地 PDF 文件。"""
        try:
            import pymupdf
        except ImportError:
            return {"error": "pymupdf 未安装。安装: uv add pymupdf"}

        try:
            doc = pymupdf.open(path)
            title = (doc.metadata.get("title") or "").strip()
            pages = [page.get_text() for page in doc]
            doc.close()
        except Exception as e:
            return {"error": f"PDF 解析失败: {e}"}

        content = "\n".join(pages)
        if not content.strip():
            return {"error": "PDF 无可提取文本（可能是扫描版）"}

        if not title:
            title = os.path.basename(path)

        return self._build_file_result(path, title, content)

    def _read_html(self, path: str) -> FetchResult | dict:
        """读取本地 HTML 文件。"""
        from tools.extract import extract_content

        try:
            with open(path, encoding="utf-8") as f:
                html = f.read()
        except Exception as e:
            return {"error": f"读取文件失败: {e}"}

        extracted = extract_content(html, f"file://{path}")
        title = extracted.get("title") or os.path.basename(path)
        content = extracted.get("content", "")

        if not content.strip():
            return {"error": "HTML 文件无可提取正文"}

        return self._build_file_result(
            path, title, content,
            author=extracted.get("author", ""),
            date=extracted.get("date", ""),
            description=extracted.get("description", ""),
        )

    def _read_text(self, path: str) -> FetchResult | dict:
        """读取本地文本文件（.md / .txt）。"""
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            return {"error": f"读取文件失败: {e}"}

        if not content.strip():
            return {"error": "文件内容为空"}

        title = os.path.basename(path)
        return self._build_file_result(path, title, content)

    @staticmethod
    def _build_file_result(
        path: str, title: str, content: str,
        author: str = "", date: str = "", description: str = "",
    ) -> FetchResult:
        """构建本地文件的 FetchResult。"""
        raw_len = len(content)
        truncated = smart_truncate(content, _MAX_FILE_CHARS, preserve_ends=True)

        result = FetchResult(
            url=path,
            title=title,
            content=truncated,
            author=author,
            date=date,
            description=description,
            word_count=raw_len,
            was_truncated=len(truncated) < raw_len,
            source_type="file",
        )
        print(f"[读取] 标题: {result.title} ({raw_len} 字)")
        return result

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
