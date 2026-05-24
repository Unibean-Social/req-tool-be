"""
Context diagram layout engine.

1: calculate_layout   — radial positions for stakeholders around center
2: review_positions   — Bedrock ordering + rule-based label-overlap elimination
"""
from __future__ import annotations

import json
import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
CANVAS_CX = 600.0
CANVAS_CY = 400.0
CENTER_R = 90.0           # project circle radius (diameter 180px)
STK_W = 220.0             # stakeholder rectangle width
STK_H = 80.0              # stakeholder rectangle height
RADIUS = CENTER_R + 300.0 # center edge → stakeholder edge gap ~300px
LABEL_W = 130.0
LABEL_H = 24.0
LABEL_PERP_OFFSET = 20.0  # px to push bidirectional labels apart


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class ContextNodeLayout:
    id: str
    x: float
    y: float
    width: float
    height: float
    angle: float = 0.0


@dataclass
class ContextEdgeLayout:
    id: str
    label_offset_x: float = 0.0
    label_offset_y: float = 0.0


@dataclass
class ContextLayout:
    center: ContextNodeLayout
    nodes: list[ContextNodeLayout]
    edges: list[ContextEdgeLayout]


# ── 1: calculate_layout ──────────────────────────────────────────────────────

def calculate_layout(
    stakeholder_ids: list[str],
    flows: list[dict],
) -> ContextLayout:
    """Place center at canvas midpoint; stakeholders equally spaced on a circle."""
    n = len(stakeholder_ids)
    angle_step = (2 * math.pi / n) if n > 0 else 0

    center = ContextNodeLayout(
        id="center", x=CANVAS_CX, y=CANVAS_CY,
        width=CENTER_R * 2, height=CENTER_R * 2,
    )
    nodes: list[ContextNodeLayout] = []
    for i, sid in enumerate(stakeholder_ids):
        angle = -math.pi / 2 + i * angle_step  # 12 o'clock start, clockwise
        nodes.append(ContextNodeLayout(
            id=sid,
            x=round(CANVAS_CX + RADIUS * math.cos(angle), 1),
            y=round(CANVAS_CY + RADIUS * math.sin(angle), 1),
            width=STK_W,
            height=STK_H,
            angle=angle,
        ))

    edges = _compute_edge_offsets(nodes, flows)
    return ContextLayout(center=center, nodes=nodes, edges=edges)


def _compute_edge_offsets(
    nodes: list[ContextNodeLayout],
    flows: list[dict],
) -> list[ContextEdgeLayout]:
    """Bidirectional pairs share the same line — push their labels apart perpendicularly."""
    node_pos: dict[str, tuple[float, float]] = {n.id: (n.x, n.y) for n in nodes}
    node_pos["center"] = (CANVAS_CX, CANVAS_CY)

    pair_flows: dict[frozenset, list[dict]] = defaultdict(list)
    for f in flows:
        pair_flows[frozenset([f.get("source", ""), f.get("target", "")])].append(f)

    result: list[ContextEdgeLayout] = []
    for pair, pf in pair_flows.items():
        ids = list(pair)
        ax, ay = node_pos.get(ids[0], (CANVAS_CX, CANVAS_CY))
        bx, by = node_pos.get(ids[1], (CANVAS_CX, CANVAS_CY))
        length = math.hypot(bx - ax, by - ay) or 1.0
        px, py = -(by - ay) / length, (bx - ax) / length  # perpendicular unit

        for i, f in enumerate(pf):
            if len(pf) == 1:
                result.append(ContextEdgeLayout(id=f["id"]))
            else:
                sign = 1 if i % 2 == 0 else -1
                result.append(ContextEdgeLayout(
                    id=f["id"],
                    label_offset_x=round(px * sign * LABEL_PERP_OFFSET, 1),
                    label_offset_y=round(py * sign * LABEL_PERP_OFFSET, 1),
                ))
    return result


# ── 2: review_positions ──────────────────────────────────────────────────────

_ORDER_PROMPT = """\
You are a context diagram layout optimizer. {n} stakeholders are arranged clockwise around "{system_name}".

Stakeholders and their edge labels:
{stakeholder_info}

Return the optimal clockwise ordering starting from top (12 o'clock) as JSON:
{{"order": [<id>, ...]}}

Rules:
- Spread stakeholders with long labels so they are not adjacent
- Place semantically related stakeholders near each other
- Distribute bidirectional actors (both inbound + outbound edges) evenly around the circle
- Return ONLY the JSON, no explanation\
"""


async def review_positions(
    layout: ContextLayout,
    stakeholder_names: dict[str, str],
    flows: list[dict],
    system_name: str = "System",
    access_key: str = "",
    secret_key: str = "",
    region: str = "us-east-1",
    model_id: str = "google.gemma-3-4b-it",
) -> ContextLayout:
    if access_key and secret_key:
        try:
            layout = await _bedrock_review(
                layout, stakeholder_names, flows, system_name,
                access_key, secret_key, region, model_id,
            )
        except Exception as exc:
            logger.warning("Bedrock context layout failed, rule-based fallback: %s", exc)
            layout = _rule_based_review(layout, flows)
    else:
        layout = _rule_based_review(layout, flows)
    return layout


