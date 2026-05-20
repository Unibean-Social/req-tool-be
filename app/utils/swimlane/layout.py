"""
Swimlane layout engine.

1: calculate_layout   — assign x, y, width, height per node
2: review_positions   — Bedrock AI optimizer with rule-based fallback
         layout_to_swimlane_dict — serialize SwimlaneLayout → JSONB dict
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

# Base dimensions per notation (width, height)
# decision/merge: fixed diamond — no text inside per UML standard; guards go on edges
NODE_DIMS: dict[str, tuple[int, int]] = {
    "action":       (200, 60),
    "decision":     (80,  80),
    "fork":         (160, 20),
    "join":         (160, 20),
    "merge":        (60,  60),
    "objectNode":   (180, 70),
    "initial_node": (30,  30),
    "final_node":   (30,  30),
}

# Vertical padding between node centers
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

DECISION_NEXT_EXTRA = 20
MIN_LANE_WIDTH = 280
LANE_SIDE_PADDING = 60
MAX_NODE_WIDTH = 320
CHAR_WIDTH = 8.5
LINE_HEIGHT = 22
LABEL_H_PADDING = 24
LABEL_V_PADDING = 20


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class LaneSpec:
    id: str
    index: int
    width: float = 300.0
    x_left: float = 0.0
    x_center: float = 0.0

    @property
    def x_right(self) -> float:
        return self.x_left + self.width


@dataclass
class NodeLayout:
    id: str
    lane_id: str
    notation: str
    label: str | None = None
    yes_guard: str | None = None  # decision: "[Condition met]"
    no_guard: str | None = None   # decision: "[Condition not met]"
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


# ── Node sizing ────────────────────────────────────────────────────────────────

def estimate_node_size(notation: str, label: str | None) -> tuple[float, float]:
    """Return (width, height) for a node. Only action/objectNode expand with label length."""
    base_w, base_h = NODE_DIMS.get(notation, NODE_DIMS["action"])

    # Nodes without label text (UML: guards on edges, not inside node)
    if notation in ("decision", "merge", "fork", "join", "initial_node", "final_node") or not label:
        return float(base_w), float(base_h)

    # action, objectNode: rectangular, wraps text
    chars = len(label)
    needed_w = min(chars * CHAR_WIDTH + LABEL_H_PADDING, MAX_NODE_WIDTH)
    w = max(float(base_w), needed_w)

    chars_per_line = max(1, int((w - LABEL_H_PADDING) / CHAR_WIDTH))
    lines = math.ceil(chars / chars_per_line)
    lines = min(lines, 5)

    h = max(float(base_h), lines * LINE_HEIGHT + LABEL_V_PADDING)
    return round(w, 1), round(h, 1)


# ── Lane geometry ──────────────────────────────────────────────────────────────

def _compute_lane_geometry(
    lanes: list[LaneSpec],
    nodes_by_lane: dict[str, list[NodeLayout]],
) -> None:
    cumulative_x = 0.0
    for lane in lanes:
        lane_nodes = nodes_by_lane.get(lane.id, [])
        max_node_w = max((n.width for n in lane_nodes), default=float(NODE_DIMS["action"][0]))
        lane.width = max(MIN_LANE_WIDTH, max_node_w + LANE_SIDE_PADDING * 2)
        lane.x_left = cumulative_x
        lane.x_center = cumulative_x + lane.width / 2
        cumulative_x += lane.width


# ── 1: calculate_layout ──────────────────────────────────────────────────

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
            label=action.get("label"),
            yes_guard=action.get("yes_guard"),
            no_guard=action.get("no_guard"),
            width=w, height=h, index=i,
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
        lane = lane_map.get(node.lane_id, first_lane)
        if i > 0:
            prev = pre_nodes[i - 1]
            extra = DECISION_NEXT_EXTRA if node.notation == "decision" else 0
            gap = prev.height / 2 + PADDING.get(prev.notation, 80) + node.height / 2 + extra
            global_y += gap
        node.x = lane.x_center
        node.y = round(global_y, 1)
        nodes.append(node)

    last = nodes[-1] if nodes else initial
    final_y = last.y + last.height / 2 + PADDING.get(last.notation, 80) + 15
    w_fin, h_fin = NODE_DIMS["final_node"]
    last_lane = lane_map.get(last.lane_id, first_lane)
    final = NodeLayout(
        id="end", lane_id=last.lane_id, notation="final_node",
        x=last_lane.x_center, y=round(final_y, 1),
        width=float(w_fin), height=float(h_fin),
    )

    flows = _build_flows(actions, nodes, initial, final, lanes)
    return SwimlaneLayout(lanes=lanes, initial_node=initial, final_node=final, nodes=nodes, flows=flows)


def _resolve_decision_guards(node: NodeLayout) -> tuple[str, str]:
    """Return (yes_guard, no_guard) for a decision node, deriving from label if not pre-computed."""
    if node.yes_guard and node.no_guard:
        return node.yes_guard, node.no_guard

    label = (node.label or "").strip().strip("[]")
    if not label:
        return "[Yes]", "[No]"

    for pattern, pos, neg in _GUARD_ANTONYMS:
        if re.match(pattern, label, re.IGNORECASE):
            matched = re.match(pattern, label, re.IGNORECASE).group(0)
            rest = label[len(matched):]
            return f"[{pos}{rest}]", f"[{neg}{rest}]"

    first = label[0].lower() + label[1:] if label else label
    if re.search(r"[àáâãèéêìíòóôõùúýăđơưạặấầẩẫắằẳẵặ]", label, re.IGNORECASE):
        return f"[{label}]", f"[Không {first}]"
    return f"[{label}]", f"[Not {first}]"


def _find_convergence(seq: list[NodeLayout], from_index: int) -> NodeLayout:
    """Find the nearest merge or final node at or after seq[from_index]."""
    for node in seq[from_index:]:
        if node.notation in ("merge", "final_node"):
            return node
    return seq[-1]


def _find_next_join(seq: list[NodeLayout], from_index: int) -> NodeLayout:
    """Find the nearest join node at or after seq[from_index]. Falls back to final."""
    for node in seq[from_index:]:
        if node.notation == "join":
            return node
    return seq[-1]


# Antonym table mirrored from label.py so layout has no external import
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


def _build_flows(
    actions: list[dict],
    nodes: list[NodeLayout],
    initial: NodeLayout,
    final: NodeLayout,
    lanes: list[LaneSpec],
) -> list[FlowLayout]:
    raw_flows: list[dict] = []
    for action in sorted(actions, key=lambda a: a.get("order", 0)):
        raw_flows.extend(action.get("edges", []))

    if raw_flows:
        return [
            FlowLayout(
                id=edge["id"],
                source=edge["source"], target=edge["target"],
                source_handle=edge.get("source_handle"),
                target_handle=edge.get("target_handle"),
                guard=edge.get("guard"),
                flow_type=edge.get("flow_type", "control"),
            )
            for edge in raw_flows
        ]

    # Auto-generate with proper decision branching and fork/join parallel sections
    seq: list[NodeLayout] = [initial] + nodes + [final]
    flows: list[FlowLayout] = []
    emitted: set[tuple[str, str]] = set()

    def emit(
        src: str, tgt: str,
        guard: str | None = None,
        source_handle: str | None = None,
        target_handle: str | None = None,
    ) -> None:
        key = (src, tgt)
        if key not in emitted:
            flows.append(FlowLayout(
                id=f"f-{src}-{tgt}",
                source=src, target=tgt,
                guard=guard,
                source_handle=source_handle,
                target_handle=target_handle,
            ))
            emitted.add(key)

    # Pre-scan: find fork→join pairs and mark indices to skip in regular loop.
    # skip_regular[i] = True means seq[i]→seq[i+1] is handled by fork logic.
    skip_regular: set[int] = set()

    for i, node in enumerate(seq):
        if node.notation != "fork":
            continue
        join_node = _find_next_join(seq, i + 1)
        join_idx = next(k for k, n in enumerate(seq) if n.id == join_node.id)
        parallel = seq[i + 1 : join_idx]  # nodes strictly between fork and join

        # Split parallel nodes into two branches (evenly by position)
        half = max(1, len(parallel) // 2) if len(parallel) > 1 else len(parallel)
        branch_a = parallel[:half]
        branch_b = parallel[half:]

        # fork → branch_a
        if branch_a:
            emit(node.id, branch_a[0].id, source_handle="bottom_left")
            for k in range(len(branch_a) - 1):
                emit(branch_a[k].id, branch_a[k + 1].id)
            emit(branch_a[-1].id, join_node.id, target_handle="top_left")
        else:
            emit(node.id, join_node.id, source_handle="bottom_left", target_handle="top_left")

        # fork → branch_b (or directly to join for empty branch)
        if branch_b:
            emit(node.id, branch_b[0].id, source_handle="bottom_right")
            for k in range(len(branch_b) - 1):
                emit(branch_b[k].id, branch_b[k + 1].id)
            emit(branch_b[-1].id, join_node.id, target_handle="top_right")
        else:
            emit(node.id, join_node.id, source_handle="bottom_right", target_handle="top_right")

        # Mark fork through (join-1) so regular loop skips these outgoing edges
        for k in range(i, join_idx):
            skip_regular.add(k)

    # Regular sequential pass (decisions get branching; fork/join segment skipped)
    for j, curr in enumerate(seq[:-1]):
        if j in skip_regular:
            continue

        next_node = seq[j + 1]

        if curr.notation == "decision":
            yes_g, no_g = _resolve_decision_guards(curr)
            emit(curr.id, next_node.id, guard=yes_g)
            alt = _find_convergence(seq, j + 1)
            if alt.id != next_node.id:
                key = (curr.id, alt.id)
                if key not in emitted:
                    flows.append(FlowLayout(
                        id=f"f-{curr.id}-{alt.id}-no",
                        source=curr.id, target=alt.id,
                        guard=no_g,
                    ))
                    emitted.add(key)
        else:
            emit(curr.id, next_node.id)

    return flows


# ── 2: review_positions ──────────────────────────────────────────────────

_REVIEW_PROMPT = """\
You are a UML swimlane diagram layout optimizer. A rule-based engine has produced an initial \
layout. Your role is to reason about the full diagram and suggest improved positions that make \
it cleaner, more readable, and visually balanced — not just fix violations.

