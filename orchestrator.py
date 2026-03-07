"""Orchestrator：LLM 驱动的 ReAct 循环，替代固定 pipeline。"""

import json
from dataclasses import dataclass, field

from agent.prompts import ORCHESTRATOR_PROMPT, ORCHESTRATOR_TOOLS
from llm.client import LLMClient
from stages.analyze import AnalyzeStage
from stages.fetch import FetchStage
from stages.models import (
    AnalysisResult,
    FetchResult,
    ReportData,
    ResearchPlan,
    ResearchResult,
)
from stages.plan import PlanStage
from stages.research import ResearchStage
from stages.synthesize import SynthesizeStage
from tools.search import search

MAX_ITERATIONS = 15
MAX_ARTICLES = 3
_DONE_SENTINEL = "DONE"


@dataclass
class OrchestratorState:
    """累积所有阶段结果的状态容器。"""
    primary_url: str
    preset: str = "beginner"
    goal: str = ""

    fetched: dict[str, FetchResult] = field(default_factory=dict)
    analyses: dict[str, AnalysisResult] = field(default_factory=dict)
    all_concepts: list[str] = field(default_factory=list)

    plan: ResearchPlan | None = None
    research_result: ResearchResult | None = None
    report_data: ReportData | None = None

    actions_taken: list[str] = field(default_factory=list)

    def summary_for_llm(self) -> str:
        lines = []

        # Fetched articles
        if self.fetched:
            lines.append(f"已抓取 {len(self.fetched)} 篇文章:")
            for url, fr in self.fetched.items():
                lines.append(f"  - {fr.title or url} ({fr.word_count} 字)")
        else:
            lines.append("尚未抓取任何文章。")

        # Analyses
        if self.analyses:
            lines.append(f"已分析 {len(self.analyses)} 篇文章:")
            for url, ar in self.analyses.items():
                lines.append(f"  - {ar.article_title or url}: {len(ar.concepts)} 个概念")
        else:
            lines.append("尚未分析任何文章。")

        # Concepts
        if self.all_concepts:
            lines.append(f"已提取概念 ({len(self.all_concepts)}): {', '.join(self.all_concepts)}")

        # Research
        if self.research_result:
            n = len(self.research_result.findings)
            lines.append(f"已完成概念研究: {n} 个概念")
        else:
            lines.append("尚未进行概念研究。")

        # Report
        if self.report_data:
            lines.append("已合成报告。")
        else:
            lines.append("尚未合成报告。")

        # Action log (last 5)
        if self.actions_taken:
            recent = self.actions_taken[-5:]
            lines.append("最近操作: " + " → ".join(recent))

        return "\n".join(lines)


# ── Tool functions ──

def tool_fetch(state: OrchestratorState, llm: LLMClient, url: str) -> str:
    if len(state.fetched) >= MAX_ARTICLES:
        return f"已达到最大抓取数 ({MAX_ARTICLES})，无法继续抓取。"
    if url in state.fetched:
        return f"已抓取过该文章: {state.fetched[url].title or url}"

    stage = FetchStage()
    result = stage.run(url)
    if isinstance(result, dict) and "error" in result:
        return f"抓取失败: {result['error']}"

    state.fetched[url] = result
    state.actions_taken.append(f"fetch({url[:40]})")
    return f"抓取成功: {result.title} ({result.word_count} 字)"


def tool_analyze(state: OrchestratorState, llm: LLMClient, url: str) -> str:
    if url not in state.fetched:
        return f"错误: 必须先 fetch_article({url})，再 analyze。"
    if url in state.analyses:
        return f"已分析过该文章，概念: {', '.join(state.analyses[url].concepts)}"

    stage = AnalyzeStage(llm)
    result = stage.run(state.fetched[url])
    if isinstance(result, dict) and "error" in result:
        return f"分析失败: {result['error']}"

    state.analyses[url] = result

    # Merge concepts (deduplicated)
    existing = set(state.all_concepts)
    for c in result.concepts:
        if c not in existing:
            state.all_concepts.append(c)
            existing.add(c)

    state.actions_taken.append(f"analyze({url[:40]})")
    return (
        f"分析完成: {result.article_title}\n"
        f"摘要: {result.article_summary[:200]}\n"
        f"概念 ({len(result.concepts)}): {', '.join(result.concepts)}\n"
        f"当前全部概念 ({len(state.all_concepts)}): {', '.join(state.all_concepts)}"
    )


def tool_search_web(state: OrchestratorState, llm: LLMClient, query: str) -> str:
    result = search(query)
    state.actions_taken.append(f"search({query[:30]})")

    if "error" in result:
        return f"搜索失败: {result['error']}"

    lines = []
    if result.get("answer"):
        lines.append(f"AI 摘要: {result['answer'][:300]}")
    for i, r in enumerate(result.get("results", []), 1):
        lines.append(f"{i}. {r['title']} — {r['url']}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet'][:150]}")
    return "\n".join(lines) or "无搜索结果"


