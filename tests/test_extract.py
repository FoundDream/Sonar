"""extract.py 单元测试：智能截断、HTML 提取。"""

from tools.extract import extract_content, smart_truncate


# ── smart_truncate ──


class TestSmartTruncate:
    def test_short_text_unchanged(self):
        text = "短文本不截断"
        assert smart_truncate(text, 100) == text

    def test_exact_limit_unchanged(self):
        text = "a" * 100
        assert smart_truncate(text, 100) == text

    def test_truncate_no_preserve_ends(self):
        """preserve_ends=False 时从头截取。"""
        text = "段落一\n\n段落二\n\n段落三很长" + "x" * 200
        result = smart_truncate(text, 20, preserve_ends=False)
        assert len(result) <= 20
        assert "段落一" in result

    def test_truncate_at_paragraph_boundary(self):
        """在段落边界（\\n\\n）切割，而非硬切。"""
        text = "A" * 10 + "\n\n" + "B" * 50
        result = smart_truncate(text, 15, preserve_ends=False)
        # 应该在 \n\n 处切割，得到前 10 个 A
        assert result == "A" * 10

    def test_hard_cut_when_no_paragraph_boundary(self):
        """没有段落边界时硬切。"""
        text = "A" * 200
        result = smart_truncate(text, 50, preserve_ends=False)
        assert len(result) == 50

    def test_preserve_ends_keeps_head_and_tail(self):
        """preserve_ends=True 保留首尾，中间省略。"""
        text = "HEAD" + "\n\n" + "M" * 500 + "\n\n" + "TAIL"
        result = smart_truncate(text, 50, preserve_ends=True)
        assert "HEAD" in result
        assert "TAIL" in result
        assert "[...省略...]" in result

    def test_preserve_ends_omission_marker(self):
        """省略标记存在于结果中。"""
        text = "A" * 200
        result = smart_truncate(text, 50, preserve_ends=True)
        assert "[...省略...]" in result


# ── extract_content ──


class TestExtractContent:
    def test_simple_html(self):
        html = "<html><head><title>标题</title></head><body><p>正文内容</p></body></html>"
        result = extract_content(html, "https://example.com")
        assert result["title"] == "标题"
        assert "正文" in result["content"]

    def test_returns_all_keys(self):
        html = "<html><body><p>text</p></body></html>"
        result = extract_content(html, "https://example.com")
        for key in ("title", "content", "author", "date", "description"):
            assert key in result

    def test_strips_script_and_style(self):
        html = (
            "<html><body>"
            "<script>alert('xss')</script>"
            "<style>.x{color:red}</style>"
            "<p>真正的内容</p>"
            "</body></html>"
        )
        result = extract_content(html, "https://example.com")
        assert "alert" not in result["content"]
        assert "color:red" not in result["content"]

    def test_empty_html_returns_empty_content(self):
        result = extract_content("", "https://example.com")
        assert result["content"] == ""

    def test_article_tag_extracted(self):
        """<article> 标签的正文能被提取。"""
        html = (
            "<html><body>"
            "<nav>导航链接</nav>"
            "<article><p>正文在这里</p></article>"
            "<footer>页脚信息</footer>"
            "</body></html>"
        )
        result = extract_content(html, "https://example.com")
        assert "正文在这里" in result["content"]
