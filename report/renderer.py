"""HTML 报告渲染器：支持 section-based 模板和旧格式兼容。"""

import os
import re

from jinja2 import Environment, FileSystemLoader


def _slugify(text: str) -> str:
    """把概念名转成 URL 安全的 HTML ID（保留中文和字母数字）。"""
    text = re.sub(r'\s+', '-', text.strip())
    text = re.sub(r'[（）()\[\]{}「」【】<>""''\"\'&@#$%^*+=|\\/?!:;！？，。；：]', '', text)
    text = re.sub(r'-+', '-', text)
    return text.strip('-')


# Paper 1 sections (overview + analysis + navigation)
_PAPER1_TYPES = {"overview", "summary", "analysis", "toc", "learning_path"}
# Paper 2 sections (content)
_PAPER2_TYPES = {"prerequisites", "concepts", "paper_list"}


def _split_sections(sections: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split sections into paper1 (overview etc) and paper2 (content)."""
    paper1 = [s for s in sections if s.get("type") in _PAPER1_TYPES]
    paper2 = [s for s in sections if s.get("type") in _PAPER2_TYPES]
    return paper1, paper2


def _convert_legacy_to_sections(data: dict) -> list[dict]:
    """Convert legacy report data (no sections key) to section list."""
    sections = []

    if data.get("overview"):
        sections.append({"type": "overview"})

    sections.append({"type": "summary"})

    if data.get("article_analysis"):
        sections.append({"type": "analysis"})

    if data.get("prerequisites") or data.get("concepts"):
        sections.append({"type": "toc"})

    if data.get("learning_path"):
        sections.append({"type": "learning_path"})

    if data.get("prerequisites"):
        sections.append({"type": "prerequisites"})

    if data.get("concepts"):
        sections.append({"type": "concepts"})

    return sections


def render_report(data: dict, output_path: str = "output/report.html") -> str:
    """把结构化报告数据渲染成 HTML 文件。"""
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    env = Environment(loader=FileSystemLoader(template_dir))
    env.filters["slugify"] = _slugify

    template = env.get_template("base.html")

    # Ensure sections exist (legacy compat)
    sections = data.get("sections") or _convert_legacy_to_sections(data)
    paper1_sections, paper2_sections = _split_sections(sections)

    render_ctx = dict(data)
    render_ctx["_paper1_sections"] = paper1_sections
    render_ctx["_paper2_sections"] = paper2_sections
    render_ctx["_has_prerequisites"] = bool(data.get("prerequisites"))

    html = template.render(**render_ctx)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path
