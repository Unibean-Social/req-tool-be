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
STK_W = 176.0             # stakeholder rectangle width (matches FE card)
STK_H = 40.0              # stakeholder rectangle height (matches FE card)
RADIUS = CENTER_R + 300.0 # center edge → stakeholder edge gap ~300px
LABEL_W = 130.0
LABEL_H = 24.0
LABEL_PERP_OFFSET = 24.0  # px to push bidirectional labels apart (scaled with wider fan)
EDGE_BULGE_PX = 80.0              # perpendicular bezier bulge per unit curvature
LABEL_BULGE_PX = EDGE_BULGE_PX / 2  # derived — always half of EDGE_BULGE_PX


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
        id="center",
        x=round(CANVAS_CX - CENTER_R, 1),
        y=round(CANVAS_CY - CENTER_R, 1),
        width=CENTER_R * 2, height=CENTER_R * 2,
    )
    nodes: list[ContextNodeLayout] = []
    for i, sid in enumerate(stakeholder_ids):
        angle = -math.pi / 2 + i * angle_step  # 12 o'clock start, clockwise
        nodes.append(ContextNodeLayout(
            id=sid,
            x=round(CANVAS_CX + RADIUS * math.cos(angle) - STK_W / 2, 1),
            y=round(CANVAS_CY + RADIUS * math.sin(angle) - STK_H / 2, 1),
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
    node_pos = _build_node_center_map(nodes)

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
    node_pos = _build_node_center_map(layout.nodes)
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

    result = await _call_bedrock(prompt, access_key, secret_key, region, model_id)
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


# ── Shared geometry helpers ────────────────────────────────────────────────────

def _build_node_center_map(nodes: list[ContextNodeLayout]) -> dict[str, tuple[float, float]]:
    """Top-left positions → center positions (React Flow stores top-left)."""
    pos = {n.id: (n.x + n.width / 2, n.y + n.height / 2) for n in nodes}
    pos["center"] = (CANVAS_CX, CANVAS_CY)
    return pos


def _bezier_midpoint(
    ax: float, ay: float, bx: float, by: float, curvature: float
) -> tuple[float, float]:
    """Quadratic bezier midpoint B(t=0.5) = 0.25*A + 0.5*C + 0.25*B."""
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy) or 1.0
    perp_x, perp_y = -dy / length, dx / length
    cx = (ax + bx) / 2 + perp_x * curvature * EDGE_BULGE_PX
    cy = (ay + by) / 2 + perp_y * curvature * EDGE_BULGE_PX
    return (0.25 * ax + 0.5 * cx + 0.25 * bx, 0.25 * ay + 0.5 * cy + 0.25 * by)


async def _call_bedrock(
    prompt: str, access_key: str, secret_key: str, region: str, model_id: str,
) -> dict:
    import asyncio
    raw = await asyncio.to_thread(_invoke_bedrock, prompt, access_key, secret_key, region, model_id)
    return _extract_json(raw)


# ── Edge geometry: anchors + label_offset from curvature ──────────────────────

def _rect_perimeter_intersect(cx: float, cy: float, half_w: float, half_h: float,
                              ux: float, uy: float) -> tuple[float, float]:
    """Ray (cx,cy)+t*(ux,uy) hitting axis-aligned rectangle perimeter."""
    if half_w <= 0 or half_h <= 0:
        logger.warning("enrich_layout_edges: zero-size node at (%.1f, %.1f) — anchor defaults to center", cx, cy)
        return cx, cy
    aux, auy = abs(ux), abs(uy)
    if aux < 1e-9:
        t = half_h / max(auy, 1e-9)
    elif auy < 1e-9:
        t = half_w / aux
    else:
        t = min(half_w / aux, half_h / auy)
    return cx + ux * t, cy + uy * t


def _node_perimeter_anchor(node_id: str, cx: float, cy: float, w: float, h: float,
                           ux: float, uy: float) -> tuple[float, float]:
    if node_id == "center":
        return cx + ux * CENTER_R, cy + uy * CENTER_R
    return _rect_perimeter_intersect(cx, cy, w / 2, h / 2, ux, uy)


def _compute_curve_geometry(
    src_id: str, tgt_id: str, curvature: float,
    node_pos: dict[str, tuple[float, float]],
    node_size: dict[str, tuple[float, float]],
    angular_offset: float = 0.0,
) -> tuple[dict, dict, dict]:
    """Return (source_anchor, target_anchor, label_offset) for a bezier flow.

    angular_offset creates symmetric arc fan:
      src_fan = base_angle + angular_offset
      tgt_fan = base_angle + pi - angular_offset
    Edges fan outward on both flanks; curvature adds bezier bow in the same direction.
    """
    sx, sy = node_pos.get(src_id, (CANVAS_CX, CANVAS_CY))
    tx, ty = node_pos.get(tgt_id, (CANVAS_CX, CANVAS_CY))

    base_angle = math.atan2(ty - sy, tx - sx)
    src_fan = base_angle + angular_offset
    tgt_fan = base_angle + math.pi - angular_offset

    sw, sh = node_size.get(src_id, (STK_W, STK_H))
    tw, th = node_size.get(tgt_id, (STK_W, STK_H))

    ax, ay = _node_perimeter_anchor(src_id, sx, sy, sw, sh, math.cos(src_fan), math.sin(src_fan))
    bx, by = _node_perimeter_anchor(tgt_id, tx, ty, tw, th, math.cos(tgt_fan), math.sin(tgt_fan))

    # Perpendicular to straight src→tgt for curvature bow direction
    dx, dy = tx - sx, ty - sy
    length = math.hypot(dx, dy) or 1.0
    perp_x, perp_y = -dy / length, dx / length

    # FE renders label at (sourceX + targetX)/2 + label_offset, where sourceX/targetX are
    # the anchor world positions — so label_offset is purely the perpendicular bezier bulge.
    return (
        {"x": round(ax - sx, 1), "y": round(ay - sy, 1)},
        {"x": round(bx - tx, 1), "y": round(by - ty, 1)},
        {"x": round(perp_x * curvature * LABEL_BULGE_PX, 1), "y": round(perp_y * curvature * LABEL_BULGE_PX, 1)},
    )


def enrich_layout_edges(layout_dict: dict | None, flows: list[dict]) -> dict | None:
    """Fill null source_anchor/target_anchor/label_offset on every edge using flow curvature.

    Preserves any explicit values (user-dragged via PUT /canvas-layout). Adds missing
    edge entries for flows not yet represented in the layout.
    """
    if not layout_dict:
        return layout_dict

    node_pos: dict[str, tuple[float, float]] = {}
    node_size: dict[str, tuple[float, float]] = {}
    for n in layout_dict.get("nodes", []):
        p = n.get("position", {})
        is_center = n["id"] == "center"
        # Always use current constants for actor nodes — stored sizes may be stale.
        # Center node: use stored width (or CENTER_R*2 default); anchor logic uses CENTER_R directly.
        w = float(n.get("width", CENTER_R * 2)) if is_center else STK_W
        h = float(n.get("height", CENTER_R * 2)) if is_center else STK_H
        px = float(p.get("x", 0.0))
        py = float(p.get("y", 0.0))
        # positions are top-left (React Flow convention); convert to center for geometry
        node_pos[n["id"]] = (px + w / 2, py + h / 2)
        node_size[n["id"]] = (w, h)

    edge_by_id = {e.get("id"): dict(e) for e in layout_dict.get("edges", [])}
    enriched: list[dict] = []
    for f in flows:
        fid = f.get("id")
        if not fid:
            continue
        edge = edge_by_id.pop(fid, {"id": fid})
        src_anchor, tgt_anchor, label_offset = _compute_curve_geometry(
            f.get("source", ""), f.get("target", ""),
            float(f.get("curvature", 0.0) or 0.0),
            node_pos, node_size,
            angular_offset=float(f.get("angular_offset", 0.0) or 0.0),
        )
        edge.setdefault("waypoint", None)
        if edge.get("source_anchor") is None:
            edge["source_anchor"] = src_anchor
        if edge.get("target_anchor") is None:
            edge["target_anchor"] = tgt_anchor
        if edge.get("label_offset") is None:
            edge["label_offset"] = label_offset
        enriched.append(edge)

    # keep orphaned edges (flow may have been deleted but layout edge lingered)
    enriched.extend(edge_by_id.values())
    layout_dict["edges"] = enriched
    return layout_dict


# ── Serialization ──────────────────────────────────────────────────────────────

def layout_to_context_dict(layout: ContextLayout, flows: list[dict]) -> dict:
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

    layout_dict = {"nodes": nodes, "edges": [{"id": f["id"]} for f in flows if f.get("id")]}
    return enrich_layout_edges(layout_dict, flows)


# ── Cross-pair edge overlap detection ─────────────────────────────────────────

def _detect_cross_pair_overlaps(
    nodes: list[ContextNodeLayout],
    flows: list[dict],
) -> list[tuple[str, str]]:
    """Detect label-region overlaps between flows from different endpoint pairs.

    Uses quadratic bezier midpoint as label proxy position.
    """
    node_pos = _build_node_center_map(nodes)

    def _label_pos(f: dict) -> tuple[float, float]:
        sx, sy = node_pos.get(f.get("source", ""), (CANVAS_CX, CANVAS_CY))
        tx, ty = node_pos.get(f.get("target", ""), (CANVAS_CX, CANVAS_CY))
        curvature = float(f.get("curvature", 0.0) or 0.0)
        return _bezier_midpoint(sx, sy, tx, ty, curvature)

    valid = [f for f in flows if f.get("id")]
    pair_of = {f["id"]: frozenset([f.get("source", ""), f.get("target", "")]) for f in valid}
    label_pos = {f["id"]: _label_pos(f) for f in valid}
    ids = [f["id"] for f in valid]

    conflicts: list[tuple[str, str]] = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if pair_of.get(a) == pair_of.get(b):
                continue
            ax, ay = label_pos[a]
            bx, by = label_pos[b]
            if abs(ax - bx) < LABEL_W and abs(ay - by) < LABEL_H:
                conflicts.append((a, b))
    return conflicts


# ── Force-repulsion conflict resolver ─────────────────────────────────────────

_REPULSE_MIN_MID_DIST = 90.0       # px — minimum bezier midpoint separation
_REPULSE_MAX_ITER = 12
_REPULSE_ANG = math.radians(8)     # angular_offset adjustment per iteration
_REPULSE_CURV = 0.12               # curvature adjustment per iteration (fallback)
_REPULSE_MAX_ANGLE = math.radians(70)
_REPULSE_MAX_CURVE = 1.2


def force_resolve_conflicts(flows: list[dict], layout: ContextLayout) -> list[dict]:
    """Resolve cross-pair bezier midpoint overlaps via force-repulsion.

    Prefers angular_offset repulsion; falls back to curvature when angle cap is hit.
    Exits early on stable state (no moved edges in an iteration).
    """
    all_nodes = [layout.center] + layout.nodes
    node_pos = _build_node_center_map(layout.nodes)
    node_size = {n.id: (n.width, n.height) for n in all_nodes}

    params: dict[str, list[float]] = {
        f["id"]: [
            float(f.get("curvature", 0.0) or 0.0),
            float(f.get("angular_offset", 0.0) or 0.0),
        ]
        for f in flows
        if f.get("id")
    }
    pair_of = {
        f["id"]: frozenset([f.get("source", ""), f.get("target", "")])
        for f in flows if f.get("id")
    }
    ids = [f["id"] for f in flows if f.get("id") and f["id"] in params]

    for _ in range(_REPULSE_MAX_ITER):
        anchors: dict[str, tuple[float, float, float, float]] = {}
        for f in flows:
            fid = f.get("id")
            if not fid or fid not in params:
                continue
            c, ang = params[fid]
            src_anchor, tgt_anchor, _ = _compute_curve_geometry(
                f.get("source", ""), f.get("target", ""), c,
                node_pos, node_size, ang,
            )
            sx, sy = node_pos.get(f.get("source", ""), (CANVAS_CX, CANVAS_CY))
            tx, ty = node_pos.get(f.get("target", ""), (CANVAS_CX, CANVAS_CY))
            anchors[fid] = (sx + src_anchor["x"], sy + src_anchor["y"],
                            tx + tgt_anchor["x"], ty + tgt_anchor["y"])

        mids = {
            fid: _bezier_midpoint(*anchors[fid], params[fid][0])
            for fid in params
            if fid in anchors
        }

        moved = False
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                if pair_of.get(a) == pair_of.get(b):
                    continue
                if a not in mids or b not in mids:
                    continue
                dist = math.hypot(mids[a][0] - mids[b][0], mids[a][1] - mids[b][1])
                if dist >= _REPULSE_MIN_MID_DIST:
                    continue
                ca, oa = params[a]
                cb, ob = params[b]
                if abs(oa) < _REPULSE_MAX_ANGLE - _REPULSE_ANG:
                    params[a][1] = oa + _REPULSE_ANG
                    params[b][1] = ob - _REPULSE_ANG
                else:
                    params[a][0] = min(ca + _REPULSE_CURV, _REPULSE_MAX_CURVE)
                    params[b][0] = max(cb - _REPULSE_CURV, -_REPULSE_MAX_CURVE)
                moved = True
        if not moved:
            break

    return [
        {**f, "curvature": round(params[f["id"]][0], 3), "angular_offset": round(params[f["id"]][1], 4)}
        if f.get("id") and f["id"] in params else f
        for f in flows
    ]

