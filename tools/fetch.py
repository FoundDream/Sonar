"""内容抓取工具：Jina Reader 优先 + 本地降级链。

主路径:
  Jina Reader (r.jina.ai) — 干净 markdown，自带 JS 渲染 / 反爬 / PDF 支持

降级路径 (Jina 不可用时):
  httpx → Content-Type 路由
    PDF  → pymupdf 提取
    HTML → trafilatura(markdown) → 质量检查 → playwright 降级
"""

import os
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


# ── 本地 HTTP 层 ──

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


def _fetch_playwright(url: str) -> str | dict:
    """Playwright JS 渲染。可选依赖，未安装则跳过。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return make_error(
            "playwright 未安装，跳过 JS 渲染。"
            "安装: uv add playwright && playwright install chromium",
            "config", retryable=False,
        )
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=_HEADERS["User-Agent"])
                page.goto(url, wait_until="networkidle", timeout=30_000)
                html = page.content()
            finally:
                browser.close()
            return html
    except Exception as e:
        return make_error(f"Playwright 失败: {e}", "browser", retryable=False)


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


# ── 本地降级链 ──

def _fetch_local(url: str) -> dict:
    """本地抓取: httpx → PDF/HTML 路由 → playwright 降级。"""
    resp = _with_retry(_httpx_get, url)
    httpx_ok = isinstance(resp, httpx.Response)

    if httpx_ok:
        # PDF
        if _is_pdf_response(resp, url):
            print("  [抓取] 检测到 PDF")
            return _extract_pdf(resp.content)

        # HTML → trafilatura markdown
        extracted = extract_content(resp.text, url)
        if len(extracted["content"]) >= _MIN_CONTENT_LEN:
            return {**extracted, "method": "httpx"}
        print(f"  [降级] 内容过短({len(extracted['content'])}字)，尝试 JS 渲染...")
    else:
        print(f"  [降级] httpx 失败({resp['error_type']})，尝试 JS 渲染...")

    # Playwright
    html_pw = _fetch_playwright(url)
    if isinstance(html_pw, str):
        return {**extract_content(html_pw, url), "method": "playwright"}

    # httpx 拿到了 HTML 但内容短 → 勉强用
    if httpx_ok:
        print("  [警告] JS 渲染不可用，使用短内容")
        return {**extract_content(resp.text, url), "method": "httpx"}

    return resp  # error dict


# ── 统一入口 ──

def _fetch(url: str) -> dict:
    """Jina 优先 → 本地降级。返回含 content 的 dict 或 error dict。"""
    result = _with_retry(_fetch_jina, url)
    if "error" not in result:
        return result
    print(f"  [降级] Jina: {result['error'][:60]}，本地抓取...")

    return _fetch_local(url)


# ── 公开接口 ──

def fetch_article(url: str) -> dict:
    """抓取文章全文，用于主流程 Analyze 阶段。

    返回 {title, content, author, date, description, word_count, was_truncated, method}
    或 error dict。
    """
    result = _fetch(url)
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
