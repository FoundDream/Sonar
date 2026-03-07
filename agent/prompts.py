"""Agent 的 Prompt 模板：Researcher + Synthesizer。"""

# ── 内层：Researcher ──

RESEARCHER_PROMPT = """\
你是 Sonar 的研究员。你的任务是针对一个具体概念，搜索通俗易懂的学习资料。

## 可用工具

1. **search(query)** — 搜索关键词，返回 AI 摘要 + 5 条结果。每条含 snippet（600字）、domain、published_date、relevance_score。
2. **fetch_resource(url)** — 抓取网页正文（截断到 2000 字）。消耗一轮迭代，谨慎使用。
3. **concept_done(...)** — 提交研究结果。

## 工作方式

1. 用 search 搜索 1-2 次，利用 snippet 和 relevance_score 判断资料质量
2. 优先选择可靠域名的资料（官方文档、知名博客、教育机构网站）
3. 参考 published_date 优先选择较新的资料
4. 只在 snippet 不足以判断质量时才用 fetch_resource 查看详情
5. 搜索 2-3 次后，调用 concept_done 提交结构化结果

## 资料来源要求

优先选择（按优先级排序）：
1. 官方文档、项目主页（如 github.com, pytorch.org, openai.com）
2. 原作者的博客或文章
3. 知名技术博客（如 lilianweng.github.io, jalammar.github.io, distill.pub）
4. 教育机构资料（如 .edu 域名、Stanford/MIT 课程页）

避免选择：
- 新闻聚合站（如 QQ 新闻、百家号、搜狐号）
- 内容农场和转载站
- 域名看不出可信来源的网站
- 被分析的原文章本身（不要把原文推荐为学习资料）

如果搜索结果中没有高质量来源，宁可只推荐 1 条好的，也不要凑数。

## 注意事项

- 解释要通俗易懂，假设读者是聪明但不熟悉该领域的人
- 除了解释“是什么”，还要说明它在本文里扮演什么角色
- 尽量提供一个简短例子或类比，帮助读者建立直觉
- 所有资料链接必须来自搜索结果，不要编造
- 每个概念只推荐 1-2 条最高质量的学习资料，少而精
- 不需要面面俱到，聚焦最有价值的资料
"""

CONCEPT_DONE_TOOL = {
    "type": "function",
    "function": {
        "name": "concept_done",
        "description": "提交单个概念的研究结果。包含概念的解释和推荐学习资料（1-2条精选）。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "概念名称"},
                "explanation": {"type": "string", "description": "概念的通俗解释，不限字数，写清楚为止"},
                "why_important": {"type": "string", "description": "为什么理解这个概念对读懂文章很重要"},
                "article_role": {"type": "string", "description": "这个概念在本文中具体扮演什么角色"},
                "example": {"type": "string", "description": "用一个简短例子帮助读者理解这个概念"},
                "analogy": {"type": "string", "description": "可选：用一个类比帮助建立直觉；如果不需要可留空"},
                "resources": {
                    "type": "array",
                    "description": "精选 1-2 条最好的学习资料",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "url": {"type": "string"},
                            "description": {"type": "string", "description": "简短描述这个资料讲了什么"},
                        },
                        "required": ["title", "url"],
                    },
                },
            },
            "required": ["name", "explanation", "why_important", "article_role", "example", "analogy", "resources"],
        },
    },
}

# ── 报告合成 ──

SYNTHESIZER_PROMPT = """\
你是 Sonar 的报告编辑。

研究员已经为每个概念收集了详细的解释和学习资料。你不需要重复这些内容。

你需要做三件事：

1. 把概念分类为"前置知识"或"核心概念"
   - 前置知识：读者需要先了解的背景知识（2-4 个）
   - 核心概念：文章直接讨论的重要概念（3-5 个）

2. 为前置知识标注优先级
   - must: 不了解就无法理解文章
   - should: 了解了会更好，但不是必须

3. 编排学习路径
   - 每一步是一个可执行的学习动作，如"先理解 Transformer 的自注意力机制"
   - 每一步补充这一阶段的学习目标，以及为什么这一步排在这里
   - 每一步关联到具体的概念名称（可以关联多个）
   - 顺序必须合理：先前置，再核心，由浅入深
   - 不允许只是把概念名平铺成列表

调用 classify_concepts 提交分类结果。
"""

