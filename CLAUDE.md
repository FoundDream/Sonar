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

### 模式与 preset 的映射关系

CLI `--mode` 是用户接口，内部 `preset` 是实现细节：

| CLI `--mode` | 内部 preset  | 适用场景            |
|--------------|-------------|---------------------|
| `reading`    | —（不用）    | 快速摘要，无概念研究 |
| `explain`    | `beginner`  | 技术博客/教程        |
| `academic`   | `research`  | 学术论文             |

映射在 `pipeline.py` 的 `_MODE_TO_PRESET` 中维护。

### 关键文件

| 文件 | 职责 |
|------|------|
| `main.py` | CLI 入口，定义 `--mode` 的合法值 |
| `pipeline.py` | 编排 stages，`_MODE_TO_PRESET` 维护模式映射 |
| `presets.py` | `beginner` / `research` preset 的 schema 和 prompt 配置 |
| `agent/prompts.py` | 所有 LLM prompt 和 tool schema |
| `stages/models.py` | 各阶段输入输出的数据模型 |
| `stages/research.py` | 并行概念研究 + Verifier 质量审查 |
| `stages/synthesize.py` | 概念分类、组装报告数据 |
| `report/` | HTML 渲染 |

## 修改 checklist

### 新增 mode

1. `main.py` — 在 `--mode` 的 `choices` 里加新值
2. `pipeline.py` — 在 `_MODE_TO_PRESET` 里加映射
3. `presets.py` — 如需新 preset，添加对应配置
4. `README.md` — 更新报告模式表格和 CLI 用法

### 修改 prompt / schema

- Researcher prompt → `agent/prompts.py` 或 `presets.py`（research 模式）
- Synthesizer prompt → `presets.py`（research 模式）/ `agent/prompts.py`（beginner 模式）
- Finding schema → `presets.py` 的 `_*_finding_schema()` 函数
- `concept_done` tool 由 `build_finding_tool(plan.finding_schema)` 动态生成

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
