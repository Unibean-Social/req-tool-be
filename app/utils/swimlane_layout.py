"""
Swimlane layout calculator — Stage 4 + Stage 5 of the swimlane generation pipeline.

Stage 4: calculate_layout  — assign x, y, width, height dynamically based on label + notation
Stage 5: review_positions  — Bedrock AI review with rule-based fallback
"""
from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

NotationType = Literal["action", "objectNode", "decision", "merge", "fork", "join"]

# ── Constants ──────────────────────────────────────────────────────────────────

# Base dimensions per notation (width, height) when no label or short label
NODE_DIMS: dict[str, tuple[int, int]] = {
    "action":       (200, 60),
    "decision":     (160, 80),
    "fork":         (160, 20),
    "join":         (160, 20),
    "merge":        (120, 30),
    "objectNode":   (180, 70),
    "initial_node": (30,  30),
    "final_node":   (30,  30),
}

# Vertical padding between node centers (added to half-heights)
PADDING: dict[str, int] = {
    "action":       80,
    "decision":     90,
    "fork":         80,
    "join":         80,
    "merge":        80,
    "objectNode":   80,
    "initial_node": 60,
    "final_node":   60,
}

DECISION_NEXT_EXTRA = 20    # extra gap before a decision node
MIN_LANE_WIDTH = 280        # minimum lane width in px
LANE_SIDE_PADDING = 60      # padding left+right of widest node in lane
MAX_NODE_WIDTH = 320        # cap node width — wider than this wraps to more lines
CHAR_WIDTH = 8.5            # estimated px per character
LINE_HEIGHT = 22            # px per text line
LABEL_H_PADDING = 24        # total horizontal inner padding of text area
LABEL_V_PADDING = 20        # total vertical inner padding of text area


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class LaneSpec:
    id: str
    index: int
    width: float = 300.0
    x_left: float = 0.0    # left edge of lane
    x_center: float = 0.0  # center x (set after width calculation)

    @property
    def x_right(self) -> float:
        return self.x_left + self.width


@dataclass
class NodeLayout:
    id: str
    lane_id: str
    notation: str
    label: str | None = None
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    index: int | None = None

    def bbox(self) -> tuple[float, float, float, float]:
        hw, hh = self.width / 2, self.height / 2
        return (self.x - hw, self.y - hh, self.x + hw, self.y + hh)


@dataclass
class FlowLayout:
    id: str
    source: str
    target: str
    source_handle: str | None = None
    target_handle: str | None = None
    guard: str | None = None
    flow_type: str = "control"


@dataclass
class SwimlaneLayout:
    lanes: list[LaneSpec]
    initial_node: NodeLayout
    final_node: NodeLayout
    nodes: list[NodeLayout]
    flows: list[FlowLayout]


class LayoutConflictError(Exception):
    pass


# ── Label-aware node sizing ────────────────────────────────────────────────────

def estimate_node_size(notation: str, label: str | None) -> tuple[float, float]:
    """Return (width, height) accounting for label length and notation shape."""
    base_w, base_h = NODE_DIMS.get(notation, NODE_DIMS["action"])

    # Nodes that don't display text as a body label
    if notation in ("fork", "join", "merge", "initial_node", "final_node") or not label:
        return float(base_w), float(base_h)

    chars = len(label)

    if notation == "decision":
        # Diamond: usable text area is ~60% of width due to shape
        usable_w = max(base_w * 0.6, 80.0)
        chars_per_line = max(1, int((usable_w - LABEL_H_PADDING) / CHAR_WIDTH))
        lines = math.ceil(chars / chars_per_line)
        # Widen diamond if label is long
        needed_w = min(chars * CHAR_WIDTH * 0.6 + LABEL_H_PADDING + 40, MAX_NODE_WIDTH)
        w = max(float(base_w), needed_w)
        # Extra height per extra line (diamond needs proportionally more)
        extra_lines = max(0, lines - 1)
        h = max(float(base_h), base_h + extra_lines * LINE_HEIGHT * 1.3)
        return round(w, 1), round(h, 1)

    # action, objectNode: rectangular, wraps text
    needed_w = min(chars * CHAR_WIDTH + LABEL_H_PADDING, MAX_NODE_WIDTH)
    w = max(float(base_w), needed_w)

    chars_per_line = max(1, int((w - LABEL_H_PADDING) / CHAR_WIDTH))
    lines = math.ceil(chars / chars_per_line)
    lines = min(lines, 5)

    h = max(float(base_h), lines * LINE_HEIGHT + LABEL_V_PADDING)
    return round(w, 1), round(h, 1)


