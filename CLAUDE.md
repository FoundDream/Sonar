# Sonar — CLAUDE.md

## 规则

每次修改代码后，如果涉及架构、模式、CLI 接口、文件职责的变动，必须同步更新：

- `CLAUDE.md`（架构和 checklist）
- `README.md`（用法说明）

## 项目概述

输入文章 URL、本地文件或项目目录，自动生成结构化学习/阅读报告的 AI multi-agent 工具。

## 开发命令

```bash
uv run pytest              # 运行全部测试
uv run pytest -m "not network"  # 仅本地文件测试（不需要网络）
uv run ruff check .        # lint
uv run main.py <url>       # 运行（默认 explain 模式）
uv run main.py ./project/  # 分析项目目录
```

## 架构

### 数据流

```
main.py
  ├── reading mode → Coordinator._run_reading(source)
  │                    └─ Fetch + Analyze → 渲染（无 LLM 协调）
  └── explain mode → Coordinator._run_coordinated(source)
                       ├── LLM 判断输入类型
                       │   ├─ URL/文件 → analyze_article → Fetch + Analyzer
                       │   └─ 项目目录 → explore_project → Scout Agent（文件系统探索）
                       ├── LLM 决策 → research_concepts（选概念 + hints）
                       │                └─ 并行 Researcher × N + Verifier
                       ├── LLM 决策 → review_research → Reviewer
                       ├── LLM 决策 → rework / accept / synthesize
                       ├── LLM 决策 → synthesize_report → Synthesizer
                       └── finalize_report [terminal] → 渲染 HTML
```

### Agent 能力矩阵

| Agent | 独特工具 | 不可替代的能力 |
|-------|---------|---------------|
| Scout | get_tree, list_directory, read_file, search_in_files | 文件系统探索、项目结构理解 |
| Researcher | search, fetch_resource | Web 搜索、外部资料获取 |
| Analyzer | — (LLM 直调) | 文章内容结构化分析 |
| Verifier | — (LLM 直调) | 单概念研究质量审查 |
| Reviewer | — (LLM 直调) | 报告级质量审查 |
| Synthesizer | — (LLM 直调) | 概念分类、学习路径编排 |
| Coordinator | 协调所有 agent 的 7 个工具 | 自主决策：入口选择、概念筛选、质量判断 |

### 两种模式

| `--mode`   | 适用场景             | 流程                                       |
| ---------- | -------------------- | ------------------------------------------ |
| `reading`  | 快速摘要，无概念研究 | fetch → Analyzer → 渲染（无 LLM 协调）    |
| `explain`  | 完整学习报告（默认） | Coordinator LLM tool loop 协调完整流程     |

### 三种输入

| 输入类型 | Fetcher | Coordinator 入口工具 |
|---------|---------|---------------------|
| URL | URLFetcher | analyze_article |
| 本地文件 (.pdf/.md/.txt/.html) | LocalFileFetcher | analyze_article |
| 项目目录 | DirectoryFetcher | explore_project → Scout |

### 关键文件

| 文件                       | 职责                                                            |
| -------------------------- | --------------------------------------------------------------- |
| `main.py`                  | CLI 入口                                                        |
| `agents/coordinator.py`    | Coordinator Agent：LLM 协调器，8 个工具，存储/resume/渲染     |
| `agents/scout.py`          | Scout Agent：文件系统探索，生成项目地图                        |
| `agents/analyzer.py`       | Analyzer — 分析文章，提取摘要、速览、核心概念                   |
| `agents/researcher.py`     | Researcher — 搜索资料、研究单个概念                             |
| `agents/verifier.py`       | Verifier — 审查单个概念的研究质量                               |
| `agents/reviewer.py`       | Reviewer — LLM-powered 报告级质量审查                          |
| `agents/synthesizer.py`    | Synthesizer — 概念分类、组装报告数据                            |
| `agents/base.py`           | Agent 基类：统一的 LLM 工具调用循环                             |
| `models.py`                | 数据模型（FetchResult, AnalysisResult, ResearchPlan, ...）     |
| `presets.py`               | 统一 preset 配置：finding schema、sections、prompt             |
| `fetchers/`                | 输入源抽象层：BaseFetcher ABC + 路由                           |
| `fetchers/directory.py`    | DirectoryFetcher — 项目目录读取                                |
| `fetchers/local_file.py`   | LocalFileFetcher — 本地文件读取                                |
| `fetchers/url.py`          | URLFetcher — URL 抓取                                          |
| `tools/filesystem.py`      | 文件系统工具：get_tree, list_directory, read_file, search_in_files |
| `tools/llm.py`             | LLMClient — OpenAI / Bedrock 统一接口                          |
| `tools/fetch.py`           | 网页抓取：Jina → Crawl4AI → httpx 三级回退                    |
| `tools/search.py`          | 搜索：Tavily / DuckDuckGo                                     |
| `tools/quality.py`         | 小模型优先、LLM 兜底的内容质量判断                             |
| `report/`                  | HTML 渲染 + 报告数据校验                                       |

### Coordinator 工具

| 工具 | 类型 | 内部调用 | 返回给 LLM |
|------|------|----------|------------|
| `analyze_article(source)` | 非终止 | Fetch + Analyzer | 标题、摘要、概念、难度、目标受众 |
| `explore_project(path)` | 非终止 | DirectoryFetcher + Scout | 项目描述、架构、概念、关键文件 |
| `research_concepts(concepts, hints)` | 非终止 | 并行 Researcher + Verifier | 完成数、质量摘要 |
| `review_research()` | 非终止 | Reviewer | passed + 返工列表 |
| `rework_concepts(rework_items)` | 非终止 | 并行 Researcher + Verifier | 同 research |
| `synthesize_report()` | 非终止 | Synthesizer | 报告概况 |
| `generate_reading_report(reasoning)` | 非终止 | 直接构建 | 跳过研究 |
| `finalize_report(status, notes)` | **终止** | — | Agent 循环结束 |

### Coordinator 决策点

1. **入口选择**：URL/文件 → analyze_article；项目目录 → explore_project
2. **是否研究**：简单内容可直接 generate_reading_report
3. **概念选择**：根据文章分析 + 用户目标筛选子集，提供 concept_hints
4. **审查判断**：根据问题严重程度决定返工、接受、或直接合成

## 修改 checklist

### 新增 agent

1. `agents/<name>.py` — 创建包含 prompt、tool schema、Agent class 的单文件
2. `agents/__init__.py` — 添加 export
3. `agents/coordinator.py` — 添加对应的 tool schema + handler，注册到 Coordinator

### 新增输入源类型

1. `fetchers/` 下新建 `xxx.py`，实现 `BaseFetcher`（`can_handle` + `fetch`）
2. `fetchers/__init__.py` — 在 `FETCHERS` 列表中注册
3. 如需 Coordinator 特殊处理，在 `coordinator.py` 添加入口工具

### 新增 Agent 工具

1. `tools/<name>.py` — 实现函数 + 定义 tool schema
2. 在对应 agent 中注册

### 修改 prompt / schema

- 各 agent 的 prompt 和 tool schema 在对应的 `agents/<name>.py` 文件中修改
- Coordinator 的 prompt 和 tool schemas 在 `agents/coordinator.py` 中修改
- Finding schema → `presets.py` 的 `_finding_schema()` 函数

## 输出目录结构

```
output/
  report.html              # 最新报告的快捷方式
  latest_run.txt           # 最近 run_id（用于 --resume-from）
  runs/<run_id>/
    fetch.json
    scout.json             # 仅项目目录输入时
    analyze.json
    plan.json
    research.json
    synthesize.json
    report.html
```
