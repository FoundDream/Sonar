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
from agents.scout import Scout
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

# ── Coordinator Prompt ───────────────────────────────────────────

COORDINATOR_PROMPT = """\
你是 Sonar 的协调器。你根据文章内容和用户需求自主决策，而不是按固定顺序执行。

## 可用工具

- analyze_article — 抓取并分析文章（URL 或单个文件）
- explore_project — 探索项目目录，生成项目地图（目录输入时使用）
- research_concepts — 并行研究你选定的概念
- review_research — 审查研究质量
- rework_concepts — 返工不合格的概念
- synthesize_report — 合成最终报告
- generate_reading_report — 跳过研究，直接生成阅读报告
- finalize_report — 完成流程（终止）

## 判断 0：使用哪个入口？

- 来源是 URL 或单个文件 → analyze_article
- 来源是项目目录 → explore_project（Scout Agent 会自主探索项目结构和代码）

## 判断 1：分析后 — 需要概念研究吗？

analyze_article 或 explore_project 返回分析结果。你需要判断：
- 文章/项目是否通俗到分析结果已经足够？（科普文、新闻评论通常不需要研究）
- 概念对目标读者来说是否属于常识？
→ 不需要研究：generate_reading_report
→ 需要研究：进入判断 2

## 判断 2：研究哪些概念？怎么研究？

这是你最重要的决策。不要无脑全选，要根据分析结果判断：

**选择概念**：
- 哪些概念对理解文章核心论点（main_thesis）最关键？
- 有用户目标时，哪些与目标最相关？不相关的要排除
- 目标读者（target_audience）已经熟悉的概念不需要研究
- 纯背景性的、不影响理解核心论点的概念可以跳过

**提供 concept_hints**：为每个选中概念写一句话，告诉研究员：
- 这个概念在文章中扮演什么角色（来自 key_insights）
- 应该从什么角度研究
好的 hints 能显著提升研究质量。

## 判断 3：审查后 — 怎么处理？

review_research 返回每个概念的审查反馈。根据问题严重程度判断：
- 解释空白、完全跑题 → rework_concepts（值得返工）
- 措辞欠佳、资料偏少但内容正确 → 直接 synthesize_report（可接受）
- 已返工过 → 不再返工

## 完成

synthesize_report 或 generate_reading_report 后，调用 finalize_report。
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

EXPLORE_PROJECT_TOOL = {
    "type": "function",
    "function": {
        "name": "explore_project",
        "description": "探索项目目录：Scout Agent 自主探索项目结构、读取关键文件，生成项目地图。用于目录输入。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "项目目录路径",
                },
            },
            "required": ["path"],
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

READING_REPORT_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_reading_report",
        "description": "生成快速阅读报告，跳过概念研究。适用于简单文章或分析结果已足够完整的情况。",
        "parameters": {
            "type": "object",
            "properties": {
                "reasoning": {
                    "type": "string",
                    "description": "说明为什么选择跳过研究",
                },
            },
            "required": ["reasoning"],
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
        self.add_tool(EXPLORE_PROJECT_TOOL, handler=self._handle_explore)
        self.add_tool(RESEARCH_TOOL, handler=self._handle_research)
        self.add_tool(REVIEW_TOOL, handler=self._handle_review)
        self.add_tool(REWORK_TOOL, handler=self._handle_rework)
        self.add_tool(SYNTHESIZE_TOOL, handler=self._handle_synthesize)
        self.add_tool(READING_REPORT_TOOL, handler=self._handle_reading_report)
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
        parts = [f"来源: {source}"]

        if os.path.isdir(source):
            parts.append("（这是一个项目目录）")

        if self.goal:
            parts.append(f"\n用户学习目标: {self.goal}")

        if resume_from:
            parts.append(f"\n从 {resume_from} 阶段恢复，之前阶段数据已加载。")
            if resume_from in ("research", "plan"):
                analysis = self._state.get("analysis")
                if analysis:
                    parts.append(f"已有分析: {len(analysis.concepts)} 个概念 — {', '.join(analysis.concepts)}")
            elif resume_from == "synthesize":
                parts.append("研究数据已加载。")

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

        article_analysis = analysis.article_analysis or {}
        result = {
            "title": analysis.article_title,
            "summary": analysis.article_summary,
            "main_thesis": article_analysis.get("main_thesis", ""),
            "key_insights": [
                i.get("title", "") for i in article_analysis.get("key_insights", [])
            ],
            "concepts": analysis.concepts,
            "concept_count": len(analysis.concepts),
            "difficulty": analysis.overview.get("difficulty", "unknown"),
            "recommendation": analysis.overview.get("recommendation", "unknown"),
            "target_audience": analysis.overview.get("target_audience", ""),
        }
        if self.goal:
            result["user_goal"] = self.goal
        return result

    def _handle_explore(self, path: str) -> dict:
        # Fetch directory content
        fetch_result = self._fetch(path)
        if isinstance(fetch_result, dict) and "error" in fetch_result:
            return fetch_result
        self._state["fetch_result"] = fetch_result
        save_stage_output(fetch_result.to_dict(), self._stage_path("fetch"))

        # Scout explores the project
        print("\n--- Scout 探索项目 ---")
        scout = Scout(self.llm)
        project_map = scout.explore(path, goal=self.goal)
        save_stage_output(project_map, self._stage_path("scout"))
        print(f"[Scout] 完成: {len(project_map.get('concepts', []))} 个概念, "
              f"{len(project_map.get('key_files', []))} 个关键文件")

        # Convert to AnalysisResult for downstream compatibility
        key_files = project_map.get("key_files", [])
        analysis = AnalysisResult(
            url=path,
            article_title=project_map.get("project_name", os.path.basename(path)),
            article_summary=project_map.get("description", ""),
            overview={
                "topic": project_map.get("description", "")[:30],
                "target_audience": "开发者",
                "difficulty": "intermediate",
                "recommendation": "deep_read",
            },
            article_analysis={
                "main_thesis": project_map.get("description", ""),
                "key_insights": [
                    {
                        "title": f.get("role", ""),
                        "detail": f.get("path", ""),
                        "why_it_matters": "",
                    }
                    for f in key_files[:4]
                ],
                "supporting_points": [],
                "author_takeaway": project_map.get("architecture", ""),
            },
            concepts=project_map.get("concepts", []),
        )
        self._state["analysis"] = analysis
        save_stage_output(analysis.to_dict(), self._stage_path("analyze"))

        # Build plan
        plan = self._build_plan(analysis)
        self._state["plan"] = plan
        save_stage_output(plan.to_dict(), self._stage_path("plan"))

        result = {
            "project_name": project_map.get("project_name", ""),
            "description": project_map.get("description", ""),
            "architecture": project_map.get("architecture", "")[:200],
            "concepts": project_map.get("concepts", []),
            "concept_count": len(project_map.get("concepts", [])),
            "key_files": len(key_files),
            "entry_points": project_map.get("entry_points", []),
        }
        if self.goal:
            result["user_goal"] = self.goal
        return result

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
        self._review_cycle += 1

        return {
            "passed": review.passed,
            "review_cycle": self._review_cycle,
            "rework_items": [
                {"concept": r.concept, "feedback": r.feedback}
                for r in review.rework
            ] if not review.passed else [],
        }

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

    def _handle_reading_report(self, reasoning: str) -> dict:
        analysis = self._state.get("analysis")
        if not analysis:
            return {"error": "请先调用 analyze_article"}

        print(f"[Coordinator] 生成阅读报告: {reasoning}")
        report_data = self._build_reading_report(analysis)
        self._state["report_data"] = report_data
        save_stage_output(report_data.to_dict(), self._stage_path("synthesize"))

        return {
            "title": report_data.title,
            "sections": [s["type"] for s in report_data.sections],
            "note": "已生成阅读报告，请调用 finalize_report 完成",
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
            verifier = Verifier(self.llm, finding_schema)
            researcher = Researcher(self.llm, verifier, finding_tool, researcher_prompt, finding_schema)
            hints = (hint_overrides or {}).get(concept, base_hints.get(concept, ""))
            result = researcher.research(concept, summary, hints=hints)
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
