from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.context_diagram import ProjectContextDiagram
from app.models.project import Project
from app.models.project_business import ProjectFlow, ProjectFlowAction
from app.models.stakeholder import Stakeholder
from app.schemas.context_diagram import (
    ContextDiagramFlow,
    ContextDiagramResponse,
    ContextDiagramStakeholder,
    FlowCreateRequest,
    FlowUpdateRequest,
    LayoutSaveRequest,
    SyncResult,
)

_CENTER = "center"

_SYSTEM_TO_ACTOR: frozenset[str] = frozenset({
    "notify", "return", "send", "confirm", "alert", "display",
    "report", "export", "gửi", "thông báo", "trả về", "xác nhận",
})


def _classify(description: str) -> str:
    return "system_to_actor" if set(description.lower().split()) & _SYSTEM_TO_ACTOR else "actor_to_system"


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

    async def _load_diagram_with_project_name(self, project_id: uuid.UUID) -> tuple[ProjectContextDiagram, str]:
        result = await self.db.execute(
            select(ProjectContextDiagram, Project.name)
            .join(Project, Project.id == ProjectContextDiagram.project_id)
            .where(ProjectContextDiagram.project_id == project_id)
        )
        row = result.one_or_none()
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Context diagram chưa được tạo")
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
        diagram, project_name = await self._load_diagram_with_project_name(project_id)
        stakeholder_map = await self._load_stakeholders_for(project_id, diagram.stakeholder_ids)
        return self._build_response(project_name, diagram, stakeholder_map)

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
        diagram, project_name = await self._load_diagram_with_project_name(project_id)

        actions_result = await self.db.execute(
            select(ProjectFlowAction, ProjectFlow.name)
            .join(ProjectFlow, ProjectFlowAction.flow_id == ProjectFlow.id)
            .where(
                ProjectFlow.project_id == project_id,
                ProjectFlowAction.actor_id.isnot(None),
            )
            .order_by(ProjectFlowAction.created_at)
        )
        rows = actions_result.all()

        existing_ids = set(diagram.stakeholder_ids)
        new_actor_ids: list[str] = []
        seen_actors: set[str] = set()
        groups: dict[tuple[str, str], str] = {}
        for action, flow_name in rows:
            aid = str(action.actor_id)
            if aid not in existing_ids and aid not in seen_actors:
                new_actor_ids.append(aid)
                seen_actors.add(aid)
            key = (aid, _classify(action.description))
            if key not in groups:
                groups[key] = flow_name

        if new_actor_ids:
            valid_result = await self.db.execute(
                select(Stakeholder).where(
                    Stakeholder.id.in_([uuid.UUID(i) for i in new_actor_ids]),
                    Stakeholder.project_id == project_id,
                )
            )
            new_actor_ids = [str(s.id) for s in valid_result.scalars().all()
                             if str(s.id) not in existing_ids]

        all_valid_ids = existing_ids | set(new_actor_ids)
        existing_pairs: set[tuple[str, str]] = {
            (f.get("source", ""), f.get("target", ""))
            for f in diagram.flows
        }
        new_flows: list[dict[str, Any]] = []
        for (aid, direction), label in groups.items():
            if aid not in all_valid_ids:
                continue
            src, tgt = (_CENTER, aid) if direction == "system_to_actor" else (aid, _CENTER)
            if (src, tgt) not in existing_pairs:
                new_flows.append({"id": str(uuid.uuid4()), "source": src, "target": tgt, "label": label})
                existing_pairs.add((src, tgt))

        if new_actor_ids:
            diagram.stakeholder_ids = diagram.stakeholder_ids + new_actor_ids
            flag_modified(diagram, "stakeholder_ids")

        if new_flows:
            diagram.flows = diagram.flows + new_flows
            flag_modified(diagram, "flows")

        if new_actor_ids or new_flows:
            await self.db.flush()

        stakeholder_map = await self._load_stakeholders_for(project_id, diagram.stakeholder_ids)
        return SyncResult(
            added_stakeholders=len(new_actor_ids),
            added_flows=len(new_flows),
            diagram=self._build_response(project_name, diagram, stakeholder_map),
        )
