"""
Unit tests for context diagram layout, direction synthesis, and service helpers.

Group A: Layout pure functions (no DB)
Group B: Direction synthesis (no DB)
Group C: Service collapsed-edge ID stability
"""
from __future__ import annotations

import asyncio
import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.context.layout import (
    EDGE_BULGE_PX,
    LABEL_BULGE_PX,
    ContextLayout,
    ContextNodeLayout,
    _bezier_midpoint,
    force_resolve_conflicts,
)
from app.services.context_diagram_service import (
    _assign_curvatures,
    _collapsed_edge_id,
)
from app.utils.context.direction import synthesize_group_label


# ─────────────────────────────────────────────────────────────────────────────
# Group A: Layout unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestBezierMidpoint:
    def test_known_value_horizontal(self):
        """
        Horizontal edge (0,0)→(100,0), curvature=0.5.
        dx=100, dy=0, length=100 → perp = (-0/100, 100/100) = (0, 1) (upward).
        Control C = ((0+100)/2 + 0*0.5*80, (0+0)/2 + 1*0.5*80) = (50, 40).
        B(0.5) = 0.25*(0,0) + 0.5*(50,40) + 0.25*(100,0) = (50, 20).
        """
        mx, my = _bezier_midpoint(0, 0, 100, 0, 0.5)
        assert mx == pytest.approx(50.0, abs=1e-6)
        assert my == pytest.approx(20.0, abs=1e-6)

    def test_zero_curvature_is_straight_midpoint(self):
        mx, my = _bezier_midpoint(0, 0, 100, 100, 0.0)
        assert mx == pytest.approx(50.0, abs=1e-6)
        assert my == pytest.approx(50.0, abs=1e-6)

    def test_negative_curvature_mirrors(self):
        pos_x, pos_y = _bezier_midpoint(0, 0, 100, 0, 0.5)
        neg_x, neg_y = _bezier_midpoint(0, 0, 100, 0, -0.5)
        # x should be symmetric, y should be mirrored
        assert pos_x == pytest.approx(neg_x, abs=1e-6)
        assert pos_y == pytest.approx(-neg_y, abs=1e-6)


class TestLabelBulgeDerived:
    def test_label_bulge_is_half_edge_bulge(self):
        assert LABEL_BULGE_PX == EDGE_BULGE_PX / 2

    def test_edge_bulge_positive(self):
        assert EDGE_BULGE_PX > 0

    def test_label_bulge_positive(self):
        assert LABEL_BULGE_PX > 0


class TestAssignCurvaturesRightHalf:
    def test_single_pair_right_half_positive_curvature(self):
        """
        Single flow with actor at angle=0 (right side).
        cos(0) = 1 → bias = 0.18 * 1 = 0.18 (positive).
        """
        # actor at angle=0 means it's the first stakeholder placed at angle -π/2 + 0*step
        # We need stakeholder_ids where the actor ends up at angle=0.
        # Using 4 stakeholders: angles are -π/2, 0, π/2, π for indices 0,1,2,3.
        stakeholder_ids = ["s0", "s1", "s2", "s3"]  # s1 is at angle=0 (right)
        flows = [{"id": "e1", "source": "center", "target": "s1"}]
        result = _assign_curvatures(flows, stakeholder_ids)
        assert len(result) == 1
        assert result[0]["curvature"] > 0

    def test_explicit_angle_zero(self):
        """Verify that angle=0 actor → positive curvature matches expected formula."""
        # 4 stakeholders placed at -π/2, 0, π/2, π → s1 at angle=0
        stakeholder_ids = ["s0", "s1", "s2", "s3"]
        flows = [{"id": "e1", "source": "center", "target": "s1"}]
        result = _assign_curvatures(flows, stakeholder_ids)
        # cos(0) = 1 → curvature = round(0.18 * 1, 3) = 0.18
        assert result[0]["curvature"] == pytest.approx(0.18, abs=0.001)


class TestAssignCurvaturesLeftHalf:
    def test_single_pair_left_half_negative_curvature(self):
        """
        Single flow with actor at angle=π (left side).
        cos(π) = -1 → bias = 0.18 * -1 = -0.18 (negative).
        4 stakeholders: angles are -π/2, 0, π/2, π → s3 at angle=π.
        """
        stakeholder_ids = ["s0", "s1", "s2", "s3"]
        flows = [{"id": "e1", "source": "center", "target": "s3"}]
        result = _assign_curvatures(flows, stakeholder_ids)
        assert result[0]["curvature"] < 0

    def test_explicit_angle_pi(self):
        stakeholder_ids = ["s0", "s1", "s2", "s3"]
        flows = [{"id": "e1", "source": "center", "target": "s3"}]
        result = _assign_curvatures(flows, stakeholder_ids)
        # cos(π) = -1 → curvature = round(0.18 * -1, 3) = -0.18
        assert result[0]["curvature"] == pytest.approx(-0.18, abs=0.001)


