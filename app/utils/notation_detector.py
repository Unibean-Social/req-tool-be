"""
Detects UML Activity Diagram notation type from action description text.

Strategy:
  1. Rule-based (O(1), no latency) — covers clear patterns in VN/EN.
  2. Bedrock LLM (google.gemma-3-4b-it) — called only when rules return "action"
     (the default), to catch objectNode and ambiguous cases rules miss.
  3. If LLM unavailable or errors → fall back to rule-based result.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Literal

NotationType = Literal["action", "objectNode", "decision", "merge", "fork", "join"]
_VALID = {"action", "objectNode", "decision", "merge", "fork", "join"}

logger = logging.getLogger(__name__)

# ── Rule-based patterns ────────────────────────────────────────────────────────

_RE_DECISION = re.compile(
    r"\b(nếu|kiểm tra|xác nhận|hợp lệ|điều kiện|phân nhánh|"
    r"if|check|validate|is valid|condition|gateway)\b",
    re.IGNORECASE,
)
_RE_FORK = re.compile(
    r"\b(tách|song song|đồng thời|bắt đầu song song|"
    r"fork|parallel|split|concurrent)\b",
    re.IGNORECASE,
)
_RE_JOIN = re.compile(
    r"\b(hội tụ|đồng bộ|kết thúc song song|synchronize|join)\b",
    re.IGNORECASE,
)
_RE_MERGE = re.compile(
    r"\b(hợp nhất|gộp lại|merge)\b",
    re.IGNORECASE,
)


def detect_notation_rules(text: str) -> NotationType:
    if _RE_DECISION.search(text):
        return "decision"
    if _RE_FORK.search(text):
        return "fork"
    if _RE_JOIN.search(text):
        return "join"
    if _RE_MERGE.search(text):
        return "merge"
    return "action"


# ── Bedrock LLM ────────────────────────────────────────────────────────────────

_PROMPT_TEMPLATE = """\
You are a UML Activity Diagram classifier. Given an action step description, \
output exactly one notation type with no extra text.

Notation types:
- action       : a regular activity performed by an actor
- objectNode   : a data object or artifact (noun phrase, not an activity)
- decision     : conditional check or branch (if/else, validate, gateway)
- merge        : converges multiple conditional paths into one path
- fork         : splits one path into parallel concurrent branches
- join         : synchronizes parallel branches back into one path

Description: "{text}"

Reply with exactly one word from: action, objectNode, decision, merge, fork, join\
"""


def _invoke_bedrock_sync(text: str, access_key: str, secret_key: str, region: str, model_id: str) -> NotationType:
    import boto3  # imported here so tests without boto3 wont break at import time

    client = boto3.client(
        "bedrock-runtime",
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    prompt = _PROMPT_TEMPLATE.format(text=text)
    response = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 10, "temperature": 0.0},
    )
    raw = response["output"]["message"]["content"][0]["text"].strip()
    # model may return "action." or "  action  " — normalise
    candidate = raw.rstrip(".").strip()
    if candidate in _VALID:
        return candidate  # type: ignore[return-value]
    # try first word in case model added extra text
    first = candidate.split()[0].rstrip(".") if candidate else ""
    return first if first in _VALID else "action"  # type: ignore[return-value]


async def detect_notation_llm(
    text: str,
    access_key: str,
    secret_key: str,
    region: str,
    model_id: str,
) -> NotationType:
    try:
        return await asyncio.to_thread(
            _invoke_bedrock_sync, text, access_key, secret_key, region, model_id
        )
    except Exception as exc:
        logger.warning("Bedrock notation detection failed, falling back to rules: %s", exc)
        return "action"


# ── Combined entry point ───────────────────────────────────────────────────────

async def detect_notation(
    text: str,
    access_key: str = "",
    secret_key: str = "",
    region: str = "us-east-1",
    model_id: str = "google.gemma-3-4b-it",
) -> NotationType:
    """
    Rules first. If rules are confident (return non-"action") → skip LLM.
    If rules return "action" and Bedrock is configured → ask LLM.
    """
    rules_result = detect_notation_rules(text)
    if rules_result != "action":
        return rules_result

    if not access_key or not secret_key:
        return rules_result

    return await detect_notation_llm(text, access_key, secret_key, region, model_id)
