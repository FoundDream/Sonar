"""Fetcher 路由：根据输入源选择合适的 Fetcher。"""

from fetchers.base import BaseFetcher, FetchError
from fetchers.local_file import LocalFileFetcher
from fetchers.url import URLFetcher

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
