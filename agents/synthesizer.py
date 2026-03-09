"""合成器 Agent：分类概念、组装报告数据。"""

import json
from urllib.parse import urlparse

from agents.base import Agent
from models import ReportData, ResearchPlan, ResearchResult
from report.schema import format_issues, has_errors, validate_report
from tools.llm import LLMClient
from tools.search import BLOCKED_DOMAINS

# ── Prompt ────────────────────────────────────────────────────────

SYNTHESIZER_PROMPT = """\
你是 Sonar 的报告编辑。

研究员已经为每个概念收集了详细的解释和学习资料。你不需要重复这些内容。

你需要做三件事：

1. 把概念分类为"前置知识"或"核心概念"
   - 前置知识：读者需要先了解的背景知识（2-4 个）
   - 核心概念：文章直接讨论的重要概念（3-5 个）

2. 为前置知识标注优先级
   - must: 不了解就无法理解文章
   - should: 了解了会更好，但不是必须

3. 编排学习路径
   - 每一步是一个可执行的学习动作，如"先理解 Transformer 的自注意力机制"
   - 每一步补充这一阶段的学习目标，以及为什么这一步排在这里
   - 每一步关联到具体的概念名称（可以关联多个）
   - 顺序必须合理：先前置，再核心，由浅入深
   - 不允许只是把概念名平铺成列表

调用 classify_concepts 提交分类结果。
"""

# ── Tool ──────────────────────────────────────────────────────────

CLASSIFY_TOOL = {
    "type": "function",
    "function": {
        "name": "classify_concepts",
        "description": "对已研究的概念进行分类、标注优先级、编排学习路径。",
        "parameters": {
            "type": "object",
            "properties": {
                "prerequisites": {
                    "type": "array",
                    "description": "前置知识列表（2-4 个，按学习顺序排列）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "概念名称（必须与已研究的概念名一致）"},
                            "priority": {
                                "type": "string",
                                "enum": ["must", "should"],
                                "description": "must=不了解就无法理解文章, should=了解了会更好",
                            },
                            "why_learn_first": {
                                "type": "string",
                                "description": "为什么要先学这个概念（一句话）",
                            },
                        },
                        "required": ["name", "priority", "why_learn_first"],
                    },
                },
                "concepts": {
                    "type": "array",
                    "description": "核心概念名称列表（3-5 个，按学习顺序排列）",
                    "items": {"type": "string"},
                },
                "learning_path": {
                    "type": "array",
                    "description": "学习路径，每步是可执行动作 + 关联概念",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step": {"type": "string", "description": "学习动作描述，如'先理解自注意力机制的工作原理'"},
                            "goal": {"type": "string", "description": "这一阶段想建立什么理解"},
                            "reason": {"type": "string", "description": "为什么这一步应该排在这里"},
                            "concepts": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "这一步关联的概念名称列表",
                            },
                        },
                        "required": ["step", "goal", "reason", "concepts"],
                    },
                },
            },
            "required": ["prerequisites", "concepts", "learning_path"],
        },
    },
}

_SKIP_FIELDS = {"name", "resources"}


# ── Agent ─────────────────────────────────────────────────────────

