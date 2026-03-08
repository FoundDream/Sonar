"""模式配置：统一的 explain preset（schema、sections 和 prompt）。"""

from stages.models import FieldSpec, ResearchPlan, SectionSpec
from stages.prompts.research import RESEARCHER_PROMPT
from stages.prompts.synthesize import CLASSIFY_TOOL, SYNTHESIZER_PROMPT


def _finding_schema() -> list[FieldSpec]:
    return [
        FieldSpec("name", "string", "概念名称", required=True),
        FieldSpec("explanation", "string", "概念的通俗解释，不限字数，写清楚为止", required=True, min_length=50),
        FieldSpec("why_important", "string", "为什么理解这个概念对读懂文章很重要", required=True),
        FieldSpec("article_role", "string", "这个概念在本文中具体扮演什么角色"),
        FieldSpec("methodology", "string", "相关的研究方法（如适用）", required=False),
        FieldSpec("key_findings", "string", "关键发现/结论（如适用）", required=False),
        FieldSpec("example", "string", "用一个简短例子帮助读者理解这个概念"),
        FieldSpec("analogy", "string", "可选：用一个类比帮助建立直觉；如果不需要可留空", required=False),
        FieldSpec("resources", "array", "精选 1-2 条最好的学习资料", required=True),
    ]


def _sections() -> list[SectionSpec]:
    return [
        SectionSpec("overview", "速览"),
        SectionSpec("summary", "摘要"),
        SectionSpec("analysis", "文章分析"),
        SectionSpec("toc", "目录"),
        SectionSpec("learning_path", "学习路径"),
        SectionSpec("prerequisites", "前置知识"),
        SectionSpec("concepts", "核心概念"),
        SectionSpec("paper_list", "延伸阅读"),
    ]


EXPLAIN_PRESET = ResearchPlan(
    preset="explain",
    finding_schema=_finding_schema(),
    sections=_sections(),
    researcher_prompt=RESEARCHER_PROMPT,
    synthesizer_prompt=SYNTHESIZER_PROMPT,
    classify_tool=CLASSIFY_TOOL,
)

_PRESETS = {
    "explain": EXPLAIN_PRESET,
}


def get_preset(name: str) -> ResearchPlan:
    """Return a copy of the named preset."""
    preset = _PRESETS.get(name)
    if preset is None:
        raise ValueError(f"Unknown preset: {name}. Available: {list(_PRESETS.keys())}")
    import copy
    return copy.deepcopy(preset)
