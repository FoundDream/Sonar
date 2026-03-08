from pathlib import Path

import agents.coordinator as coordinator_mod
from agents.coordinator import Coordinator
from models import (
    AnalysisResult,
    FetchResult,
    save_stage_output,
)


def _patch_output_paths(monkeypatch, base: Path) -> None:
    output_dir = base / "output"
    monkeypatch.setattr(coordinator_mod, "OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(coordinator_mod, "RUNS_DIR", str(output_dir / "runs"))
    monkeypatch.setattr(coordinator_mod, "LATEST_RUN_FILE", str(output_dir / "latest_run.txt"))


def test_sanitize_run_id() -> None:
    assert Coordinator._sanitize_run_id(" demo / run ") == "demo-run"


def test_init_run_storage_writes_latest_run(monkeypatch, tmp_path: Path) -> None:
    _patch_output_paths(monkeypatch, tmp_path)
    c = Coordinator(llm=None, mode="explain")  # type: ignore[arg-type]

    c._init_run_storage(resume_from=None, run_id="my run")

    assert c.run_id == "my-run"
    assert Path(c.run_dir).is_dir()
    latest = (tmp_path / "output" / "latest_run.txt").read_text(encoding="utf-8")
    assert latest == "my-run"


def test_resume_reuses_latest_run(monkeypatch, tmp_path: Path) -> None:
    _patch_output_paths(monkeypatch, tmp_path)
    latest_file = tmp_path / "output" / "latest_run.txt"
    latest_file.parent.mkdir(parents=True, exist_ok=True)
    latest_file.write_text("saved-run", encoding="utf-8")

    c = Coordinator(llm=None, mode="explain")  # type: ignore[arg-type]
    c._init_run_storage(resume_from="analyze", run_id=None)

    assert c.run_id == "saved-run"
    assert c.run_dir.endswith("output/runs/saved-run")


def test_load_source_from_previous_stage(tmp_path: Path) -> None:
    c = Coordinator(llm=None, mode="explain")  # type: ignore[arg-type]
    c.run_dir = str(tmp_path)
    save_stage_output({"url": "https://example.com/article"}, str(tmp_path / "fetch.json"))

    assert c._load_source("") == "https://example.com/article"


def test_build_reading_report() -> None:
    analysis = AnalysisResult(
        url="https://example.com/article",
        article_title="Test Article",
        article_summary="This is a summary.",
        overview={"topic": "testing", "difficulty": "beginner"},
        article_analysis={"main_thesis": "Testing is good."},
        concepts=["concept1", "concept2"],
    )

    report = Coordinator._build_reading_report(analysis)

    assert report.title == "Test Article"
    assert report.source_url == "https://example.com/article"
    assert report.summary == "This is a summary."
    assert report.overview == {"topic": "testing", "difficulty": "beginner"}
    assert report.article_analysis == {"main_thesis": "Testing is good."}
    # Reading report should have no concepts/prerequisites/learning_path
    assert report.prerequisites == []
    assert report.concepts == []
    assert report.learning_path == []
    # Sections: overview, summary, analysis
    section_types = [s["type"] for s in report.sections]
    assert section_types == ["overview", "summary", "analysis"]


def test_fetch_result_to_dict_includes_method() -> None:
    result = FetchResult(
        url="https://example.com/article",
        title="Test Article",
        content="content",
        method="crawl4ai",
        source_type="url",
    )

    data = result.to_dict()

    assert data["method"] == "crawl4ai"
