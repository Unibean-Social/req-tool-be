from __future__ import annotations

import asyncio
import hashlib
import math
import uuid
from collections import defaultdict
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.context_diagram import ProjectContextDiagram
from app.models.project import Project
from app.models.project_business import ProjectFlow, ProjectFlowAction
from app.models.stakeholder import ActorType, Stakeholder
from app.schemas.context_diagram import (
    ContextDiagramFlow,
    ContextDiagramResponse,
    ContextDiagramStakeholder,
    FlowCreateRequest,
    FlowUpdateRequest,
    LayoutSaveRequest,
    SyncResult,
)
from app.utils.context.direction import classify_direction

_CENTER = "center"

# Curvature offsets for parallel edges sharing the same (source, target).
# Pattern: 0, +0.4, -0.4, +0.8, -0.8, ...
_CURVE_STEPS = [0.0, 0.4, -0.4, 0.8, -0.8, 1.2, -1.2]
_LABEL_PERP_PX = 30  # pixels to shift label perpendicular to edge per curvature unit


def _assign_curvatures(flows: list[dict], layout: dict | None = None) -> list[dict]:
    """Assign curvature + label_offset to parallel edges sharing the same (source, target).

    label_offset is a perpendicular shift so labels don't pile on top of each other.
    When layout node positions are available, compute the actual perpendicular direction.
    Otherwise fall back to a horizontal offset (frontend must rotate as needed).
    """
    node_pos: dict[str, tuple[float, float]] = {}
    if layout:
        for node in layout.get("nodes", []):
            p = node.get("position", {})
            node_pos[node["id"]] = (float(p.get("x", 0)), float(p.get("y", 0)))

    pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    result = []
    for f in flows:
        src, tgt = f.get("source", ""), f.get("target", "")
        pair = (src, tgt)
        idx = pair_counts[pair]
        curvature = (
            _CURVE_STEPS[idx]
            if idx < len(_CURVE_STEPS)
            else (idx // 2 + 1) * 0.4 * (1 if idx % 2 == 0 else -1)
        )

        # perpendicular direction: rotate edge vector 90°
        if src in node_pos and tgt in node_pos:
            dx = node_pos[tgt][0] - node_pos[src][0]
            dy = node_pos[tgt][1] - node_pos[src][1]
            length = math.hypot(dx, dy) or 1.0
            # perpendicular unit vector (rotate 90° CCW)
            px, py = -dy / length, dx / length
            shift = curvature * _LABEL_PERP_PX
            label_offset = {"x": round(px * shift, 1), "y": round(py * shift, 1)}
        else:
            # no layout: store a scalar hint; frontend applies perpendicular rotation
            label_offset = {"x": round(curvature * _LABEL_PERP_PX, 1), "y": 0.0}

        result.append({**f, "curvature": curvature, "label_offset": label_offset})
        pair_counts[pair] += 1
    return result


class ContextDiagramService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _load_diagram(self, project_id: uuid.UUID) -> ProjectContextDiagram:
        result = await self.db.execute(
            select(ProjectContextDiagram).where(
                ProjectContextDiagram.project_id == project_id
            )
        )
        diagram = result.scalar_one_or_none()
        if not diagram:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Context diagram chưa được tạo")
        return diagram

    async def _load_diagram_with_project_name(
        self, project_id: uuid.UUID, *, create_if_missing: bool = False
    ) -> tuple[ProjectContextDiagram, str]:
        result = await self.db.execute(
            select(ProjectContextDiagram, Project.name)
            .join(Project, Project.id == ProjectContextDiagram.project_id)
            .where(ProjectContextDiagram.project_id == project_id)
        )
        row = result.one_or_none()
        if not row:
            if not create_if_missing:
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Context diagram chưa được tạo")
            project_result = await self.db.execute(
                select(Project).where(Project.id == project_id)
            )
            project = project_result.scalar_one_or_none()
            if not project:
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project không tồn tại")
            diagram = ProjectContextDiagram(project_id=project_id, stakeholder_ids=[], flows=[])
            self.db.add(diagram)
            await self.db.flush()
            return diagram, project.name
        return row[0], row[1]

    async def _load_stakeholders_for(
        self, project_id: uuid.UUID, ids: list[str]
    ) -> dict[str, Stakeholder]:
        if not ids:
            return {}
        result = await self.db.execute(
            select(Stakeholder).where(
                Stakeholder.id.in_([uuid.UUID(i) for i in ids]),
                Stakeholder.project_id == project_id,
            )
        )
        return {str(s.id): s for s in result.scalars().all()}

    def _build_response(
        self,
        project_name: str,
        diagram: ProjectContextDiagram,
        stakeholder_map: dict[str, Stakeholder],
    ) -> ContextDiagramResponse:
        stakeholders = []
        for sid in diagram.stakeholder_ids:
            s = stakeholder_map.get(sid)
            stakeholders.append(ContextDiagramStakeholder(
                id=sid,
                name=s.name if s else sid,
                role=s.system_description if s else None,
            ))
        return ContextDiagramResponse(
            center_label=project_name,
            stakeholders=stakeholders,
            flows=[ContextDiagramFlow(**f) for f in diagram.flows],
            layout=diagram.layout,
        )

    async def get(self, project_id: uuid.UUID) -> ContextDiagramResponse:
        diagram, project_name = await self._load_diagram_with_project_name(project_id, create_if_missing=True)
        if not diagram.stakeholder_ids:
            await self._sync_typed_stakeholders(project_id, diagram)
        stakeholder_map = await self._load_stakeholders_for(project_id, diagram.stakeholder_ids)
        return self._build_response(project_name, diagram, stakeholder_map)

    async def _sync_typed_stakeholders(
        self, project_id: uuid.UUID, diagram: ProjectContextDiagram
    ) -> None:
        existing_ids = set(diagram.stakeholder_ids)
        result = await self.db.execute(
            select(Stakeholder).where(
                Stakeholder.project_id == project_id,
                Stakeholder.actor_type.in_([ActorType.business_actor, ActorType.other_actor]),
            )
        )
        missing = [str(s.id) for s in result.scalars().all() if str(s.id) not in existing_ids]
        if missing:
            diagram.stakeholder_ids = diagram.stakeholder_ids + missing
            flag_modified(diagram, "stakeholder_ids")
            await self.db.flush()

    async def _add_stakeholder_to_diagram(
        self, project_id: uuid.UUID, stakeholder_id: uuid.UUID
    ) -> None:
        result = await self.db.execute(
            select(ProjectContextDiagram).where(
                ProjectContextDiagram.project_id == project_id
            )
        )
        diagram = result.scalar_one_or_none()
        if not diagram:
            diagram = ProjectContextDiagram(
                project_id=project_id,
                stakeholder_ids=[],
                flows=[],
                layout=None,
            )
            self.db.add(diagram)
            await self.db.flush()
            await self.db.refresh(diagram)

        sid = str(stakeholder_id)
        if sid not in diagram.stakeholder_ids:
            diagram.stakeholder_ids = diagram.stakeholder_ids + [sid]
            flag_modified(diagram, "stakeholder_ids")
            await self.db.flush()

    async def _remove_stakeholder_from_diagram(
        self, project_id: uuid.UUID, stakeholder_id: uuid.UUID
    ) -> None:
        result = await self.db.execute(
            select(ProjectContextDiagram).where(
                ProjectContextDiagram.project_id == project_id
            )
        )
        diagram = result.scalar_one_or_none()
        if not diagram:
            return

        sid = str(stakeholder_id)
        if sid not in diagram.stakeholder_ids:
            return

        diagram.stakeholder_ids = [i for i in diagram.stakeholder_ids if i != sid]
        diagram.flows = [
            f for f in diagram.flows
            if f.get("source") != sid and f.get("target") != sid
        ]
        flag_modified(diagram, "stakeholder_ids")
        flag_modified(diagram, "flows")
        await self.db.flush()

    async def create_flow(
        self, project_id: uuid.UUID, body: FlowCreateRequest
    ) -> ContextDiagramFlow:
        diagram = await self._load_diagram(project_id)
        valid_nodes = {_CENTER} | set(diagram.stakeholder_ids)

        if body.source not in valid_nodes or body.target not in valid_nodes:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="source và target phải là 'center' hoặc stakeholder_id hợp lệ",
            )
        if body.source == body.target:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="source và target không được giống nhau",
            )

        flow: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "source": body.source,
            "target": body.target,
            "label": body.label,
        }
        diagram.flows = diagram.flows + [flow]
        flag_modified(diagram, "flows")
        await self.db.flush()

        return ContextDiagramFlow(**flow)

    async def update_flow(
        self, project_id: uuid.UUID, flow_id: str, body: FlowUpdateRequest
    ) -> ContextDiagramFlow:
        diagram = await self._load_diagram(project_id)
        flows = list(diagram.flows)

        idx = next((i for i, f in enumerate(flows) if f.get("id") == flow_id), None)
        if idx is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Flow không tìm thấy")

        flows[idx] = {**flows[idx], "label": body.label}
        diagram.flows = flows
        flag_modified(diagram, "flows")
        await self.db.flush()

        return ContextDiagramFlow(**flows[idx])

    async def delete_flow(self, project_id: uuid.UUID, flow_id: str) -> None:
        diagram = await self._load_diagram(project_id)
        flows = list(diagram.flows)

        new_flows = [f for f in flows if f.get("id") != flow_id]
        if len(new_flows) == len(flows):
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Flow không tìm thấy")

        diagram.flows = new_flows
        flag_modified(diagram, "flows")
        await self.db.flush()

    async def save_layout(self, project_id: uuid.UUID, body: LayoutSaveRequest) -> None:
        diagram = await self._load_diagram(project_id)
        diagram.layout = body.model_dump()
        flag_modified(diagram, "layout")
        await self.db.flush()

    async def sync(self, project_id: uuid.UUID) -> SyncResult:
        from app.config import settings

        diagram, project_name = await self._load_diagram_with_project_name(project_id)
        await self._sync_typed_stakeholders(project_id, diagram)

        existing_ids = set(diagram.stakeholder_ids)
        existing_meta: dict[str, Any] = diagram.sync_meta or {}

        bedrock_kwargs = dict(
            access_key=settings.aws_access_key_id,
            secret_key=settings.aws_secret_access_key,
            region=settings.aws_region,
            model_id=settings.bedrock_notation_model,
        )

        actions_result = await self.db.execute(
            select(ProjectFlowAction, ProjectFlow.id, ProjectFlow.name, Stakeholder.name)
            .join(ProjectFlow, ProjectFlowAction.flow_id == ProjectFlow.id)
            .join(Stakeholder, ProjectFlowAction.actor_id == Stakeholder.id)
            .where(
                ProjectFlow.project_id == project_id,
                ProjectFlowAction.actor_id.isnot(None),
            )
            .order_by(ProjectFlowAction.created_at)
        )
        rows = actions_result.all()

        new_meta: dict[str, Any] = dict(existing_meta)
        seen_actors: set[str] = set(existing_ids)
        flow_actor_ids: list[str] = []

        # group uncached rows by flow, preserving insertion order
        uncached_by_flow: dict[str, list[tuple[Any, str, str, str]]] = {}
        for action, flow_id, flow_name, actor_name in rows:
            aid = str(action.actor_id)
            desc_hash = hashlib.sha256((action.description or "").encode()).hexdigest()
            cached = existing_meta.get(str(action.id), {})
            if cached.get("hash") != desc_hash:
                uncached_by_flow.setdefault(str(flow_id), []).append(
                    (action, flow_name, actor_name, desc_hash)
                )
            if aid not in seen_actors:
                flow_actor_ids.append(aid)
                seen_actors.add(aid)

        # classify one flow at a time — keeps Bedrock context scoped per flow
        for flow_rows in uncached_by_flow.values():
            bedrock_results = await asyncio.gather(*[
                classify_direction(action.description or "", actor=actor_name or "", **bedrock_kwargs)
                for action, _, actor_name, _ in flow_rows
            ])
            for (action, _, _, desc_hash), result in zip(flow_rows, bedrock_results):
                new_meta[str(action.id)] = {
                    "hash": desc_hash,
                    "direction": result["direction"],
                    "label": result["label"],
                }

        # one edge per (actor, flow, direction) — preserves per-flow labels
        groups: dict[tuple[str, str, str], str] = {}
        for action, flow_id, flow_name, _ in rows:
            aid = str(action.actor_id)
            entry = new_meta.get(str(action.id), {})
            direction = entry.get("direction", "actor_to_system")
            label = entry.get("label", flow_name)
            key = (aid, str(flow_id), direction)
            if key not in groups:
                groups[key] = label

        all_valid_ids = existing_ids | set(flow_actor_ids)
        existing_triples: set[tuple[str, str, str]] = {
            (f.get("source", ""), f.get("target", ""), f.get("label", ""))
            for f in diagram.flows
        }
        actors_with_edges: set[str] = {
            f.get("source", "") for f in diagram.flows if f.get("source") != _CENTER
        } | {
            f.get("target", "") for f in diagram.flows if f.get("target") != _CENTER
        }
        new_flows: list[dict[str, Any]] = []

        for (aid, _flow_id, direction), label in groups.items():
            if aid not in all_valid_ids:
                continue
            src, tgt = (_CENTER, aid) if direction == "system_to_actor" else (aid, _CENTER)
            if (src, tgt, label) not in existing_triples:
                new_flows.append({"id": str(uuid.uuid4()), "source": src, "target": tgt, "label": label})
                existing_triples.add((src, tgt, label))
            actors_with_edges.add(aid)

        # stakeholders with no edge at all get a default actor→center edge
        all_stakeholder_ids = list(existing_ids) + flow_actor_ids
        for sid in all_stakeholder_ids:
            if sid not in actors_with_edges:
                new_flows.append({"id": str(uuid.uuid4()), "source": sid, "target": _CENTER, "label": ""})
                existing_triples.add((sid, _CENTER, ""))
                actors_with_edges.add(sid)

        if flow_actor_ids:
            diagram.stakeholder_ids = diagram.stakeholder_ids + flow_actor_ids
            flag_modified(diagram, "stakeholder_ids")

        if new_flows:
            merged = diagram.flows + new_flows
            merged = _assign_curvatures(merged, layout=diagram.layout)
            diagram.flows = merged
            flag_modified(diagram, "flows")

        meta_changed = new_meta != existing_meta
        if meta_changed:
            diagram.sync_meta = new_meta
            flag_modified(diagram, "sync_meta")

        if flow_actor_ids or new_flows or meta_changed:
            await self.db.flush()

        stakeholder_map = await self._load_stakeholders_for(project_id, diagram.stakeholder_ids)
        return SyncResult(
            added_stakeholders=len(flow_actor_ids),
            added_flows=len(new_flows),
            diagram=self._build_response(project_name, diagram, stakeholder_map),
        )