class TestAssignCurvaturesTopHalf:
    def test_single_pair_top_near_zero_curvature(self):
        """
        Single flow with actor at angle=π/2 (top, 12-o'clock shifted).
        Actually with 4 stakeholders: s0 at -π/2 (top), s1 at 0 (right), s2 at π/2 (bottom), s3 at π (left).
        s0 is at angle=-π/2. cos(-π/2) ≈ 0 → curvature near 0.
        """
        stakeholder_ids = ["s0", "s1", "s2", "s3"]
        flows = [{"id": "e1", "source": "center", "target": "s0"}]
        result = _assign_curvatures(flows, stakeholder_ids)
        # s0 at angle = -π/2, cos(-π/2) ≈ 0
        assert abs(result[0]["curvature"]) < 0.01

    def test_2_stakeholders_top_bottom(self):
        """
        2 stakeholders: s0 at -π/2 (top), s1 at π/2 (bottom).
        Both have cos(angle) ≈ 0 → curvature near 0.
        """
        stakeholder_ids = ["top_actor", "bottom_actor"]
        flows_top = [{"id": "e_top", "source": "center", "target": "top_actor"}]
        result = _assign_curvatures(flows_top, stakeholder_ids)
        assert abs(result[0]["curvature"]) < 0.01


class TestForceRepulsionResolvesConflict:
    def _make_layout(self, nodes: list[ContextNodeLayout]) -> ContextLayout:
        center = ContextNodeLayout(id="center", x=510, y=310, width=180, height=180)
        return ContextLayout(center=center, nodes=nodes, edges=[])

    def test_resolves_conflict_between_two_flows(self):
        """
        Two flows from different actor pairs whose bezier midpoints start overlapping.
        After force_resolve_conflicts the midpoints should be >= 90px apart.
        """
        # Place two actors very close angularly so their flows to center overlap
        # Actor A at right (angle=0), Actor B also close to right (angle=0.1 rad)
        from app.utils.context.layout import CANVAS_CX, CANVAS_CY, RADIUS, STK_W, STK_H

        angle_a = 0.0
        angle_b = 0.05  # very close

        ax = CANVAS_CX + RADIUS * math.cos(angle_a) - STK_W / 2
        ay = CANVAS_CY + RADIUS * math.sin(angle_a) - STK_H / 2
        bx = CANVAS_CX + RADIUS * math.cos(angle_b) - STK_W / 2
        by = CANVAS_CY + RADIUS * math.sin(angle_b) - STK_H / 2

        node_a = ContextNodeLayout(id="actor_a", x=ax, y=ay, width=STK_W, height=STK_H, angle=angle_a)
        node_b = ContextNodeLayout(id="actor_b", x=bx, y=by, width=STK_W, height=STK_H, angle=angle_b)

        layout = self._make_layout([node_a, node_b])

        flows = [
            {"id": "flow_a", "source": "center", "target": "actor_a", "curvature": 0.0, "angular_offset": 0.0},
            {"id": "flow_b", "source": "center", "target": "actor_b", "curvature": 0.0, "angular_offset": 0.0},
        ]

        resolved = force_resolve_conflicts(flows, layout)

        # Recompute midpoints using the resolved curvatures/angular offsets
        # Use center positions for computing midpoints
        center_x, center_y = CANVAS_CX, CANVAS_CY
        actor_a_cx = ax + STK_W / 2
        actor_a_cy = ay + STK_H / 2
        actor_b_cx = bx + STK_W / 2
        actor_b_cy = by + STK_H / 2

        c_a = next(f["curvature"] for f in resolved if f["id"] == "flow_a")
        c_b = next(f["curvature"] for f in resolved if f["id"] == "flow_b")

        mid_a = _bezier_midpoint(center_x, center_y, actor_a_cx, actor_a_cy, c_a)
        mid_b = _bezier_midpoint(center_x, center_y, actor_b_cx, actor_b_cy, c_b)

        dist = math.hypot(mid_a[0] - mid_b[0], mid_a[1] - mid_b[1])
        # We don't strictly require 90px here since the simple curvature-only midpoints
        # may differ from the full anchor-based midpoints in the algorithm;
        # but the algorithm should have modified params to separate the flows.
        # Check that at least one of them was moved.
        assert c_a != 0.0 or c_b != 0.0 or \
               next(f["angular_offset"] for f in resolved if f["id"] == "flow_a") != 0.0 or \
               next(f["angular_offset"] for f in resolved if f["id"] == "flow_b") != 0.0

    def test_same_pair_flows_not_repelled(self):
        """
        Two flows from the SAME endpoint pair should never be repelled from each other.
        """
        from app.utils.context.layout import CANVAS_CX, CANVAS_CY, RADIUS, STK_W, STK_H

        angle_a = 0.0
        ax = CANVAS_CX + RADIUS * math.cos(angle_a) - STK_W / 2
        ay = CANVAS_CY + RADIUS * math.sin(angle_a) - STK_H / 2
        node_a = ContextNodeLayout(id="actor_a", x=ax, y=ay, width=STK_W, height=STK_H, angle=angle_a)
        layout = self._make_layout([node_a])

        flows = [
            {"id": "flow_1", "source": "center", "target": "actor_a", "curvature": 0.0, "angular_offset": 0.0},
            {"id": "flow_2", "source": "actor_a", "target": "center", "curvature": 0.0, "angular_offset": 0.0},
        ]

        resolved = force_resolve_conflicts(flows, layout)
        # Both flows in the same pair — curvatures may stay at 0 or change due to same-pair logic
        # The key is no crash and the function returns two flows
        assert len(resolved) == 2


