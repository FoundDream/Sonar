"""fetch.py 纯函数单元测试：URL 重写、重试逻辑、降级链。

不需要网络，不需要 mock LLM，直接测试内部逻辑。
"""

import pytest

from tools.extract import make_error
from tools.fetch import _rewrite_url, _with_retry


# ── URL 重写 ──

@pytest.mark.parametrize("input_url,expected", [
    # Reddit 变体
    ("https://www.reddit.com/r/Python/comments/abc", "https://old.reddit.com/r/Python/comments/abc"),
    ("https://reddit.com/r/Python/comments/abc",     "https://old.reddit.com/r/Python/comments/abc"),
    ("http://reddit.com/r/test",                     "http://old.reddit.com/r/test"),
    # X / Twitter 变体
    ("https://x.com/user/status/123",                "https://fixupx.com/user/status/123"),
    ("https://www.x.com/user/status/123",            "https://fixupx.com/user/status/123"),
    ("https://twitter.com/user/status/456",          "https://fixupx.com/user/status/456"),
    ("https://www.twitter.com/user/status/456",      "https://fixupx.com/user/status/456"),
    # 不应重写
    ("https://example.com/article",                  "https://example.com/article"),
    ("https://notredditor.com/page",                 "https://notredditor.com/page"),  # 相似域名不匹配
    ("https://old.reddit.com/r/Python",              "https://old.reddit.com/r/Python"),  # 不双重重写
])
def test_rewrite_url(input_url, expected):
    assert _rewrite_url(input_url) == expected


def test_rewrite_url_preserves_query_and_fragment():
    url = "https://reddit.com/r/test?sort=new#comments"
    result = _rewrite_url(url)
    assert "old.reddit.com" in result
    assert "?sort=new#comments" in result


# ── 重试逻辑 ──


class TestWithRetry:
    """_with_retry() 指数退避重试可重试错误。"""

    def test_success_on_first_try(self):
        def fn():
            return {"content": "ok"}
        assert _with_retry(fn) == {"content": "ok"}

    def test_retryable_error_retries(self):
        """可重试错误会重试，最终成功。"""
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return make_error("暂时失败", "timeout", retryable=True)
            return {"content": "ok"}

        result = _with_retry(fn)
        assert result == {"content": "ok"}
        assert call_count == 3  # 1 initial + 2 retries

    def test_non_retryable_error_no_retry(self):
        """不可重试错误直接返回，不重试。"""
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            return make_error("永久失败", "http_4xx", retryable=False)

        result = _with_retry(fn)
        assert "error" in result
        assert call_count == 1

    def test_max_retries_exhausted(self):
        """超过最大重试次数后返回最后的错误。"""
        def fn():
            return make_error("一直失败", "timeout", retryable=True)

        result = _with_retry(fn)
        assert "error" in result
        assert result["error"] == "一直失败"

    def test_passes_args_to_fn(self):
        """参数正确传递给被重试的函数。"""
        def fn(a, b):
            return {"sum": a + b}

        result = _with_retry(fn, 3, 4)
        assert result == {"sum": 7}

    def test_non_dict_result_is_success(self):
        """返回非 dict 的结果视为成功。"""
        def fn():
            return "plain string"

        assert _with_retry(fn) == "plain string"


# ── make_error ──


class TestMakeError:
    def test_structure(self):
        err = make_error("出错了", "timeout", retryable=True)
        assert err == {
            "error": "出错了",
            "error_type": "timeout",
            "retryable": True,
        }

    def test_non_retryable(self):
        err = make_error("404", "http_4xx", retryable=False)
        assert err["retryable"] is False