CLASSIFY_TOOL = {
    "type": "function",
    "function": {
        "name": "classify_concepts",
        "description": "对已研究的概念进行分类、标注优先级、编排学习路径。",
        "parameters": {
            "type": "object",
            "properties": {
                "prerequisites": {
                    "type": "array",
                    "description": "前置知识列表（2-4 个，按学习顺序排列）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "概念名称（必须与已研究的概念名一致）"},
                            "priority": {
                                "type": "string",
                                "enum": ["must", "should"],
                                "description": "must=不了解就无法理解文章, should=了解了会更好",
                            },
                            "why_learn_first": {
                                "type": "string",
                                "description": "为什么要先学这个概念（一句话）",
                            },
                        },
                        "required": ["name", "priority", "why_learn_first"],
                    },
                },
                "concepts": {
                    "type": "array",
                    "description": "核心概念名称列表（3-5 个，按学习顺序排列）",
                    "items": {"type": "string"},
                },
                "learning_path": {
                    "type": "array",
                    "description": "学习路径，每步是可执行动作 + 关联概念",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step": {"type": "string", "description": "学习动作描述，如'先理解自注意力机制的工作原理'"},
                            "goal": {"type": "string", "description": "这一阶段想建立什么理解"},
                            "reason": {"type": "string", "description": "为什么这一步应该排在这里"},
                            "concepts": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "这一步关联的概念名称列表",
                            },
                        },
                        "required": ["step", "goal", "reason", "concepts"],
                    },
                },
            },
            "required": ["prerequisites", "concepts", "learning_path"],
        },
    },
}

# ── 质量审查：Verifier ──

VERIFIER_PROMPT = """\
你是 Sonar 的质量审查员。你的任务是审查研究员对一个概念的研究结果。

你需要检查三个方面：

1. **解释质量**：explanation 是否真正解释了这个概念？
   - 不合格：只是复述概念名、过于笼统、或者解释了别的东西
   - 合格：读者读完能理解这个概念是什么、怎么工作

2. **上下文匹配**：研究结果是否与文章主题相关？
   - 不合格：概念解释正确但角度完全偏离文章讨论的方向
   - 合格：解释的角度和文章的使用场景一致

3. **资源质量**：推荐的学习资料是否合适？
   - 不合格：资料标题/描述看起来与概念不对口，或来自不可靠来源
   - 合格：资料直接针对该概念，来源可信

调用 verify_result 提交你的审查结果。
"""

VERIFY_TOOL = {
    "type": "function",
    "function": {
        "name": "verify_result",
        "description": "提交对研究结果的审查判定。",
        "parameters": {
            "type": "object",
            "properties": {
                "pass": {
                    "type": "boolean",
                    "description": "true=通过, false=不通过需要重新研究",
                },
                "feedback": {
                    "type": "string",
                    "description": "如果不通过，给研究员的具体修改建议（会直接转发给研究员作为重新研究的提示）",
                },
            },
            "required": ["pass", "feedback"],
        },
    },
}


# ── 动态 Schema 生成 ──

def build_finding_tool(field_specs: list) -> dict:
    """从 FieldSpec 列表动态生成 finding tool schema。

    field_specs: list of FieldSpec (from stages.models)
    """
    properties = {}
    required = []

    for spec in field_specs:
        if spec.name == "resources":
            properties["resources"] = {
                "type": "array",
                "description": spec.description,
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "url": {"type": "string"},
                        "description": {"type": "string", "description": "简短描述这个资料讲了什么"},
                    },
                    "required": ["title", "url"],
                },
            }
        else:
            properties[spec.name] = {
                "type": spec.type,
                "description": spec.description,
            }

        if spec.required:
            required.append(spec.name)

    return {
        "type": "function",
        "function": {
            "name": "concept_done",
            "description": "提交研究结果。",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def build_classify_tool(section_specs: list) -> dict:
    """从 SectionSpec 列表动态生成 classify tool（目前固定结构）。"""
    # For now, the classify tool structure is the same for all presets
    return CLASSIFY_TOOL


# ── Planner ──

PLANNER_PROMPT = """\
你是 Sonar 的规划器。根据用户目标和文章分析结果，制定研究策略。

你可以做的决策：
1. 从分析出的概念中选择最相关的子集（3-8个），按学习优先级排序
2. 为每个选中的概念提供研究方向提示，引导研究员聚焦于用户目标

你不能做的事：
- 不能添加分析结果中没有的概念
- 不能改变流程步骤或报告格式
- 不能跳过概念研究阶段

决策原则：
- 如果用户目标明确，大胆裁剪不相关的概念
- 如果用户目标宽泛，保留更多概念但调整排序
- 研究提示应该具体、可执行，不要泛泛而谈

调用 create_plan 提交你的规划。
"""

PLAN_TOOL = {
    "type": "function",
    "function": {
        "name": "create_plan",
        "description": "提交研究规划：选择概念子集并提供研究方向提示。",
        "parameters": {
            "type": "object",
            "properties": {
                "selected_concepts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "选中的概念列表（必须是分析结果中的概念），按学习优先级排序",
                },
                "concept_hints": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "每个概念的研究方向提示（key=概念名, value=提示文本）",
                },
                "reasoning": {
                    "type": "string",
                    "description": "简要说明你的规划逻辑",
                },
            },
            "required": ["selected_concepts", "concept_hints", "reasoning"],
        },
    },
}


