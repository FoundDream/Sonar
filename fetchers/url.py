"""URLFetcher — 包装 tools/fetch.fetch_article() 处理 URL 输入。"""

from collections.abc import Callable

from fetchers.base import BaseFetcher, FetchError
from stages.models import FetchResult
from tools.fetch import fetch_article


class URLFetcher(BaseFetcher):
    def __init__(self):
        self.quality_checker: Callable[[str], bool] | None = None

    def can_handle(self, source: str) -> bool:
        return source.startswith(("http://", "https://"))

    def fetch(self, source: str) -> FetchResult:
        print("\n--- 抓取文章 ---")
        result = fetch_article(source, quality_checker=self.quality_checker)
        if "error" in result:
            raise FetchError(f"抓取失败: {result['error']}")

        fetch_result = FetchResult(
            url=source,
            title=result.get("title", ""),
            content=result.get("content", ""),
            author=result.get("author", ""),
            date=result.get("date", ""),
            description=result.get("description", ""),
            word_count=result.get("word_count", 0),
            was_truncated=result.get("was_truncated", False),
            source_type="url",
        )
        print(f"[抓取] 标题: {fetch_result.title}")
        return fetch_result
