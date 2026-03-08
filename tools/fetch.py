"""内容抓取工具：Jina Reader 优先 + Crawl4AI 降级链。

主路径:
  Jina Reader (r.jina.ai) — 干净 markdown，自带 JS 渲染 / 反爬 / PDF 支持

降级路径 (Jina 不可用时):
  Crawl4AI — headless Chromium，处理 JS 渲染 / 反爬站点
  httpx — 轻量 fallback（PDF / 简单静态页）
"""

import asyncio
import os
import re
import time
from urllib.parse import urlparse

import httpx

from tools.extract import extract_content, make_error, smart_truncate

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
}

_MAX_RETRIES = 2
_RETRY_DELAYS = [1, 3]
_MIN_CONTENT_LEN = 100


# ── URL 预处理 ──

_URL_REWRITES: list[tuple[re.Pattern, str, str]] = [
    # Reddit → old.reddit.com（更简单的 HTML，更少反爬）
    (re.compile(r"https?://(www\.)?reddit\.com"), "reddit.com", "old.reddit.com"),
    # Twitter/X → fixupx.com 代理（提供可抓取的元数据）
    (re.compile(r"https?://(www\.)?x\.com"), "x.com", "fixupx.com"),
    (re.compile(r"https?://(www\.)?twitter\.com"), "twitter.com", "fixupx.com"),
]


def _rewrite_url(url: str) -> str:
    """对已知难抓的站点做 URL 重写。"""
    for pattern, old, new in _URL_REWRITES:
        if pattern.match(url):
            # 去掉 www. 前缀再替换，避免双重替换
            new_url = re.sub(r"(https?://)(?:www\.)?" + re.escape(old), r"\1" + new, url, count=1)
            if new_url != url:
                print(f"  [重写] {url} → {new_url}")
            return new_url
    return url


# ── 重试 ──

def _with_retry(fn, *args):
    """retryable error 自动重试，指数退避。"""
    last_err = None
    for attempt in range(_MAX_RETRIES + 1):
        result = fn(*args)
        if not isinstance(result, dict) or "error" not in result:
            return result
        if not result.get("retryable"):
            return result
        last_err = result
        if attempt < _MAX_RETRIES:
            delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
            print(f"  [重试] {delay}s 后第 {attempt + 2} 次尝试...")
            time.sleep(delay)
    return last_err


# ── Jina Reader（主路径）──

def _fetch_jina(url: str) -> dict:
    """Jina Reader: 任意 URL → 干净 markdown。"""
    headers = {"Accept": "application/json"}
    api_key = os.environ.get("JINA_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        resp = httpx.get(
            f"https://r.jina.ai/{url}",
            headers=headers,
            timeout=60,
        )
        resp.raise_for_status()
    except httpx.TimeoutException:
        return make_error("Jina Reader 超时", "timeout", retryable=True)
    except httpx.HTTPError as e:
        return make_error(f"Jina Reader 失败: {e}", "network", retryable=True)

    try:
        data = resp.json().get("data", {})
    except (ValueError, AttributeError):
        return make_error("Jina 返回格式异常", "parse", retryable=False)

    content = data.get("content", "")
    if len(content.strip()) < _MIN_CONTENT_LEN:
        return make_error(
            f"Jina 内容过短({len(content.strip())}字)", "parse", retryable=False,
        )

    return {
        "title": data.get("title", ""),
        "content": content,
        "description": data.get("description", ""),
        "author": "",
        "date": "",
        "method": "jina",
    }


# ── Crawl4AI（降级路径）──

def _fetch_crawl4ai(url: str) -> dict:
    """Crawl4AI: headless Chromium 抓取，处理 JS 渲染和反爬。"""
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    except (ImportError, Exception) as e:
        return make_error(f"crawl4ai 不可用: {e}", "config", retryable=False)

    async def _crawl():
        browser_cfg = BrowserConfig(headless=True, verbose=False)
        run_cfg = CrawlerRunConfig(
            word_count_threshold=50,
            page_timeout=30000,
            wait_until="networkidle",
        )
        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            result = await crawler.arun(url, config=run_cfg)
            return result

    try:
        result = asyncio.run(_crawl())
    except Exception as e:
        return make_error(f"Crawl4AI 失败: {e}", "browser", retryable=False)

    if not result.success:
        return make_error(f"Crawl4AI 抓取失败: {result.error_message}", "browser", retryable=False)

    # 优先用 markdown，fallback 到 extracted content
    content = result.markdown_v2.raw_markdown if hasattr(result, "markdown_v2") and result.markdown_v2 else ""
    if not content:
        content = result.markdown or ""
    if not content:
        content = result.extracted_content or ""

    if len(content.strip()) < _MIN_CONTENT_LEN:
        return make_error(f"Crawl4AI 内容过短({len(content.strip())}字)", "parse", retryable=False)

    title = ""
    if result.metadata:
        title = result.metadata.get("title", "") or ""

    return {
        "title": title,
        "content": content,
        "description": "",
        "author": "",
        "date": "",
        "method": "crawl4ai",
    }


# ── httpx 轻量请求 ──

