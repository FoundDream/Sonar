# Sonar — CLAUDE.md

## 规则

每次修改代码后，如果涉及架构、模式、CLI 接口、文件职责的变动，必须同步更新：

- `CLAUDE.md`（架构和 checklist）
- `README.md`（用法说明）

## 项目概述

输入文章 URL 或本地文件，自动生成结构化学习/阅读报告的 AI pipeline 工具。

## 开发命令

```bash
uv run pytest              # 运行全部测试
uv run pytest -m "not network"  # 仅本地文件测试（不需要网络）
uv run ruff check .        # lint
uv run main.py <url>       # 运行（默认 explain 模式）
```

## 架构

### 数据流

```
Pipeline (orchestrator)
  ├─ fetch ──────────── fetchers/
  ├─ Analyzer ───────── agents/analyzer.py
  ├─ Planner ────────── agents/planner.py
  ├─ Researcher × N ─── agents/researcher.py (并行 + Verifier 审查)
  ├─ Reviewer ───────── agents/reviewer.py
  │   └─ 未通过? → 回到 Researcher.rework()
  └─ Synthesizer ────── agents/synthesizer.py → report/
```

- `reading` 模式跳过 Plan / Research / Synthesize，直接 fetch → Analyzer → 渲染
- `explain`（默认）走完整流程，适用于任何类型的文章（博客、论文、教程等）

每个阶段的输出保存在 `output/runs/<run_id>/<stage>.json`，支持 `--resume-from <stage>` 断点恢复。

### 两种模式

| `--mode`   | 适用场景             | 流程                          |
| ---------- | -------------------- | ----------------------------- |
| `reading`  | 快速摘要，无概念研究 | fetch → Analyzer → 渲染      |
| `explain`  | 完整学习报告（默认） | 完整 pipeline                 |

统一的 preset 配置在 `presets.py`，finding schema 包含核心字段（explanation, why_important, example 等）和可选扩展字段（methodology, key_findings），研究员按内容类型自适应填写。

### 关键文件

| 文件                       | 职责                                                            |
| -------------------------- | --------------------------------------------------------------- |
| `main.py`                  | CLI 入口，定义 `--mode` 的合法值                                |
| `pipeline.py`              | Orchestrator：调度 agents，review↔research 循环，并行研究编排  |
| `models.py`                | 数据模型（FetchResult, AnalysisResult, ResearchPlan, ...）     |
| `presets.py`               | 统一 preset 配置：finding schema、sections、prompt             |
| `agents/base.py`           | Agent 基类：统一的 LLM 工具调用循环                             |
| `agents/analyzer.py`       | Analyzer — 分析文章，提取摘要、速览、核心概念                   |
| `agents/planner.py`        | Planner — 根据用户目标筛选概念、生成研究提示                    |
| `agents/researcher.py`     | Researcher — 搜索资料、研究单个概念                             |
| `agents/verifier.py`       | Verifier — 审查单个概念的研究质量                               |
| `agents/reviewer.py`       | Reviewer — LLM-powered 报告级质量审查                          |
| `agents/synthesizer.py`    | Synthesizer — 概念分类、组装报告数据                            |
| `fetchers/`                | 输入源抽象层：`BaseFetcher` ABC + 路由 + `fetch_source()`     |
| `fetchers/base.py`         | `BaseFetcher` 接口、`FetchError` 异常                          |
| `fetchers/url.py`          | `URLFetcher` — 包装 `tools/fetch.fetch_article()`              |
| `fetchers/local_file.py`   | `LocalFileFetcher` — 本地文件读取（pdf/md/txt/html）           |
| `tools/llm.py`             | LLMClient — OpenAI / Bedrock 统一接口                          |
| `tools/fetch.py`           | 网页抓取：Jina → Crawl4AI → httpx 三级回退                    |
| `tools/search.py`          | 搜索：Tavily / DuckDuckGo                                     |
| `tools/quality.py`         | `make_quality_checker()` — 小模型优先、LLM 兜底的内容质量判断 |
| `tools/classify.py`        | DeBERTa 小模型内容分类（可选依赖 `local-classifier`）         |
| `report/`                  | HTML 渲染 + 报告数据校验                                       |

### Agent 文件结构

每个 agent 是一个独立的 `.py` 文件，包含 prompt + tool schema + class：

```
agents/<name>.py   # PROMPT + TOOL_SCHEMA + Agent class
```

## 修改 checklist

### 新增 agent

1. `agents/<name>.py` — 创建包含 prompt、tool schema、Agent class 的单文件
2. `agents/__init__.py` — 添加 export
3. `pipeline.py` — 在 `_execute_step` 中集成

### 新增输入源类型

1. `fetchers/` 下新建 `xxx.py`，实现 `BaseFetcher`（`can_handle` + `fetch`）
2. `fetchers/__init__.py` — 在 `FETCHERS` 列表中注册

### 修改 prompt / schema

- 各 agent 的 prompt 和 tool schema 直接在对应的 `agents/<name>.py` 文件中修改
- Finding schema → `presets.py` 的 `_finding_schema()` 函数
- `concept_done` tool 由 `agents/researcher.py` 中的 `build_finding_tool(plan.finding_schema)` 动态生成

## 输出目录结构

```
output/
  report.html              # 最新报告的快捷方式
  latest_run.txt           # 最近 run_id（用于 --resume-from）
  runs/<run_id>/
    fetch.json
    analyze.json
    plan.json
    research.json
    synthesize.json
    report.html
```
