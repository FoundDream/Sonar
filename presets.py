"""预设配置：beginner / research 模式。"""

from agent.prompts import (
    CLASSIFY_TOOL,
    RESEARCH_RESEARCHER_PROMPT,
    RESEARCHER_PROMPT,
    SYNTHESIZER_PROMPT,
)
from stages.models import FieldSpec, ResearchPlan, SectionSpec


def _beginner_finding_schema() -> list[FieldSpec]:
    return [
        FieldSpec("name", "string", "概念名称", required=True),
        FieldSpec("explanation", "string", "概念的通俗解释，不限字数，写清楚为止", required=True, min_length=50),
        FieldSpec("why_important", "string", "为什么理解这个概念对读懂文章很重要", required=True),
        FieldSpec("article_role", "string", "这个概念在本文中具体扮演什么角色"),
        FieldSpec("example", "string", "用一个简短例子帮助读者理解这个概念"),
        FieldSpec("analogy", "string", "可选：用一个类比帮助建立直觉；如果不需要可留空", required=False),
        FieldSpec("resources", "array", "精选 1-2 条最好的学习资料", required=True),
    ]


def _beginner_sections() -> list[SectionSpec]:
    return [
        SectionSpec("overview", "速览"),
        SectionSpec("summary", "摘要"),
        SectionSpec("analysis", "文章分析"),
        SectionSpec("toc", "目录"),
        SectionSpec("learning_path", "学习路径"),
        SectionSpec("prerequisites", "前置知识"),
        SectionSpec("concepts", "核心概念"),
    ]


BEGINNER_PRESET = ResearchPlan(
    preset="beginner",
    finding_schema=_beginner_finding_schema(),
    sections=_beginner_sections(),
    researcher_prompt=RESEARCHER_PROMPT,
    synthesizer_prompt=SYNTHESIZER_PROMPT,
    classify_tool=CLASSIFY_TOOL,
)


def _research_finding_schema() -> list[FieldSpec]:
    return [
        FieldSpec("name", "string", "概念/论文名称", required=True),
        FieldSpec("summary", "string", "核心内容概述", required=True, min_length=80),
        FieldSpec("methodology", "string", "研究方法"),
        FieldSpec("key_findings", "string", "关键发现/结论", required=True, min_length=50),
        FieldSpec("relevance", "string", "与原文的关联"),
        FieldSpec("resources", "array", "相关论文和资料链接", required=True),
    ]


def _research_sections() -> list[SectionSpec]:
    return [
        SectionSpec("overview", "速览"),
        SectionSpec("summary", "摘要"),
        SectionSpec("analysis", "文章分析"),
        SectionSpec("toc", "目录"),
        SectionSpec("learning_path", "探索路径"),
        SectionSpec("prerequisites", "背景知识"),
        SectionSpec("concepts", "核心概念"),
        SectionSpec("paper_list", "相关论文"),
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


RESEARCH_PRESET = ResearchPlan(
    preset="research",
    finding_schema=_research_finding_schema(),
    sections=_research_sections(),
    researcher_prompt=RESEARCH_RESEARCHER_PROMPT,
    synthesizer_prompt=RESEARCH_SYNTHESIZER_PROMPT,
    classify_tool=CLASSIFY_TOOL,
)

_PRESETS = {
    "beginner": BEGINNER_PRESET,
    "research": RESEARCH_PRESET,
}


def get_preset(name: str) -> ResearchPlan:
    """Return a copy of the named preset."""
    preset = _PRESETS.get(name)
    if preset is None:
        raise ValueError(f"Unknown preset: {name}. Available: {list(_PRESETS.keys())}")
    # Return a shallow copy so mutations don't affect the global
    import copy
    return copy.deepcopy(preset)
