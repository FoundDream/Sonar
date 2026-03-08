"""本地文件抓取测试：验证各种本地文件格式的读取能力。

不需要网络，直接运行：uv run python -m pytest tests/test_fetch_file.py -v
"""

from pathlib import Path

import pytest

from fetchers import fetch_source, is_local_file
from models import FetchResult


class TestIsLocalFile:
    def test_http_url_is_not_local(self):
        assert is_local_file("https://example.com/article") is False
        assert is_local_file("http://example.com/article") is False

    def test_nonexistent_path_is_not_local(self):
        assert is_local_file("/nonexistent/file.md") is False

    def test_existing_file_is_local(self, tmp_path: Path):
        f = tmp_path / "test.md"
        f.write_text("hello", encoding="utf-8")
        assert is_local_file(str(f)) is True


class TestLocalFiles:
    def test_markdown_file(self, tmp_path: Path) -> None:
        f = tmp_path / "article.md"
        f.write_text(
            "# 深度学习入门\n\n本文介绍深度学习的基本概念。\n\n"
            "## 神经网络\n\n神经网络是深度学习的基础架构。\n\n"
            "## 反向传播\n\n反向传播算法用于训练神经网络。",
            encoding="utf-8",
        )
        result = fetch_source(str(f))

        assert isinstance(result, FetchResult)
        assert result.source_type == "file"
        assert result.title == "article.md"
        assert "深度学习" in result.content
        assert result.word_count > 0

    def test_txt_file(self, tmp_path: Path) -> None:
        f = tmp_path / "notes.txt"
        f.write_text("这是一份纯文本笔记。\n包含多行内容。\n用于验证功能。", encoding="utf-8")
        result = fetch_source(str(f))

        assert isinstance(result, FetchResult)
        assert result.source_type == "file"
        assert "纯文本笔记" in result.content

    def test_html_file(self, tmp_path: Path) -> None:
        f = tmp_path / "page.html"
        f.write_text(
            '<!DOCTYPE html><html><head><title>测试页面</title></head>'
            "<body><article><h1>HTML 文章</h1>"
            "<p>这是正文内容，用于验证 HTML 解析。</p>"
            "</article></body></html>",
            encoding="utf-8",
        )
        result = fetch_source(str(f))

        assert isinstance(result, FetchResult)
        assert result.source_type == "file"
        assert "正文内容" in result.content

    def test_pdf_file(self, tmp_path: Path) -> None:
        pymupdf = pytest.importorskip("pymupdf")
        pdf_path = tmp_path / "doc.pdf"

        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Deep Learning Introduction\n\nNeural networks are fundamental.", fontsize=12)
        doc.save(str(pdf_path))
        doc.close()

        result = fetch_source(str(pdf_path))

        assert isinstance(result, FetchResult)
        assert result.source_type == "file"
        assert "Deep Learning" in result.content or "Neural" in result.content

    def test_empty_file_returns_error(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.md"
        f.write_text("", encoding="utf-8")
        result = fetch_source(str(f))

        assert isinstance(result, dict)
        assert "error" in result

    def test_unsupported_extension_returns_error(self, tmp_path: Path) -> None:
        f = tmp_path / "data.csv"
        f.write_text("a,b,c\n1,2,3", encoding="utf-8")
        result = fetch_source(str(f))

        assert isinstance(result, dict)
        assert "error" in result
        assert ".csv" in result["error"]

    def test_large_file_gets_truncated(self, tmp_path: Path) -> None:
        f = tmp_path / "large.md"
        content = "# 大文件测试\n\n" + ("这是重复内容用于测试截断功能。" * 1000)
        f.write_text(content, encoding="utf-8")
        result = fetch_source(str(f))

        assert isinstance(result, FetchResult)
        assert result.was_truncated is True
        assert len(result.content) <= 8500
