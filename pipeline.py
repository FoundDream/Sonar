"""Pipeline 编排器：orchestrator 模式，直接协调 agents，支持 review → research 返工循环。"""

import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from uuid import uuid4

from llm.client import LLMClient

from agents.analyzer import Analyzer
from agents.planner import Planner
from agents.researcher import EMPTY_FINDING, Researcher, build_finding_tool
from agents.reviewer import Reviewer
from agents.synthesizer import Synthesizer
from agents.verifier import Verifier
from fetchers import get_fetcher
from fetchers.base import FetchError
from fetchers.url import URLFetcher
from models import (
    AnalysisResult,
    FetchResult,
    ReportData,
    ResearchPlan,
    ResearchResult,
    load_stage_output,
    save_stage_output,
)
from report.renderer import render_report
from tools.quality import make_quality_checker

OUTPUT_DIR = "output"
RUNS_DIR = os.path.join(OUTPUT_DIR, "runs")
LATEST_RUN_FILE = os.path.join(OUTPUT_DIR, "latest_run.txt")
LEGACY_RUN_ID = "__legacy__"

STAGE_ORDER = ["fetch", "analyze", "plan", "research", "synthesize"]

MAX_REVIEW_CYCLES = 1
MAX_VERIFY_RETRIES = 1


class Pipeline:
    def __init__(self, llm: LLMClient, mode: str = "explain", goal: str = ""):
        self.llm = llm
        self.mode = mode
        self.preset = mode
        self.goal = goal
        self.run_id: str | None = None
        self.run_dir: str = OUTPUT_DIR

    def run(self, source: str, resume_from: str | None = None, run_id: str | None = None) -> str:
        self._init_run_storage(resume_from=resume_from, run_id=run_id)
        if self.mode == "reading":
            return self._run_reading(source, resume_from)
        return self._run_orchestrated(source, resume_from)

    # ── Reading mode (simple linear) ──────────────────────────────

    def _run_reading(self, source: str, resume_from: str | None = None) -> str:
        print("[Pipeline] 阅读报告模式")

        fetch_result: FetchResult | None = None
        analysis: AnalysisResult | None = None

        if resume_from == "synthesize":
            analysis = AnalysisResult.from_dict(
                load_stage_output(self._stage_path("analyze"))
            )
        elif resume_from == "analyze":
            fetch_result = FetchResult.from_dict(
                load_stage_output(self._stage_path("fetch"))
            )
        elif resume_from and resume_from != "fetch":
            analysis = AnalysisResult.from_dict(
                load_stage_output(self._stage_path("analyze"))
            )

        if not analysis and not fetch_result:
            result = self._fetch(source)
            if isinstance(result, dict) and "error" in result:
                raise RuntimeError(result["error"])
            fetch_result = result
            save_stage_output(fetch_result.to_dict(), self._stage_path("fetch"))

        if not analysis:
            analyzer = Analyzer(self.llm)
            result = analyzer.analyze(fetch_result)
            if isinstance(result, dict) and "error" in result:
                raise RuntimeError(result["error"])
            analysis = result
            save_stage_output(analysis.to_dict(), self._stage_path("analyze"))

        report_data = self._build_reading_report(analysis)
        save_stage_output(report_data.to_dict(), self._stage_path("synthesize"))

        output_path = render_report(report_data.to_dict(), self._report_path())
        self._publish_latest_report(output_path)
        return output_path

    @staticmethod
    def _build_reading_report(analysis: AnalysisResult) -> ReportData:
        sections = [{"type": "overview"}, {"type": "summary"}]
        if analysis.article_analysis:
            sections.append({"type": "analysis"})

        return ReportData(
            title=analysis.article_title,
            source_url=analysis.url,
            overview=analysis.overview,
            summary=analysis.article_summary,
            article_analysis=analysis.article_analysis,
            sections=sections,
        )

    # ── Orchestrated mode (with review loop) ──────────────────────

    def _run_orchestrated(self, source: str, resume_from: str | None = None) -> str:
        if resume_from:
            if resume_from not in STAGE_ORDER:
                raise ValueError(f"Unknown stage: {resume_from}. Valid: {STAGE_ORDER}")
            start_step = resume_from
        else:
            start_step = "fetch"

        ctx = self._load_context(source, start_step)

        step = start_step
        while step:
            step = self._execute_step(step, ctx)

        output_path = render_report(ctx["report_data"].to_dict(), self._report_path())
        self._publish_latest_report(output_path)
        return output_path

    def _execute_step(self, step: str, ctx: dict) -> str | None:

        if step == "fetch":
            result = self._fetch(ctx["source"])
            if isinstance(result, dict) and "error" in result:
                raise RuntimeError(result["error"])
            ctx["fetch_result"] = result
            save_stage_output(result.to_dict(), self._stage_path("fetch"))
            return "analyze"

        if step == "analyze":
            analyzer = Analyzer(self.llm)
            result = analyzer.analyze(ctx["fetch_result"])
            if isinstance(result, dict) and "error" in result:
                raise RuntimeError(result["error"])
            ctx["analysis"] = result
            save_stage_output(result.to_dict(), self._stage_path("analyze"))
            return "plan"

        if step == "plan":
            planner = Planner(self.llm)
            ctx["plan"] = planner.plan(self.preset, self.goal, ctx["analysis"])
            save_stage_output(ctx["plan"].to_dict(), self._stage_path("plan"))
            return "research"

        if step == "research":
            plan = ctx.get("plan")
            ctx["research"] = self._research(ctx["analysis"], plan)
            save_stage_output(ctx["research"].to_dict(), self._stage_path("research"))
            return "review"

        if step == "review":
            reviewer = Reviewer(self.llm)
            review = reviewer.review(ctx["research"])

            cycle = ctx.get("review_cycle", 0)
            if not review.passed and cycle < MAX_REVIEW_CYCLES:
                ctx["review_cycle"] = cycle + 1
                plan = ctx.get("plan")
                ctx["research"] = self._rework(ctx["research"], review.rework, plan)
                save_stage_output(ctx["research"].to_dict(), self._stage_path("research"))
                return "review"
            return "synthesize"

        if step == "synthesize":
            synthesizer = Synthesizer(self.llm, ctx.get("plan"))
            ctx["report_data"] = synthesizer.synthesize(ctx["research"])
            save_stage_output(ctx["report_data"].to_dict(), self._stage_path("synthesize"))
            return None

        raise ValueError(f"Unknown step: {step}")

    # ── Fetch ─────────────────────────────────────────────────────

    def _fetch(self, source: str) -> FetchResult | dict:
        try:
            fetcher = get_fetcher(source)
            if isinstance(fetcher, URLFetcher):
                fetcher.quality_checker = make_quality_checker(llm=self.llm)
            return fetcher.fetch(source)
        except FetchError as e:
            return {"error": str(e)}

    # ── Research orchestration ────────────────────────────────────

    def _research(self, analysis: AnalysisResult, plan: ResearchPlan | None) -> ResearchResult:
        if plan and plan.selected_concepts:
            concepts = plan.selected_concepts
        else:
            concepts = analysis.concepts

        print(f"\n--- 并行研究 {len(concepts)} 个概念 ---")
        findings = self._research_concepts(concepts, analysis.article_summary, plan)
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

    def _rework(
        self, research: ResearchResult, rework_items: list, plan: ResearchPlan | None
    ) -> ResearchResult:
        feedback_map = {item.concept: item.feedback for item in rework_items}
        concepts_to_redo = list(feedback_map.keys())

        print(f"\n--- 返工 {len(concepts_to_redo)} 个概念 ---")

        base_hints = plan.concept_hints if plan else {}
        extra_hints = {}
        for concept in concepts_to_redo:
            base = base_hints.get(concept, "")
            feedback = feedback_map.get(concept, "")
            extra_hints[concept] = f"{base}\n上一轮审查反馈：{feedback}".strip() if feedback else base

        findings = self._research_concepts(
            concepts_to_redo, research.article_summary, plan, hint_overrides=extra_hints
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
        plan: ResearchPlan | None,
        hint_overrides: dict[str, str] | None = None,
    ) -> dict[str, dict]:
        finding_tool = None
        finding_schema = None
        if plan and plan.finding_schema:
            finding_tool = build_finding_tool(plan.finding_schema)
            finding_schema = plan.finding_schema

        researcher_prompt = plan.researcher_prompt if plan else None
        base_hints = plan.concept_hints if plan else {}

        def _research_one(concept: str) -> tuple[str, dict]:
            researcher = Researcher(self.llm, finding_tool, researcher_prompt, finding_schema)
            verifier = Verifier(self.llm, finding_schema)

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

    # ── Context loading (for resume) ──────────────────────────────

    def _load_context(self, source: str, start_step: str) -> dict:
        ctx: dict = {"source": source}

        if start_step == "fetch":
            return ctx

        if not source:
            ctx["source"] = self._load_source(source)

        step_idx = STAGE_ORDER.index(start_step)

        if step_idx > STAGE_ORDER.index("fetch"):
            ctx["fetch_result"] = FetchResult.from_dict(
                load_stage_output(self._stage_path("fetch"))
            )

        if step_idx > STAGE_ORDER.index("analyze"):
            ctx["analysis"] = AnalysisResult.from_dict(
                load_stage_output(self._stage_path("analyze"))
            )

        if step_idx > STAGE_ORDER.index("plan"):
            plan_path = self._stage_path("plan")
            if os.path.exists(plan_path):
                ctx["plan"] = ResearchPlan.from_dict(load_stage_output(plan_path))

        if step_idx > STAGE_ORDER.index("research"):
            ctx["research"] = ResearchResult.from_dict(
                load_stage_output(self._stage_path("research"))
            )

        return ctx

    # ── Storage helpers ───────────────────────────────────────────

    def _stage_path(self, stage: str) -> str:
        return os.path.join(self.run_dir, f"{stage}.json")

    def _report_path(self) -> str:
        return os.path.join(self.run_dir, "report.html")

    def _init_run_storage(self, resume_from: str | None, run_id: str | None) -> None:
        if run_id:
            resolved_run_id = self._sanitize_run_id(run_id)
        elif resume_from:
            resolved_run_id = self._load_latest_run_id() or LEGACY_RUN_ID
        else:
            resolved_run_id = self._new_run_id()

        self.run_id = resolved_run_id
        if resolved_run_id == LEGACY_RUN_ID:
            self.run_dir = OUTPUT_DIR
        else:
            self.run_dir = os.path.join(RUNS_DIR, resolved_run_id)
        os.makedirs(self.run_dir, exist_ok=True)

        if resolved_run_id != LEGACY_RUN_ID:
            self._save_latest_run_id(resolved_run_id)
            print(f"[Pipeline] run_id: {resolved_run_id}")

    def _publish_latest_report(self, report_path: str) -> None:
        latest_report_path = os.path.join(OUTPUT_DIR, "report.html")
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        if os.path.abspath(report_path) != os.path.abspath(latest_report_path):
            shutil.copyfile(report_path, latest_report_path)

    @staticmethod
    def _new_run_id() -> str:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"{ts}-{uuid4().hex[:6]}"

    @staticmethod
    def _sanitize_run_id(run_id: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", run_id.strip())
        return cleaned.strip("-") or Pipeline._new_run_id()

    def _save_latest_run_id(self, run_id: str) -> None:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(LATEST_RUN_FILE, "w", encoding="utf-8") as f:
            f.write(run_id)

    def _load_latest_run_id(self) -> str | None:
        if not os.path.exists(LATEST_RUN_FILE):
            return None
        with open(LATEST_RUN_FILE, encoding="utf-8") as f:
            content = f.read().strip()
        return content or None

    def _load_source(self, source: str) -> str:
        if source:
            return source
        for stage in ["fetch", "analyze", "research"]:
            path = self._stage_path(stage)
            if os.path.exists(path):
                data = load_stage_output(path)
                if "url" in data:
                    return data["url"]
        raise ValueError(
            "Cannot determine source when resuming. "
            "Provide a source or ensure prior stage outputs exist."
        )
