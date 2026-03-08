## Sonar

输入文章 URL 或本地文件，自动生成结构化学习报告。适用于任何类型的文章（技术博客、学术论文、教程等）。

## Quickstart

```bash
# 1) 安装依赖
uv sync

# 2) 配置环境变量
cp .env.example .env

# 3) 分析网页文章（概念解读，默认模式）
uv run main.py https://example.com/some-article

# 4) 分析本地文件（支持 .pdf / .md / .txt / .html）
uv run main.py ./paper.pdf
```

## 报告模式

| 模式                       | 说明                                   | 流程                                           | 成本             |
| -------------------------- | -------------------------------------- | ---------------------------------------------- | ---------------- |
| `--mode reading`           | 快速摘要：核心论点、关键洞见           | Fetch → Analyze → 渲染                         | 2 次 LLM，无搜索 |
| `--mode explain`（默认）   | 完整学习报告：概念解释、学习路径、延伸阅读 | Fetch → Analyze → Plan → Research → Synthesize | 多次 LLM + 搜索  |

## CLI 用法

输入可以是 URL 或本地文件路径：

```bash
# 完整学习报告（默认，适合任何类型的文章）
uv run main.py <URL或文件>

# 快速摘要（摘要 + 观点拆解，不做概念研究）
uv run main.py <URL或文件> --mode reading
```

额外选项：

```bash
# 自定义学习目标（LLM 会据此筛选和排序概念）
uv run main.py <URL或文件> --goal "我想理解这篇文章里的系统设计权衡"
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

本地内容质量分类器依赖较重（`torch`/`transformers`），默认不安装。只执行 `uv sync` 也可以正常运行，程序会自动降级到 LLM 质量检查；如果想启用本地分类器，再额外安装：

```bash
uv sync --extra local-classifier
```

## 架构

```
main.py (CLI)
  → pipeline.py (编排)
      → fetchers/          输入层：BaseFetcher 接口 + 路由
      │   local_file.py      本地文件 (.pdf/.md/.txt/.html)
      │   url.py             URL (Jina → Crawl4AI → httpx 降级链)
      → stages/            处理层：Analyze → Plan → Research → Synthesize
      → report/            输出层：HTML 渲染
```

扩展新输入类型（如 YouTube、GitHub 仓库）：在 `fetchers/` 下新建文件实现 `BaseFetcher`，注册到 `fetchers/__init__.py` 即可。

## 开发与贡献

```bash
# 安装开发依赖
uv sync --group dev

# 运行测试与 lint
uv run pytest
uv run ruff check tests
```
