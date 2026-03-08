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

### Pipeline 阶段

```
Fetch → Analyze → Plan → Research → Synthesize → render_report
```

- `reading` 模式跳过 Plan / Research / Synthesize，直接 Fetch → Analyze → 渲染
- `explain` / `academic` 模式走完整流程

每个阶段的输出保存在 `output/runs/<run_id>/<stage>.json`，支持 `--resume-from <stage>` 断点恢复。

### 三种模式

| `--mode`   | 适用场景             | 流程                          |
| ---------- | -------------------- | ----------------------------- |
| `reading`  | 快速摘要，无概念研究 | Fetch → Analyze → 渲染       |
| `explain`  | 技术博客/教程        | 完整 pipeline（默认）         |
| `academic` | 学术论文             | 完整 pipeline，学术侧 preset |

`explain` / `academic` 各有对应的 preset 配置（`presets.py`），mode 名 = preset 名，无额外映射。

### 关键文件

| 文件                   | 职责                                                                  |
| ---------------------- | --------------------------------------------------------------------- |
| `main.py`              | CLI 入口，定义 `--mode` 的合法值                                      |
| `pipeline.py`          | 编排 stages，mode 直接作为 preset 名传入                              |
| `fetchers/`            | 输入源抽象层：`BaseFetcher` ABC + 路由注册                           |
| `fetchers/base.py`     | `BaseFetcher` 接口、`FetchError` 异常                                |
| `fetchers/url.py`      | `URLFetcher` — 包装 `tools/fetch.fetch_article()`                    |
| `fetchers/local_file.py` | `LocalFileFetcher` — 本地文件读取（pdf/md/txt/html）               |
| `stages/fetch.py`      | `FetchStage` — 调 `get_fetcher().fetch()`，注入质量检查器            |
| `tools/quality.py`     | `make_quality_checker()` — 小模型优先、LLM 兜底的内容质量判断       |
| `tools/classify.py`    | DeBERTa 小模型内容分类（可选依赖 `local-classifier`）               |
| `presets.py`           | `explain` / `academic` preset 的 schema、sections 和 prompt 覆盖配置 |
| `stages/prompts/`      | 按 stage 拆分的默认 prompt 和 tool schema                             |
| `stages/models.py`     | 各阶段输入输出的数据模型                                              |
| `stages/research.py`   | 并行概念研究 + Verifier 质量审查                                      |
| `stages/synthesize.py` | 概念分类、组装报告数据                                                |
| `report/`              | HTML 渲染                                                             |

## 修改 checklist

### 新增输入源类型

1. `fetchers/` 下新建 `xxx.py`，实现 `BaseFetcher`（`can_handle` + `fetch`）
2. `fetchers/__init__.py` — 在 `FETCHERS` 列表中注册

### 新增 mode

1. `main.py` — 在 `--mode` 的 `choices` 里加新值
2. `presets.py` — 添加同名 preset 配置
4. `README.md` — 更新报告模式表格和 CLI 用法

### 修改 prompt / schema

- Plan prompt / tool → `stages/prompts/plan.py`
- Researcher prompt → `stages/prompts/research.py`；如需按 preset 覆盖，再改 `presets.py`
- Verifier prompt / tool → `stages/prompts/verify.py`
- Synthesizer prompt / classify tool → `stages/prompts/synthesize.py`；如需按 preset 覆盖，再改 `presets.py`
- Finding schema → `presets.py` 的 `_*_finding_schema()` 函数
- `concept_done` tool 由 `stages/prompts/schemas.py` 中的 `build_finding_tool(plan.finding_schema)` 动态生成

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