# ── Rule-based: detect + fix label overlaps ───────────────────────────────────

def _rule_based_review(layout: ContextLayout, flows: list[dict]) -> ContextLayout:
    current = layout
    for _ in range(len(current.nodes)):
        conflicts = _find_label_conflicts(current, flows)
        if not conflicts:
            break
        best = current
        best_count = len(conflicts)
        for i in range(len(current.nodes) - 1):
            candidate = _swap_nodes(current, i, i + 1, flows)
            c = len(_find_label_conflicts(candidate, flows))
            if c < best_count:
                best, best_count = candidate, c
        if best is current:
            break
        current = best
    return current


def _find_label_conflicts(layout: ContextLayout, flows: list[dict]) -> list[tuple[str, str]]:
    node_pos: dict[str, tuple[float, float]] = {n.id: (n.x, n.y) for n in layout.nodes}
    node_pos["center"] = (CANVAS_CX, CANVAS_CY)
    offsets = {e.id: (e.label_offset_x, e.label_offset_y) for e in layout.edges}

    boxes: list[tuple[str, float, float]] = []
    for f in flows:
        sx, sy = node_pos.get(f.get("source", ""), (CANVAS_CX, CANVAS_CY))
        tx, ty = node_pos.get(f.get("target", ""), (CANVAS_CX, CANVAS_CY))
        ox, oy = offsets.get(f["id"], (0.0, 0.0))
        boxes.append((f["id"], (sx + tx) / 2 + ox, (sy + ty) / 2 + oy))

    return [
        (a_id, b_id)
        for i, (a_id, ax, ay) in enumerate(boxes)
        for b_id, bx, by in boxes[i + 1:]
        if abs(ax - bx) < LABEL_W and abs(ay - by) < LABEL_H
    ]


def _swap_nodes(layout: ContextLayout, i: int, j: int, flows: list[dict]) -> ContextLayout:
    nodes = [
        ContextNodeLayout(id=n.id, x=n.x, y=n.y, width=n.width, height=n.height, angle=n.angle)
        for n in layout.nodes
    ]
    nodes[i].id, nodes[j].id = nodes[j].id, nodes[i].id
    return ContextLayout(
        center=layout.center,
        nodes=nodes,
        edges=_compute_edge_offsets(nodes, flows),
    )


# ── Bedrock ordering ──────────────────────────────────────────────────────────

async def _bedrock_review(
    layout: ContextLayout,
    stakeholder_names: dict[str, str],
    flows: list[dict],
    system_name: str,
    access_key: str,
    secret_key: str,
    region: str,
    model_id: str,
) -> ContextLayout:
    import asyncio

    flow_by_actor: dict[str, list[str]] = defaultdict(list)
    for f in flows:
        src, tgt, label = f.get("source", ""), f.get("target", ""), f.get("label", "")
        actor = tgt if src == "center" else src
        direction = "hệ thống→actor" if src == "center" else "actor→hệ thống"
        flow_by_actor[actor].append(f'"{label}" ({direction})')

    stakeholder_info = "\n".join(
        f'- id={sid} name="{stakeholder_names.get(sid, sid)}": '
        f'{", ".join(flow_by_actor.get(sid, ["(chưa có cạnh)"]))}'
        for sid in [n.id for n in layout.nodes]
    )

    prompt = _ORDER_PROMPT.format(
        n=len(layout.nodes),
        system_name=system_name,
        stakeholder_info=stakeholder_info,
    )

    raw = await asyncio.to_thread(
        _invoke_bedrock, prompt, access_key, secret_key, region, model_id
    )

    result = _extract_json(raw)
    ordered = [sid for sid in result.get("order", []) if sid in {n.id for n in layout.nodes}]
    for n in layout.nodes:
        if n.id not in ordered:
            ordered.append(n.id)

    if len(ordered) == len(layout.nodes):
        new_layout = calculate_layout(ordered, flows)
        new_layout.center = layout.center
        return new_layout

    return layout


def _invoke_bedrock(
    prompt: str, access_key: str, secret_key: str, region: str, model_id: str,
) -> str:
    import boto3
    client = boto3.client(
        "bedrock-runtime", region_name=region,
        aws_access_key_id=access_key, aws_secret_access_key=secret_key,
    )
    response = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 256, "temperature": 0.0},
    )
    return response["output"]["message"]["content"][0]["text"].strip()


def _extract_json(text: str) -> dict:
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text.strip(), re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {}


# ── Serialization ──────────────────────────────────────────────────────────────

def layout_to_context_dict(layout: ContextLayout) -> dict:
    nodes = [
        {
            "id": "center",
            "position": {"x": layout.center.x, "y": layout.center.y},
            "width": layout.center.width,
            "height": layout.center.height,
        }
    ]
    for n in layout.nodes:
        nodes.append({
            "id": n.id,
            "position": {"x": n.x, "y": n.y},
            "width": n.width,
            "height": n.height,
        })

    edges = []
    for e in layout.edges:
        entry: dict = {"id": e.id}
        if e.label_offset_x or e.label_offset_y:
            entry["label_offset"] = {"x": e.label_offset_x, "y": e.label_offset_y}
        edges.append(entry)

    return {"nodes": nodes, "edges": edges}
