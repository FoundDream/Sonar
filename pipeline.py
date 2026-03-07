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
RUNS_DIR = os.path.join(OUTPUT_DIR, "runs")
LATEST_RUN_FILE = os.path.join(OUTPUT_DIR, "latest_run.txt")
LEGACY_RUN_ID = "__legacy__"
STAGE_ORDER = ["fetch", "analyze", "plan", "research", "synthesize"]


class Pipeline:
    def __init__(self, llm: LLMClient, preset: str = "beginner", goal: str = "",
                 force_orchestrator: bool = False):
        self.llm = llm
        self.preset = preset
        self.goal = goal
        self.force_orchestrator = force_orchestrator
        self.run_id: str | None = None
        self.run_dir: str = OUTPUT_DIR

    def run(self, url: str, resume_from: str | None = None, run_id: str | None = None) -> str:
        """Run the pipeline. Uses orchestrator when appropriate.

        Returns the output HTML path.
        """
        self._init_run_storage(resume_from=resume_from, run_id=run_id)
        if resume_from or not self._should_use_orchestrator():
            return self._run_fixed(url, resume_from)
        return self._run_orchestrated(url)

    def _should_use_orchestrator(self) -> bool:
        return self.force_orchestrator

    def _run_orchestrated(self, url: str) -> str:
        from orchestrator import Orchestrator

        print("[Pipeline] 使用 Orchestrator 模式")

        def _persist_stage(stage_name: str, data: dict) -> None:
            save_stage_output(data, self._stage_path(stage_name))

        orch = Orchestrator(self.llm, self.preset, self.goal, on_stage_output=_persist_stage)
        report_data = orch.run(url)

        save_stage_output(report_data.to_dict(), self._stage_path("synthesize"))
        output_path = render_report(report_data.to_dict(), self._report_path())
        self._publish_latest_report(output_path)
        return output_path

    def _run_fixed(self, url: str, resume_from: str | None = None) -> str:
        """Run the fixed pipeline, optionally resuming from a stage.

        Returns the output HTML path.
        """
        # Determine which stages to skip
        if resume_from:
            if resume_from not in STAGE_ORDER:
                raise ValueError(f"Unknown stage: {resume_from}. Valid: {STAGE_ORDER}")
            start_idx = STAGE_ORDER.index(resume_from)
        else:
            start_idx = 0

        # Stage outputs
        fetch_result: FetchResult | None = None
        analysis: AnalysisResult | None = None
        plan: ResearchPlan | None = None
        research: ResearchResult | None = None
        report_data: ReportData | None = None

        # Load prior stage outputs if resuming
        if start_idx > 0:
            url = self._load_url(url)

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
                result = stage.run(url)
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

    def _load_url(self, url: str) -> str:
        """Try to get URL from prior stage outputs when resuming."""
        if url:
            return url
        for stage in ["fetch", "analyze", "research"]:
            path = self._stage_path(stage)
            if os.path.exists(path):
                data = load_stage_output(path)
                if "url" in data:
                    return data["url"]
        raise ValueError(
            "Cannot determine URL when resuming. "
            "Provide a URL or ensure prior stage outputs exist."
        )
