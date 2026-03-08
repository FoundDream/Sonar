"""Pipeline 编排器：orchestrator 模式，支持 review → research 返工循环和断点恢复。"""

import os
import re
import shutil
from datetime import datetime
from uuid import uuid4

from llm.client import LLMClient
from report.renderer import render_report
from stages.analyze import AnalyzeStage
from stages.fetch import FetchStage
from stages.models import (
    AnalysisResult,
    FetchResult,
    ReportData,
    ResearchPlan,
    ResearchResult,
    load_stage_output,
    save_stage_output,
)
from stages.research import ResearchStage
from stages.review import ReviewStage
from stages.synthesize import SynthesizeStage

OUTPUT_DIR = "output"
RUNS_DIR = os.path.join(OUTPUT_DIR, "runs")
LATEST_RUN_FILE = os.path.join(OUTPUT_DIR, "latest_run.txt")
LEGACY_RUN_ID = "__legacy__"

# Resume-able stages (review is not independently resumable)
STAGE_ORDER = ["fetch", "analyze", "plan", "research", "synthesize"]

MAX_REVIEW_CYCLES = 1


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
            stage = FetchStage(self.llm)
            result = stage.run(source)
            if isinstance(result, dict) and "error" in result:
                raise RuntimeError(result["error"])
            fetch_result = result
            save_stage_output(fetch_result.to_dict(), self._stage_path("fetch"))

        if not analysis:
            stage = AnalyzeStage(self.llm)
            result = stage.run(fetch_result)
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
        """Orchestrator: dispatch steps with transitions, supporting review→research loop."""
        if resume_from:
            if resume_from not in STAGE_ORDER:
                raise ValueError(f"Unknown stage: {resume_from}. Valid: {STAGE_ORDER}")
            start_step = resume_from
        else:
            start_step = "fetch"

        # Load cached state for resume
        ctx = self._load_context(source, start_step)

        # Orchestrator loop
        step = start_step
        while step:
            step = self._execute_step(step, ctx)

        # Render HTML
        output_path = render_report(ctx["report_data"].to_dict(), self._report_path())
        self._publish_latest_report(output_path)
        return output_path

    def _execute_step(self, step: str, ctx: dict) -> str | None:
        """Execute a step and return the next step (or None to stop)."""

        if step == "fetch":
            stage = FetchStage(self.llm)
            result = stage.run(ctx["source"])
            if isinstance(result, dict) and "error" in result:
                raise RuntimeError(result["error"])
            ctx["fetch_result"] = result
            save_stage_output(result.to_dict(), self._stage_path("fetch"))
            return "analyze"

        if step == "analyze":
            stage = AnalyzeStage(self.llm)
            result = stage.run(ctx["fetch_result"])
            if isinstance(result, dict) and "error" in result:
                raise RuntimeError(result["error"])
            ctx["analysis"] = result
            save_stage_output(result.to_dict(), self._stage_path("analyze"))
            return "plan"

        if step == "plan":
            from stages.plan import PlanStage
            stage = PlanStage(self.llm)
            ctx["plan"] = stage.run(self.preset, self.goal, ctx["analysis"])
            save_stage_output(ctx["plan"].to_dict(), self._stage_path("plan"))
            return "research"

        if step == "research":
            stage = ResearchStage(self.llm, ctx.get("plan"))
            ctx["research"] = stage.run(ctx["analysis"])
            save_stage_output(ctx["research"].to_dict(), self._stage_path("research"))
            return "review"

        if step == "review":
            review_stage = ReviewStage(ctx.get("plan"))
            review = review_stage.run(ctx["research"])

            cycle = ctx.get("review_cycle", 0)
            if not review.passed and cycle < MAX_REVIEW_CYCLES:
                ctx["review_cycle"] = cycle + 1
                # Rework flagged concepts
                research_stage = ResearchStage(self.llm, ctx.get("plan"))
                ctx["research"] = research_stage.rework(ctx["research"], review.rework)
                save_stage_output(ctx["research"].to_dict(), self._stage_path("research"))
                # Re-review after rework
                return "review"
            return "synthesize"

        if step == "synthesize":
            stage = SynthesizeStage(self.llm, ctx.get("plan"))
            ctx["report_data"] = stage.run(ctx["research"])
            save_stage_output(ctx["report_data"].to_dict(), self._stage_path("synthesize"))
            return None

        raise ValueError(f"Unknown step: {step}")

    def _load_context(self, source: str, start_step: str) -> dict:
        """Load cached stage outputs needed for the start step."""
        ctx: dict = {"source": source}

        if start_step == "fetch":
            return ctx

        # Need source from prior outputs if not provided
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
