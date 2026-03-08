import sys
from types import SimpleNamespace

import tools.quality as quality


def test_quality_checker_disables_broken_local_classifier_after_first_failure(monkeypatch) -> None:
    calls = {"local": 0, "llm": 0}

    def broken_local_check(_content: str) -> dict:
        calls["local"] += 1
        raise ImportError("No module named 'torch'")

    def fake_llm_check(_content: str, _llm) -> bool:
        calls["llm"] += 1
        return True

    monkeypatch.setattr(quality, "_llm_check", fake_llm_check)
    monkeypatch.setitem(
        sys.modules,
        "tools.classify",
        SimpleNamespace(check_content_quality=broken_local_check),
    )

    checker = quality.make_quality_checker(llm="fake-llm")

    assert checker("useful content" * 20) is True
    assert checker("useful content" * 20) is True
    assert calls == {"local": 1, "llm": 2}


def test_quality_checker_allows_when_local_classifier_missing_and_no_llm(monkeypatch) -> None:
    def broken_local_check(_content: str) -> dict:
        raise ImportError("No module named 'transformers'")

    monkeypatch.setitem(
        sys.modules,
        "tools.classify",
        SimpleNamespace(check_content_quality=broken_local_check),
    )

    checker = quality.make_quality_checker(llm=None)

    assert checker("useful content" * 20) is True
