"""
Swimlane layout calculator — Stage 4 + Stage 5 of the swimlane generation pipeline.

Stage 4: calculate_layout  — assign x, y, width, height to each node
Stage 5: review_positions  — detect overlaps, corridor collisions; auto-fix or raise
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

NotationType = Literal["action", "objectNode", "decision", "merge", "fork", "join"]

LANE_WIDTH = 300

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

DECISION_NEXT_EXTRA = 20  # extra gap when next node is decision
MIN_CORRIDOR_OFFSET = 180  # rightmost_lane_x + this → first corridor
CORRIDOR_STEP = 60


@dataclass
class LaneSpec:
    id: str
    index: int

    @property
    def x_center(self) -> float:
        return self.index * LANE_WIDTH + LANE_WIDTH / 2


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
        """(x_min, y_min, x_max, y_max)"""
        hw, hh = self.width / 2, self.height / 2
        return (self.x - hw, self.y - hh, self.x + hw, self.y + hh)


@dataclass
class WaypointSpec:
    x: float
    y: float


@dataclass
class FlowLayout:
    id: str
    source: str
    target: str
    source_handle: str | None = None
    target_handle: str | None = None
    guard: str | None = None
    flow_type: str = "control"
    waypoints: list[WaypointSpec] = field(default_factory=list)


@dataclass
class SwimlaneLayout:
    lanes: list[LaneSpec]
    initial_node: NodeLayout
    final_node: NodeLayout
    nodes: list[NodeLayout]
    flows: list[FlowLayout]


class LayoutConflictError(Exception):
    pass


# ── Stage 4: calculate_layout ──────────────────────────────────────────────────

def calculate_layout(
    actions: list[dict],  # [{id, lane_id, notation, label?, order}]
    lane_ids: list[str],  # ordered list of lane ids
) -> SwimlaneLayout:
    lanes = [LaneSpec(id=lid, index=i) for i, lid in enumerate(lane_ids)]
    lane_map = {ln.id: ln for ln in lanes}
    rightmost_x = lanes[-1].x_center if lanes else 150.0

    w_init, h_init = NODE_DIMS["initial_node"]
    w_final, h_final = NODE_DIMS["final_node"]

    START_Y = 50.0
    first_lane = lanes[0]

    # y cursor per lane
    y_cursor: dict[str, float] = {ln.id: START_Y for ln in lanes}
    global_y = START_Y  # main vertical progression

    initial = NodeLayout(
        id="start", lane_id=first_lane.id, notation="initial_node",
        x=first_lane.x_center, y=START_Y,
        width=w_init, height=h_init,
    )
    global_y += h_init / 2 + PADDING["initial_node"] + 30  # gap to first action

    nodes: list[NodeLayout] = []
    sorted_actions = sorted(actions, key=lambda a: a.get("order", 0))

    for i, action in enumerate(sorted_actions):
        notation: str = action.get("notation", "action")
        w, h = NODE_DIMS.get(notation, NODE_DIMS["action"])
        lane_id = action["lane_id"]
        lane = lane_map.get(lane_id, first_lane)

        # Extra gap if current node is decision
        extra = 0
        if i > 0:
            prev_notation = sorted_actions[i - 1].get("notation", "action")
            extra = DECISION_NEXT_EXTRA if notation == "decision" else 0
            pad = PADDING.get(prev_notation, 80)
            prev_h = NODE_DIMS.get(prev_notation, NODE_DIMS["action"])[1]
            gap = prev_h / 2 + pad + h / 2 + extra
            global_y += gap

        node = NodeLayout(
            id=str(action["id"]),
            lane_id=lane_id,
            notation=notation,
            label=action.get("label"),
            x=lane.x_center,
            y=round(global_y, 1),
            width=w,
            height=h,
            index=i,
        )
        nodes.append(node)

    # Final node — place below last node
    last = nodes[-1] if nodes else initial
    last_pad = PADDING.get(last.notation, 80)
    final_y = last.y + last.height / 2 + last_pad + h_final / 2
    final = NodeLayout(
        id="end", lane_id=first_lane.id, notation="final_node",
        x=lane_map.get(last.lane_id, first_lane).x_center,
        y=round(final_y, 1),
        width=w_final, height=h_final,
    )

    # Build flows with reject corridors
    flows = _build_flows(actions, nodes, initial, final, rightmost_x)

    return SwimlaneLayout(lanes=lanes, initial_node=initial, final_node=final, nodes=nodes, flows=flows)


def _build_flows(
    actions: list[dict],
    nodes: list[NodeLayout],
    initial: NodeLayout,
    final: NodeLayout,
    rightmost_x: float,
) -> list[FlowLayout]:
    node_map: dict[str, NodeLayout] = {n.id: n for n in [initial, final] + nodes}
    flows: list[FlowLayout] = []
    reject_index = 0

    flows.append(FlowLayout(id="f-start-0", source="start", target=nodes[0].id if nodes else "end"))

    raw_flows: list[dict] = []
    for action in sorted(actions, key=lambda a: a.get("order", 0)):
        for edge in action.get("edges", []):
            raw_flows.append(edge)

    if not raw_flows:
        # Auto-generate linear flow
        all_nodes = nodes + [final]
        prev = initial
        for n in all_nodes:
            flows.append(FlowLayout(id=f"f-{prev.id}-{n.id}", source=prev.id, target=n.id))
            prev = n
        return flows

    for edge in raw_flows:
        src_node = node_map.get(edge["source"])
        tgt_node = node_map.get(edge["target"])
        is_reject = edge.get("source_handle") == "right"

        waypoints: list[WaypointSpec] = []
        target_handle = edge.get("target_handle")

        if is_reject and tgt_node:
            corridor_x = rightmost_x + MIN_CORRIDOR_OFFSET + reject_index * CORRIDOR_STEP
            reject_index += 1
            waypoints = [
                WaypointSpec(x=corridor_x, y=src_node.y if src_node else 0),
                WaypointSpec(x=corridor_x, y=tgt_node.y),
            ]
            target_handle = "right"
        elif src_node and tgt_node and tgt_node.x < src_node.x:
            # Cross-lane going left
            mid_y = (src_node.y + tgt_node.y) / 2
            waypoints = [
                WaypointSpec(x=tgt_node.x + 130, y=src_node.y),
                WaypointSpec(x=tgt_node.x, y=mid_y),
            ]
            target_handle = "top"

        flows.append(FlowLayout(
            id=edge["id"],
            source=edge["source"],
            target=edge["target"],
            source_handle=edge.get("source_handle"),
            target_handle=target_handle,
            guard=edge.get("guard"),
            flow_type=edge.get("flow_type", "control"),
            waypoints=waypoints,
        ))

    return flows


# ── Stage 5: review_positions ──────────────────────────────────────────────────

_REVIEW_PROMPT = """\
You are a UML swimlane diagram layout reviewer.
Review the node positions below and return adjusted positions for any node that needs repositioning.

