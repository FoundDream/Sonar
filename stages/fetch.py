"""Fetch 阶段：路由到合适的 Fetcher，质量检查集成在降级链中。"""

import os

from fetchers import get_fetcher
from fetchers.base import FetchError
from fetchers.url import URLFetcher
from llm.client import LLMClient
from stages.models import FetchResult
from tools.quality import make_quality_checker


def is_local_file(source: str) -> bool:
    """判断输入是本地文件还是 URL。"""
    if source.startswith(("http://", "https://")):
        return False
    return os.path.isfile(source)


class FetchStage:
    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm

    def run(self, source: str) -> FetchResult | dict:
        """抓取内容。source 可以是 URL 或本地文件路径。"""
        try:
            fetcher = get_fetcher(source)

            # URL 抓取时注入质量检查器（驱动降级链）
            if isinstance(fetcher, URLFetcher):
                fetcher.quality_checker = make_quality_checker(llm=self.llm)

            result = fetcher.fetch(source)
        except FetchError as e:
            return {"error": str(e)}

        return result
