"""Research 阶段：并行研究概念 + 质量审查。"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from llm.client import LLMClient
from report.schema import format_issues, validate_concept
from stages.models import AnalysisResult, ResearchPlan, ResearchResult
from stages.prompts.research import RESEARCHER_PROMPT
from stages.prompts.schemas import CONCEPT_DONE_TOOL, build_finding_tool
from stages.prompts.verify import VERIFIER_PROMPT, VERIFY_TOOL
from tools.fetch import FETCH_RESOURCE_TOOL, fetch_resource
from tools.search import SEARCH_TOOL, search

TOOL_REGISTRY = {
    "search": search,
    "fetch_resource": fetch_resource,
}

MAX_RESEARCHER_ITERATIONS = 5
MAX_VERIFY_RETRIES = 1

EMPTY_FINDING = {
    "name": "",
    "explanation": "",
    "why_important": "",
    "article_role": "",
    "example": "",
    "analogy": "",
    "resources": [],
}


class ConceptResearcher:
    """内层 Agent：独立 context 研究单个概念。"""

    def __init__(self, llm: LLMClient, finding_tool: dict | None = None,
                 researcher_prompt: str | None = None):
        self.llm = llm
        self.finding_tool = finding_tool or CONCEPT_DONE_TOOL
        self.finding_tool_name = self.finding_tool["function"]["name"]
        self.researcher_prompt = researcher_prompt or RESEARCHER_PROMPT

    def research(self, concept: str, article_summary: str, hints: str = "") -> dict:
        messages = [
            {"role": "system", "content": self.researcher_prompt},
            {"role": "user", "content": self._build_task(concept, article_summary, hints)},
        ]

        tools = [SEARCH_TOOL, FETCH_RESOURCE_TOOL, self.finding_tool]
        best_result: dict | None = None

        for i in range(MAX_RESEARCHER_ITERATIONS):
            print(f"  [研究员] 第 {i + 1} 轮")
            resp = self.llm.chat(messages, tools=tools)
            messages.append(resp)

            if resp.get("content"):
                print(f"  [思考] {resp['content'][:80]}...")

            if "tool_calls" not in resp:
                continue

            for tc in resp["tool_calls"]:
                name = tc["function"]["name"]
                raw_args = tc["function"]["arguments"]
                call_id = tc["id"]

                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError as e:
                    print(f"  [错误] {name} 参数 JSON 解析失败: {e}")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": f"JSON 解析失败: {e}。请重新调用，确保参数是合法 JSON。",
                    })
                    continue

                if name == self.finding_tool_name:
                    issues = validate_concept(args)
                    errors = [iss for iss in issues if iss.severity == "error"]

                    if not errors:
                        print(f"  [完成] 提交了 {concept} 的研究结果")
                        return args

                    best_result = args
                    feedback = (
                        "结果未通过质量检查，请修正后重新调用 concept_done:\n"
                        + format_issues(errors)
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": feedback,
                    })
                    print(f"  [校验] {concept} 未通过（{len(errors)} 个问题），要求修正")
                    continue

                print(f"  [工具] {name}({json.dumps(args, ensure_ascii=False)[:60]})")

                func = TOOL_REGISTRY.get(name)
                if func is None:
                    tool_result = {"error": f"未知工具: {name}"}
                else:
                    tool_result = func(**args)

                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(tool_result, ensure_ascii=False),
                })

                result_str = json.dumps(tool_result, ensure_ascii=False)
                print(f"  [结果] {result_str[:100]}...")

        if best_result:
            print(f"  [警告] {concept} 使用未完全通过校验的结果")
            return best_result
        return self._force_result(concept, messages)

    def _build_task(self, concept: str, article_summary: str, hints: str) -> str:
        parts = [f"请研究以下概念，找到通俗易懂的学习资料：\n\n**概念**: {concept}"]
        if article_summary:
            parts.append(f"\n**文章背景**:\n{article_summary[:500]}")
        if hints:
            parts.append(f"\n**搜索建议**: {hints}")
        parts.append("\n搜索 2-3 次后，调用 concept_done 提交你的研究结果（精选 1-2 条最好的资料）。")
        return "\n".join(parts)

    def _force_result(self, concept: str, messages: list[dict]) -> dict:
        messages.append({
            "role": "user",
            "content": "时间到了，请立刻调用 concept_done 提交你目前的研究结果。",
        })
        resp = self.llm.chat(messages, tools=[self.finding_tool])
        if "tool_calls" in resp:
            for tc in resp["tool_calls"]:
                if tc["function"]["name"] == self.finding_tool_name:
                    return json.loads(tc["function"]["arguments"])
        return {"name": concept, "explanation": "", "why_important": "", "resources": []}


class ConceptVerifier:
    """审查 Researcher 产出的内容质量。"""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def verify(self, result: dict, article_summary: str) -> dict:
        messages = [
            {"role": "system", "content": VERIFIER_PROMPT},
            {"role": "user", "content": self._build_review(result, article_summary)},
        ]
        resp = self.llm.chat(messages, tools=[VERIFY_TOOL])

        if "tool_calls" in resp:
            for tc in resp["tool_calls"]:
                if tc["function"]["name"] == "verify_result":
                    try:
                        return json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError as e:
                        print(f"  [审查] 警告: verify_result 参数解析失败: {e}")

        print("  [审查] 警告: Verifier 未正常调用 verify_result，视为未通过")
        return {"pass": False, "feedback": "Verifier 调用异常，请重新研究并改进结果质量。"}

    def _build_review(self, result: dict, article_summary: str) -> str:
        resources_text = ""
        for r in result.get("resources", []):
            resources_text += f"  - {r.get('title', '?')} ({r.get('url', '?')})\n"
            if r.get("description"):
                resources_text += f"    {r['description']}\n"

        return f"""请审查以下研究结果：

**概念**: {result.get('name', '?')}

**文章背景**: {article_summary[:400]}

**研究员的解释**: {result.get('explanation', '(空)')}

**为什么重要**: {result.get('why_important', '(空)')}

**推荐资料**:
{resources_text or '(无)'}

请调用 verify_result 提交审查结果。如果不通过，在 feedback 里具体说明哪里有问题、应该怎么改。"""


class ResearchStage:
    """并行研究所有概念。"""

    def __init__(self, llm: LLMClient, plan: ResearchPlan | None = None):
        self.llm = llm
        self.plan = plan
        self._finding_tool = None
        if plan and plan.finding_schema:
            self._finding_tool = build_finding_tool(plan.finding_schema)

    def run(self, analysis: AnalysisResult) -> ResearchResult:
        # Use plan's selected concepts if available, otherwise fall back to analysis
        if self.plan and self.plan.selected_concepts:
            concepts = self.plan.selected_concepts
        else:
            concepts = analysis.concepts
        summary = analysis.article_summary

        print(f"\n--- 并行研究 {len(concepts)} 个概念 ---")

        researcher_prompt = self.plan.researcher_prompt if self.plan else None
        concept_hints = self.plan.concept_hints if self.plan else {}

        def _research_one(concept: str) -> tuple[str, dict]:
            researcher = ConceptResearcher(self.llm, self._finding_tool, researcher_prompt)
            verifier = ConceptVerifier(self.llm)

            hints = concept_hints.get(concept, "")
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
                    print(f"  [审查] {concept}: 重试后仍未通过，丢弃结果")
                    result = dict(EMPTY_FINDING, name=concept)

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
