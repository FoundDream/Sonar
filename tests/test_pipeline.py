from pathlib import Path

import orchestrator
import pipeline
from pipeline import Pipeline
from stages.models import (
    AnalysisResult,
    FetchResult,
    ReportData,
    ResearchPlan,
    ResearchResult,
    save_stage_output,
)


def _patch_output_paths(monkeypatch, base: Path) -> None:
    output_dir = base / "output"
    monkeypatch.setattr(pipeline, "OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(pipeline, "RUNS_DIR", str(output_dir / "runs"))
    monkeypatch.setattr(pipeline, "LATEST_RUN_FILE", str(output_dir / "latest_run.txt"))


def test_sanitize_run_id() -> None:
    assert Pipeline._sanitize_run_id(" demo / run ") == "demo-run"


def test_init_run_storage_writes_latest_run(monkeypatch, tmp_path: Path) -> None:
    _patch_output_paths(monkeypatch, tmp_path)
    p = Pipeline(llm=None)  # type: ignore[arg-type]

    p._init_run_storage(resume_from=None, run_id="my run")

    assert p.run_id == "my-run"
    assert Path(p.run_dir).is_dir()
    latest = (tmp_path / "output" / "latest_run.txt").read_text(encoding="utf-8")
    assert latest == "my-run"


def test_resume_reuses_latest_run(monkeypatch, tmp_path: Path) -> None:
    _patch_output_paths(monkeypatch, tmp_path)
    latest_file = tmp_path / "output" / "latest_run.txt"
    latest_file.parent.mkdir(parents=True, exist_ok=True)
    latest_file.write_text("saved-run", encoding="utf-8")

    p = Pipeline(llm=None)  # type: ignore[arg-type]
    p._init_run_storage(resume_from="analyze", run_id=None)

    assert p.run_id == "saved-run"
    assert p.run_dir.endswith("output/runs/saved-run")


def test_load_url_from_previous_stage(tmp_path: Path) -> None:
    p = Pipeline(llm=None)  # type: ignore[arg-type]
    p.run_dir = str(tmp_path)
    save_stage_output({"url": "https://example.com/article"}, str(tmp_path / "fetch.json"))

    assert p._load_url("") == "https://example.com/article"


def test_orchestrator_build_stage_snapshots_prefers_primary_url() -> None:
    url_a = "https://example.com/a"
    url_b = "https://example.com/b"

    state = orchestrator.OrchestratorState(primary_url=url_a)
    state.fetched[url_b] = FetchResult(url=url_b, title="B")
    state.fetched[url_a] = FetchResult(url=url_a, title="A")
    state.analyses[url_a] = AnalysisResult(
        url=url_a,
        article_title="Article A",
        article_summary="Summary A",
        concepts=["alpha"],
    )
    state.analyses[url_b] = AnalysisResult(
        url=url_b,
        article_title="Article B",
        article_summary="Summary B",
        concepts=["beta"],
    )
    state.all_concepts = ["alpha", "beta"]
    state.plan = ResearchPlan(preset="beginner")
    state.research_result = ResearchResult(url=url_a, concepts=["alpha"], findings={})
    state.report_data = ReportData(title="Report A", source_url=url_a)

    orch = orchestrator.Orchestrator(llm=None)  # type: ignore[arg-type]
    snapshots = orch._build_stage_snapshots(state)

    assert snapshots["fetch"]["url"] == url_a
    assert snapshots["analyze"]["url"] == url_a
    assert snapshots["analyze"]["concepts"] == ["alpha", "beta"]
    assert "[Article A] Summary A" in snapshots["analyze"]["article_summary"]
    assert "[Article B] Summary B" in snapshots["analyze"]["article_summary"]
    assert set(snapshots) == {"fetch", "analyze", "plan", "research", "synthesize"}


def test_run_orchestrated_persists_stage_outputs(monkeypatch, tmp_path: Path) -> None:
    _patch_output_paths(monkeypatch, tmp_path)
    p = Pipeline(llm=None)  # type: ignore[arg-type]
    p._init_run_storage(resume_from=None, run_id="orch-run")

    class FakeOrchestrator:
        def __init__(self, llm, preset, goal, on_stage_output=None):
            self.on_stage_output = on_stage_output

        def run(self, url: str) -> ReportData:
            self.on_stage_output("fetch", FetchResult(url=url, title="T").to_dict())
            analysis = AnalysisResult(
                url=url,
                article_title="T",
                article_summary="S",
                concepts=["c1"],
            )
            self.on_stage_output(
                "analyze",
                analysis.to_dict(),
            )
            self.on_stage_output("plan", ResearchPlan(preset="beginner").to_dict())
            research = ResearchResult(
                url=url,
                article_title="T",
                concepts=["c1"],
                findings={"c1": {}},
            )
            self.on_stage_output(
                "research",
                research.to_dict(),
            )
            report = ReportData(title="R", source_url=url, summary="Done")
            self.on_stage_output("synthesize", report.to_dict())
            return report

    monkeypatch.setattr(orchestrator, "Orchestrator", FakeOrchestrator)

    output_path = p._run_orchestrated("https://example.com/orch")
    assert Path(output_path).is_file()
    for stage in ["fetch", "analyze", "plan", "research", "synthesize"]:
        assert Path(p._stage_path(stage)).is_file()
