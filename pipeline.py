"""Pipeline 编排器：链式执行 stages，支持断点恢复。"""

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
from stages.synthesize import SynthesizeStage

OUTPUT_DIR = "output"
_MODE_TO_PRESET = {"explain": "beginner", "academic": "research"}
RUNS_DIR = os.path.join(OUTPUT_DIR, "runs")
LATEST_RUN_FILE = os.path.join(OUTPUT_DIR, "latest_run.txt")
LEGACY_RUN_ID = "__legacy__"
STAGE_ORDER = ["fetch", "analyze", "plan", "research", "synthesize"]


class Pipeline:
    def __init__(self, llm: LLMClient, mode: str = "explain", goal: str = ""):
        self.llm = llm
        self.mode = mode
        self.preset = _MODE_TO_PRESET.get(mode, "beginner")
        self.goal = goal
        self.run_id: str | None = None
        self.run_dir: str = OUTPUT_DIR

    def run(self, source: str, resume_from: str | None = None, run_id: str | None = None) -> str:
        """Run the pipeline. Routes based on mode.

        source: URL or local file path.
        Returns the output HTML path.
        """
        self._init_run_storage(resume_from=resume_from, run_id=run_id)
        if self.mode == "reading":
            return self._run_reading(source, resume_from)
        return self._run_fixed(source, resume_from)  # explain / academic

    def _run_reading(self, source: str, resume_from: str | None = None) -> str:
        """Reading mode: Fetch -> Analyze -> Render. No concept research."""
        print("[Pipeline] 阅读报告模式")

        fetch_result: FetchResult | None = None
        analysis: AnalysisResult | None = None

        # Load cached stages if resuming
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

        # Fetch
        if not analysis and not fetch_result:
            stage = FetchStage(self.llm)
            result = stage.run(source)
            if isinstance(result, dict) and "error" in result:
                raise RuntimeError(result["error"])
            fetch_result = result
            save_stage_output(fetch_result.to_dict(), self._stage_path("fetch"))

        # Analyze
        if not analysis:
            stage = AnalyzeStage(self.llm)
            result = stage.run(fetch_result)
            if isinstance(result, dict) and "error" in result:
                raise RuntimeError(result["error"])
            analysis = result
            save_stage_output(analysis.to_dict(), self._stage_path("analyze"))

        # Build reading report directly from analysis
        report_data = self._build_reading_report(analysis)
        save_stage_output(report_data.to_dict(), self._stage_path("synthesize"))

        output_path = render_report(report_data.to_dict(), self._report_path())
        self._publish_latest_report(output_path)
        return output_path

    @staticmethod
    def _build_reading_report(analysis: AnalysisResult) -> ReportData:
        """Assemble a reading report from analysis output. No concepts/research."""
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

    def _run_fixed(self, source: str, resume_from: str | None = None) -> str:
        """Run the fixed pipeline, optionally resuming from a stage.

        Returns the output HTML path.
        """
        if resume_from:
            if resume_from not in STAGE_ORDER:
                raise ValueError(f"Unknown stage: {resume_from}. Valid: {STAGE_ORDER}")
            start_idx = STAGE_ORDER.index(resume_from)
        else:
            start_idx = 0

        fetch_result: FetchResult | None = None
        analysis: AnalysisResult | None = None
        plan: ResearchPlan | None = None
        research: ResearchResult | None = None
        report_data: ReportData | None = None

        if start_idx > 0:
            source = self._load_source(source)

        if start_idx > STAGE_ORDER.index("fetch"):
            fetch_result = FetchResult.from_dict(
                load_stage_output(self._stage_path("fetch"))
            )

        if start_idx > STAGE_ORDER.index("analyze"):
            analysis = AnalysisResult.from_dict(
                load_stage_output(self._stage_path("analyze"))
            )

        if start_idx > STAGE_ORDER.index("plan"):
            plan_path = self._stage_path("plan")
            if os.path.exists(plan_path):
                plan = ResearchPlan.from_dict(load_stage_output(plan_path))

        if start_idx > STAGE_ORDER.index("research"):
            research = ResearchResult.from_dict(
                load_stage_output(self._stage_path("research"))
            )

        # Execute stages from start point
        for stage_name in STAGE_ORDER[start_idx:]:
            if stage_name == "fetch":
                stage = FetchStage(self.llm)
                result = stage.run(source)
                if isinstance(result, dict) and "error" in result:
                    raise RuntimeError(result["error"])
                fetch_result = result
                save_stage_output(fetch_result.to_dict(), self._stage_path("fetch"))

            elif stage_name == "analyze":
                stage = AnalyzeStage(self.llm)
                result = stage.run(fetch_result)
                if isinstance(result, dict) and "error" in result:
                    raise RuntimeError(result["error"])
                analysis = result
                save_stage_output(analysis.to_dict(), self._stage_path("analyze"))

            elif stage_name == "plan":
                from stages.plan import PlanStage
                stage = PlanStage(self.llm)
                plan = stage.run(self.preset, self.goal, analysis)
                save_stage_output(plan.to_dict(), self._stage_path("plan"))

            elif stage_name == "research":
                stage = ResearchStage(self.llm, plan)
                research = stage.run(analysis)
                save_stage_output(research.to_dict(), self._stage_path("research"))

            elif stage_name == "synthesize":
                stage = SynthesizeStage(self.llm, plan)
                report_data = stage.run(research)
                save_stage_output(report_data.to_dict(), self._stage_path("synthesize"))

        # Render HTML
        output_path = render_report(report_data.to_dict(), self._report_path())
        self._publish_latest_report(output_path)
        return output_path

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
        """Try to get source from prior stage outputs when resuming."""
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
