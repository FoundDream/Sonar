"""内容质量分类器：基于 NVIDIA DeBERTa 模型，本地推理。

使用 nvidia/quality-classifier-deberta 判断网页内容质量 (High/Medium/Low)。
模型约 86M 参数，推理 ~10ms，无需 API 调用。
"""

from __future__ import annotations

_classifier = None


def _get_classifier():
    """懒加载模型，首次调用时下载 + 加载，后续复用。"""
    global _classifier
    if _classifier is not None:
        return _classifier

    from transformers import pipeline

    _classifier = pipeline(
        "text-classification",
        model="nvidia/quality-classifier-deberta",
        device=-1,  # CPU
    )
    return _classifier


def check_content_quality(text: str, min_chars: int = 50) -> dict:
    """判断内容质量。

    返回 {"quality": "High"|"Medium"|"Low", "score": float, "usable": bool}。
    文本过短直接判 Low。
    """
    if len(text.strip()) < min_chars:
        return {"quality": "Low", "score": 1.0, "usable": False}

    classifier = _get_classifier()
    # 只取前 512 字符，够判断质量，省推理时间
    result = classifier(text[:512], truncation=True)[0]

    label = result["label"]  # "High", "Medium", "Low"
    score = result["score"]

    return {
        "quality": label,
        "score": score,
        "usable": label != "Low",
    }
