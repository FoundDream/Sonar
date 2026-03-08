"""模式配置：explain / academic 的 schema、sections 和 prompt。"""

from stages.models import FieldSpec, ResearchPlan, SectionSpec
from stages.prompts.research import RESEARCH_RESEARCHER_PROMPT, RESEARCHER_PROMPT
from stages.prompts.synthesize import CLASSIFY_TOOL, SYNTHESIZER_PROMPT


def _explain_finding_schema() -> list[FieldSpec]:
    return [
        FieldSpec("name", "string", "概念名称", required=True),
        FieldSpec("explanation", "string", "概念的通俗解释，不限字数，写清楚为止", required=True, min_length=50),
        FieldSpec("why_important", "string", "为什么理解这个概念对读懂文章很重要", required=True),
        FieldSpec("article_role", "string", "这个概念在本文中具体扮演什么角色"),
        FieldSpec("example", "string", "用一个简短例子帮助读者理解这个概念"),
        FieldSpec("analogy", "string", "可选：用一个类比帮助建立直觉；如果不需要可留空", required=False),
        FieldSpec("resources", "array", "精选 1-2 条最好的学习资料", required=True),
    ]


def _explain_sections() -> list[SectionSpec]:
    return [
        SectionSpec("overview", "速览"),
        SectionSpec("summary", "摘要"),
        SectionSpec("analysis", "文章分析"),
        SectionSpec("toc", "目录"),
        SectionSpec("learning_path", "学习路径"),
        SectionSpec("prerequisites", "前置知识"),
        SectionSpec("concepts", "核心概念"),
    ]


EXPLAIN_PRESET = ResearchPlan(
    preset="explain",
    finding_schema=_explain_finding_schema(),
    sections=_explain_sections(),
    researcher_prompt=RESEARCHER_PROMPT,
    synthesizer_prompt=SYNTHESIZER_PROMPT,
    classify_tool=CLASSIFY_TOOL,
)


def _academic_finding_schema() -> list[FieldSpec]:
    return [
        FieldSpec("name", "string", "概念/论文名称", required=True),
        FieldSpec("explanation", "string", "概念的通俗解释，让非专业读者也能理解", required=True, min_length=50),
        FieldSpec("why_important", "string", "为什么理解这个概念对读懂论文很重要", required=True),
        FieldSpec("article_role", "string", "这个概念在本论文中具体扮演什么角色"),
        FieldSpec("methodology", "string", "相关的研究方法（如适用）", required=False),
        FieldSpec("key_findings", "string", "关键发现/结论（如适用）", required=False),
        FieldSpec("example", "string", "用一个简短例子帮助读者建立直觉", required=True),
        FieldSpec("analogy", "string", "可选：用一个类比帮助理解；如果不需要可留空", required=False),
        FieldSpec("resources", "array", "精选 1-2 条最好的学习资料", required=True),
    ]


def _academic_sections() -> list[SectionSpec]:
    return [
        SectionSpec("overview", "速览"),
        SectionSpec("summary", "摘要"),
        SectionSpec("analysis", "文章分析"),
        SectionSpec("toc", "目录"),
        SectionSpec("learning_path", "探索路径"),
        SectionSpec("prerequisites", "背景知识"),
        SectionSpec("concepts", "核心概念"),
        SectionSpec("paper_list", "延伸阅读"),
    ]


RESEARCH_SYNTHESIZER_PROMPT = """\
你是 Sonar 的报告编辑（论文探索模式）。

研究员已经为每个概念/论文收集了详细的分析和相关资料。

你需要做三件事：

1. 把概念分类为"背景知识"或"核心概念"
   - 背景知识：理解论文所需的前置知识（2-4 个）
   - 核心概念：论文直接相关的重要概念和方法（3-5 个）

2. 为背景知识标注优先级
   - must: 不了解就无法理解论文
   - should: 了解了会更好

3. 编排探索路径
   - 按从基础到前沿的顺序
   - 每步关联具体概念名

调用 classify_concepts 提交分类结果。
"""


ACADEMIC_PRESET = ResearchPlan(
    preset="academic",
    finding_schema=_academic_finding_schema(),
    sections=_academic_sections(),
    researcher_prompt=RESEARCH_RESEARCHER_PROMPT,
    synthesizer_prompt=RESEARCH_SYNTHESIZER_PROMPT,
    classify_tool=CLASSIFY_TOOL,
)

_PRESETS = {
    "explain": EXPLAIN_PRESET,
    "academic": ACADEMIC_PRESET,
}


def get_preset(name: str) -> ResearchPlan:
    """Return a copy of the named preset."""
    preset = _PRESETS.get(name)
    if preset is None:
        raise ValueError(f"Unknown preset: {name}. Available: {list(_PRESETS.keys())}")
    # Return a shallow copy so mutations don't affect the global
    import copy
    return copy.deepcopy(preset)
