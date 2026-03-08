"""Learning Report Schema V1.2 — 基于 PRD 的字段校验规则。

四个入口：
- validate_concept(data) → 校验 concept_done 返回值（Researcher 产出）
- validate_overview(data) → 校验文章速览（Analyze 产出）
- validate_article_analysis(data) → 校验文章观点拆解（Analyze 产出）
- validate_report(data)  → 校验最终报告
返回 Issue 列表，空列表 = 通过。
"""

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class Issue:
    field: str
    message: str
    severity: str  # "error" = 必须修复, "warning" = 可接受但不理想


# ── 枚举值 ──

VALID_DIFFICULTIES = {"beginner", "intermediate", "advanced"}
VALID_RECOMMENDATIONS = {"deep_read", "skim_first", "learn_prerequisites"}
VALID_PRIORITIES = {"must", "should"}


# ── 资源校验 ──

def validate_resource(r: dict, index: int) -> list[Issue]:
    issues = []
    prefix = f"resources[{index}]"

    title = r.get("title", "")
    if not title or not title.strip():
        issues.append(Issue(f"{prefix}.title", "标题为空", "error"))

    url = r.get("url", "")
    if not url or not url.strip():
        issues.append(Issue(f"{prefix}.url", "URL 为空", "error"))
    elif not url.startswith(("http://", "https://")):
        issues.append(Issue(f"{prefix}.url", f"URL 格式异常: {url[:60]}", "error"))
    else:
        try:
            parsed = urlparse(url)
            if not parsed.netloc:
                issues.append(Issue(f"{prefix}.url", "URL 缺少域名", "error"))
        except Exception:
            issues.append(Issue(f"{prefix}.url", "URL 解析失败", "error"))

    return issues


# ── 概念校验（concept_done 返回值）──

MIN_EXPLANATION_CHARS = 50
MIN_RESOURCES = 1
MAX_RESOURCES = 2


def _validate_concept_base(data: dict, why_field: str, why_label: str) -> list[Issue]:
    """校验概念的通用字段：name、explanation、why_*、resources。"""
    issues = []

    name = data.get("name", "")
    if not name or not name.strip():
        issues.append(Issue("name", "概念名称为空", "error"))

    explanation = data.get("explanation", "")
    if not explanation or not explanation.strip():
        issues.append(Issue("explanation", "解释为空", "error"))
    elif len(explanation.strip()) < MIN_EXPLANATION_CHARS:
        issues.append(Issue(
            "explanation",
            f"解释过短（{len(explanation.strip())} 字符，最少 {MIN_EXPLANATION_CHARS}）",
            "warning",
        ))

    why = data.get(why_field, "")
    if not why or not why.strip():
        issues.append(Issue(why_field, f"{why_label}为空", "warning"))

    article_role = data.get("article_role", "")
    if "article_role" in data and (not article_role or not article_role.strip()):
        issues.append(Issue("article_role", "缺少该概念在本文中的角色说明", "warning"))

    example = data.get("example", "")
    analogy = data.get("analogy", "")
    if "example" in data and (not example or not example.strip()) and (not analogy or not analogy.strip()):
        issues.append(Issue("example", "缺少例子或类比，解释可能不够直观", "warning"))

    resources = data.get("resources", [])
    if len(resources) < MIN_RESOURCES:
        issues.append(Issue(
            "resources",
            f"资料不足（{len(resources)} 条，最少 {MIN_RESOURCES}）",
            "error",
        ))
    elif len(resources) > MAX_RESOURCES:
        issues.append(Issue(
            "resources",
            f"资料过多（{len(resources)} 条，最多 {MAX_RESOURCES}），请精选最好的 {MAX_RESOURCES} 条",
            "warning",
        ))

    for i, r in enumerate(resources):
        issues.extend(validate_resource(r, i))

    urls = [r.get("url", "") for r in resources if r.get("url")]
    if len(urls) != len(set(urls)):
        issues.append(Issue("resources", "存在重复 URL", "error"))

    return issues


def validate_concept(data: dict) -> list[Issue]:
    """校验单个核心概念（Researcher 产出 / 报告中的 concepts 条目）。"""
    return _validate_concept_base(data, "why_important", "重要性说明")


def validate_prerequisite(data: dict) -> list[Issue]:
    """校验单个前置知识条目（字段是 why_learn_first 而非 why_important）。"""
    return _validate_concept_base(data, "why_learn_first", "先学理由")


