"""
UML Activity Diagram text normalizer.

normalize_node_label : returns display text appropriate for the notation type:
  - action / objectNode → concise verb phrase for INSIDE the node
  - decision            → short condition phrase for the OUTGOING EDGE guard
  - fork/join/merge/initial/final → None (no text needed)
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
You are a UML Activity Diagram text formatter. Given an action description and its UML notation \
type, produce the appropriate display text.

Notation-specific output:
- action / objectNode  → label INSIDE the node: 2–5 word verb phrase, imperative form
  e.g. "Chọn khóa học", "Gửi đơn đăng ký", "Submit order form"
- decision             → guard text ON the outgoing EDGE (diamond is empty): short condition phrase
  e.g. "Kiểm tra ngân sách", "Xác thực thông tin", "Validate credentials"

Common rules:
- Remove the actor name if it appears at the start (actor is shown in swimlane header)
- 2–5 words maximum
- Same language as input (Vietnamese or English)
- No subject pronoun, no trailing punctuation
- No filler words (muốn, cần phải, đang, sẽ, thực hiện việc, ...)

Notation: "{notation}"
Actor: "{actor}"
Description: "{text}"

Reply with ONLY the short text, nothing else.\
"""


def _invoke_bedrock(
    text: str, actor_name: str, notation: str,
    access_key: str, secret_key: str, region: str, model_id: str,
) -> str:
    import boto3

    client = boto3.client(
        "bedrock-runtime", region_name=region,
        aws_access_key_id=access_key, aws_secret_access_key=secret_key,
    )
    prompt = _PROMPT.format(notation=notation, actor=actor_name, text=text)
    response = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
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
    """
    Returns normalized text for the notation, or None if the notation carries no text.

    action/objectNode → in-node label
    decision          → edge guard text (layout engine puts it on outgoing edge)
    fork/join/merge/initial_node/final_node → None
    """
    if notation in ("fork", "join", "merge", "initial_node", "final_node"):
        return None
    if not text:
        return None

    rule_result = normalize_label_rules(text, actor_name)
    if not access_key or not secret_key:
        return rule_result

    try:
        return await asyncio.to_thread(
            _invoke_bedrock, text, actor_name or "", notation,
            access_key, secret_key, region, model_id,
        )
    except Exception as exc:
        logger.warning("Bedrock label normalization failed, using rule-based: %s", exc)
        return rule_result