# ── Lane width calculation ─────────────────────────────────────────────────────

def _compute_lane_geometry(
    lanes: list[LaneSpec],
    nodes_by_lane: dict[str, list[NodeLayout]],
) -> None:
    """Mutate lanes: set width and x_left/x_center based on widest node in each lane."""
    cumulative_x = 0.0
    for lane in lanes:
        lane_nodes = nodes_by_lane.get(lane.id, [])
        max_node_w = max((n.width for n in lane_nodes), default=float(NODE_DIMS["action"][0]))
        lane.width = max(MIN_LANE_WIDTH, max_node_w + LANE_SIDE_PADDING * 2)
        lane.x_left = cumulative_x
        lane.x_center = cumulative_x + lane.width / 2
        cumulative_x += lane.width


# ── Stage 4: calculate_layout ──────────────────────────────────────────────────

def calculate_layout(
    actions: list[dict],  # [{id, lane_id, notation, label?, order}]
    lane_ids: list[str],
) -> SwimlaneLayout:
    lanes = [LaneSpec(id=lid, index=i) for i, lid in enumerate(lane_ids)]
    lane_map = {ln.id: ln for ln in lanes}
    sorted_actions = sorted(actions, key=lambda a: a.get("order", 0))
    first_lane = lanes[0] if lanes else LaneSpec(id="lane-default", index=0)

    # Pass 1: estimate node sizes
    pre_nodes: list[NodeLayout] = []
    for i, action in enumerate(sorted_actions):
        notation = action.get("notation", "action")
        w, h = estimate_node_size(notation, action.get("label"))
        lid = action["lane_id"]
        pre_nodes.append(NodeLayout(
            id=str(action["id"]), lane_id=lid, notation=notation,
            label=action.get("label"), width=w, height=h, index=i,
        ))

    # Pass 2: compute lane widths from node sizes
    nodes_by_lane: dict[str, list[NodeLayout]] = {}
    for n in pre_nodes:
        nodes_by_lane.setdefault(n.lane_id, []).append(n)
    _compute_lane_geometry(lanes, nodes_by_lane)

    # Pass 3: assign x, y positions
    w_init, h_init = NODE_DIMS["initial_node"]
    initial = NodeLayout(
        id="start", lane_id=first_lane.id, notation="initial_node",
        x=first_lane.x_center, y=50.0, width=float(w_init), height=float(h_init),
    )

    global_y = 50.0 + h_init / 2 + PADDING["initial_node"] + 30

    nodes: list[NodeLayout] = []
    for i, (action, node) in enumerate(zip(sorted_actions, pre_nodes)):
        notation = node.notation
        lane = lane_map.get(node.lane_id, first_lane)

        if i > 0:
            prev = pre_nodes[i - 1]
            extra = DECISION_NEXT_EXTRA if notation == "decision" else 0
            gap = prev.height / 2 + PADDING.get(prev.notation, 80) + node.height / 2 + extra
            global_y += gap

        node.x = lane.x_center
        node.y = round(global_y, 1)
        nodes.append(node)

    # Final node
    last = nodes[-1] if nodes else initial
    final_y = last.y + last.height / 2 + PADDING.get(last.notation, 80) + 15
    w_fin, h_fin = NODE_DIMS["final_node"]
    last_lane = lane_map.get(last.lane_id, first_lane)
    final = NodeLayout(
        id="end", lane_id=last.lane_id, notation="final_node",
        x=last_lane.x_center, y=round(final_y, 1),
        width=float(w_fin), height=float(h_fin),
    )

    # Build flows
    flows = _build_flows(actions, nodes, initial, final, lanes)

    return SwimlaneLayout(lanes=lanes, initial_node=initial, final_node=final, nodes=nodes, flows=flows)


