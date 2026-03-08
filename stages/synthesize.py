"""Synthesize 阶段：分类概念、组装报告数据。"""

import json
from urllib.parse import urlparse

from llm.client import LLMClient
from report.schema import format_issues, has_errors, validate_report
from stages.models import ReportData, ResearchPlan, ResearchResult
from stages.prompts.synthesize import CLASSIFY_TOOL, SYNTHESIZER_PROMPT
from tools.search import BLOCKED_DOMAINS


_FIELD_ALIASES: dict[str, list[str]] = {
    "explanation": ["explanation", "summary"],
    "why_important": ["why_important", "key_findings"],
    "article_role": ["article_role", "relevance"],
}

_SKIP_FIELDS = {"name", "resources"}


class SynthesizeStage:
    def __init__(self, llm: LLMClient, plan: ResearchPlan | None = None):
        self.llm = llm
        self.plan = plan

    def run(self, research: ResearchResult) -> ReportData:
        classification = self._classify(research)
        report_dict = self._assemble(research, classification)
        return ReportData.from_dict(report_dict)

    def _classify(self, research: ResearchResult) -> dict | None:
        concept_names = list(research.findings.keys())
        synthesizer_prompt = SYNTHESIZER_PROMPT
        classify_tool = CLASSIFY_TOOL
        if self.plan:
            if self.plan.synthesizer_prompt:
                synthesizer_prompt = self.plan.synthesizer_prompt
            if self.plan.classify_tool:
                classify_tool = self.plan.classify_tool

        messages = [
            {"role": "system", "content": synthesizer_prompt},
            {"role": "user", "content": f"""文章标题: {research.article_title}
文章摘要: {research.article_summary}

已研究的概念列表:
{json.dumps(concept_names, ensure_ascii=False)}

请调用 classify_concepts 对这些概念进行分类、标注优先级、编排学习路径。"""},
        ]

        print(f"[Synthesizer] 对 {len(concept_names)} 个概念进行分类...")
        resp = self.llm.chat(messages, tools=[classify_tool])

        if "tool_calls" in resp:
            for tc in resp["tool_calls"]:
                fn_name = tc["function"]["name"]
                if fn_name == classify_tool["function"]["name"]:
                    try:
                        return json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError as e:
                        print(f"[Synthesizer] JSON 解析失败: {e}")
        return None

    def _extract_finding_fields(self, finding: dict) -> dict:
        """Extract fields from a finding using the plan's schema, with alias mapping."""
        if self.plan and self.plan.finding_schema:
            raw: dict[str, str] = {}
            for field in self.plan.finding_schema:
                if field.name in _SKIP_FIELDS:
                    continue
                raw[field.name] = finding.get(field.name, "")

            # Map schema fields to canonical names via aliases
            result: dict[str, str] = {}
            for canonical, aliases in _FIELD_ALIASES.items():
                for alias in aliases:
                    if alias in raw and raw[alias]:
                        result[canonical] = raw.pop(alias)
                        break
                else:
                    # No alias matched with a value; try empty string fallback
                    for alias in aliases:
                        if alias in raw:
                            result[canonical] = raw.pop(alias)
                            break
            # Pass through remaining fields (e.g. methodology, example, analogy)
            result.update(raw)
            return result

        # Fallback: hardcoded explain fields (for reading mode / no plan)
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

        # Build paper_list for research mode
        paper_list = []
        if self.plan and self.plan.preset == "academic":
            paper_list = self._build_paper_list(concepts)

        # Build sections list for modular template rendering
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
        """Build sections list for section-based template rendering."""
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
    def _build_paper_list(concepts: list[dict]) -> list[dict]:
        """Extract paper-like entries from concepts for research mode."""
        papers = []
        for c in concepts:
            paper = {
                "name": c.get("name", ""),
                "summary": c.get("explanation", ""),
                "key_findings": c.get("why_important", ""),
                "relevance": c.get("article_role", ""),
                "methodology": c.get("methodology", ""),
                "resources": c.get("resources", []),
            }
            papers.append(paper)
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