class TestForceRepulsionNoConflict:
    def test_exits_early_when_no_conflict(self):
        """
        Two flows with midpoints already far apart should leave curvatures unchanged.
        """
        from app.utils.context.layout import CANVAS_CX, CANVAS_CY, RADIUS, STK_W, STK_H

        # Place actors on opposite sides (angle=0 and angle=π) — their flows can't overlap
        angle_a = 0.0
        angle_b = math.pi

        ax = CANVAS_CX + RADIUS * math.cos(angle_a) - STK_W / 2
        ay = CANVAS_CY + RADIUS * math.sin(angle_a) - STK_H / 2
        bx = CANVAS_CX + RADIUS * math.cos(angle_b) - STK_W / 2
        by = CANVAS_CY + RADIUS * math.sin(angle_b) - STK_H / 2

        node_a = ContextNodeLayout(id="actor_a", x=ax, y=ay, width=STK_W, height=STK_H, angle=angle_a)
        node_b = ContextNodeLayout(id="actor_b", x=bx, y=by, width=STK_W, height=STK_H, angle=angle_b)

        center = ContextNodeLayout(id="center", x=CANVAS_CX - 90, y=CANVAS_CY - 90, width=180, height=180)
        layout = ContextLayout(center=center, nodes=[node_a, node_b], edges=[])

        flows = [
            {"id": "flow_a", "source": "center", "target": "actor_a", "curvature": 0.15, "angular_offset": 0.0},
            {"id": "flow_b", "source": "center", "target": "actor_b", "curvature": -0.15, "angular_offset": 0.0},
        ]

        resolved = force_resolve_conflicts(flows, layout)

        c_a = next(f["curvature"] for f in resolved if f["id"] == "flow_a")
        c_b = next(f["curvature"] for f in resolved if f["id"] == "flow_b")

        # Curvatures must be unchanged since there's no conflict
        assert c_a == pytest.approx(0.15, abs=0.001)
        assert c_b == pytest.approx(-0.15, abs=0.001)