# ── 文章速览校验 ──

def validate_overview(data: dict) -> list[Issue]:
    """校验 overview 字段。"""
    issues = []

    if not data:
        issues.append(Issue("overview", "文章速览为空", "error"))
        return issues

    topic = data.get("topic", "")
    if not topic or not topic.strip():
        issues.append(Issue("overview.topic", "主题概括为空", "error"))

    audience = data.get("target_audience", "")
    if not audience or not audience.strip():
        issues.append(Issue("overview.target_audience", "适合人群为空", "warning"))

    difficulty = data.get("difficulty", "")
    if difficulty not in VALID_DIFFICULTIES:
        issues.append(Issue(
            "overview.difficulty",
            f"难度值无效: '{difficulty}'，应为 {VALID_DIFFICULTIES}",
            "warning",
        ))

    recommendation = data.get("recommendation", "")
    if recommendation not in VALID_RECOMMENDATIONS:
        issues.append(Issue(
            "overview.recommendation",
            f"建议值无效: '{recommendation}'，应为 {VALID_RECOMMENDATIONS}",
            "warning",
        ))

    return issues


def validate_article_analysis(data: dict) -> list[Issue]:
    """校验 article_analysis 字段。"""
    issues = []

    if not data:
        issues.append(Issue("article_analysis", "文章核心观点拆解为空", "error"))
        return issues

    thesis = data.get("main_thesis", "")
    if not thesis or not thesis.strip():
        issues.append(Issue("article_analysis.main_thesis", "核心论点为空", "error"))

    key_insights = data.get("key_insights", [])
    if len(key_insights) < 2:
        issues.append(Issue(
            "article_analysis.key_insights",
            f"关键洞见不足（{len(key_insights)} 条，最少 2）",
            "warning",
        ))
    for i, item in enumerate(key_insights):
        if not item.get("title", "").strip():
            issues.append(Issue(f"article_analysis.key_insights[{i}].title", "洞见标题为空", "warning"))
        if not item.get("detail", "").strip():
            issues.append(Issue(f"article_analysis.key_insights[{i}].detail", "洞见展开为空", "warning"))
        if not item.get("why_it_matters", "").strip():
            issues.append(Issue(f"article_analysis.key_insights[{i}].why_it_matters", "缺少洞见重要性说明", "warning"))

    supporting_points = data.get("supporting_points", [])
    if len(supporting_points) < 2:
        issues.append(Issue(
            "article_analysis.supporting_points",
            f"支撑论点不足（{len(supporting_points)} 条，最少 2）",
            "warning",
        ))
    for i, item in enumerate(supporting_points):
        if not item.get("claim", "").strip():
            issues.append(Issue(f"article_analysis.supporting_points[{i}].claim", "主张为空", "warning"))
        if not item.get("evidence", "").strip():
            issues.append(Issue(f"article_analysis.supporting_points[{i}].evidence", "论据为空", "warning"))

    takeaway = data.get("author_takeaway", "")
    if not takeaway or not takeaway.strip():
        issues.append(Issue("article_analysis.author_takeaway", "作者结论为空", "warning"))

    return issues


# ── 报告校验 ──

MIN_SUMMARY_CHARS = 80
MIN_PREREQUISITES = 2
MAX_PREREQUISITES = 4
MIN_CONCEPTS = 3
MAX_CONCEPTS = 5


