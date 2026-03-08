"""内容质量分类器：基于 Qwen3.5-0.8B 小模型，本地推理。

用 LLM 判断抓取的网页内容是否为有效正文（vs 导航页/错误页/付费墙等）。
模型约 0.8B 参数，CPU 推理 ~1-2s，无需 API 调用。
"""

from __future__ import annotations

_model = None
_tokenizer = None

_MODEL_NAME = "Qwen/Qwen3.5-0.8B"

_SYSTEM_PROMPT = """\
You are a content quality classifier. Given a text snippet from a web page, \
respond with exactly one word: High, Medium, or Low.

- High: Real article/document content with substantive paragraphs
- Medium: Some real content mixed with noise (ads, navigation, etc.)
- Low: Navigation pages, error pages (404/403), login walls, paywalls, \
cookie consent pages, or pages with no real article content"""


def _load():
    """懒加载模型 + tokenizer，首次调用时下载，后续复用。"""
    global _model, _tokenizer

    if _model is not None:
        return

    from transformers import AutoModelForCausalLM, AutoTokenizer

    _tokenizer = AutoTokenizer.from_pretrained(_MODEL_NAME)
    _model = AutoModelForCausalLM.from_pretrained(
        _MODEL_NAME,
        torch_dtype="auto",
    )
    _model.eval()


def check_content_quality(text: str, min_chars: int = 50) -> dict:
    """判断内容质量。

    返回 {"quality": "High"|"Medium"|"Low", "score": float, "usable": bool}。
    文本过短直接判 Low。
    """
    if len(text.strip()) < min_chars:
        return {"quality": "Low", "score": 1.0, "usable": False}

    import torch

    _load()

    # 只取前 512 字符，够判断质量
    snippet = text[:512]
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": snippet},
    ]

    input_text = _tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True,
        enable_thinking=False,
    )
    inputs = _tokenizer(input_text, return_tensors="pt")

    with torch.no_grad():
        outputs = _model.generate(
            **inputs,
            max_new_tokens=3,
            temperature=None,
            top_p=None,
            do_sample=False,
        )

    # 只取生成的新 token
    new_tokens = outputs[0][inputs["input_ids"].shape[1]:]
    response = _tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

    # 解析结果
    label = "Medium"  # 默认中等
    for candidate in ("High", "Medium", "Low"):
        if candidate.lower() in response.lower():
            label = candidate
            break

    return {
        "quality": label,
        "score": 1.0,
        "usable": label != "Low",
    }
