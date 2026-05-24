"""
Context diagram edge classifier.

classify_direction_rules : rule-based keyword match, O(1)
classify_direction        : rules first, Bedrock fallback for label + direction
"""
from __future__ import annotations

import asyncio
import logging
from typing import TypedDict

logger = logging.getLogger(__name__)

_SYSTEM_TO_ACTOR_KEYWORDS: tuple[str, ...] = (
    "notify", "return", "send", "confirm", "alert", "display",
    "report", "export", "respond", "reply", "push", "emit",
    "gửi", "thông báo", "trả về", "xác nhận", "phản hồi", "hiển thị",
    "nhận lệnh", "nhận được", "nhận thông báo", "nhận hàng",
)

_PROMPT = """\
You are a UML Context Diagram edge classifier. Given a use-case action step, determine the edge direction between the external actor and the central system.

Rules:
- "actor_to_system": the actor initiates, requests, submits, or sends something TO the system
- "system_to_actor": the system sends, notifies, returns, or responds TO the actor; also use this when the actor RECEIVES something from the system

Generate a concise 2-5 word Vietnamese label matching the classified direction:
- actor_to_system: describe what the actor does or sends (e.g. "Gửi đơn hàng", "Tải lên tệp", "Yêu cầu báo cáo")
- system_to_actor: describe what the system provides (e.g. "Xác nhận thanh toán", "Gửi thông báo", "Trả kết quả"){actors_hint}

Return exactly two lines with no extra text:
direction: <actor_to_system|system_to_actor>
label: <nhãn tiếng Việt ngắn gọn>

Actor: "{actor}"
Description: "{text}"\
"""


class DirectionResult(TypedDict):
    direction: str
    label: str


def classify_direction_rules(description: str) -> str:
    lower = description.lower()
    return "system_to_actor" if any(kw in lower for kw in _SYSTEM_TO_ACTOR_KEYWORDS) else "actor_to_system"


def _invoke_bedrock(
    text: str,
    actor: str,
    access_key: str,
    secret_key: str,
    region: str,
    model_id: str,
    other_actors: list[str],
) -> DirectionResult:
    import boto3

    actors_hint = (
        f"\nOther actors in the system: {', '.join(other_actors)}"
        if other_actors else ""
    )
    prompt = _PROMPT.format(text=text, actor=actor, actors_hint=actors_hint)

    client = boto3.client(
        "bedrock-runtime",
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    response = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 40, "temperature": 0.0},
    )
    raw = response["output"]["message"]["content"][0]["text"].strip()

    direction = classify_direction_rules(text)
    label = text[:50]

    for line in raw.splitlines():
        if line.startswith("direction:"):
            val = line.split(":", 1)[1].strip()
            if val in {"actor_to_system", "system_to_actor"}:
                direction = val
        elif line.startswith("label:"):
            label = line.split(":", 1)[1].strip()

    return {"direction": direction, "label": label}


async def classify_direction(
    text: str,
    actor: str = "",
    other_actors: list[str] | None = None,
    access_key: str = "",
    secret_key: str = "",
    region: str = "us-east-1",
    model_id: str = "google.gemma-3-4b-it",
) -> DirectionResult:
    """Rule-based direction; Bedrock for both direction and label when credentials present."""
    if not access_key or not secret_key:
        return {
            "direction": classify_direction_rules(text),
            "label": text[:50],
        }
    try:
        return await asyncio.to_thread(
            _invoke_bedrock, text, actor, access_key, secret_key, region, model_id,
            other_actors or [],
        )
    except Exception as exc:
        logger.warning("Bedrock direction classification failed (%s), using rules", type(exc).__name__)
        return {
            "direction": classify_direction_rules(text),
            "label": text[:50],
        }