## Diagram context
- Lanes: {lane_count} | Nodes: {node_count} (incl. start/end) | Canvas width: {canvas_width}px
- Reading direction: top-to-bottom, left-to-right across lanes

## Lane geometry (fixed — do not change x_left/x_right boundaries)
{lane_info}

## Current node positions
{nodes_json}

## Flow topology (edges, guards, handles)
{flows_json}

## Optimization goals — reason about ALL of these holistically

### 1. Label fit (action / objectNode only — decision/merge/fork/join have no text inside)
- char_width=8.5px, h_padding=24px, v_padding=20px, line_height=22px, max_lines=5
- action/objectNode: usable_w = width - 24; lines = ceil(label_chars / floor(usable_w / 8.5))
  required_height = lines * 22 + 20; cap width at {max_node_width}px
- decision diamond: fixed 80×80 — no label inside; guard text lives on outgoing edges

### 2. Visual breathing room
- Minimum gap between consecutive nodes (same lane): prev.height/2 + 80 + next.height/2
- Decision nodes deserve extra space: add 30px before AND after each decision
- Fork/join bars (height=20): add 20px extra above and below
- Prefer consistent rhythm — if most gaps in a lane are ~120px, align outliers to that

### 3. Cross-lane alignment
- Nodes connected by a horizontal edge (source_handle=left/right) should ideally share the same y \
  so the edge is level — adjust either node's y within its spacing constraints