def _build_flows(
    actions: list[dict],
    nodes: list[NodeLayout],
    initial: NodeLayout,
    final: NodeLayout,
    lanes: list[LaneSpec],
) -> list[FlowLayout]:
    flows: list[FlowLayout] = []

    raw_flows: list[dict] = []
    for action in sorted(actions, key=lambda a: a.get("order", 0)):
        for edge in action.get("edges", []):
            raw_flows.append(edge)

    if not raw_flows:
        seq: list[NodeLayout] = [initial] + nodes + [final]
        for j in range(len(seq) - 1):
            flows.append(FlowLayout(
                id=f"f-{seq[j].id}-{seq[j+1].id}",
                source=seq[j].id, target=seq[j+1].id,
            ))
        return flows

    for edge in raw_flows:
        flows.append(FlowLayout(
            id=edge["id"],
            source=edge["source"], target=edge["target"],
            source_handle=edge.get("source_handle"),
            target_handle=edge.get("target_handle"),
            guard=edge.get("guard"),
            flow_type=edge.get("flow_type", "control"),
        ))

    return flows


# ── Stage 5: review_positions ──────────────────────────────────────────────────

_REVIEW_PROMPT = """\
You are a UML swimlane diagram layout validator. You receive exact node positions calculated \
by a rule-based engine. Your job is to detect violations only — do NOT invent new positions, \
do NOT move nodes unless a rule below is provably violated by the given numbers.

## Context
- Total lanes: {lane_count}
- Total nodes: {node_count} (including start/end)
- Canvas width: {canvas_width}px

## Lane geometry (authoritative — do not change lane boundaries)
{lane_info}

## Nodes (id, notation, lane, current x/y/width/height, label length in chars)
{nodes_json}

## Flows (edges between nodes)
{flows_json}

## Validation rules — check each node against these, using the EXACT numbers above

1. **Label overflow** — char_width=8.5px, h_padding=24px, v_padding=20px, line_height=22px
   - action/objectNode: usable_w = width - 24; chars_per_line = floor(usable_w / 8.5)
     lines = ceil(label_chars / chars_per_line); required_height = lines * 22 + 20
     If current height < required_height → set height = required_height
   - decision: usable_w = width * 0.6 - 24; apply same formula; cap width at {max_node_width}px

2. **Lane boundary** — node center x must satisfy:
   - x - width/2 >= lane_x_left + 20  AND  x + width/2 <= lane_x_right - 20
   - If violated: set x = lane_x_center (use the x_center from Lane geometry above)

3. **Vertical spacing** — for nodes in the SAME lane, sorted by y:
   - min_gap = prev.height/2 + 80 + next.height/2
   - If next.y - prev.y < min_gap → set next.y = prev.y + min_gap (cascade down)

4. **Aspect ratio** — for action/objectNode: if height < 42 (line_height + v_padding) → set height = 42

## STRICT output rules
- Only include nodes where you changed at least one value
- Do NOT change x unless rule 2 is violated
- Do NOT guess or estimate — use only the numbers provided above
- Do NOT add explanation, markdown, or commentary

Return exactly:
{{"nodes": [{{"id": "...", "x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}}]}}

If no violations found: {{"nodes": []}}\
"""


async def review_positions(
    layout: SwimlaneLayout,
    access_key: str = "",
    secret_key: str = "",
    region: str = "us-east-1",
    model_id: str = "google.gemma-3-4b-it",
    max_iterations: int = 3,
) -> SwimlaneLayout:
    if access_key and secret_key:
        try:
            layout = await _bedrock_review(layout, access_key, secret_key, region, model_id)
        except Exception as exc:
            logger.warning("Bedrock layout review failed, falling back to rule-based: %s", exc)
            layout = _rule_based_review(layout, max_iterations)
    else:
        layout = _rule_based_review(layout, max_iterations)
    return layout


