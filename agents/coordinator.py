"""Coordinator Agent：LLM 驱动的多 Agent 协调器，取代硬编码 Pipeline。"""

import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from uuid import uuid4

from agents.analyzer import Analyzer
from agents.base import Agent
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
from presets import get_preset
from report.renderer import render_report
from tools.llm import LLMClient
from tools.quality import make_quality_checker

OUTPUT_DIR = "output"
RUNS_DIR = os.path.join(OUTPUT_DIR, "runs")
LATEST_RUN_FILE = os.path.join(OUTPUT_DIR, "latest_run.txt")
LEGACY_RUN_ID = "__legacy__"

STAGE_ORDER = ["fetch", "analyze", "plan", "research", "synthesize"]

MAX_REVIEW_CYCLES = 1
MAX_VERIFY_RETRIES = 1

# ── Coordinator Prompt ───────────────────────────────────────────

COORDINATOR_PROMPT = """\
你是 Sonar 的协调器（Coordinator）。你负责协调多个专家 Agent 来为用户生成一份高质量的学习报告。

## 你的职责

你根据当前状态自主决定下一步操作。你的工作流程是：

1. **analyze_article** — 抓取并分析文章，获取摘要、速览、核心概念
2. **research_concepts** — 并行研究所有核心概念（每个概念由独立的研究员 Agent 完成）
3. **review_research** — 审查研究质量
4. （可选）**rework_concepts** — 如果审查发现质量问题，返工特定概念
5. **synthesize_report** — 合成最终报告
6. **finalize_report** — 标记完成

## 决策原则

- 按顺序执行，每一步完成后根据结果决定下一步
- review 后如果有返工项，调用 rework_concepts；如果全部通过，直接 synthesize
- 最多返工一次，避免死循环
- 完成所有步骤后，必须调用 finalize_report 结束流程
"""

# ── Tool Schemas ─────────────────────────────────────────────────

ANALYZE_TOOL = {
    "type": "function",
    "function": {
        "name": "analyze_article",
        "description": "抓取并分析文章。返回标题、摘要、核心概念列表。这是流程的第一步。",
        "parameters": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "文章 URL 或本地文件路径",
                },
            },
            "required": ["source"],
        },
    },
}

RESEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "research_concepts",
        "description": "并行研究多个概念。每个概念由独立研究员搜索资料并生成解释。",
        "parameters": {
            "type": "object",
            "properties": {
                "concepts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要研究的概念列表",
                },
                "reasoning": {
                    "type": "string",
                    "description": "简要说明为什么研究这些概念",
                },
                "concept_hints": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "可选：每个概念的研究方向提示（key=概念名, value=提示）",
                },
            },
            "required": ["concepts", "reasoning"],
        },
    },
}

REVIEW_TOOL = {
    "type": "function",
    "function": {
        "name": "review_research",
        "description": "审查所有概念的研究质量。返回是否通过以及需要返工的概念列表。",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}

REWORK_TOOL = {
    "type": "function",
    "function": {
        "name": "rework_concepts",
        "description": "返工质量不合格的概念。传入需要返工的概念及反馈。",
        "parameters": {
            "type": "object",
            "properties": {
                "rework_items": {
                    "type": "array",
                    "description": "需要返工的概念列表",
                    "items": {
                        "type": "object",
                        "properties": {
                            "concept": {"type": "string"},
                            "feedback": {"type": "string"},
                        },
                        "required": ["concept", "feedback"],
                    },
                },
            },
            "required": ["rework_items"],
        },
    },
}

SYNTHESIZE_TOOL = {
    "type": "function",
    "function": {
        "name": "synthesize_report",
        "description": "合成最终报告：对概念分类、编排学习路径、组装报告数据。",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}

FINALIZE_TOOL = {
    "type": "function",
    "function": {
        "name": "finalize_report",
        "description": "标记报告完成。这是最后一步，调用后流程结束。",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["complete", "partial"],
                    "description": "complete=正常完成, partial=部分完成（有降级）",
                },
                "notes": {
                    "type": "string",
                    "description": "可选：完成备注",
                },
            },
            "required": ["status"],
        },
    },
}