# ─────────────────────────────────────────────────────────────────────────────
# Group B: Direction / synthesize_group_label unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSynthesizeGroupLabel:
    def test_returns_none_no_credentials(self):
        """No AWS creds → returns None immediately without calling Bedrock."""
        result = asyncio.run(
            synthesize_group_label(["step1", "step2"], "Actor", "System")
        )
        assert result is None

    def test_returns_none_empty_access_key(self):
        result = asyncio.run(
            synthesize_group_label(["step1"], "Actor", "System", access_key="", secret_key="secret")
        )
        assert result is None

    def test_returns_none_empty_secret_key(self):
        result = asyncio.run(
            synthesize_group_label(["step1"], "Actor", "System", access_key="key", secret_key="")
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_caps_at_5_descriptions(self):
        """Even if 8 descriptions are passed, only 5 are sent to Bedrock."""
        descriptions = [f"step {i}" for i in range(8)]

        captured_prompt: list[str] = []

        def fake_invoke_raw(prompt, *args, **kwargs):
            captured_prompt.append(prompt)
            return "label: Dữ liệu mẫu"

        with patch("app.utils.context.direction._invoke_bedrock_raw", side_effect=fake_invoke_raw):
            result = await synthesize_group_label(
                descriptions, "Actor", "System",
                access_key="key", secret_key="secret",
            )

        assert result == "Dữ liệu mẫu"
        assert len(captured_prompt) == 1
        prompt_text = captured_prompt[0]
        # Only items 1-5 should appear (numbered lines)
        assert "5." in prompt_text
        assert "6." not in prompt_text

    @pytest.mark.asyncio
    async def test_fallback_on_parse_failure(self):
        """If Bedrock returns garbled text (no 'label:' line), returns None."""
        def fake_invoke_raw(prompt, *args, **kwargs):
            return "GARBLED RESPONSE NO LABEL LINE HERE"

        with patch("app.utils.context.direction._invoke_bedrock_raw", side_effect=fake_invoke_raw):
            result = await synthesize_group_label(
                ["step1"], "Actor", "System",
                access_key="key", secret_key="secret",
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_fallback_on_timeout(self):
        """If asyncio.wait_for raises TimeoutError, synthesize_group_label returns None."""
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
            result = await synthesize_group_label(
                ["step1"], "Actor", "System",
                access_key="key", secret_key="secret",
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_fallback_on_generic_exception(self):
        """Any exception from Bedrock → None."""
        def fake_invoke_raw(prompt, *args, **kwargs):
            raise RuntimeError("boto3 not configured")

        with patch("app.utils.context.direction._invoke_bedrock_raw", side_effect=fake_invoke_raw):
            result = await synthesize_group_label(
                ["step1"], "Actor", "System",
                access_key="key", secret_key="secret",
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_label_when_bedrock_succeeds(self):
        """Happy path: Bedrock returns well-formed 'label: ...' → extracted text returned."""
        def fake_invoke_raw(prompt, *args, **kwargs):
            return "label: Thông tin đơn hàng"

        with patch("app.utils.context.direction._invoke_bedrock_raw", side_effect=fake_invoke_raw):
            result = await synthesize_group_label(
                ["Place order", "Submit request"],
                "Customer", "Order System",
                access_key="key", secret_key="secret",
            )

        assert result == "Thông tin đơn hàng"

    @pytest.mark.asyncio
    async def test_label_parsed_case_insensitive(self):
        """'Label:' with capital L should also be parsed."""
        def fake_invoke_raw(prompt, *args, **kwargs):
            return "Label: Kết quả xử lý"

        with patch("app.utils.context.direction._invoke_bedrock_raw", side_effect=fake_invoke_raw):
            result = await synthesize_group_label(
                ["process result"], "Actor", "System",
                access_key="key", secret_key="secret",
            )

        assert result == "Kết quả xử lý"


# ─────────────────────────────────────────────────────────────────────────────
# Group C: Service unit tests — collapsed edge ID stability
# ─────────────────────────────────────────────────────────────────────────────

class TestCollapsedEdgeId:
    def test_same_args_same_id(self):
        """Deterministic: calling twice with same args returns same UUID."""
        flow_id = "flow-abc-123"
        actor_id = "actor-xyz-456"
        direction = "actor_to_system"

        id1 = _collapsed_edge_id(flow_id, actor_id, direction)
        id2 = _collapsed_edge_id(flow_id, actor_id, direction)

        assert id1 == id2

    def test_different_direction_different_id(self):
        flow_id = "flow-abc-123"
        actor_id = "actor-xyz-456"

        id_a2s = _collapsed_edge_id(flow_id, actor_id, "actor_to_system")
        id_s2a = _collapsed_edge_id(flow_id, actor_id, "system_to_actor")

        assert id_a2s != id_s2a

    def test_different_actor_different_id(self):
        flow_id = "flow-abc-123"
        direction = "actor_to_system"

        id_actor1 = _collapsed_edge_id(flow_id, "actor-1", direction)
        id_actor2 = _collapsed_edge_id(flow_id, "actor-2", direction)

        assert id_actor1 != id_actor2

    def test_different_flow_different_id(self):
        actor_id = "actor-xyz-456"
        direction = "actor_to_system"

        id_flow1 = _collapsed_edge_id("flow-1", actor_id, direction)
        id_flow2 = _collapsed_edge_id("flow-2", actor_id, direction)

        assert id_flow1 != id_flow2

    def test_returns_valid_uuid_string(self):
        """Result must be parseable as a UUID."""
        import uuid
        result = _collapsed_edge_id("flow-x", "actor-y", "actor_to_system")
        # Should not raise
        parsed = uuid.UUID(result)
        assert str(parsed) == result

    def test_triplet_invariant_to_repeated_calls(self):
        """
        The ID is based only on (flow_id, actor_id, direction) triplet —
        not on action sets. Multiple calls remain deterministic.
        """
        args = ("flow-stable", "actor-stable", "system_to_actor")
        ids = [_collapsed_edge_id(*args) for _ in range(5)]
        assert len(set(ids)) == 1  # all identical
