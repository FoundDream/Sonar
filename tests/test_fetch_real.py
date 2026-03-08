"""网络抓取测试：验证各平台 URL 的实际抓取能力。

默认跳过，需要 --run-network 参数才运行：
  uv run python -m pytest tests/test_fetch_real.py --run-network -v
"""

import pytest

from fetchers import fetch_source
from models import FetchResult


class _FetchHelper:
    """Thin wrapper to keep test interface (stage.run) working."""
    @staticmethod
    def run(source: str):
        return fetch_source(source)


@pytest.fixture
def stage():
    return _FetchHelper()


@pytest.mark.network
class TestURLFetch:
    def test_english_article(self, stage) -> None:
        """Paul Graham 博客 — 简单静态页面，应该稳定可抓。"""
        result = stage.run("https://paulgraham.com/writes.html")

        assert isinstance(result, FetchResult)
        assert result.source_type == "url"
        assert len(result.content) > 200
        assert result.title

    def test_chinese_article(self, stage) -> None:
        """少数派文章 — 中文内容站点。"""
        result = stage.run("https://sspai.com/post/77922")

        assert isinstance(result, FetchResult)
        assert result.source_type == "url"
        assert len(result.content) > 200

    def test_github_readme(self, stage) -> None:
        """GitHub 仓库页面。"""
        result = stage.run("https://github.com/anthropics/anthropic-cookbook")

        assert isinstance(result, FetchResult)
        assert result.source_type == "url"
        assert len(result.content) > 100

    def test_wechat_article_quality(self, stage) -> None:
        """微信公众号文章 — 已知反爬严重，验证我们能否检测到内容不可用。"""
        result = stage.run("https://mp.weixin.qq.com/s/HbjCFCQ_hFPSdMHgBNPGUw")

        # 微信文章目前拿到的是空壳，内容极短
        # 这个测试记录当前行为，后续改进时更新断言
        if isinstance(result, FetchResult):
            assert len(result.content) < 300, (
                f"微信文章竟然拿到了 {len(result.content)} 字符的内容？可能反爬策略变了"
            )

    def test_x_twitter_post(self, stage) -> None:
        """X/Twitter 帖子 — URL 重写到 fixupx.com 代理。"""
        result = stage.run("https://x.com/kaborogevara/status/1898909941498044517")

        self._log_result("X/Twitter", result)
        assert isinstance(result, FetchResult)
        assert len(result.content) > 50

    def test_reddit_post(self, stage) -> None:
        """Reddit 帖子 — old.reddit.com 通常比较友好。"""
        result = stage.run("https://www.reddit.com/r/LocalLLaMA/comments/1jjp39n/qwen3_confirmed_by_alibaba/")

        self._log_result("Reddit", result)
        assert isinstance(result, FetchResult)
        assert len(result.content) > 50

    def test_medium_article(self, stage) -> None:
        """Medium 文章 — Jina 失败时 Crawl4AI 降级。"""
        result = stage.run("https://medium.com/@karpathy/software-2-0-a64152b37c35")

        self._log_result("Medium", result)
        assert isinstance(result, FetchResult)
        assert len(result.content) > 200

    def test_substack_article(self, stage) -> None:
        """Substack newsletter — 通常可抓。"""
        result = stage.run("https://www.oneusefulthing.org/p/what-just-happened-with-ai")

        self._log_result("Substack", result)
        assert isinstance(result, FetchResult)
        assert len(result.content) > 200

    def test_wikipedia(self, stage) -> None:
        """Wikipedia — 应该非常稳定。"""
        result = stage.run("https://en.wikipedia.org/wiki/Transformer_(deep_learning_architecture)")

        assert isinstance(result, FetchResult)
        assert len(result.content) > 500
        assert result.title

    def test_arxiv_abstract(self, stage) -> None:
        """arXiv 摘要页 — 学术论文入口。"""
        result = stage.run("https://arxiv.org/abs/1706.03762")

        self._log_result("arXiv", result)
        assert isinstance(result, FetchResult)
        assert "attention" in result.content.lower() or "transformer" in result.content.lower()

    def test_zhihu_article(self, stage) -> None:
        """知乎文章 — Jina 失败时 Crawl4AI 降级。"""
        result = stage.run("https://zhuanlan.zhihu.com/p/350017443")

        self._log_result("知乎", result)
        assert isinstance(result, FetchResult)
        assert len(result.content) > 200

    def test_hacker_news(self, stage) -> None:
        """Hacker News — 简单 HTML，应该稳定。"""
        result = stage.run("https://news.ycombinator.com/item?id=41778461")

        self._log_result("HN", result)
        assert isinstance(result, FetchResult)

    def test_youtube_video_page(self, stage) -> None:
        """YouTube 页面 — JS 渲染重，通常拿不到正文。"""
        result = stage.run("https://www.youtube.com/watch?v=aircAruvnKk")

        self._log_result("YouTube", result)

    def test_36kr(self, stage) -> None:
        """36氪 — 中文科技媒体。"""
        result = stage.run("https://36kr.com/p/2564524328960002")

        self._log_result("36氪", result)
        assert isinstance(result, FetchResult)
        assert len(result.content) > 200

    def test_csdn(self, stage) -> None:
        """CSDN 博客 — 中文技术社区。"""
        result = stage.run("https://blog.csdn.net/v_JULY_v/article/details/127411638")

        self._log_result("CSDN", result)
        assert isinstance(result, FetchResult)
        assert len(result.content) > 500

    def test_devto(self, stage) -> None:
        """Dev.to — 英文开发者社区。"""
        result = stage.run("https://dev.to/lydiahallie/javascript-visualized-event-loop-3dif")

        self._log_result("Dev.to", result)
        assert isinstance(result, FetchResult)
        assert len(result.content) > 500

    def test_ithome(self, stage) -> None:
        """IT之家 — 中文科技资讯。"""
        result = stage.run("https://www.ithome.com/0/800/578.htm")

        self._log_result("IT之家", result)
        assert isinstance(result, FetchResult)
        assert len(result.content) > 200

    def test_douban(self, stage) -> None:
        """豆瓣电影 — 中文内容平台。"""
        result = stage.run("https://movie.douban.com/subject/1292052/")

        self._log_result("豆瓣", result)
        assert isinstance(result, FetchResult)
        assert len(result.content) > 500

    def test_weread(self, stage) -> None:
        """微信读书 — 书籍页面（公开信息）。"""
        result = stage.run("https://weread.qq.com/web/bookDetail/ce032b305a9bc1ce0b0dd2a")

        self._log_result("微信读书", result)
        assert isinstance(result, FetchResult)
        assert len(result.content) > 200

    def test_v2ex(self, stage) -> None:
        """V2EX — 中文技术社区。"""
        result = stage.run("https://www.v2ex.com/t/1095923")

        self._log_result("V2EX", result)
        assert isinstance(result, FetchResult)
        assert len(result.content) > 200

    def test_bbc(self, stage) -> None:
        """BBC News — 英文新闻。"""
        result = stage.run("https://www.bbc.com/news/technology-68128396")

        self._log_result("BBC", result)
        assert isinstance(result, FetchResult)
        assert len(result.content) > 500

    def test_infoq(self, stage) -> None:
        """InfoQ — 技术媒体。"""
        result = stage.run("https://www.infoq.com/articles/architecture-trends-2025/")

        self._log_result("InfoQ", result)
        assert isinstance(result, FetchResult)
        assert len(result.content) > 500

    def test_bilibili_video(self, stage) -> None:
        """B站视频页 — JS 渲染站，Jina 通常能拿到描述。"""
        result = stage.run("https://www.bilibili.com/video/BV1Xt411q7XZ/")

        self._log_result("B站", result)
        assert isinstance(result, FetchResult)

    def test_gitlab(self, stage) -> None:
        """GitLab 仓库页面。"""
        result = stage.run("https://gitlab.com/gitlab-org/gitlab/-/blob/master/README.md")

        self._log_result("GitLab", result)
        assert isinstance(result, FetchResult)
        assert len(result.content) > 200

    def test_npm_package(self, stage) -> None:
        """NPM 包页面。"""
        result = stage.run("https://www.npmjs.com/package/react")

        self._log_result("NPM", result)
        assert isinstance(result, FetchResult)
        assert len(result.content) > 200

    def test_arxiv_pdf(self, stage) -> None:
        """arXiv PDF — 直接 PDF 链接。"""
        result = stage.run("https://arxiv.org/pdf/1706.03762")

        self._log_result("arXiv PDF", result)
        assert isinstance(result, FetchResult)
        assert len(result.content) > 500

    def test_stackoverflow(self, stage) -> None:
        """Stack Overflow — 技术问答。"""
        result = stage.run("https://stackoverflow.com/questions/44209978/what-is-an-attention-mechanism")

        self._log_result("StackOverflow", result)
        assert isinstance(result, FetchResult)
        assert len(result.content) > 200

    @staticmethod
    def _log_result(label: str, result) -> None:
        """打印测试结果供人工检查。"""
        if isinstance(result, dict) and "error" in result:
            print(f"\n[{label}] FAIL: {result['error'][:100]}")
        elif isinstance(result, FetchResult):
            print(f"\n[{label}] OK: title={result.title[:60]!r}, len={len(result.content)}, truncated={result.was_truncated}")
        else:
            print(f"\n[{label}] UNEXPECTED: {type(result)}")