Lane width: {lane_width}px. Lane x-centers: {lane_x_map}

Nodes (JSON):
{nodes_json}

Rules to enforce:
- Minimum gap between consecutive nodes in the same lane: ceil(a.height/2) + 80 + ceil(b.height/2)
- Add extra 20px before any decision node
- x must remain at the node's lane center — do not change x
- No two nodes in the same lane may overlap (|y_a - y_b| < min(h_a, h_b))
- Reject/alternative corridor waypoints must not intersect any node bounding box (±20px margin)

Return ONLY a compact JSON array of adjustments for nodes that need repositioning:
[{{"id": "...", "x": 0.0, "y": 0.0}}, ...]
If no adjustments are needed, return exactly: []
Do not include any explanation or extra text.\
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


async def _bedrock_review(
    layout: SwimlaneLayout,
    access_key: str,
    secret_key: str,
    region: str,
    model_id: str,
) -> SwimlaneLayout:
    import asyncio
    import json

    all_nodes = [layout.initial_node] + layout.nodes + [layout.final_node]
    nodes_payload = [
        {"id": n.id, "lane_id": n.lane_id, "notation": n.notation,
         "x": n.x, "y": n.y, "width": n.width, "height": n.height}
        for n in all_nodes
    ]
    lane_x_map = {ln.id: ln.x_center for ln in layout.lanes}
    prompt = _REVIEW_PROMPT.format(
        lane_width=LANE_WIDTH,
        lane_x_map=json.dumps(lane_x_map),
        nodes_json=json.dumps(nodes_payload, indent=2),
    )

    raw = await asyncio.to_thread(
        _invoke_bedrock_review, prompt, access_key, secret_key, region, model_id
    )

    adjustments: list[dict] = json.loads(raw) if raw.strip() not in ("[]", "") else []
    if not adjustments:
        return layout

    node_map = {n.id: n for n in all_nodes}
    for adj in adjustments:
        node = node_map.get(adj.get("id", ""))
        if node:
            node.y = float(adj.get("y", node.y))
            # x is ignored — must stay at lane center

    # Run rule-based pass after LLM to catch anything the LLM missed
    return _rule_based_review(layout, max_iterations=1)