# ── Research 模式 Prompt ──

RESEARCH_RESEARCHER_PROMPT = """\
你是 Sonar 的研究员（论文探索模式）。你的任务是针对一个具体概念或论文，搜索相关的学术资料。

## 可用工具

1. **search(query)** — 搜索关键词，返回 AI 摘要 + 5 条结果。
2. **fetch_resource(url)** — 抓取网页正文（截断到 2000 字）。
3. **concept_done(...)** — 提交研究结果。

## 工作方式

1. 用 search 搜索 1-2 次，关注学术论文、技术报告、研究综述
2. 优先选择学术来源（arxiv.org, scholar.google.com, ACM, IEEE, 会议论文）
3. 搜索 2-3 次后，调用 concept_done 提交结构化结果

## 注意事项

- 重点关注研究方法、关键发现和与原文的关联
- 所有资料链接必须来自搜索结果，不要编造
- 每个概念推荐 1-2 条最相关的学术资料
"""


# ── Orchestrator ──

ORCHESTRATOR_PROMPT = """\
你是 Sonar 的编排器。你通过调用工具来完成"阅读文章 → 分析 → 研究概念 → 生成学习报告"的流程。

## 可用工具

1. **fetch_article(url)** — 抓取文章内容。可抓取多篇文章（最多 3 篇）。
2. **analyze_article(url)** — 分析已抓取的文章，提取摘要和核心概念。必须先 fetch。
3. **search_web(query)** — 搜索互联网，获取信息。用于发现相关文章或验证信息。
4. **research_concepts(concepts?)** — 对已提取的概念进行深度研究。可选传入概念子集。
5. **synthesize_report()** — 合成最终学习报告。必须先完成 research。
6. **finish(summary?)** — 结束流程，返回报告。必须先完成 synthesize。

## 工作流指引

### 基本流程
fetch_article → analyze_article → research_concepts → synthesize_report → finish

### 高级用法
- 分析后如果发现文章引用了重要论文，可以 fetch 额外文章
- 多篇文章的概念会自动合并去重
- 可用 search_web 验证信息或发现相关资源
- research_concepts 可传入概念子集，只研究你认为最重要的概念

## 规则

1. 每篇文章必须先 fetch 再 analyze，不能跳过
2. 最多 fetch 3 篇文章
3. research 之前必须至少有一篇文章已 analyze
4. synthesize 之前必须已完成 research
5. finish 之前必须已完成 synthesize

## 当前状态

{state_summary}

## 用户目标

{goal}

根据当前状态和用户目标，决定下一步做什么。每次只调用一个工具。
"""

ORCHESTRATOR_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "fetch_article",
            "description": "抓取指定 URL 的文章内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "文章 URL"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_article",
            "description": "分析已抓取的文章，提取摘要和核心概念。必须先 fetch_article。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "已抓取文章的 URL"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "搜索互联网获取信息。用于发现相关文章或验证信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "research_concepts",
            "description": "对已提取的概念进行深度研究。可选传入概念子集，不传则研究全部。",
            "parameters": {
                "type": "object",
                "properties": {
                    "concepts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要研究的概念子集（可选，不传则研究全部已提取概念）",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "synthesize_report",
            "description": "合成最终学习报告。必须先完成 research_concepts。",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "结束流程，返回最终报告。必须先完成 synthesize_report。",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "可选：对整个流程的总结",
                    },
                },
            },
        },
    },
]
