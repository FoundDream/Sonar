"""Fetcher 接口定义。"""

from abc import ABC, abstractmethod

from models import FetchResult


class FetchError(Exception):
    """获取失败，携带用户友好的错误消息。"""
    pass


class BaseFetcher(ABC):
    @abstractmethod
    def can_handle(self, source: str) -> bool:
        """判断是否能处理该输入源。"""
        ...

    @abstractmethod
    def fetch(self, source: str) -> FetchResult:
        """获取内容。失败抛 FetchError。"""
        ...