def _invoke_bedrock_review(
    prompt: str,
    access_key: str,
    secret_key: str,
    region: str,
    model_id: str,
) -> str:
    import boto3

    client = boto3.client(
        "bedrock-runtime",
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    response = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 1024, "temperature": 0.0},
    )
    return response["output"]["message"]["content"][0]["text"].strip()


def _find_conflicts(layout: SwimlaneLayout) -> list[dict]:
    conflicts: list[dict] = []
    all_nodes = layout.nodes + [layout.initial_node, layout.final_node]

    by_lane: dict[str, list[NodeLayout]] = {}
    for n in all_nodes:
        by_lane.setdefault(n.lane_id, []).append(n)

    for lane_id, lane_nodes in by_lane.items():
        sorted_nodes = sorted(lane_nodes, key=lambda n: n.y)
        for i in range(len(sorted_nodes) - 1):
            a, b = sorted_nodes[i], sorted_nodes[i + 1]
            min_gap = a.height / 2 + 80 + b.height / 2
            actual_gap = b.y - a.y
            if actual_gap < min_gap:
                conflicts.append({
                    "type": "overlap",
                    "desc": f"nodes {a.id} and {b.id} in lane {lane_id}: gap={actual_gap:.0f} < min={min_gap:.0f}",
                    "node_id": b.id,
                    "delta": min_gap - actual_gap,
                })

    # Corridor collision: check reject waypoints don't pass through node bboxes
    node_map = {n.id: n for n in all_nodes}
    for flow in layout.flows:
        if not flow.waypoints:
            continue
        for wp in flow.waypoints:
            for n in all_nodes:
                x_min, y_min, x_max, y_max = n.bbox()
                if x_min - 20 <= wp.x <= x_max + 20 and y_min - 20 <= wp.y <= y_max + 20:
                    conflicts.append({
                        "type": "corridor_collision",
                        "desc": f"waypoint ({wp.x},{wp.y}) of flow {flow.id} passes through node {n.id}",
                        "flow_id": flow.id,
                        "delta": 0,
                    })

    return conflicts


def _auto_fix(layout: SwimlaneLayout, conflicts: list[dict]) -> SwimlaneLayout:
    node_map = {n.id: n for n in layout.nodes + [layout.initial_node, layout.final_node]}

    for conflict in conflicts:
        if conflict["type"] == "overlap":
            node = node_map.get(conflict["node_id"])
            if node:
                node.y += conflict["delta"]
                # Cascade: push all nodes below this one in the same lane
                for other in layout.nodes:
                    if other.lane_id == node.lane_id and other.y > node.y and other.id != node.id:
                        other.y += conflict["delta"]
                layout.final_node.y = max(
                    layout.final_node.y,
                    max((n.y for n in layout.nodes), default=0) + 120,
                )

    return layout


# ── Serialization helper ───────────────────────────────────────────────────────

def layout_to_swimlane_dict(layout: SwimlaneLayout, flow_id: str, title: str) -> dict:
    """Convert SwimlaneLayout to the JSONB dict stored in ProjectFlow.swimlane."""
    return {
        "id": flow_id,
        "title": title,
        "lanes": [{"id": ln.id, "title": ln.id} for ln in layout.lanes],
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
                "waypoints": [{"x": wp.x, "y": wp.y} for wp in f.waypoints] or None,
            }
            for f in layout.flows
        ],
        "layout": None,
    }