def tool_research(state: OrchestratorState, llm: LLMClient, concepts: list[str] | None = None) -> str:
    if not state.analyses:
        return "错误: 必须先分析至少一篇文章。"

    # Build a merged AnalysisResult from all analyses
    primary = next(iter(state.analyses.values()))
    merged_summary = "\n\n".join(
        f"[{ar.article_title}] {ar.article_summary}"
        for ar in state.analyses.values()
    )

    target_concepts = concepts if concepts else list(state.all_concepts)
    if not target_concepts:
        return "错误: 没有可研究的概念。请先 analyze_article。"

    # Create plan
    plan_stage = PlanStage(llm)
    plan = plan_stage.run(state.preset, state.goal, primary)
    state.plan = plan

    # Build a combined AnalysisResult for ResearchStage
    combined = AnalysisResult(
        url=primary.url,
        article_title=primary.article_title,
        article_summary=merged_summary,
        overview=primary.overview,
        article_analysis=primary.article_analysis,
        concepts=target_concepts,
    )

    stage = ResearchStage(llm, plan)
    result = stage.run(combined)
    state.research_result = result

    state.actions_taken.append(f"research({len(target_concepts)} concepts)")
    return f"研究完成: {len(result.findings)} 个概念已研究"


def tool_synthesize(state: OrchestratorState, llm: LLMClient) -> str:
    if not state.research_result:
        return "错误: 必须先完成 research_concepts。"

    stage = SynthesizeStage(llm, state.plan)
    report_data = stage.run(state.research_result)
    state.report_data = report_data

    state.actions_taken.append("synthesize")
    return f"报告合成完成: {report_data.title}"


def tool_finish(state: OrchestratorState, llm: LLMClient, summary: str = "") -> str:
    if not state.report_data:
        return "错误: 必须先完成 synthesize_report。"

    state.actions_taken.append("finish")
    if summary:
        print(f"[Orchestrator] 总结: {summary}")
    return _DONE_SENTINEL


_TOOL_DISPATCH = {
    "fetch_article": lambda state, llm, args: tool_fetch(state, llm, args["url"]),
    "analyze_article": lambda state, llm, args: tool_analyze(state, llm, args["url"]),
    "search_web": lambda state, llm, args: tool_search_web(state, llm, args["query"]),
    "research_concepts": lambda state, llm, args: tool_research(state, llm, args.get("concepts")),
    "synthesize_report": lambda state, llm, args: tool_synthesize(state, llm),
    "finish": lambda state, llm, args: tool_finish(state, llm, args.get("summary", "")),
}


# ── Orchestrator class ──

class Orchestrator:
    def __init__(self, llm: LLMClient, preset: str = "beginner", goal: str = ""):
        self.llm = llm
        self.preset = preset
        self.goal = goal

    def run(self, url: str) -> ReportData:
        state = OrchestratorState(
            primary_url=url,
            preset=self.preset,
            goal=self.goal,
        )

        goal_text = self.goal or f"分析文章并生成学习报告（{self.preset} 模式）"

        messages = [
            {"role": "system", "content": ORCHESTRATOR_PROMPT.format(
                state_summary=state.summary_for_llm(),
                goal=goal_text,
            )},
            {"role": "user", "content": f"请开始处理这篇文章: {url}"},
        ]

        for iteration in range(MAX_ITERATIONS):
            print(f"\n[Orchestrator] 第 {iteration + 1} 轮")

            # Update system prompt with latest state
            messages[0] = {
                "role": "system",
                "content": ORCHESTRATOR_PROMPT.format(
                    state_summary=state.summary_for_llm(),
                    goal=goal_text,
                ),
            }

            resp = self.llm.chat(messages, tools=ORCHESTRATOR_TOOLS)
            messages.append(resp)

            if resp.get("content"):
                print(f"[Orchestrator] 思考: {resp['content'][:120]}")

            if "tool_calls" not in resp:
                # No tool calls — nudge LLM
                if state.report_data:
                    # Report is ready, nudge to finish
                    messages.append({
                        "role": "user",
                        "content": "报告已合成完成，请调用 finish 结束流程。",
                    })
                else:
                    messages.append({
                        "role": "user",
                        "content": "请调用工具继续处理。根据当前状态，选择下一步操作。",
                    })
                continue

            # Process tool calls
            done = False
            for tc in resp["tool_calls"]:
                name = tc["function"]["name"]
                call_id = tc["id"]

                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError as e:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": f"参数解析失败: {e}",
                    })
                    continue

                print(f"[Orchestrator] 调用工具: {name}({json.dumps(args, ensure_ascii=False)[:80]})")

                handler = _TOOL_DISPATCH.get(name)
                if handler is None:
                    result = f"未知工具: {name}"
                else:
                    result = handler(state, self.llm, args)

                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result,
                })

                if result == _DONE_SENTINEL:
                    done = True
                    break

            if done:
                break
        else:
            print(f"[Orchestrator] 达到最大迭代次数 ({MAX_ITERATIONS})")
            # Force synthesize and finish if we have research but no report
            if state.research_result and not state.report_data:
                tool_synthesize(state, self.llm)
            if not state.report_data:
                raise RuntimeError("Orchestrator 未能在限定轮次内完成报告")

        return state.report_data
