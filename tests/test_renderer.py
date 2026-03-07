from pathlib import Path

from report.renderer import _convert_legacy_to_sections, _slugify, render_report


def test_slugify_keeps_cjk_and_removes_symbols() -> None:
    assert _slugify(" 概念 A/B: 入门？ ") == "概念-AB-入门"


def test_convert_legacy_to_sections() -> None:
    sections = _convert_legacy_to_sections(
        {
            "overview": {"theme": "x"},
            "summary": "s",
            "article_analysis": {"thesis": "t"},
            "prerequisites": [{"name": "python"}],
            "concepts": [{"name": "agent"}],
            "learning_path": [{"step": "read"}],
        }
    )

    section_types = [s["type"] for s in sections]
    assert section_types == [
        "overview",
        "summary",
        "analysis",
        "toc",
        "learning_path",
        "prerequisites",
        "concepts",
    ]


def test_render_report_creates_html(tmp_path: Path) -> None:
    output = tmp_path / "report.html"
    render_report(
        {
            "title": "Test Report",
            "source_url": "https://example.com",
            "summary": "hello",
            "overview": {},
            "article_analysis": {},
            "prerequisites": [],
            "concepts": [],
            "learning_path": [],
        },
        str(output),
    )

    html = output.read_text(encoding="utf-8")
    assert "Test Report" in html
    assert "Sonar 学习报告" in html
