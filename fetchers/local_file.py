"""LocalFileFetcher — 处理本地文件（pdf/md/txt/html）。"""

import os

from fetchers.base import BaseFetcher, FetchError
from stages.models import FetchResult
from tools.extract import smart_truncate

_SUPPORTED_EXTENSIONS = {".pdf", ".md", ".txt", ".html", ".htm"}
_MAX_FILE_CHARS = 8000


class LocalFileFetcher(BaseFetcher):
    def can_handle(self, source: str) -> bool:
        if source.startswith(("http://", "https://")):
            return False
        return os.path.isfile(source)

    def fetch(self, source: str) -> FetchResult:
        print(f"\n--- 读取本地文件: {source} ---")
        abs_path = os.path.abspath(source)
        ext = os.path.splitext(abs_path)[1].lower()

        if ext not in _SUPPORTED_EXTENSIONS:
            raise FetchError(
                f"不支持的文件类型: {ext}（支持: {', '.join(sorted(_SUPPORTED_EXTENSIONS))}）"
            )

        if ext == ".pdf":
            return self._read_pdf(abs_path)
        if ext in (".html", ".htm"):
            return self._read_html(abs_path)
        return self._read_text(abs_path)

    def _read_pdf(self, path: str) -> FetchResult:
        try:
            import pymupdf
        except ImportError:
            raise FetchError("pymupdf 未安装。安装: uv add pymupdf") from None

        try:
            doc = pymupdf.open(path)
            title = (doc.metadata.get("title") or "").strip()
            pages = [page.get_text() for page in doc]
            doc.close()
        except Exception as e:
            raise FetchError(f"PDF 解析失败: {e}") from e

        content = "\n".join(pages)
        if not content.strip():
            raise FetchError("PDF 无可提取文本（可能是扫描版）")

        if not title:
            title = os.path.basename(path)

        return self._build_file_result(path, title, content)

    def _read_html(self, path: str) -> FetchResult:
        from tools.extract import extract_content

        try:
            with open(path, encoding="utf-8") as f:
                html = f.read()
        except Exception as e:
            raise FetchError(f"读取文件失败: {e}") from e

        extracted = extract_content(html, f"file://{path}")
        title = extracted.get("title") or os.path.basename(path)
        content = extracted.get("content", "")

        if not content.strip():
            raise FetchError("HTML 文件无可提取正文")

        return self._build_file_result(
            path, title, content,
            author=extracted.get("author", ""),
            date=extracted.get("date", ""),
            description=extracted.get("description", ""),
        )

    def _read_text(self, path: str) -> FetchResult:
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            raise FetchError(f"读取文件失败: {e}") from e

        if not content.strip():
            raise FetchError("文件内容为空")

        title = os.path.basename(path)
        return self._build_file_result(path, title, content)

    @staticmethod
    def _build_file_result(
        path: str, title: str, content: str,
        author: str = "", date: str = "", description: str = "",
    ) -> FetchResult:
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
