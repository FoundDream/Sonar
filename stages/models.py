"""Pipeline 数据模型：各阶段的输入输出。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass
class FieldSpec:
    """描述 finding 中一个字段的 schema。"""
    name: str
    type: str  # "string" | "array"
    description: str
    required: bool = True
    min_length: int = 0  # 仅对 string 生效


@dataclass
class SectionSpec:
    """描述报告中的一个 section。"""
    type: str  # 对应模板文件名，如 "overview", "concepts"
    title: str = ""
    description: str = ""


@dataclass
class FetchResult:
    """Fetch 阶段输出。"""
    url: str
    title: str = ""
    content: str = ""
    author: str = ""
    date: str = ""
    description: str = ""
    word_count: int = 0
    was_truncated: bool = False

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "content": self.content,
            "author": self.author,
            "date": self.date,
            "description": self.description,
            "word_count": self.word_count,
            "was_truncated": self.was_truncated,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FetchResult:
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


@dataclass
class AnalysisResult:
    """Analyze 阶段输出。"""
    url: str
    article_title: str = ""
    article_summary: str = ""
    overview: dict = field(default_factory=dict)
    article_analysis: dict = field(default_factory=dict)
    concepts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "article_title": self.article_title,
            "article_summary": self.article_summary,
            "overview": self.overview,
            "article_analysis": self.article_analysis,
            "concepts": self.concepts,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AnalysisResult:
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


@dataclass
class ResearchPlan:
    """Plan 阶段输出：控制后续研究和报告行为。"""
    preset: str = "beginner"
    goal: str = ""
    finding_schema: list[FieldSpec] = field(default_factory=list)
    sections: list[SectionSpec] = field(default_factory=list)
    researcher_prompt: str = ""
    synthesizer_prompt: str = ""
    classify_tool: dict = field(default_factory=dict)
    selected_concepts: list[str] = field(default_factory=list)
    concept_hints: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "preset": self.preset,
            "goal": self.goal,
            "finding_schema": [
                {"name": f.name, "type": f.type, "description": f.description,
                 "required": f.required, "min_length": f.min_length}
                for f in self.finding_schema
            ],
            "sections": [
                {"type": s.type, "title": s.title, "description": s.description}
                for s in self.sections
            ],
            "researcher_prompt": self.researcher_prompt,
            "synthesizer_prompt": self.synthesizer_prompt,
            "classify_tool": self.classify_tool,
        }
        if self.selected_concepts:
            d["selected_concepts"] = self.selected_concepts
        if self.concept_hints:
            d["concept_hints"] = self.concept_hints
        return d

    @classmethod
    def from_dict(cls, data: dict) -> ResearchPlan:
        plan = cls(
            preset=data.get("preset", "beginner"),
            goal=data.get("goal", ""),
            researcher_prompt=data.get("researcher_prompt", ""),
            synthesizer_prompt=data.get("synthesizer_prompt", ""),
            classify_tool=data.get("classify_tool", {}),
            selected_concepts=data.get("selected_concepts", []),
            concept_hints=data.get("concept_hints", {}),
        )
        plan.finding_schema = [
            FieldSpec(**f) for f in data.get("finding_schema", [])
        ]
        plan.sections = [
            SectionSpec(**s) for s in data.get("sections", [])
        ]
        return plan


@dataclass
class Finding:
    """单个概念的研究结果。"""
    name: str = ""
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.data


@dataclass
class ResearchResult:
    """Research 阶段输出。"""
    url: str
    article_title: str = ""
    article_summary: str = ""
    overview: dict = field(default_factory=dict)
    article_analysis: dict = field(default_factory=dict)
    concepts: list[str] = field(default_factory=list)
    findings: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "article_title": self.article_title,
            "article_summary": self.article_summary,
            "overview": self.overview,
            "article_analysis": self.article_analysis,
            "concepts": self.concepts,
            "findings": self.findings,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ResearchResult:
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


@dataclass
class ReportData:
    """Synthesize 阶段输出，即最终报告数据。"""
    title: str = ""
    source_url: str = ""
    overview: dict = field(default_factory=dict)
    summary: str = ""
    article_analysis: dict = field(default_factory=dict)
    prerequisites: list[dict] = field(default_factory=list)
    concepts: list[dict] = field(default_factory=list)
    learning_path: list[dict] = field(default_factory=list)
    sections: list[dict] = field(default_factory=list)
    quality_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "title": self.title,
            "source_url": self.source_url,
            "overview": self.overview,
            "summary": self.summary,
            "article_analysis": self.article_analysis,
            "prerequisites": self.prerequisites,
            "concepts": self.concepts,
            "learning_path": self.learning_path,
        }
        if self.sections:
            d["sections"] = self.sections
        if self.quality_warnings:
            d["quality_warnings"] = self.quality_warnings
        return d

    @classmethod
    def from_dict(cls, data: dict) -> ReportData:
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


def save_stage_output(data: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[状态] 已保存到 {path}")


def load_stage_output(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
