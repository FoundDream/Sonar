"""Research 阶段：并行研究概念 + 质量审查。"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from agents.researcher import Researcher
from agents.researcher.tools import EMPTY_FINDING, build_finding_tool
from agents.verifier import Verifier
from llm.client import LLMClient
from stages.models import AnalysisResult, ResearchPlan, ResearchResult, ReworkItem

MAX_VERIFY_RETRIES = 1


class ResearchStage:
    """并行研究所有概念。"""

    def __init__(self, llm: LLMClient, plan: ResearchPlan | None = None):
        self.llm = llm
        self.plan = plan
        self._finding_tool = None
        self._finding_schema = None
        if plan and plan.finding_schema:
            self._finding_tool = build_finding_tool(plan.finding_schema)
            self._finding_schema = plan.finding_schema

    def run(self, analysis: AnalysisResult) -> ResearchResult:
        if self.plan and self.plan.selected_concepts:
            concepts = self.plan.selected_concepts
        else:
            concepts = analysis.concepts
        summary = analysis.article_summary

        print(f"\n--- 并行研究 {len(concepts)} 个概念 ---")

        findings = self._research_concepts(concepts, summary)

        print("\n--- 所有概念研究完成 ---")

        return ResearchResult(
            url=analysis.url,
            article_title=analysis.article_title,
            article_summary=analysis.article_summary,
            overview=analysis.overview,
            article_analysis=analysis.article_analysis,
            concepts=analysis.concepts,
            findings=findings,
        )

    def rework(self, research: ResearchResult, rework_items: list[ReworkItem]) -> ResearchResult:
        """Re-research specific concepts with reviewer feedback."""
        feedback_map = {item.concept: item.feedback for item in rework_items}
        concepts_to_redo = list(feedback_map.keys())

        print(f"\n--- 返工 {len(concepts_to_redo)} 个概念 ---")

        base_hints = self.plan.concept_hints if self.plan else {}
        extra_hints = {}
        for concept in concepts_to_redo:
            base = base_hints.get(concept, "")
            feedback = feedback_map.get(concept, "")
            extra_hints[concept] = f"{base}\n上一轮审查反馈：{feedback}".strip() if feedback else base

        findings = self._research_concepts(
            concepts_to_redo, research.article_summary, hint_overrides=extra_hints
        )

        print("\n--- 返工完成 ---")

        updated_findings = dict(research.findings)
        updated_findings.update(findings)

        return ResearchResult(
            url=research.url,
            article_title=research.article_title,
            article_summary=research.article_summary,
            overview=research.overview,
            article_analysis=research.article_analysis,
            concepts=research.concepts,
            findings=updated_findings,
        )

    def _research_concepts(
        self, concepts: list[str], summary: str,
        hint_overrides: dict[str, str] | None = None,
    ) -> dict[str, dict]:
        """Research a list of concepts in parallel with verify loop."""
        researcher_prompt = self.plan.researcher_prompt if self.plan else None
        base_hints = self.plan.concept_hints if self.plan else {}

        def _research_one(concept: str) -> tuple[str, dict]:
            researcher = Researcher(
                self.llm, self._finding_tool, researcher_prompt, self._finding_schema
            )
            verifier = Verifier(self.llm, self._finding_schema)

            hints = (hint_overrides or {}).get(concept, base_hints.get(concept, ""))
            result = researcher.research(concept, summary, hints=hints)

            for attempt in range(1 + MAX_VERIFY_RETRIES):
                verdict = verifier.verify(result, summary)
                if verdict.get("pass", True):
                    print(f"  [审查] {concept}: 通过")
                    break
                if attempt < MAX_VERIFY_RETRIES:
                    feedback = verdict.get("feedback", "")
                    combined_hints = f"{hints}\n{feedback}".strip() if hints else feedback
                    print(f"  [审查] {concept}: 未通过，重新研究 — {feedback[:80]}")
                    result = researcher.research(concept, summary, hints=combined_hints)
                else:
                    print(f"  [审查] {concept}: 重试后仍未通过，保留当前结果")

            return concept, result

        findings: dict[str, dict] = {}

        with ThreadPoolExecutor(max_workers=min(len(concepts), 4)) as pool:
            futures = {pool.submit(_research_one, c): c for c in concepts}
            for future in as_completed(futures):
                concept = futures[future]
                try:
                    _, result = future.result()
                    findings[concept] = result
                    n_resources = len(result.get("resources", []))
                    print(f"[完成] {concept}: {n_resources} 条资料")
                except Exception as e:
                    print(f"[错误] {concept} 研究失败: {e}")
                    findings[concept] = dict(EMPTY_FINDING, name=concept)

        return findings
