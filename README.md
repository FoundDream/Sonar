## Sonar

输入文章 URL，自动抓取内容并生成结构化报告。支持两种模式：快速阅读报告和深度概念学习报告。

## Quickstart

```bash
# 1) 安装依赖
uv sync

# 2) 配置环境变量
cp .env.example .env

# 3) 快速阅读报告（摘要 + 观点拆解，不研究概念）
uv run main.py https://example.com/some-article --mode reading

# 4) 深度学习报告（概念研究 + 学习路径）
uv run main.py https://example.com/some-article
```

## 报告模式

| 模式 | 说明 | 流程 | 成本 |
| --- | --- | --- | --- |
| `--mode reading` | 阅读报告：摘要、核心论点、关键洞见 | Fetch → Analyze → 渲染 | 2 次 LLM，无搜索 |
| `--mode learning`（默认） | 学习报告：概念解释、学习资料、学习路径 | Fetch → Analyze → Plan → Research → Synthesize | 多次 LLM + 搜索 |

## CLI 用法

```bash
# 阅读报告（摘要 + 观点拆解）
uv run main.py <URL> --mode reading

# 学习报告（默认，概念研究 + 学习路径）
uv run main.py <URL>
```

Learning 模式下的额外选项：

```bash
# 学术论文导向（关注方法论/关键发现/相关论文）
uv run main.py <URL> --preset research

# 自定义学习目标（LLM 会据此筛选和排序概念）
uv run main.py <URL> --goal "我想理解这篇文章里的系统设计权衡"
```

断点恢复：

```bash
# 从 analyze 阶段恢复（默认使用最近一次 run）
uv run main.py --resume-from analyze

# 指定 run_id 恢复
uv run main.py --run-id 20260307-demo --resume-from research
```

## 输出目录

- 每次运行输出到 `output/runs/<run_id>/`
- 阶段快照：`fetch.json / analyze.json / plan.json / research.json / synthesize.json`
- 报告：`report.html`
- `output/report.html` 始终指向最近一次结果

## 分层调试

### Learning 模式

```
Fetch -> Analyze -> Plan -> Research -> Synthesize
```

| 改了什么         | 怎么测                     | 成本        |
| ---------------- | -------------------------- | ----------- |
| 模板/CSS         | `--resume-from synthesize` | 无 LLM/搜索 |
| 报告组装逻辑     | `--resume-from synthesize` | 无 LLM/搜索 |
| 研究/合成 prompt | `--resume-from analyze`    | LLM + 搜索  |
| 全流程           | 直接跑 URL                 | 全部        |

### Reading 模式

```
Fetch -> Analyze -> 渲染
```

| 改了什么     | 怎么测                                          | 成本     |
| ------------ | ----------------------------------------------- | -------- |
| 模板/CSS     | `--mode reading --resume-from synthesize`       | 无 LLM   |
| 分析 prompt  | `--mode reading --resume-from analyze`          | 1 次 LLM |
| 全流程       | `--mode reading` + URL                          | 2 次 LLM |

## 配置

### LLM（OpenAI 兼容）

```env
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o
```

### Amazon Bedrock（OpenAI 兼容网关）

```env
OPENAI_BASE_URL=https://bedrock-mantle.<region>.api.aws/v1
OPENAI_MODEL=us.anthropic.claude-3-7-sonnet-20250219-v1:0
AWS_BEARER_TOKEN_BEDROCK=...
```

### 搜索后端

```env
# Tavily（默认）
TAVILY_API_KEY=tvly-xxx

# DuckDuckGo（无需 API key，适合开发）
SEARCH_BACKEND=duckduckgo
```

## 可选依赖

本地内容质量分类器依赖较重（`torch`/`transformers`），默认不安装：

```bash
uv sync --extra local-classifier
```

## 开发与贡献

```bash
# 安装开发依赖
uv sync --group dev

# 运行测试与 lint
uv run pytest
uv run ruff check tests
```
