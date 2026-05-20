"""
UML Activity Diagram text normalizer.

normalize_node_label      : label for action/objectNode (inside node) — None for structural nodes
normalize_decision_guards : (yes_guard, no_guard) bracket pair for decision outgoing edges
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

# (pattern, positive_replacement, negative_replacement)
_GUARD_ANTONYMS = [
    (r"^Đủ\b",           "Đủ",               "Không đủ"),
    (r"^Hợp lệ$",        "Hợp lệ",           "Không hợp lệ"),
    (r"^Thành công$",    "Thành công",        "Thất bại"),
    (r"^Được phê duyệt", "Được phê duyệt",   "Bị từ chối"),
    (r"^Tồn tại$",       "Tồn tại",           "Không tồn tại"),
    (r"^Có\b",           "Có",               "Không"),
    (r"^Yes\b",          "Yes",              "No"),
    (r"^Valid\b",        "Valid",            "Invalid"),
    (r"^Approved\b",     "Approved",         "Rejected"),
    (r"^Passed\b",       "Passed",           "Failed"),
]


def normalize_label_rules(text: str, actor_name: str | None) -> str:
    label = text.strip().rstrip(".!?").strip()
    if actor_name:
        prefix = re.compile(r"^" + re.escape(actor_name.strip()) + r"\s+", re.IGNORECASE)
        label = prefix.sub("", label).strip()
    label = _FILLER_VN.sub("", label).strip()
    if label:
        label = label[0].upper() + label[1:]
    return label


def _guard_pair_rules(label: str) -> tuple[str, str]:
    """Derive [yes] / [no] bracket guards from a condition description."""
    label = label.strip().strip("[]")
    for pattern, pos, neg in _GUARD_ANTONYMS:
        if re.match(pattern, label, re.IGNORECASE):
            matched = re.match(pattern, label, re.IGNORECASE).group(0)
            rest = label[len(matched):]
            return f"[{pos}{rest}]", f"[{neg}{rest}]"
    # Generic: prepend "Không" for Vietnamese, else "[Not ...]"
    first = label[0].lower() + label[1:] if label else label
    if re.search(r"[àáâãèéêìíòóôõùúýăđơưạặấầẩẫắằẳẵặ]", label, re.IGNORECASE):
        return f"[{label}]", f"[Không {first}]"
    return f"[{label}]", f"[Not {first}]"


# ── Bedrock: action / objectNode ───────────────────────────────────────────────

_ACTION_PROMPT = """\
You are a UML Activity Diagram text formatter. Given an action description, produce a concise \
label for INSIDE the action node.

Rules:
- 2–5 word verb phrase, imperative form
- Remove the actor name if it appears at the start (actor is in swimlane header)
- Same language as input (Vietnamese or English)
- No subject pronoun, no trailing punctuation
- No filler words (muốn, cần phải, đang, sẽ, thực hiện việc, ...)

Examples: "Chọn khóa học", "Gửi đơn đăng ký", "Submit order form"

Actor: "{actor}"
Description: "{text}"

Reply with ONLY the short label, nothing else.\
"""


def _invoke_bedrock_action(
    text: str, actor_name: str,
    access_key: str, secret_key: str, region: str, model_id: str,
) -> str:
    import boto3
    client = boto3.client(
        "bedrock-runtime", region_name=region,
        aws_access_key_id=access_key, aws_secret_access_key=secret_key,
    )
    prompt = _ACTION_PROMPT.format(actor=actor_name, text=text)
    response = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 30, "temperature": 0.0},
    )
    raw = response["output"]["message"]["content"][0]["text"].strip().rstrip(".!?")
    return raw if raw else normalize_label_rules(text, actor_name)


# ── Bedrock: decision guards ───────────────────────────────────────────────────

_DECISION_PROMPT = """\
You are a UML Activity Diagram text formatter for decision (diamond) nodes.
Given the decision description, produce EXACTLY TWO guard labels for the outgoing edges.

Rules:
- Line 1: positive/happy-path branch, wrapped in [brackets], e.g. "[Đủ điều kiện]", "[Hợp lệ]"
- Line 2: negative/alt-path branch, wrapped in [brackets], e.g. "[Không đủ điều kiện]", "[Không hợp lệ]"
- 1–4 words inside the brackets
- Same language as input (Vietnamese or English)
- No subject pronoun, no trailing punctuation inside brackets
- Do NOT include the actor name

Actor: "{actor}"
Description: "{text}"

Reply with ONLY 2 lines — positive guard on line 1, negative guard on line 2. Nothing else.\
"""


def _invoke_bedrock_decision(
    text: str, actor_name: str,
    access_key: str, secret_key: str, region: str, model_id: str,
) -> tuple[str, str]:
    import boto3
    client = boto3.client(
        "bedrock-runtime", region_name=region,
        aws_access_key_id=access_key, aws_secret_access_key=secret_key,
    )
    prompt = _DECISION_PROMPT.format(actor=actor_name, text=text)
    response = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 40, "temperature": 0.0},
    )
    raw = response["output"]["message"]["content"][0]["text"].strip()
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if len(lines) >= 2:
        yes = lines[0] if lines[0].startswith("[") else f"[{lines[0].rstrip('.!?')}]"
        no = lines[1] if lines[1].startswith("[") else f"[{lines[1].rstrip('.!?')}]"
        return yes, no
    fallback = normalize_label_rules(text, actor_name)
    return _guard_pair_rules(fallback)


# ── Entry points ───────────────────────────────────────────────────────────────

async def normalize_node_label(
    text: str,
    actor_name: str | None = None,
    notation: str = "action",
    access_key: str = "",
    secret_key: str = "",
    region: str = "us-east-1",
    model_id: str = "google.gemma-3-4b-it",
) -> str | None:
    """In-node label for action/objectNode. Returns None for structural notations."""
    if notation in ("decision", "fork", "join", "merge", "initial_node", "final_node"):
        return None
    if not text:
        return None

    rule_result = normalize_label_rules(text, actor_name)
    if not access_key or not secret_key:
        return rule_result

    try:
        return await asyncio.to_thread(
            _invoke_bedrock_action, text, actor_name or "",
            access_key, secret_key, region, model_id,
        )
    except Exception as exc:
        logger.warning("Bedrock label normalization failed, using rule-based: %s", exc)
        return rule_result


async def normalize_decision_guards(
    text: str,
    actor_name: str | None = None,
    access_key: str = "",
    secret_key: str = "",
    region: str = "us-east-1",
    model_id: str = "google.gemma-3-4b-it",
) -> tuple[str, str]:
    """
    Returns (yes_guard, no_guard) bracket strings for a decision node's outgoing edges.
    e.g. ("[Đủ điều kiện]", "[Không đủ điều kiện]")
    """
    if not text:
        return "[Yes]", "[No]"

    base = normalize_label_rules(text, actor_name)
    if not access_key or not secret_key:
        return _guard_pair_rules(base)

    try:
        return await asyncio.to_thread(
            _invoke_bedrock_decision, text, actor_name or "",
            access_key, secret_key, region, model_id,
        )
    except Exception as exc:
        logger.warning("Bedrock decision guards failed, using rule-based: %s", exc)
        return _guard_pair_rules(base)