# ── Coordinator Agent ────────────────────────────────────────────

class Coordinator(Agent):
    """LLM-driven coordinator that orchestrates expert agents."""

    def __init__(self, llm: LLMClient, mode: str = "explain", goal: str = ""):
        super().__init__(
            llm,
            name="Coordinator",
            system_prompt=COORDINATOR_PROMPT,
            max_iterations=8,
        )
        self.mode = mode
        self.preset = mode
        self.goal = goal
        self.run_id: str | None = None
        self.run_dir: str = OUTPUT_DIR

        self._state: dict = {
            "fetch_result": None,
            "analysis": None,
            "plan": None,
            "findings": {},
            "research_result": None,
            "report_data": None,
        }
        self._review_cycle = 0

        # Register tools
        self.add_tool(ANALYZE_TOOL, handler=self._handle_analyze)
        self.add_tool(RESEARCH_TOOL, handler=self._handle_research)
        self.add_tool(REVIEW_TOOL, handler=self._handle_review)
        self.add_tool(REWORK_TOOL, handler=self._handle_rework)
        self.add_tool(SYNTHESIZE_TOOL, handler=self._handle_synthesize)
        self.add_terminal_tool(FINALIZE_TOOL)

    # ── Public API ───────────────────────────────────────────────

    def run(self, source: str, resume_from: str | None = None, run_id: str | None = None) -> str:
        """Run the full pipeline. Returns the report file path."""
        self._init_run_storage(resume_from=resume_from, run_id=run_id)
        if self.mode == "reading":
            return self._run_reading(source, resume_from)
        return self._run_coordinated(source, resume_from)

    # ── Reading mode (no LLM coordination) ───────────────────────

    def _run_reading(self, source: str, resume_from: str | None = None) -> str:
        print("[Coordinator] 阅读报告模式")

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

    # ── Coordinated mode (LLM tool loop) ─────────────────────────

    def _run_coordinated(self, source: str, resume_from: str | None = None) -> str:
        if resume_from:
            if resume_from not in STAGE_ORDER:
                raise ValueError(f"Unknown stage: {resume_from}. Valid: {STAGE_ORDER}")
            self._load_state_for_resume(resume_from)

        task = self._build_task(source, resume_from)

        # Use Agent.run() — the LLM tool-calling loop
        Agent.run(self, task)

        # After the loop ends, render the report
        report_data = self._state["report_data"]
        if report_data is None:
            raise RuntimeError("Coordinator 未能生成报告数据")

        output_path = render_report(report_data.to_dict(), self._report_path())
        self._publish_latest_report(output_path)
        return output_path

    def _build_task(self, source: str, resume_from: str | None) -> str:
        parts = [f"请为以下来源生成完整的学习报告。\n\n来源: {source}"]

        if self.goal:
            parts.append(f"\n用户学习目标: {self.goal}")

        if resume_from:
            parts.append(f"\n注意：从 {resume_from} 阶段恢复执行。之前的阶段数据已加载。")
            if resume_from in ("research", "plan"):
                analysis = self._state.get("analysis")
                if analysis:
                    parts.append(f"已有分析结果，包含 {len(analysis.concepts)} 个概念: {', '.join(analysis.concepts)}")
                    parts.append("请直接调用 research_concepts 开始研究。")
            elif resume_from == "synthesize":
                parts.append("研究数据已加载，请直接调用 synthesize_report。")
        else:
            parts.append("\n请从 analyze_article 开始。")

        return "\n".join(parts)

    def _load_state_for_resume(self, resume_from: str) -> None:
        step_idx = STAGE_ORDER.index(resume_from)

        if step_idx > STAGE_ORDER.index("fetch"):
            self._state["fetch_result"] = FetchResult.from_dict(
                load_stage_output(self._stage_path("fetch"))
            )

        if step_idx > STAGE_ORDER.index("analyze"):
            self._state["analysis"] = AnalysisResult.from_dict(
                load_stage_output(self._stage_path("analyze"))
            )

        if step_idx > STAGE_ORDER.index("plan"):
            plan_path = self._stage_path("plan")
            if os.path.exists(plan_path):
                self._state["plan"] = ResearchPlan.from_dict(load_stage_output(plan_path))

        if step_idx > STAGE_ORDER.index("research"):
            research = ResearchResult.from_dict(
                load_stage_output(self._stage_path("research"))
            )
            self._state["research_result"] = research
            self._state["findings"] = dict(research.findings)

    # ── Tool Handlers ────────────────────────────────────────────

    def _handle_analyze(self, source: str) -> dict:
        # Fetch
        fetch_result = self._fetch(source)
        if isinstance(fetch_result, dict) and "error" in fetch_result:
            return fetch_result
        self._state["fetch_result"] = fetch_result
        save_stage_output(fetch_result.to_dict(), self._stage_path("fetch"))

        # Analyze
        analyzer = Analyzer(self.llm)
        analysis = analyzer.analyze(fetch_result)
        if isinstance(analysis, dict) and "error" in analysis:
            return analysis
        self._state["analysis"] = analysis
        save_stage_output(analysis.to_dict(), self._stage_path("analyze"))

        # Build plan (absorbs Planner role)
        plan = self._build_plan(analysis)
        self._state["plan"] = plan
        save_stage_output(plan.to_dict(), self._stage_path("plan"))

        return {
            "title": analysis.article_title,
            "summary": analysis.article_summary[:200],
            "concepts": analysis.concepts,
            "concept_count": len(analysis.concepts),
            "difficulty": analysis.overview.get("difficulty", "unknown"),
        }

    def _handle_research(self, concepts: list[str], reasoning: str, concept_hints: dict | None = None) -> dict:
        analysis = self._state.get("analysis")
        plan = self._state.get("plan")

        if not analysis:
            return {"error": "请先调用 analyze_article"}

        # Merge caller hints with plan hints
        if plan and concept_hints:
            merged_hints = dict(plan.concept_hints)
            merged_hints.update(concept_hints)
            plan.concept_hints = merged_hints
        elif concept_hints and plan:
            plan.concept_hints = concept_hints

        print(f"\n--- 并行研究 {len(concepts)} 个概念 ---")
        findings = self._research_concepts(concepts, analysis.article_summary, plan)
        print("\n--- 所有概念研究完成 ---")

        self._state["findings"].update(findings)

        research_result = ResearchResult(
            url=analysis.url,
            article_title=analysis.article_title,
            article_summary=analysis.article_summary,
            overview=analysis.overview,
            article_analysis=analysis.article_analysis,
            concepts=analysis.concepts,
            findings=dict(self._state["findings"]),
        )
        self._state["research_result"] = research_result
        save_stage_output(research_result.to_dict(), self._stage_path("research"))

        quality_summary = []
        for name, finding in findings.items():
            n_res = len(finding.get("resources", []))
            has_explanation = bool(finding.get("explanation", "").strip())
            quality_summary.append(f"{name}: {'OK' if has_explanation and n_res > 0 else 'WEAK'} ({n_res} 资料)")

        return {
            "completed": len(findings),
            "total": len(concepts),
            "quality": quality_summary,
        }

    def _handle_review(self) -> dict:
        research = self._state.get("research_result")
        if not research:
            return {"error": "请先调用 research_concepts"}

        reviewer = Reviewer(self.llm)
        review = reviewer.review(research)

        if not review.passed and self._review_cycle < MAX_REVIEW_CYCLES:
            self._review_cycle += 1
            return {
                "passed": False,
                "rework_items": [
                    {"concept": r.concept, "feedback": r.feedback}
                    for r in review.rework
                ],
            }

        return {"passed": True, "rework_items": []}

    def _handle_rework(self, rework_items: list[dict]) -> dict:
        research = self._state.get("research_result")
        plan = self._state.get("plan")
        if not research:
            return {"error": "请先调用 research_concepts"}

        feedback_map = {item["concept"]: item.get("feedback", "") for item in rework_items}
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

        self._state["findings"].update(findings)

        updated_research = ResearchResult(
            url=research.url,
            article_title=research.article_title,
            article_summary=research.article_summary,
            overview=research.overview,
            article_analysis=research.article_analysis,
            concepts=research.concepts,
            findings=dict(self._state["findings"]),
        )
        self._state["research_result"] = updated_research
        save_stage_output(updated_research.to_dict(), self._stage_path("research"))

        return {
            "reworked": len(findings),
            "total_findings": len(self._state["findings"]),
        }

    def _handle_synthesize(self) -> dict:
        research = self._state.get("research_result")
        plan = self._state.get("plan")
        if not research:
            return {"error": "请先完成研究阶段"}

        synthesizer = Synthesizer(self.llm, plan)
        report_data = synthesizer.synthesize(research)
        self._state["report_data"] = report_data
        save_stage_output(report_data.to_dict(), self._stage_path("synthesize"))

        return {
            "title": report_data.title,
            "prerequisites": len(report_data.prerequisites),
            "concepts": len(report_data.concepts),
            "learning_path_steps": len(report_data.learning_path),
        }

    # ── Agent hooks ──────────────────────────────────────────────

    def on_timeout(self, messages: list[dict]) -> dict:
        """Timeout degradation strategy."""
        if self._state.get("report_data"):
            self._log("超时但已有报告数据，标记完成")
            return {"status": "complete", "notes": "timeout with report data"}

        if self._state.get("findings"):
            self._log("超时，强制合成已有研究结果")
            try:
                self._handle_synthesize()
                return {"status": "partial", "notes": "timeout, forced synthesize"}
            except Exception as e:
                self._log(f"强制合成失败: {e}")

        if self._state.get("analysis"):
            self._log("超时，降级为阅读报告")
            analysis = self._state["analysis"]
            report_data = self._build_reading_report(analysis)
            self._state["report_data"] = report_data
            save_stage_output(report_data.to_dict(), self._stage_path("synthesize"))
            return {"status": "partial", "notes": "timeout, degraded to reading report"}

        self._log("超时且无可用数据")
        return {"status": "partial", "notes": "timeout, no data"}

    # ── Fetch helper ─────────────────────────────────────────────

    def _fetch(self, source: str) -> FetchResult | dict:
        try:
            fetcher = get_fetcher(source)
            if isinstance(fetcher, URLFetcher):
                fetcher.quality_checker = make_quality_checker(llm=self.llm)
            return fetcher.fetch(source)
        except FetchError as e:
            return {"error": str(e)}

    # ── Plan builder (absorbs Planner role) ──────────────────────

    def _build_plan(self, analysis: AnalysisResult) -> ResearchPlan:
        plan = get_preset(self.preset)
        plan.goal = self.goal
        # No separate Planner LLM call — Coordinator decides concepts via tools
        return plan

    # ── Research orchestration ───────────────────────────────────

    def _research_concepts(
        self, concepts: list[str], summary: str,
        plan: ResearchPlan | None,
        hint_overrides: dict[str, str] | None = None,
    ) -> dict[str, dict]:
        finding_tool = None
        if plan and plan.finding_schema:
            finding_tool = build_finding_tool(plan.finding_schema)

        finding_schema = plan.finding_schema if plan else None
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

    # ── Storage helpers ──────────────────────────────────────────

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
            print(f"[Coordinator] run_id: {resolved_run_id}")

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
        return cleaned.strip("-") or Coordinator._new_run_id()

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