- Fork output targets in different lanes should be at the same y as the fork node ± 40px

### 4. Node sizing
- action/objectNode with very long labels (> 60 chars): prefer wider over taller (max width first)

### 5. Lane x centering
- Each node's x must be the lane's x_center
- Only deviate if the node is wider than the lane — do not violate lane_x_left+20 / lane_x_right-20

## Hard constraints (never violate)
- x - width/2 >= lane_x_left + 20
- x + width/2 <= lane_x_right - 20
- y > 0 for all nodes
- Preserve topological order: if node A flows into node B in the same lane, A.y < B.y

## Output
Return ONLY compact JSON — no explanation, no markdown, no commentary.
Only include nodes where you are changing at least one value.

{{"nodes": [{{"id": "...", "x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}}]}}

If the layout is already optimal: {{"nodes": []}}\
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


def fix_layout(layout: SwimlaneLayout, max_iterations: int = 3) -> SwimlaneLayout:
    """Rule-based conflict resolution — no external deps. Always safe to call."""
    return _rule_based_review(layout, max_iterations)


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
        {"id": ln.id, "index": ln.index, "x_left": ln.x_left,
         "x_center": ln.x_center, "x_right": ln.x_right, "width": ln.width}
        for ln in layout.lanes
    ]
    nodes_payload = [
        {"id": n.id, "lane_id": n.lane_id, "notation": n.notation,
         "label": n.label or "", "label_chars": len(n.label or ""),
         "x": n.x, "y": n.y, "width": n.width, "height": n.height}
        for n in all_nodes
    ]
    flows_payload = [
        {"id": f.id, "source": f.source, "target": f.target,
         "source_handle": f.source_handle, "guard": f.guard}
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

    result = _extract_json_from_response(raw)
    for adj in result.get("nodes", []):
        node = node_map.get(adj.get("id", ""))
        if node:
            node.y = float(adj.get("y", node.y))
            node.width = float(adj.get("width", node.width))
            node.height = float(adj.get("height", node.height))
            new_x = float(adj.get("x", node.x))
            lane = next((ln for ln in layout.lanes if ln.id == node.lane_id), None)
            if lane and (lane.x_left + node.width / 2 + 20 <= new_x <= lane.x_right - node.width / 2 - 20):
                node.x = new_x

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

    by_lane: dict[str, list[NodeLayout]] = {}
    for n in all_nodes:
        by_lane.setdefault(n.lane_id, []).append(n)

    for lane_nodes in by_lane.values():
        sorted_nodes = sorted(lane_nodes, key=lambda n: n.y)
        for a, b in zip(sorted_nodes, sorted_nodes[1:]):
            min_gap = a.height / 2 + 80 + b.height / 2
            if b.y - a.y < min_gap:
                conflicts.append({
                    "type": "overlap", "node_id": b.id,
                    "delta": min_gap - (b.y - a.y),
                    "desc": f"{a.id}↔{b.id} gap {b.y-a.y:.0f}px < {min_gap:.0f}px",
                })

    for n in all_nodes:
        lane = lane_map.get(n.lane_id)
        if lane and (n.x - n.width / 2 < lane.x_left + 20 or n.x + n.width / 2 > lane.x_right - 20):
            conflicts.append({
                "type": "out_of_lane", "node_id": n.id, "delta": 0,
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
                needed = node.width + LANE_SIDE_PADDING * 2
                if needed > lane.width:
                    delta = needed - lane.width
                    lane.width += delta
                    lane.x_center = lane.x_left + lane.width / 2
                    for ln in layout.lanes:
                        if ln.index > lane.index:
                            ln.x_left += delta
                            ln.x_center = ln.x_left + ln.width / 2
                    for n in layout.nodes + [layout.initial_node, layout.final_node]:
                        affected = next((ln for ln in layout.lanes if ln.id == n.lane_id), None)
                        if affected:
                            n.x = affected.x_center

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
                "label": n.label if n.notation in ("action", "objectNode") else None,
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
                "label": None,
                "flow_type": f.flow_type,
                "label_offset": None,
                "waypoints": None,
            }
            for f in layout.flows
        ],
        "layout": None,
    }