def _httpx_get(url: str) -> httpx.Response | dict:
    """httpx GET，返回 Response 或 error dict。"""
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=60, headers=_HEADERS)
        resp.raise_for_status()
        return resp
    except httpx.TimeoutException as e:
        return make_error(f"请求超时: {e}", "timeout", retryable=True)
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        if 400 <= code < 500:
            return make_error(f"HTTP {code}: {e}", "http_4xx", retryable=False)
        return make_error(f"HTTP {code}: {e}", "http_5xx", retryable=True)
    except httpx.HTTPError as e:
        return make_error(f"网络错误: {e}", "network", retryable=True)


# ── PDF 提取 ──

def _is_pdf_response(resp: httpx.Response, url: str) -> bool:
    """根据 Content-Type + URL 后缀判断。"""
    ct = resp.headers.get("content-type", "")
    if "application/pdf" in ct:
        return True
    return urlparse(url).path.lower().endswith(".pdf")


def _extract_pdf(data: bytes) -> dict:
    """pymupdf 提取 PDF 文本。"""
    try:
        import pymupdf
    except ImportError:
        return make_error("pymupdf 未安装。安装: uv add pymupdf", "config", retryable=False)
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
        title = (doc.metadata.get("title") or "").strip()
        pages = [page.get_text() for page in doc]
        doc.close()
    except Exception as e:
        return make_error(f"PDF 解析失败: {e}", "parse", retryable=False)

    content = "\n".join(pages)
    if not content.strip():
        return make_error("PDF 无可提取文本（可能是扫描版）", "parse", retryable=False)
    return {"title": title, "content": content, "method": "pdf"}


# ── 降级链 ──

def _is_usable(result: dict, quality_checker=None) -> bool:
    """检查抓取结果是否可用：无 error + 通过质量检查。"""
    if "error" in result:
        return False
    if quality_checker and not quality_checker(result.get("content", "")):
        return False
    return True


def _fetch_fallback(url: str, quality_checker=None) -> dict:
    """降级抓取: 先尝试 httpx(PDF) → Crawl4AI(JS渲染+反爬)。"""
    # 先用轻量 httpx 试一下，主要为了 PDF 检测
    resp = _with_retry(_httpx_get, url)
    httpx_ok = isinstance(resp, httpx.Response)

    if httpx_ok:
        # PDF → pymupdf（PDF 不做质量检查，有文本就行）
        if _is_pdf_response(resp, url):
            print("  [抓取] 检测到 PDF")
            return _extract_pdf(resp.content)

        # HTML → trafilatura
        extracted = extract_content(resp.text, url)
        result = {**extracted, "method": "httpx"}
        if _is_usable(result, quality_checker):
            return result
        print("  [降级] httpx 内容质量不足，尝试 Crawl4AI...")
    else:
        print(f"  [降级] httpx 失败({resp['error_type']})，尝试 Crawl4AI...")

    # Crawl4AI — headless browser
    crawl_result = _fetch_crawl4ai(url)
    if _is_usable(crawl_result, quality_checker):
        return crawl_result

    # Crawl4AI 也失败了，用 httpx 短内容勉强兜底
    if httpx_ok:
        extracted = extract_content(resp.text, url)
        if extracted["content"].strip():
            print("  [警告] Crawl4AI 不可用，使用 httpx 短内容")
            return {**extracted, "method": "httpx"}

    if "error" in crawl_result:
        return crawl_result
    return make_error("所有抓取方式均未获得可用内容", "quality", retryable=False)


# ── 统一入口 ──

def _fetch(url: str, quality_checker=None) -> dict:
    """Jina 优先 → 降级链。返回含 content 的 dict 或 error dict。"""
    # URL 重写
    url = _rewrite_url(url)

    result = _with_retry(_fetch_jina, url)
    if _is_usable(result, quality_checker):
        return result

    reason = result.get("error", "内容质量不足")[:60]
    print(f"  [降级] Jina: {reason}，降级抓取...")

    return _fetch_fallback(url, quality_checker)


# ── 公开接口 ──

def fetch_article(url: str, quality_checker=None) -> dict:
    """抓取文章全文，用于主流程 Analyze 阶段。

    返回 {title, content, author, date, description, word_count, was_truncated, method}
    或 error dict。
    """
    result = _fetch(url, quality_checker)
    if "error" in result:
        return result

    raw = result["content"]
    truncated = smart_truncate(raw, 8000, preserve_ends=True)

    return {
        "title": result.get("title", ""),
        "content": truncated,
        "author": result.get("author", ""),
        "date": result.get("date", ""),
        "description": result.get("description", ""),
        "word_count": len(raw),
        "was_truncated": len(truncated) < len(raw),
        "method": result["method"],
    }


def fetch_resource(url: str) -> dict:
    """抓取资料页面，供 Researcher 判断资料质量。

    返回 {title, content, word_count, method} 或 error dict。
    """
    result = _fetch(url)
    if "error" in result:
        return result

    raw = result["content"]
    truncated = smart_truncate(raw, 2000, preserve_ends=False)

    return {
        "title": result.get("title", ""),
        "content": truncated,
        "word_count": len(raw),
        "method": result["method"],
    }


FETCH_RESOURCE_TOOL = {
    "type": "function",
    "function": {
        "name": "fetch_resource",
        "description": (
            "抓取指定 URL 的内容（截断到 2000 字符）。支持网页和 PDF。"
            "消耗一轮迭代，请先看 search 返回的 snippet，确认值得深入时再调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要抓取的网页或 PDF URL",
                }
            },
            "required": ["url"],
        },
    },
}