def validate_report(data: dict) -> list[Issue]:
    """校验最终组装的报告，返回问题列表。"""
    issues = []

    title = data.get("title", "")
    if not title or not title.strip():
        issues.append(Issue("title", "报告标题为空", "error"))

    # overview
    issues.extend(validate_overview(data.get("overview")))

    # summary
    summary = data.get("summary", "")
    if not summary or not summary.strip():
        issues.append(Issue("summary", "摘要为空", "error"))
    elif len(summary.strip()) < MIN_SUMMARY_CHARS:
        issues.append(Issue(
            "summary",
            f"摘要过短（{len(summary.strip())} 字符，最少 {MIN_SUMMARY_CHARS}）",
            "warning",
        ))

    # article_analysis
    issues.extend(validate_article_analysis(data.get("article_analysis")))

    # prerequisites 数量
    prerequisites = data.get("prerequisites", [])
    if len(prerequisites) < MIN_PREREQUISITES:
        issues.append(Issue(
            "prerequisites",
            f"前置知识不足（{len(prerequisites)} 个，最少 {MIN_PREREQUISITES}）",
            "warning",
        ))
    elif len(prerequisites) > MAX_PREREQUISITES:
        issues.append(Issue(
            "prerequisites",
            f"前置知识过多（{len(prerequisites)} 个，最多 {MAX_PREREQUISITES}）",
            "warning",
        ))

    # concepts 数量
    concepts = data.get("concepts", [])
    if not concepts:
        issues.append(Issue("concepts", "核心概念为空", "error"))
    elif len(concepts) < MIN_CONCEPTS:
        issues.append(Issue(
            "concepts",
            f"核心概念不足（{len(concepts)} 个，最少 {MIN_CONCEPTS}）",
            "warning",
        ))
    elif len(concepts) > MAX_CONCEPTS:
        issues.append(Issue(
            "concepts",
            f"核心概念过多（{len(concepts)} 个，最多 {MAX_CONCEPTS}）",
            "warning",
        ))

    # 校验每个前置知识（用 validate_prerequisite，检查 why_learn_first）
    for item in prerequisites:
        prereq_issues = validate_prerequisite(item)
        label = item.get("name", "?")
        for pi in prereq_issues:
            issues.append(Issue(f"prereq[{label}].{pi.field}", pi.message, pi.severity))
        # priority 枚举校验
        priority = item.get("priority", "")
        if priority and priority not in VALID_PRIORITIES:
            issues.append(Issue(
                f"prereq[{label}].priority",
                f"优先级无效: '{priority}'，应为 {VALID_PRIORITIES}",
                "warning",
            ))

    # 校验每个核心概念（用 validate_concept，检查 why_important）
    for item in concepts:
        concept_issues = validate_concept(item)
        label = item.get("name", "?")
        for ci in concept_issues:
            issues.append(Issue(f"concept[{label}].{ci.field}", ci.message, ci.severity))

    # learning_path：检查非空 + 锚点引用有效性
    all_concept_names = {item.get("name", "") for item in prerequisites} | {item.get("name", "") for item in concepts}
    learning_path = data.get("learning_path", [])
    if not learning_path:
        issues.append(Issue("learning_path", "缺少学习路径", "warning"))
    for i, step in enumerate(learning_path):
        if not step.get("goal", "").strip():
            issues.append(Issue(f"learning_path[{i}].goal", "缺少学习目标", "warning"))
        if not step.get("reason", "").strip():
            issues.append(Issue(f"learning_path[{i}].reason", "缺少排序原因", "warning"))
        refs = step.get("concepts", [])
        for ref in refs:
            if ref not in all_concept_names:
                issues.append(Issue(
                    f"learning_path[{i}].concepts",
                    f"引用了不存在的概念 '{ref}'，会产生死链接",
                    "warning",
                ))

    return issues


# ── 动态 Finding 校验 ──

def validate_finding(data: dict, field_specs: list) -> list[Issue]:
    """按 FieldSpec 列表校验 finding 数据。

    field_specs: list of FieldSpec (from models)
    """
    issues = []

    for spec in field_specs:
        value = data.get(spec.name)

        if spec.required:
            if spec.type == "array":
                if not value or not isinstance(value, list) or len(value) == 0:
                    issues.append(Issue(spec.name, f"{spec.description} 为空", "error"))
                    continue
            elif spec.type == "string":
                if not value or not str(value).strip():
                    issues.append(Issue(spec.name, f"{spec.description} 为空", "error"))
                    continue

        if spec.type == "string" and spec.min_length > 0 and value:
            if len(str(value).strip()) < spec.min_length:
                issues.append(Issue(
                    spec.name,
                    f"内容过短（{len(str(value).strip())} 字符，最少 {spec.min_length}）",
                    "warning",
                ))

        if spec.name == "resources" and isinstance(value, list):
            for i, r in enumerate(value):
                issues.extend(validate_resource(r, i))
            urls = [r.get("url", "") for r in value if r.get("url")]
            if len(urls) != len(set(urls)):
                issues.append(Issue("resources", "存在重复 URL", "error"))

    return issues


def has_errors(issues: list[Issue]) -> bool:
    return any(i.severity == "error" for i in issues)


def format_issues(issues: list[Issue]) -> str:
    if not issues:
        return "All checks passed."
    lines = []
    for i in issues:
        icon = "x" if i.severity == "error" else "!"
        lines.append(f"  [{icon}] {i.field}: {i.message}")
    return "\n".join(lines)
