"""Fetcher 路由：根据输入源选择合适的 Fetcher。"""

import os

from fetchers.base import BaseFetcher, FetchError
from fetchers.local_file import LocalFileFetcher
from fetchers.url import URLFetcher
from models import FetchResult

FETCHERS: list[BaseFetcher] = [
    LocalFileFetcher(),  # 先检查本地文件（更具体）
    URLFetcher(),        # URL 作为 fallback
]


def get_fetcher(source: str) -> BaseFetcher:
    """根据 source 找到能处理它的 Fetcher。"""
    for f in FETCHERS:
        if f.can_handle(source):
            return f
    raise FetchError(f"不支持的输入: {source}")


def is_local_file(source: str) -> bool:
    """判断输入是本地文件还是 URL。"""
    if source.startswith(("http://", "https://")):
        return False
    return os.path.isfile(source)


def fetch_source(source: str, llm=None) -> FetchResult | dict:
    """抓取内容的便捷函数。source 可以是 URL 或本地文件路径。"""
    from tools.quality import make_quality_checker

    try:
        fetcher = get_fetcher(source)
        if isinstance(fetcher, URLFetcher):
            fetcher.quality_checker = make_quality_checker(llm=llm)
        return fetcher.fetch(source)
    except FetchError as e:
        return {"error": str(e)}