def _rule_based_review(layout: SwimlaneLayout, max_iterations: int = 3) -> SwimlaneLayout:
    for _ in range(max_iterations):
        conflicts = _find_conflicts(layout)
        if not conflicts:
            return layout
        layout = _auto_fix(layout, conflicts)

    remaining = _find_conflicts(layout)
    if remaining:
        details = "; ".join(f"{c['type']}: {c['desc']}" for c in remaining)
        raise LayoutConflictError(f"Layout conflicts after {max_iterations} iterations: {details}")
    return layout


def _extract_json_from_response(text: str) -> dict:
    """Extract a JSON object from Bedrock response — handles prose, code fences, and bare JSON."""
    stripped = text.strip()
    if not stripped:
        return {}
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{.*\}", stripped, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {}


async def _bedrock_review(
    layout: SwimlaneLayout,
    access_key: str,
    secret_key: str,
    region: str,
    model_id: str,
) -> SwimlaneLayout:
    import asyncio

    all_nodes = [layout.initial_node] + layout.nodes + [layout.final_node]
    node_map = {n.id: n for n in all_nodes}

    lane_info = [
        {
            "id": ln.id,
            "index": ln.index,
            "x_left": ln.x_left,
            "x_center": ln.x_center,
            "x_right": ln.x_right,
            "width": ln.width,
        }
        for ln in layout.lanes
    ]
    nodes_payload = [
        {
            "id": n.id,
            "lane_id": n.lane_id,
            "notation": n.notation,
            "label": n.label or "",
            "label_chars": len(n.label or ""),
            "x": n.x,
            "y": n.y,
            "width": n.width,
            "height": n.height,
        }
        for n in all_nodes
    ]
    flows_payload = [
        {
            "id": f.id,
            "source": f.source,
            "target": f.target,
            "source_handle": f.source_handle,
            "guard": f.guard,
        }
        for f in layout.flows
    ]

    canvas_width = layout.lanes[-1].x_right if layout.lanes else 600.0
    prompt = _REVIEW_PROMPT.format(
        lane_count=len(layout.lanes),
        node_count=len(all_nodes),
        canvas_width=round(canvas_width),
        lane_info=json.dumps(lane_info, indent=2),
        nodes_json=json.dumps(nodes_payload, indent=2),
        flows_json=json.dumps(flows_payload, indent=2),
        max_node_width=MAX_NODE_WIDTH,
    )

    raw = await asyncio.to_thread(
        _invoke_bedrock_review, prompt, access_key, secret_key, region, model_id
    )

    result: dict = _extract_json_from_response(raw)
    node_adjustments: list[dict] = result.get("nodes", [])
    flow_adjustments: list[dict] = result.get("flows", [])

    for adj in node_adjustments:
        node = node_map.get(adj.get("id", ""))
        if node:
            node.y = float(adj.get("y", node.y))
            node.width = float(adj.get("width", node.width))
            node.height = float(adj.get("height", node.height))
            # x: only accept if it stays within the node's lane
            new_x = float(adj.get("x", node.x))
            lane = next((ln for ln in layout.lanes if ln.id == node.lane_id), None)
            if lane and (lane.x_left + node.width / 2 + 20 <= new_x <= lane.x_right - node.width / 2 - 20):
                node.x = new_x
            # else: ignore — x stays at lane center

    # Safety net: single rule-based pass after LLM — silent (no raise on remaining conflicts)
    conflicts = _find_conflicts(layout)
    if conflicts:
        layout = _auto_fix(layout, conflicts)
    return layout


def _invoke_bedrock_review(
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
        inferenceConfig={"maxTokens": 2048, "temperature": 0.0},
    )
    return response["output"]["message"]["content"][0]["text"].strip()


# ── Rule-based conflict detection + auto-fix ───────────────────────────────────