class Synthesizer(Agent):
    def __init__(self, llm: LLMClient, plan: ResearchPlan | None = None):
        synthesizer_prompt = (plan.synthesizer_prompt if plan else None) or SYNTHESIZER_PROMPT
        classify_tool = (plan.classify_tool if plan else None) or CLASSIFY_TOOL
        super().__init__(llm, name="合成员", system_prompt=synthesizer_prompt, max_iterations=3)
        self.plan = plan
        self.add_terminal_tool(classify_tool)

    def synthesize(self, research: ResearchResult) -> ReportData:
        concept_names = list(research.findings.keys())
        print(f"[Synthesizer] 对 {len(concept_names)} 个概念进行分类...")
        task = f"""文章标题: {research.article_title}
文章摘要: {research.article_summary}

已研究的概念列表:
{json.dumps(concept_names, ensure_ascii=False)}

请调用 classify_concepts 对这些概念进行分类、标注优先级、编排学习路径。"""
        classification = self.run(task)
        report_dict = self._assemble(research, classification)
        return ReportData.from_dict(report_dict)

    def _extract_finding_fields(self, finding: dict) -> dict:
        if self.plan and self.plan.finding_schema:
            return {
                field.name: finding.get(field.name, "")
                for field in self.plan.finding_schema
                if field.name not in _SKIP_FIELDS
            }

        return {
            "explanation": finding.get("explanation", ""),
            "why_important": finding.get("why_important", ""),
            "article_role": finding.get("article_role", ""),
            "example": finding.get("example", ""),
            "analogy": finding.get("analogy", ""),
        }

    def _assemble(self, research: ResearchResult, classification: dict | None) -> dict:
        if classification:
            prereq_items = classification.get("prerequisites", [])
            concept_names = classification.get("concepts", [])
            learning_path = classification.get("learning_path", [])
        else:
            print("[Synthesizer] 分类失败，使用 fallback")
            prereq_items = []
            concept_names = list(research.findings.keys())
            learning_path = [
                {
                    "step": f"学习 {c}",
                    "goal": "建立对该概念的基本理解",
                    "reason": "这是理解原文所需的关键节点。",
                    "concepts": [c],
                }
                for c in concept_names
            ]

        all_finding_names = set(research.findings.keys())
        self._normalize_concept_names(learning_path, all_finding_names)

        source_normalized = self._normalize_url(research.url)

        def _filter_resources(resources: list[dict]) -> list[dict]:
            seen: set[str] = set()
            filtered = []
            for r in resources:
                url = r.get("url", "")
                if not url or url in seen:
                    continue
                seen.add(url)
                if self._normalize_url(url) == source_normalized:
                    print(f"  [过滤] 移除原文循环引用: {url[:60]}")
                    continue
                try:
                    domain = urlparse(url).netloc
                except Exception:
                    domain = ""
                if domain in BLOCKED_DOMAINS:
                    print(f"  [过滤] 移除低质量来源: {domain} ({url[:60]})")
                    continue
                if r.get("description"):
                    r["description"] = self._clean_description(r["description"])
                filtered.append(r)
            return filtered

        prerequisites = []
        prereq_name_set = set()
        for item in prereq_items:
            name = item.get("name", "")
            prereq_name_set.add(name)
            finding = research.findings.get(name, {})
            if not finding:
                continue
            fields = self._extract_finding_fields(finding)
            fields["name"] = finding.get("name", name)
            fields["why_learn_first"] = item.get("why_learn_first", "")
            fields["priority"] = item.get("priority", "should")
            fields["resources"] = _filter_resources(finding.get("resources", []))
            prerequisites.append(fields)

        concepts = []
        for name in concept_names:
            finding = research.findings.get(name, {})
            if not finding:
                continue
            fields = self._extract_finding_fields(finding)
            fields["name"] = finding.get("name", name)
            fields["resources"] = _filter_resources(finding.get("resources", []))
            concepts.append(fields)

        classified = prereq_name_set | set(concept_names)
        for name in research.findings:
            if name not in classified:
                finding = research.findings[name]
                fields = self._extract_finding_fields(finding)
                fields["name"] = finding.get("name", name)
                fields["resources"] = _filter_resources(finding.get("resources", []))
                concepts.append(fields)

        overview = dict(research.overview) if research.overview else {}
        has_must_prereqs = any(p.get("priority") == "must" for p in prerequisites)
        if has_must_prereqs and overview.get("recommendation") == "deep_read":
            overview["recommendation"] = "learn_prerequisites"
            print("[修正] overview.recommendation: deep_read → learn_prerequisites（存在必须前置知识）")
        elif prerequisites and overview.get("recommendation") == "deep_read":
            overview["recommendation"] = "skim_first"
            print("[修正] overview.recommendation: deep_read → skim_first（存在前置知识）")

        paper_list = self._build_paper_list(prerequisites, concepts)
        sections = self._build_sections(overview, research, prerequisites, concepts, learning_path, paper_list)

        report = {
            "title": research.article_title,
            "source_url": research.url,
            "overview": overview,
            "summary": research.article_summary,
            "article_analysis": research.article_analysis,
            "prerequisites": prerequisites,
            "concepts": concepts,
            "learning_path": learning_path,
            "sections": sections,
        }
        if paper_list:
            report["paper_list"] = paper_list

        issues = validate_report(report)
        if issues:
            print(f"[校验] 报告质量检查:\n{format_issues(issues)}")
            if has_errors(issues):
                report["quality_warnings"] = [
                    f"{iss.field}: {iss.message}"
                    for iss in issues if iss.severity == "error"
                ]
        else:
            print("[校验] 报告质量检查通过")

        return report

    def _build_sections(
        self, overview, research, prerequisites, concepts, learning_path, paper_list=None
    ) -> list[dict]:
        sections = []
        if overview:
            sections.append({"type": "overview"})
        sections.append({"type": "summary"})
        if research.article_analysis:
            sections.append({"type": "analysis"})
        if prerequisites or concepts:
            sections.append({"type": "toc"})
        if learning_path:
            sections.append({"type": "learning_path"})
        if prerequisites:
            sections.append({"type": "prerequisites"})
        if concepts:
            sections.append({"type": "concepts"})
        if paper_list:
            sections.append({"type": "paper_list"})
        return sections

    @staticmethod
    def _build_paper_list(prerequisites: list[dict], concepts: list[dict]) -> list[dict]:
        seen_urls: set[str] = set()
        papers = []
        for item in [*prerequisites, *concepts]:
            for r in item.get("resources", []):
                url = r.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                papers.append({
                    "title": r.get("title", ""),
                    "url": url,
                    "description": r.get("description", ""),
                    "from_concept": item.get("name", ""),
                })
        return papers

    @staticmethod
    def _normalize_concept_names(learning_path: list[dict], all_names: set[str]) -> None:
        for step in learning_path:
            normalized = []
            for c in step.get("concepts", []):
                if c in all_names:
                    normalized.append(c)
                    continue
                matched = next(
                    (full for full in all_names if full.startswith(c) or c in full),
                    c,
                )
                if matched != c:
                    print(f"  [归一化] 学习路径概念名: {c!r} → {matched!r}")
                normalized.append(matched)
            step["concepts"] = normalized

    @staticmethod
    def _normalize_url(url: str) -> str:
        try:
            p = urlparse(url)
            return (p.netloc + p.path).rstrip("/").lower()
        except Exception:
            return url.lower().rstrip("/")

    @staticmethod
    def _clean_description(text: str) -> str:
        text = text.strip()
        while text.startswith(">"):
            text = text[1:].lstrip()
        return text
