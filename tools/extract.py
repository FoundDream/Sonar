"""共享提取逻辑：trafilatura + BS4 fallback、智能截断、结构化错误。"""

import trafilatura
from bs4 import BeautifulSoup


def extract_content(html: str, url: str) -> dict:
    """从 HTML 提取正文和元数据，trafilatura 优先，BS4 fallback。

    返回 {"title", "content", "author", "date", "description"}。
    """
    # trafilatura 提取正文
    content = trafilatura.extract(
        html, url=url, include_comments=False, output_format="markdown",
    )

    # trafilatura 提取元数据
    meta = trafilatura.extract_metadata(html, default_url=url)

    title = ""
    author = ""
    date = ""
    description = ""

    if meta:
        title = meta.title or ""
        author = meta.author or ""
        date = meta.date or ""
        description = meta.description or ""

    # fallback：trafilatura 提取失败时用 BS4
    if not content:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        if not title:
            title = soup.title.string.strip() if soup.title and soup.title.string else ""
        article = soup.find("article") or soup.find("body")
        content = article.get_text(separator="\n", strip=True) if article else ""

    return {
        "title": title,
        "content": content or "",
        "author": author,
        "date": date,
        "description": description,
    }


def smart_truncate(text: str, max_chars: int, preserve_ends: bool = False) -> str:
    """智能截断文本。

    preserve_ends=True: 保留前 60% + 后 25%，中间标记省略，在段落边界切割。
    preserve_ends=False: 从头截取到最近的段落边界。
    """
    if len(text) <= max_chars:
        return text

    if preserve_ends:
        head_budget = int(max_chars * 0.60)
        tail_budget = int(max_chars * 0.25)

        # 在段落边界切割 head
        head_cut = text.rfind("\n\n", 0, head_budget)
        if head_cut == -1:
            head_cut = head_budget
        head = text[:head_cut]

        # 在段落边界切割 tail
        tail_start = len(text) - tail_budget
        tail_cut = text.find("\n\n", tail_start)
        if tail_cut == -1:
            tail_cut = tail_start
        tail = text[tail_cut:]

        return head + "\n\n[...省略...]\n\n" + tail
    else:
        cut = text.rfind("\n\n", 0, max_chars)
        if cut == -1:
            cut = max_chars
        return text[:cut]


def make_error(message: str, error_type: str, retryable: bool) -> dict:
    """统一错误结构。

    error_type: timeout / http_4xx / http_5xx / network / parse / unknown
    """
    return {
        "error": message,
        "error_type": error_type,
        "retryable": retryable,
    }
