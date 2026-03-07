"""联网搜索工具：支持 Tavily / DuckDuckGo 双后端，通过 SEARCH_BACKEND 环境变量切换。"""

import os
from urllib.parse import urlparse

from tools.extract import make_error

# ── 后端选择 ──

SEARCH_BACKEND = os.environ.get("SEARCH_BACKEND", "tavily").lower()

# 硬过滤：新闻聚合、内容农场、转载站 — 最终报告中直接移除
BLOCKED_DOMAINS = {
    "news.qq.com", "new.qq.com", "baijiahao.baidu.com", "www.sohu.com",
    "www.163.com", "www.toutiao.com", "www.thepaper.cn",
    "53ai.com", "www.53ai.com",
}

# 降权：质量参差不齐 — 搜索结果中标记 warning，但不从最终报告中移除
WARN_DOMAINS = {
    "blog.csdn.net",
    "www.jianshu.com",
    "mp.weixin.qq.com",
}


def _tag_quality(item: dict, domain: str) -> None:
    """为搜索结果标记质量警告。"""
    if domain in BLOCKED_DOMAINS:
        item["quality_warning"] = "低质量来源（新闻聚合/内容农场），建议忽略"
    elif domain in WARN_DOMAINS:
        item["quality_warning"] = "该来源质量参差不齐，请仔细判断内容质量"


def _parse_domain(url: str) -> str:
    if not url:
        return ""
    try:
        return urlparse(url).netloc
    except Exception:
        return ""


# ── Tavily 后端 ──

_tavily_client = None


def _get_tavily_client():
    global _tavily_client
    if _tavily_client is None:
        from tavily import TavilyClient
        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            raise ValueError("未设置 TAVILY_API_KEY 环境变量")
        _tavily_client = TavilyClient(api_key=api_key)
    return _tavily_client


def _search_tavily(query: str) -> dict:
    try:
        client = _get_tavily_client()
    except ValueError as e:
        return make_error(str(e), "config", retryable=False)

    try:
        raw = client.search(
            query=query,
            search_depth="advanced",
            max_results=5,
            include_answer="advanced",
        )
    except Exception as e:
        err_str = str(e).lower()
        if "api key" in err_str or "unauthorized" in err_str or "401" in err_str:
            return make_error(f"认证失败: {e}", "config", retryable=False)
        if "invalid" in err_str or "400" in err_str:
            return make_error(f"参数错误: {e}", "parse", retryable=False)
        return make_error(f"搜索失败: {e}", "network", retryable=True)

    results = []
    for r in raw.get("results", []):
        url = r.get("url", "")
        domain = _parse_domain(url)
        item = {
            "title": r.get("title", ""),
            "url": url,
            "snippet": r.get("content", "")[:600],
            "domain": domain,
            "published_date": r.get("published_date"),
            "relevance_score": r.get("score"),
        }
        _tag_quality(item, domain)
        results.append(item)

    answer = raw.get("answer")
    return {
        "answer": answer[:800] if answer else None,
        "results": results,
    }


# ── DuckDuckGo 后端 ──

def _search_duckduckgo(query: str) -> dict:
    try:
        from ddgs import DDGS
    except ImportError:
        return make_error("未安装 ddgs，请运行: uv add ddgs", "config", retryable=False)

    try:
        raw = DDGS().text(query, max_results=5)
    except Exception as e:
        return make_error(f"DuckDuckGo 搜索失败: {e}", "network", retryable=True)

    results = []
    for r in raw:
        url = r.get("href", "")
        domain = _parse_domain(url)
        item = {
            "title": r.get("title", ""),
            "url": url,
            "snippet": r.get("body", "")[:600],
            "domain": domain,
            "published_date": None,
            "relevance_score": None,
        }
        _tag_quality(item, domain)
        results.append(item)

    return {
        "answer": None,
        "results": results,
    }


# ── 统一入口 ──

def search(query: str) -> dict:
    """搜索指定关键词，返回 AI 摘要 + 5 条结果（含完整元数据）。"""
    if SEARCH_BACKEND == "duckduckgo":
        return _search_duckduckgo(query)
    return _search_tavily(query)


SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search",
        "description": "搜索指定关键词，返回 AI 摘要和 5 条结果。每条结果含 snippet（600字）、domain、published_date、relevance_score。优先参考 snippet 内容和 relevance_score 判断资料质量。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
            },
            "required": ["query"],
        },
    },
}
