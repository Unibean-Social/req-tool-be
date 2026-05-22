from __future__ import annotations

import asyncio
import uuid
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.project import Project
from app.models.project_business import (
    ProjectBusinessRequirement,
    ProjectConstraint,
    ProjectFlow,
    ProjectFlowAction,
    ProjectGoal,
    ProjectOutOfScope,
    ProjectRule,
    RuleType,
)
from app.models.stakeholder import Stakeholder


def _or_na(value) -> str:
    return str(value) if value else "_N/A_"


class BRDExportService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate(self, project_id: uuid.UUID) -> str:
        (
            project,
            goals_result,
            brs_result,
            stakeholders_result,
            rules_result,
            flows_result,
            constraints_result,
            out_of_scope_result,
        ) = await asyncio.gather(
            self.db.get(Project, project_id),
            self.db.execute(
                select(ProjectGoal)
                .where(ProjectGoal.project_id == project_id)
                .order_by(ProjectGoal.order)
                .options(selectinload(ProjectGoal.objectives))
            ),
            self.db.execute(
                select(ProjectBusinessRequirement)
                .where(ProjectBusinessRequirement.project_id == project_id)
                .order_by(ProjectBusinessRequirement.created_at)
            ),
            self.db.execute(
                select(Stakeholder).where(Stakeholder.project_id == project_id).order_by(Stakeholder.name)
            ),
            self.db.execute(
                select(ProjectRule).where(ProjectRule.project_id == project_id).order_by(ProjectRule.created_at)
            ),
            self.db.execute(
                select(ProjectFlow)
                .where(ProjectFlow.project_id == project_id)
                .options(selectinload(ProjectFlow.actions).selectinload(ProjectFlowAction.actor))
            ),
            self.db.execute(
                select(ProjectConstraint).where(ProjectConstraint.project_id == project_id).order_by(ProjectConstraint.created_at)
            ),
            self.db.execute(
                select(ProjectOutOfScope)
                .where(ProjectOutOfScope.project_id == project_id)
                .order_by(ProjectOutOfScope.order)
            ),
        )

        if project is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found")

        goals = goals_result.scalars().all()
        brs = brs_result.scalars().all()
        stakeholders = stakeholders_result.scalars().all()
        rules = rules_result.scalars().all()
        flows = flows_result.scalars().all()
        constraints = constraints_result.scalars().all()
        out_of_scope_items = out_of_scope_result.scalars().all()

        start = str(project.start_date) if project.start_date else "TBD"
        end = str(project.end_date) if project.end_date else "TBD"
        budget = f"{project.budget:,.2f}" if project.budget is not None else "TBD"
        today = date.today().isoformat()

        sections: list[str] = []

        # Header
        sections.append(
            f"# Business Requirements Document\n"
            f"**Project:** {project.name}\n"
            f"**Scope:** {start} → {end} | Budget: {budget}\n"
            f"**Exported:** {today}"
        )

        # 1. Executive Summary
        sections.append(
            f"## 1. Executive Summary\n"
            f"{project.executive_summary or '_N/A_'}"
        )

        # 2. Business Goals & Objectives
        if goals:
            goal_blocks = []
            for g in goals:
                obj_lines = "\n".join(f"- {o.description}" for o in g.objectives) if g.objectives else "- _No objectives defined._"
                goal_blocks.append(
                    f"### {g.description} `[{g.priority.value}]`\n"
                    f"- **Success Metric:** {_or_na(g.success_metric)}\n"
                    f"- **Target Date:** {_or_na(g.target_date)}\n\n"
                    f"**Objectives:**\n{obj_lines}"
                )
            sections.append("## 2. Business Goals & Objectives\n\n" + "\n\n".join(goal_blocks))
        else:
            sections.append("## 2. Business Goals & Objectives\n\n_No goals defined._")

        # 3. Business Requirements
        if brs:
            rows = ["| # | Priority | Critical | Description |", "|---|----------|----------|-------------|"]
            for i, br in enumerate(brs, 1):
                critical = "✓" if br.is_critical else ""
                rows.append(f"| {i} | {br.priority.value} | {critical} | {br.description} |")
            sections.append("## 3. Business Requirements\n\n" + "\n".join(rows))
        else:
            sections.append("## 3. Business Requirements\n\n_No business requirements defined._")

        # 4. Stakeholders
        if stakeholders:
            rows = ["| Name | Role | Type |", "|------|------|------|"]
            for s in stakeholders:
                stype = "Business Actor" if s.is_business_actor else "Stakeholder"
                rows.append(f"| {s.name} | {_or_na(s.role)} | {stype} |")
            sections.append("## 4. Stakeholders\n\n" + "\n".join(rows))
        else:
            sections.append("## 4. Stakeholders\n\n_No stakeholders defined._")

        # 5. Business Rules (grouped by type)
        if rules:
            grouped: dict[RuleType, list] = {}
            for r in rules:
                grouped.setdefault(r.type, []).append(r)
            rule_blocks = []
            type_labels = {
                RuleType.constraint: "Constraints",
                RuleType.validation: "Validations",
                RuleType.policy: "Policies",
                RuleType.calculation: "Calculations",
                RuleType.process: "Processes",
                RuleType.regulation: "Regulations",
            }
            for rtype, label in type_labels.items():
                if rtype in grouped:
                    items = "\n".join(f"- {r.rule_def}" for r in grouped[rtype])
                    rule_blocks.append(f"### {label}\n{items}")
            sections.append("## 5. Business Rules\n\n" + "\n\n".join(rule_blocks))
        else:
            sections.append("## 5. Business Rules\n\n_No business rules defined._")

        # 6. Business Flows
        if flows:
            flow_blocks = []
            for f in flows:
                desc = f"\n{f.description}" if f.description else ""
                if f.actions:
                    sorted_actions = sorted(f.actions, key=lambda a: a.order)
                    rows = ["| Step | Action | Actor |", "|------|--------|-------|"]
                    for i, a in enumerate(sorted_actions, 1):
                        actor_name = a.actor.name if a.actor else "—"
                        rows.append(f"| {i} | {a.description} | {actor_name} |")
                    action_table = "\n".join(rows)
                else:
                    action_table = "_No actions defined._"
                flow_blocks.append(f"### {f.name}{desc}\n\n{action_table}")
            sections.append("## 6. Business Flows\n\n" + "\n\n".join(flow_blocks))
        else:
            sections.append("## 6. Business Flows\n\n_No business flows defined._")

        # 7. Constraints
        if constraints:
            rows = ["| Type | Severity | Description |", "|------|----------|-------------|"]
            for c in constraints:
                rows.append(f"| {c.type.value} | {c.severity.value} | {c.description} |")
            sections.append("## 7. Constraints\n\n" + "\n".join(rows))
        else:
            sections.append("## 7. Constraints\n\n_No constraints defined._")

        # 8. Out of Scope
        if out_of_scope_items:
            rows = ["| # | Category | Description |", "|---|----------|-------------|"]
            for i, item in enumerate(out_of_scope_items, 1):
                cat = item.category.value if item.category else "—"
                rows.append(f"| {i} | {cat} | {item.description} |")
            sections.append("## 8. Out of Scope\n\n" + "\n".join(rows))
        else:
            sections.append("## 8. Out of Scope\n\n_No out-of-scope items defined._")

        return "\n\n---\n\n".join(sections)
