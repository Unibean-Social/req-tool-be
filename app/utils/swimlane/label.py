"""
UML Activity Diagram node label normalizer.

normalize_node_label : shorten a full action description to a concise in-node label.
                       Returns None for notation types that carry no text (decision/merge/fork/join).
"""
from __future__ import annotations

import asyncio
import logging
import re

logger = logging.getLogger(__name__)

# ── Rule-based ─────────────────────────────────────────────────────────────────

_FILLER_VN = re.compile(
    r"\b(muốn|cần phải|cần|sẽ|đang|thực hiện việc|tiến hành|có thể|được phép|nhằm mục đích)\b",
    re.IGNORECASE,
)


def normalize_label_rules(text: str, actor_name: str | None) -> str:
    label = text.strip().rstrip(".!?").strip()
    if actor_name:
        prefix = re.compile(r"^" + re.escape(actor_name.strip()) + r"\s+", re.IGNORECASE)
        label = prefix.sub("", label).strip()
    label = _FILLER_VN.sub("", label).strip()
    if label:
        label = label[0].upper() + label[1:]
    return label


# ── Bedrock ────────────────────────────────────────────────────────────────────

_PROMPT = """\
You are a UML Activity Diagram label formatter. Rewrite the description as a concise label \
for inside a UML activity node.

Rules:
- Remove the actor name if it appears at the start (actor is already shown in the swimlane header)
- 2–5 words maximum
- Verb phrase — imperative or infinitive form, e.g. "Chọn khóa học", "Gửi đơn đăng ký", "Submit order"
- Same language as input (Vietnamese or English)
- No subject pronoun, no trailing punctuation, no filler words (muốn, cần phải, đang, sẽ, ...)

Actor: "{actor}"
Description: "{text}"

Reply with ONLY the short label text, nothing else.\
"""


def _invoke_bedrock(
    text: str, actor_name: str, access_key: str, secret_key: str, region: str, model_id: str
) -> str:
    import boto3

    client = boto3.client(
        "bedrock-runtime", region_name=region,
        aws_access_key_id=access_key, aws_secret_access_key=secret_key,
    )
    response = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": _PROMPT.format(actor=actor_name, text=text)}]}],
        inferenceConfig={"maxTokens": 30, "temperature": 0.0},
    )
    raw = response["output"]["message"]["content"][0]["text"].strip().rstrip(".!?")
    return raw if raw else normalize_label_rules(text, actor_name)


# ── Entry point ────────────────────────────────────────────────────────────────

async def normalize_node_label(
    text: str,
    actor_name: str | None = None,
    notation: str = "action",
    access_key: str = "",
    secret_key: str = "",
    region: str = "us-east-1",
    model_id: str = "google.gemma-3-4b-it",
) -> str | None:
    """Concise label for inside a UML node; None for label-less notations (decision/merge/fork/join)."""
    if notation not in ("action", "objectNode"):
        return None
    if not text:
        return None

    rule_result = normalize_label_rules(text, actor_name)
    if not access_key or not secret_key:
        return rule_result

    try:
        return await asyncio.to_thread(
            _invoke_bedrock, text, actor_name or "", access_key, secret_key, region, model_id
        )
    except Exception as exc:
        logger.warning("Bedrock label normalization failed, using rule-based: %s", exc)
        return rule_result