def _find_conflicts(layout: SwimlaneLayout) -> list[dict]:
    conflicts: list[dict] = []
    all_nodes = layout.nodes + [layout.initial_node, layout.final_node]
    lane_map = {ln.id: ln for ln in layout.lanes}

    # 1. Vertical overlap in same lane
    by_lane: dict[str, list[NodeLayout]] = {}
    for n in all_nodes:
        by_lane.setdefault(n.lane_id, []).append(n)

    for lane_id, lane_nodes in by_lane.items():
        for a, b in zip(
            sorted(lane_nodes, key=lambda n: n.y),
            sorted(lane_nodes, key=lambda n: n.y)[1:],
        ):
            min_gap = a.height / 2 + 80 + b.height / 2
            if b.y - a.y < min_gap:
                conflicts.append({
                    "type": "overlap",
                    "node_id": b.id,
                    "delta": min_gap - (b.y - a.y),
                    "desc": f"{a.id}↔{b.id} gap {b.y-a.y:.0f}px < {min_gap:.0f}px",
                })

    # 2. Lane boundary violation
    for n in all_nodes:
        lane = lane_map.get(n.lane_id)
        if lane:
            if n.x - n.width / 2 < lane.x_left + 20 or n.x + n.width / 2 > lane.x_right - 20:
                conflicts.append({
                    "type": "out_of_lane",
                    "node_id": n.id,
                    "delta": 0,
                    "desc": f"node {n.id} (w={n.width}) exceeds lane [{lane.x_left},{lane.x_right}]",
                })

    return conflicts


def _auto_fix(layout: SwimlaneLayout, conflicts: list[dict]) -> SwimlaneLayout:
    node_map = {n.id: n for n in layout.nodes + [layout.initial_node, layout.final_node]}

    for c in conflicts:
        if c["type"] == "overlap":
            node = node_map.get(c["node_id"])
            if node:
                node.y += c["delta"]
                for other in layout.nodes:
                    if other.lane_id == node.lane_id and other.y > node.y and other.id != node.id:
                        other.y += c["delta"]
                layout.final_node.y = max(
                    layout.final_node.y,
                    max((n.y for n in layout.nodes), default=0) + 120,
                )

        elif c["type"] == "out_of_lane":
            node = node_map.get(c["node_id"])
            lane = next((ln for ln in layout.lanes if ln.id == (node.lane_id if node else "")), None)
            if node and lane:
                # Widen lane to fit node
                needed = node.width + LANE_SIDE_PADDING * 2
                if needed > lane.width:
                    delta = needed - lane.width
                    lane.width += delta
                    lane.x_center = lane.x_left + lane.width / 2
                    # Shift all lanes to the right of this one
                    for ln in layout.lanes:
                        if ln.index > lane.index:
                            ln.x_left += delta
                            ln.x_center = ln.x_left + ln.width / 2
                    # Re-center all nodes in affected lanes
                    for n in layout.nodes + [layout.initial_node, layout.final_node]:
                        affected_lane = next((ln for ln in layout.lanes if ln.id == n.lane_id), None)
                        if affected_lane:
                            n.x = affected_lane.x_center

    return layout


# ── Serialization ──────────────────────────────────────────────────────────────

def layout_to_swimlane_dict(layout: SwimlaneLayout, flow_id: str, title: str) -> dict:
    return {
        "id": flow_id,
        "title": title,
        "lanes": [
            {"id": ln.id, "title": ln.id, "width": ln.width, "x_left": ln.x_left}
            for ln in layout.lanes
        ],
        "initial_node": {
            "id": layout.initial_node.id,
            "lane_id": layout.initial_node.lane_id,
            "x": layout.initial_node.x,
            "y": layout.initial_node.y,
        },
        "activity_final_node": {
            "id": layout.final_node.id,
            "lane_id": layout.final_node.lane_id,
            "x": layout.final_node.x,
            "y": layout.final_node.y,
        },
        "actions": [
            {
                "id": n.id,
                "lane_id": n.lane_id,
                "notation": n.notation,
                "index": n.index,
                "x": n.x,
                "y": n.y,
                "label": n.label,
                "width": n.width,
                "height": n.height,
            }
            for n in layout.nodes
        ],
        "flows": [
            {
                "id": f.id,
                "source": f.source,
                "target": f.target,
                "source_handle": f.source_handle,
                "target_handle": f.target_handle,
                "guard": f.guard,
                "flow_type": f.flow_type,
            }
            for f in layout.flows
        ],
        "layout": None,
    }
