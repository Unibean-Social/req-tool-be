"""
Seed a realistic mock project: "Hệ thống quản lý đặt hàng nội bộ" (Internal Order Management).
Full BRD data + detailed swimlane with all UML notation types.

Idempotent — deletes existing project with same slug before re-seeding.

Prerequisites:
  - seed_dev_users.py must have run (uses alice-dev as org owner)

Usage:
    python scripts/seed_mock_project.py                          # seed project only
    python scripts/seed_mock_project.py --add-member <login>     # add GitHub user as org member + project member
"""

import asyncio
import sys
import os
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import select, delete

from app.database import async_session_factory
from app.models.user import User
from app.models.organization import Organization, OrgMember
from app.models.project import Project
from app.models.project_business import (
    ProjectGoal, ProjectGoalObjective, ProjectFlow, ProjectFlowAction,
    ProjectRule, ProjectConstraint, ProjectBusinessRequirement,
    GoalPriority, ConstraintType, ConstraintSeverity, RuleType,
    project_flow_action_rules,
)
from app.models.stakeholder import Stakeholder, InfluenceLevel
from app.models.actor import Actor
from app.models.nfr import NFR, NFRCategory
from app.models.requirements import (
    Epic, Feature, Story, Task, AcceptanceCriteria,
    Priority, ItemStatus,
)


ORG_SLUG = "fpt-software"
PROJECT_SLUG = "internal-order-mgmt"


async def _get_or_create_org(session, owner: User) -> Organization:
    result = await session.execute(select(Organization).where(Organization.slug == ORG_SLUG))
    org = result.scalar_one_or_none()
    if org:
        return org
    org = Organization(name="FPT Software", slug=ORG_SLUG, owner_id=owner.id)
    session.add(org)
    await session.flush()
    member = OrgMember(org_id=org.id, user_id=owner.id, role="owner")
    session.add(member)
    await session.flush()
    return org


async def _get_alice(session) -> User:
    result = await session.execute(select(User).where(User.github_id == "dev_1001"))
    user = result.scalar_one_or_none()
    if not user:
        raise RuntimeError("Run seed_dev_users.py first")
    return user


async def seed():
    async with async_session_factory() as session:
        alice = await _get_alice(session)
        org = await _get_or_create_org(session, alice)

        # Idempotent: remove existing
        existing = await session.execute(
            select(Project).where(Project.slug == PROJECT_SLUG, Project.org_id == org.id)
        )
        old = existing.scalar_one_or_none()
        if old:
            await session.delete(old)
            await session.flush()
            print("[seed] removed existing project, re-seeding...")

        # ── Project ──────────────────────────────────────────────────────────
        project = Project(
            org_id=org.id,
            name="Hệ thống quản lý đặt hàng nội bộ",
            slug=PROJECT_SLUG,
            description=(
                "Xây dựng nền tảng số hóa toàn bộ quy trình đặt hàng nội bộ từ phòng ban "
                "đến kho và kế toán, thay thế hoàn toàn quy trình thủ công trên Excel."
            ),
            context=(
                "Công ty hiện xử lý ~500 đơn đặt hàng/tháng qua email + Excel, dẫn đến sai lệch "
                "dữ liệu, mất tích hợp kế toán và trễ giao hàng trung bình 3 ngày. Dự án nằm trong "
                "chương trình chuyển đổi số 2026 của FPT Software."
            ),
            problems=[
                "Quy trình thủ công dẫn đến sai lệch tồn kho ~8% mỗi quý",
                "Không có visibility real-time về trạng thái đơn hàng",
                "Tích hợp kế toán mất 2-3 ngày thủ công mỗi tháng",
                "Khó audit trail khi cần đối chiếu sai lệch",
            ],
            proposed_solutions=[
                "Hệ thống web app với phân quyền theo vai trò (Requester / Approver / Warehouse / Accountant)",
                "Workflow tự động: tạo đơn → duyệt → xử lý kho → xuất hóa đơn",
                "Tích hợp ERP qua REST API (SAP B1)",
                "Dashboard analytics real-time cho quản lý",
            ],
            start_date=date(2026, 6, 1),
            end_date=date(2026, 12, 31),
            budget=Decimal("850000000"),  # 850 triệu VND
            executive_summary=(
                "Dự án số hóa quy trình đặt hàng nội bộ nhằm giảm 80% thời gian xử lý thủ công, "
                "đạt độ chính xác tồn kho ≥ 99%, và tích hợp real-time với ERP trong Q4/2026."
            ),
            roi_notes=(
                "Tiết kiệm ước tính 240 giờ nhân công/tháng (≈ 96 triệu VND/năm). "
                "Giảm sai lệch tồn kho từ 8% xuống <1% — tránh thiệt hại ≈ 200 triệu/năm. "
                "Hoàn vốn dự kiến trong 6-8 tháng sau go-live."
            ),
        )
        session.add(project)
        await session.flush()

        pid = project.id

        # ── Stakeholders ─────────────────────────────────────────────────────
        sh_pm = Stakeholder(
            project_id=pid, name="Nguyễn Minh Tuấn", role="Project Manager",
            impact_area="Toàn dự án — lập kế hoạch, quản lý rủi ro",
            influence_level=InfluenceLevel.high, is_business_actor=False,
            notes="Người phê duyệt ngân sách chính, cần báo cáo tiến độ tuần",
        )
        sh_po = Stakeholder(
            project_id=pid, name="Trần Thị Lan", role="Product Owner / Trưởng phòng Mua hàng",
            impact_area="Nghiệp vụ đặt hàng và duyệt chi",
            influence_level=InfluenceLevel.high, is_business_actor=True,
            notes="Người xác nhận nghiệp vụ, tham gia UAT sprint 3",
        )
        sh_wh = Stakeholder(
            project_id=pid, name="Lê Văn Hùng", role="Trưởng kho",
            impact_area="Quy trình nhận hàng, xuất hàng và kiểm kê",
            influence_level=InfluenceLevel.medium, is_business_actor=True,
            notes="Cần đào tạo UX do ít kinh nghiệm với web app",
        )
        sh_acc = Stakeholder(
            project_id=pid, name="Phạm Thị Hoa", role="Kế toán trưởng",
            impact_area="Tích hợp ERP, xuất hóa đơn, báo cáo tài chính",
            influence_level=InfluenceLevel.high, is_business_actor=True,
            notes="Yêu cầu audit log đầy đủ theo tiêu chuẩn ISO 27001",
        )
        sh_it = Stakeholder(
            project_id=pid, name="Đỗ Quang Minh", role="IT Infrastructure Lead",
            impact_area="Hạ tầng triển khai, bảo mật, tích hợp ERP",
            influence_level=InfluenceLevel.medium, is_business_actor=False,
            notes="Phụ trách review kiến trúc và go-live checklist",
        )
        session.add_all([sh_pm, sh_po, sh_wh, sh_acc, sh_it])
        await session.flush()

        # ── Goals ─────────────────────────────────────────────────────────────
        goal1 = ProjectGoal(
            project_id=pid, order=1, priority=GoalPriority.high,
            description="Giảm thời gian xử lý đơn hàng trung bình từ 3 ngày xuống còn 4 giờ",
            success_metric="Lead time trung bình ≤ 4h đo trên 95% đơn trong tháng đầu sau go-live",
            target_date=date(2026, 11, 30),
        )
        goal2 = ProjectGoal(
            project_id=pid, order=2, priority=GoalPriority.high,
            description="Đạt độ chính xác tồn kho ≥ 99% và loại bỏ sai lệch do nhập liệu thủ công",
            success_metric="Tỷ lệ chênh lệch tồn kho < 1% sau 3 tháng vận hành",
            target_date=date(2026, 12, 31),
        )
        goal3 = ProjectGoal(
            project_id=pid, order=3, priority=GoalPriority.medium,
            description="Tích hợp real-time với SAP B1 ERP, loại bỏ nhập liệu kế toán thủ công",
            success_metric="100% đơn đã duyệt đồng bộ ERP trong vòng 5 phút; 0 bản ghi nhập tay",
            target_date=date(2026, 12, 15),
        )
        goal4 = ProjectGoal(
            project_id=pid, order=4, priority=GoalPriority.low,
            description="Cung cấp dashboard analytics để quản lý ra quyết định dựa trên dữ liệu",
            success_metric="Tối thiểu 3 KPI dashboard được sử dụng hàng tuần bởi cấp quản lý",
            target_date=date(2026, 12, 31),
        )
        session.add_all([goal1, goal2, goal3, goal4])
        await session.flush()

        # Objectives
        objs = [
            ProjectGoalObjective(goal_id=goal1.id, description="Chuẩn hóa form đặt hàng số, tích hợp catalog sản phẩm"),
            ProjectGoalObjective(goal_id=goal1.id, description="Workflow duyệt 1-click qua email/app notification"),
            ProjectGoalObjective(goal_id=goal1.id, description="Auto-assign đơn đến kho phụ trách theo category"),
            ProjectGoalObjective(goal_id=goal2.id, description="Barcode scan khi nhận/xuất hàng tại kho"),
            ProjectGoalObjective(goal_id=goal2.id, description="Reconciliation report tự động cuối ngày"),
            ProjectGoalObjective(goal_id=goal3.id, description="REST API connector đến SAP B1 Purchase Order module"),
            ProjectGoalObjective(goal_id=goal3.id, description="Retry queue cho các event đồng bộ thất bại"),
            ProjectGoalObjective(goal_id=goal4.id, description="Biểu đồ trạng thái đơn theo thời gian thực"),
            ProjectGoalObjective(goal_id=goal4.id, description="Báo cáo top nhà cung cấp theo giá trị đơn hàng"),
        ]
        session.add_all(objs)
        await session.flush()

        # ── Constraints ───────────────────────────────────────────────────────
        constraints = [
            ProjectConstraint(
                project_id=pid, type=ConstraintType.budget, severity=ConstraintSeverity.high,
                description="Tổng ngân sách không vượt 850 triệu VND; không được phép request thêm ngân sách sau tháng 9",
            ),
            ProjectConstraint(
                project_id=pid, type=ConstraintType.timeline, severity=ConstraintSeverity.high,
                description="Go-live bắt buộc trước 31/12/2026 để kịp chu kỳ quyết toán Q4",
            ),
            ProjectConstraint(
                project_id=pid, type=ConstraintType.technical, severity=ConstraintSeverity.medium,
                description="Phải tương thích với SAP B1 9.3 — không thể nâng cấp ERP trong vòng dự án",
            ),
            ProjectConstraint(
                project_id=pid, type=ConstraintType.technical, severity=ConstraintSeverity.medium,
                description="Stack backend giới hạn ở Python/FastAPI + PostgreSQL theo chuẩn nội bộ FPT",
            ),
            ProjectConstraint(
                project_id=pid, type=ConstraintType.resource, severity=ConstraintSeverity.medium,
                description="Team tối đa 6 người (2 BE, 2 FE, 1 QA, 1 DevOps); không được outsource",
            ),
            ProjectConstraint(
                project_id=pid, type=ConstraintType.regulatory, severity=ConstraintSeverity.high,
                description="Dữ liệu tài chính phải lưu trữ tối thiểu 5 năm theo Luật kế toán 88/2015/QH13",
            ),
        ]
        session.add_all(constraints)
        await session.flush()

        # ── Business Requirements ──────────────────────────────────────────────
        brs = [
            ProjectBusinessRequirement(
                project_id=pid, priority=GoalPriority.high, is_critical=True,
                description="Hệ thống phải hỗ trợ phân quyền 4 vai trò: Requester, Approver, Warehouse Staff, Accountant",
            ),
            ProjectBusinessRequirement(
                project_id=pid, priority=GoalPriority.high, is_critical=True,
                description="Đơn hàng phải qua ít nhất 1 bước duyệt (Approver) trước khi chuyển kho",
            ),
            ProjectBusinessRequirement(
                project_id=pid, priority=GoalPriority.high, is_critical=True,
                description="Mọi thay đổi trạng thái đơn hàng phải ghi audit log với timestamp và user thực hiện",
            ),
            ProjectBusinessRequirement(
                project_id=pid, priority=GoalPriority.high, is_critical=False,
                description="Gửi thông báo email/in-app tại các bước: đơn mới, duyệt/từ chối, kho xác nhận, hoàn thành",
            ),
            ProjectBusinessRequirement(
                project_id=pid, priority=GoalPriority.medium, is_critical=False,
                description="Hỗ trợ đặt hàng theo catalog sản phẩm với đơn giá tham chiếu từ nhà cung cấp ưu tiên",
            ),
            ProjectBusinessRequirement(
                project_id=pid, priority=GoalPriority.medium, is_critical=False,
                description="Requester có thể theo dõi real-time trạng thái đơn đã tạo",
            ),
            ProjectBusinessRequirement(
                project_id=pid, priority=GoalPriority.low, is_critical=False,
                description="Cho phép đính kèm file (quotation, invoice) tối đa 10MB/file, tối đa 5 file/đơn",
            ),
        ]
        session.add_all(brs)
        await session.flush()

        # ── Business Rules ─────────────────────────────────────────────────────
        rule_approval = ProjectRule(
            project_id=pid, type=RuleType.policy,
            rule_def="Đơn hàng có giá trị > 50 triệu VND phải có chữ ký duyệt của 2 cấp quản lý",
            is_dynamic=False, source="Quy chế tài chính nội bộ FPT-TC-2024-07",
        )
        rule_supplier = ProjectRule(
            project_id=pid, type=RuleType.constraint,
            rule_def="Chỉ được đặt hàng từ nhà cung cấp trong danh sách phê duyệt (approved vendor list)",
            is_dynamic=False, source="Chính sách mua hàng FPT-MH-2025-03",
        )
        rule_budget_check = ProjectRule(
            project_id=pid, type=RuleType.validation,
            rule_def="Tổng giá trị đơn hàng phòng ban trong tháng không được vượt ngân sách phân bổ",
            is_dynamic=True, source="Hệ thống ERP SAP B1 — cost center budget",
        )
        rule_stock = ProjectRule(
            project_id=pid, type=RuleType.process,
            rule_def="Khi nhận hàng, số lượng thực nhận phải được xác nhận trong vòng 24h; quá hạn tự động escalate",
            is_dynamic=False, source="SLA kho nội bộ",
        )
        rule_erp_sync = ProjectRule(
            project_id=pid, type=RuleType.process,
            rule_def="Sau khi đơn hàng chuyển sang trạng thái 'Đã duyệt', hệ thống tự động tạo Purchase Order trên SAP B1",
            is_dynamic=False, source="Tích hợp ERP design doc v1.2",
        )
        rule_tax = ProjectRule(
            project_id=pid, type=RuleType.regulation,
            rule_def="Hóa đơn VAT phải được upload và liên kết với đơn hàng trong vòng 30 ngày theo Thông tư 78/2021/TT-BTC",
            is_dynamic=False, source="Thông tư 78/2021/TT-BTC",
        )
        rule_cancel = ProjectRule(
            project_id=pid, type=RuleType.policy,
            rule_def="Đơn hàng chỉ có thể hủy khi chưa kho xác nhận xuất; sau đó cần approval từ Approver",
            is_dynamic=False, source="Quy trình mua hàng nội bộ v3",
        )
        session.add_all([rule_approval, rule_supplier, rule_budget_check, rule_stock, rule_erp_sync, rule_tax, rule_cancel])
        await session.flush()

        # ── Actors (functional) ───────────────────────────────────────────────
        actor_requester = Actor(
            project_id=pid, name="Requester",
            role_description="Nhân viên/phòng ban tạo yêu cầu đặt hàng. Có thể xem trạng thái đơn do mình tạo.",
        )
        actor_approver = Actor(
            project_id=pid, name="Approver",
            role_description="Quản lý cấp trung phê duyệt hoặc từ chối đơn hàng. Nhận notification khi có đơn chờ duyệt.",
        )
        actor_warehouse = Actor(
            project_id=pid, name="Warehouse Staff",
            role_description="Nhân viên kho xử lý đơn đã duyệt: xác nhận nhận hàng, cập nhật tồn kho.",
        )
        actor_accountant = Actor(
            project_id=pid, name="Accountant",
            role_description="Kế toán xử lý hóa đơn tài chính, đồng bộ ERP và xuất báo cáo tài chính.",
        )
        session.add_all([actor_requester, actor_approver, actor_warehouse, actor_accountant])
        await session.flush()

        # ── NFRs ──────────────────────────────────────────────────────────────
        nfrs = [
            NFR(project_id=pid, category=NFRCategory.performance, priority=Priority.high,
                description="API response time < 500ms ở P95 với load 200 concurrent users"),
            NFR(project_id=pid, category=NFRCategory.performance, priority=Priority.medium,
                description="Trang danh sách đơn hàng load < 2s với 10,000 bản ghi"),
            NFR(project_id=pid, category=NFRCategory.security, priority=Priority.critical,
                description="Xác thực JWT HS256; session hết hạn sau 8h; refresh token 30 ngày"),
            NFR(project_id=pid, category=NFRCategory.security, priority=Priority.high,
                description="Mọi API endpoint phải có RBAC theo 4 vai trò; kiểm tra lúc runtime"),
            NFR(project_id=pid, category=NFRCategory.reliability, priority=Priority.high,
                description="Uptime ≥ 99.5% trong giờ hành chính (8h-18h, T2-T6)"),
            NFR(project_id=pid, category=NFRCategory.reliability, priority=Priority.medium,
                description="Retry tự động tối đa 3 lần với exponential backoff cho ERP sync"),
            NFR(project_id=pid, category=NFRCategory.usability, priority=Priority.medium,
                description="Giao diện đáp ứng Mobile (≥ 768px); nhân viên kho dùng máy tính bảng"),
            NFR(project_id=pid, category=NFRCategory.compliance, priority=Priority.high,
                description="Audit log bất biến (append-only), lưu trữ tối thiểu 5 năm theo Luật kế toán"),
            NFR(project_id=pid, category=NFRCategory.maintainability, priority=Priority.medium,
                description="Code coverage ≥ 80%; pipeline CI/CD tự động với gate kiểm tra coverage"),
        ]
        session.add_all(nfrs)
        await session.flush()

        # ── Flows ─────────────────────────────────────────────────────────────
        # Flow 1: Main order processing flow — full swimlane with all notation types
        flow1 = ProjectFlow(
            project_id=pid, code="FLOW-001",
            name="Quy trình đặt hàng và duyệt",
            description=(
                "Luồng chính từ khi Requester tạo đơn đến khi đơn được duyệt hoặc từ chối, "
                "bao gồm kiểm tra ngân sách và đồng bộ ERP sau duyệt."
            ),
        )
        flow2 = ProjectFlow(
            project_id=pid, code="FLOW-002",
            name="Quy trình xử lý kho và hoàn tất",
            description=(
                "Luồng xử lý tại kho sau khi đơn được duyệt: nhận hàng, kiểm tra chất lượng, "
                "cập nhật tồn kho, xác nhận hoàn thành."
            ),
        )
        session.add_all([flow1, flow2])
        await session.flush()

        # ── Flow 1 Actions — Requester + Approver lanes, all notation types ──
        # Stakeholders used as actors in swimlane
        actions_f1 = [
            ProjectFlowAction(flow_id=flow1.id, order=1, actor_id=sh_po.id,
                description="Nhân viên điền form đặt hàng: chọn sản phẩm từ catalog, số lượng, nhà cung cấp ưu tiên"),
            ProjectFlowAction(flow_id=flow1.id, order=2, actor_id=sh_po.id,
                description="Kiểm tra nhà cung cấp có trong danh sách phê duyệt (approved vendor list) không"),
            ProjectFlowAction(flow_id=flow1.id, order=3, actor_id=sh_po.id,
                description="Tách đơn song song: gửi đơn lên hệ thống và đồng thời gửi email notification cho Approver"),
            ProjectFlowAction(flow_id=flow1.id, order=4, actor_id=sh_acc.id,
                description="Kiểm tra ngân sách phòng ban còn lại — nếu vượt hạn mức thì từ chối tự động"),
            ProjectFlowAction(flow_id=flow1.id, order=5, actor_id=sh_pm.id,
                description="Hội tụ kết quả kiểm tra ngân sách và xác nhận notification đã gửi trước khi Approver duyệt"),
            ProjectFlowAction(flow_id=flow1.id, order=6, actor_id=sh_pm.id,
                description="Approver xem xét đơn hàng: kiểm tra thông tin sản phẩm, nhà cung cấp, và ngân sách"),
            ProjectFlowAction(flow_id=flow1.id, order=7, actor_id=sh_pm.id,
                description="Nếu giá trị đơn > 50 triệu VND thì yêu cầu duyệt cấp 2; nếu không thì duyệt trực tiếp"),
            ProjectFlowAction(flow_id=flow1.id, order=8, actor_id=sh_pm.id,
                description="Approver ghi chú quyết định (duyệt hoặc từ chối) và xác nhận trên hệ thống"),
            ProjectFlowAction(flow_id=flow1.id, order=9, actor_id=sh_acc.id,
                description="Sau khi duyệt, hợp nhất luồng xử lý và cập nhật trạng thái đơn thành 'Đã duyệt'"),
            ProjectFlowAction(flow_id=flow1.id, order=10, actor_id=sh_acc.id,
                description="Tự động tạo Purchase Order trên SAP B1 và lưu mã PO vào hệ thống"),
        ]
        session.add_all(actions_f1)
        await session.flush()

        # Link rules to flow 1 actions via M2M association table
        from sqlalchemy import insert as sa_insert
        await session.execute(sa_insert(project_flow_action_rules).values(action_id=actions_f1[1].id, rule_id=rule_supplier.id))
        await session.execute(sa_insert(project_flow_action_rules).values(action_id=actions_f1[3].id, rule_id=rule_budget_check.id))
        await session.execute(sa_insert(project_flow_action_rules).values(action_id=actions_f1[6].id, rule_id=rule_approval.id))
        await session.execute(sa_insert(project_flow_action_rules).values(action_id=actions_f1[9].id, rule_id=rule_erp_sync.id))
        await session.flush()

        # ── Flow 1 Swimlane (manual — full UML notation) ──────────────────────
        a = actions_f1
        flow1.swimlane = {
            "id": str(flow1.id),
            "title": "Quy trình đặt hàng và duyệt",
            "lanes": [
                {"id": f"lane-{sh_po.id}", "title": "Requester (Phòng ban)"},
                {"id": f"lane-{sh_acc.id}", "title": "Kế toán / Hệ thống"},
                {"id": f"lane-{sh_pm.id}", "title": "Approver (Quản lý)"},
            ],
            "initial_node": {"id": "start", "lane_id": f"lane-{sh_po.id}", "y": 50},
            "activity_final_node": {"id": "end", "lane_id": f"lane-{sh_acc.id}", "y": 1050},
            "actions": [
                # order=1: action — Requester fills form
                {"id": str(a[0].id), "lane_id": f"lane-{sh_po.id}",   "notation": "action",    "index": 0, "y": 150,  "label": a[0].description},
                # order=2: decision — is vendor in approved list?
                {"id": str(a[1].id), "lane_id": f"lane-{sh_po.id}",   "notation": "decision",  "index": 1, "y": 250,  "label": "Nhà cung cấp có trong danh sách phê duyệt?"},
                # order=3: fork — parallel split: submit form + send email
                {"id": str(a[2].id), "lane_id": f"lane-{sh_po.id}",   "notation": "fork",      "index": 2, "y": 350,  "label": "Fork: Gửi đơn & Gửi notification song song"},
                # order=4: decision — budget check
                {"id": str(a[3].id), "lane_id": f"lane-{sh_acc.id}",  "notation": "decision",  "index": 3, "y": 450,  "label": "Ngân sách còn đủ?"},
                # order=5: join — synchronize parallel paths
                {"id": str(a[4].id), "lane_id": f"lane-{sh_pm.id}",   "notation": "join",      "index": 4, "y": 550,  "label": "Join: Đồng bộ kết quả kiểm tra ngân sách"},
                # order=6: action — Approver reviews
                {"id": str(a[5].id), "lane_id": f"lane-{sh_pm.id}",   "notation": "action",    "index": 5, "y": 650,  "label": a[5].description},
                # order=7: decision — value > 50M requires L2 approval
                {"id": str(a[6].id), "lane_id": f"lane-{sh_pm.id}",   "notation": "decision",  "index": 6, "y": 750,  "label": "Giá trị > 50 triệu VND?"},
                # order=8: action — Approver records decision
                {"id": str(a[7].id), "lane_id": f"lane-{sh_pm.id}",   "notation": "action",    "index": 7, "y": 850,  "label": a[7].description},
                # order=9: merge — merge approved paths
                {"id": str(a[8].id), "lane_id": f"lane-{sh_acc.id}",  "notation": "merge",     "index": 8, "y": 950,  "label": "Merge: Hợp nhất luồng duyệt"},
                # order=10: objectNode — ERP Purchase Order record
                {"id": str(a[9].id), "lane_id": f"lane-{sh_acc.id}",  "notation": "objectNode","index": 9, "y": 1000, "label": "SAP B1 Purchase Order [đã tạo]"},
            ],
            "flows": [
                {"id": "f-start-a0", "source": "start", "target": str(a[0].id), "flow_type": "control"},
                {"id": f"f-a0-a1", "source": str(a[0].id), "target": str(a[1].id), "flow_type": "control"},
                # Decision a[1]: approved → fork; rejected → end directly
                {"id": f"f-a1-a2",    "source": str(a[1].id), "target": str(a[2].id), "flow_type": "control", "guard": "Có trong danh sách"},
                {"id": f"f-a1-end",   "source": str(a[1].id), "target": "end",        "flow_type": "control", "guard": "Không có → từ chối"},
                # Fork → budget check lane + join (notification side implicit)
                {"id": f"f-a2-a3",    "source": str(a[2].id), "target": str(a[3].id), "flow_type": "control"},
                {"id": f"f-a2-a4",    "source": str(a[2].id), "target": str(a[4].id), "flow_type": "control"},
                # Budget decision
                {"id": f"f-a3-a4",    "source": str(a[3].id), "target": str(a[4].id), "flow_type": "control", "guard": "Đủ ngân sách"},
                {"id": f"f-a3-end",   "source": str(a[3].id), "target": "end",        "flow_type": "control", "guard": "Vượt ngân sách → từ chối"},
                {"id": f"f-a4-a5",    "source": str(a[4].id), "target": str(a[5].id), "flow_type": "control"},
                {"id": f"f-a5-a6",    "source": str(a[5].id), "target": str(a[6].id), "flow_type": "control"},
                # L2 approval decision
                {"id": f"f-a6-a7",    "source": str(a[6].id), "target": str(a[7].id), "flow_type": "control", "guard": "≤ 50M VND"},
                {"id": f"f-a6-l2",    "source": str(a[6].id), "target": str(a[7].id), "flow_type": "control", "guard": "> 50M VND → duyệt cấp 2"},
                {"id": f"f-a7-a8",    "source": str(a[7].id), "target": str(a[8].id), "flow_type": "control"},
                {"id": f"f-a8-a9",    "source": str(a[8].id), "target": str(a[9].id), "flow_type": "object"},
                {"id": f"f-a9-end",   "source": str(a[9].id), "target": "end",        "flow_type": "control"},
            ],
            "layout": None,
        }

        # ── Flow 2 Actions — Warehouse + Accountant lanes ─────────────────────
        actions_f2 = [
            ProjectFlowAction(flow_id=flow2.id, order=1, actor_id=sh_wh.id,
                description="Kho nhận thông báo đơn hàng đã duyệt và chuẩn bị tiếp nhận hàng"),
            ProjectFlowAction(flow_id=flow2.id, order=2, actor_id=sh_wh.id,
                description="Kiểm tra hàng thực tế nhận được: số lượng, chất lượng, hạn sử dụng"),
            ProjectFlowAction(flow_id=flow2.id, order=3, actor_id=sh_wh.id,
                description="Nếu hàng có sai lệch (thiếu/hỏng) thì báo cáo sự cố; nếu không thì tiếp tục nhập kho"),
            ProjectFlowAction(flow_id=flow2.id, order=4, actor_id=sh_wh.id,
                description="Scan barcode và cập nhật tồn kho trong hệ thống"),
            ProjectFlowAction(flow_id=flow2.id, order=5, actor_id=sh_acc.id,
                description="Kế toán nhận hóa đơn VAT từ nhà cung cấp và upload lên hệ thống"),
            ProjectFlowAction(flow_id=flow2.id, order=6, actor_id=sh_acc.id,
                description="Đồng bộ dữ liệu nhập kho và hóa đơn vào SAP B1 — cập nhật Goods Receipt + Invoice"),
            ProjectFlowAction(flow_id=flow2.id, order=7, actor_id=sh_acc.id,
                description="Dữ liệu tài chính đã được xử lý: bản ghi kế toán hoàn tất [objectNode]"),
            ProjectFlowAction(flow_id=flow2.id, order=8, actor_id=sh_wh.id,
                description="Gửi xác nhận hoàn thành đơn hàng đến Requester và đánh dấu đơn Done"),
        ]
        session.add_all(actions_f2)
        await session.flush()

        await session.execute(sa_insert(project_flow_action_rules).values(action_id=actions_f2[3].id, rule_id=rule_stock.id))
        await session.execute(sa_insert(project_flow_action_rules).values(action_id=actions_f2[4].id, rule_id=rule_tax.id))
        await session.execute(sa_insert(project_flow_action_rules).values(action_id=actions_f2[5].id, rule_id=rule_erp_sync.id))
        await session.flush()

        b = actions_f2
        flow2.swimlane = {
            "id": str(flow2.id),
            "title": "Quy trình xử lý kho và hoàn tất",
            "lanes": [
                {"id": f"lane-{sh_wh.id}", "title": "Warehouse Staff (Kho)"},
                {"id": f"lane-{sh_acc.id}", "title": "Accountant (Kế toán)"},
            ],
            "initial_node": {"id": "start", "lane_id": f"lane-{sh_wh.id}", "y": 50},
            "activity_final_node": {"id": "end", "lane_id": f"lane-{sh_wh.id}", "y": 950},
            "actions": [
                {"id": str(b[0].id), "lane_id": f"lane-{sh_wh.id}",  "notation": "action",    "index": 0, "y": 150,  "label": b[0].description},
                {"id": str(b[1].id), "lane_id": f"lane-{sh_wh.id}",  "notation": "action",    "index": 1, "y": 250,  "label": b[1].description},
                {"id": str(b[2].id), "lane_id": f"lane-{sh_wh.id}",  "notation": "decision",  "index": 2, "y": 350,  "label": "Hàng có sai lệch (thiếu/hỏng)?"},
                {"id": str(b[3].id), "lane_id": f"lane-{sh_wh.id}",  "notation": "action",    "index": 3, "y": 500,  "label": b[3].description},
                {"id": str(b[4].id), "lane_id": f"lane-{sh_acc.id}", "notation": "action",    "index": 4, "y": 550,  "label": b[4].description},
                {"id": str(b[5].id), "lane_id": f"lane-{sh_acc.id}", "notation": "action",    "index": 5, "y": 650,  "label": b[5].description},
                {"id": str(b[6].id), "lane_id": f"lane-{sh_acc.id}", "notation": "objectNode","index": 6, "y": 750,  "label": "Bản ghi kế toán [hoàn tất]"},
                {"id": str(b[7].id), "lane_id": f"lane-{sh_wh.id}",  "notation": "action",    "index": 7, "y": 850,  "label": b[7].description},
            ],
            "flows": [
                {"id": "f-start-b0", "source": "start",    "target": str(b[0].id), "flow_type": "control"},
                {"id": "f-b0-b1",    "source": str(b[0].id),"target": str(b[1].id),"flow_type": "control"},
                {"id": "f-b1-b2",    "source": str(b[1].id),"target": str(b[2].id),"flow_type": "control"},
                {"id": "f-b2-b3",    "source": str(b[2].id),"target": str(b[3].id),"flow_type": "control", "guard": "Không sai lệch"},
                {"id": "f-b2-inc",   "source": str(b[2].id),"target": "end",       "flow_type": "control", "guard": "Có sai lệch → báo cáo sự cố"},
                {"id": "f-b3-b4",    "source": str(b[3].id),"target": str(b[4].id),"flow_type": "control"},
                {"id": "f-b4-b5",    "source": str(b[4].id),"target": str(b[5].id),"flow_type": "control"},
                {"id": "f-b5-b6",    "source": str(b[5].id),"target": str(b[6].id),"flow_type": "object"},
                {"id": "f-b6-b7",    "source": str(b[6].id),"target": str(b[7].id),"flow_type": "control"},
                {"id": "f-b7-end",   "source": str(b[7].id),"target": "end",       "flow_type": "control"},
            ],
            "layout": None,
        }
        await session.flush()

        # ── Epics / Features / Stories / Tasks ────────────────────────────────
        epic1 = Epic(
            project_id=pid, prefix="EP-001",
            title="Quản lý đơn đặt hàng (Order Management)",
            description="Toàn bộ nghiệp vụ tạo, duyệt và theo dõi đơn đặt hàng nội bộ",
            status=ItemStatus.in_progress, priority=Priority.high,
            labels=["core", "requester", "approver"],
        )
        epic2 = Epic(
            project_id=pid, prefix="EP-002",
            title="Quản lý kho (Warehouse Management)",
            description="Nhận hàng, kiểm tra, cập nhật tồn kho và xác nhận hoàn tất",
            status=ItemStatus.draft, priority=Priority.high,
            labels=["warehouse", "inventory"],
        )
        epic3 = Epic(
            project_id=pid, prefix="EP-003",
            title="Tích hợp ERP & Kế toán",
            description="Đồng bộ hai chiều với SAP B1: Purchase Order, Goods Receipt, Invoice",
            status=ItemStatus.draft, priority=Priority.high,
            labels=["erp", "accounting", "integration"],
        )
        epic4 = Epic(
            project_id=pid, prefix="EP-004",
            title="Dashboard & Báo cáo",
            description="Biểu đồ trạng thái đơn, KPI kho, top nhà cung cấp",
            status=ItemStatus.draft, priority=Priority.medium,
            labels=["analytics", "reporting"],
        )
        session.add_all([epic1, epic2, epic3, epic4])
        await session.flush()

        # Features for EP-001
        feat1_1 = Feature(
            epic_id=epic1.id, prefix="EP-001-F01",
            title="Tạo và quản lý đơn đặt hàng",
            description="Form tạo đơn với catalog sản phẩm, upload file đính kèm, lưu nháp",
            status=ItemStatus.in_progress, priority=Priority.high,
        )
        feat1_2 = Feature(
            epic_id=epic1.id, prefix="EP-001-F02",
            title="Workflow duyệt đơn hàng",
            description="Luồng duyệt 1-2 cấp, notification, audit log",
            status=ItemStatus.draft, priority=Priority.high,
        )
        feat1_3 = Feature(
            epic_id=epic1.id, prefix="EP-001-F03",
            title="Theo dõi trạng thái đơn hàng",
            description="Timeline view, real-time status, filter và search đơn",
            status=ItemStatus.draft, priority=Priority.medium,
        )
        # Features for EP-002
        feat2_1 = Feature(
            epic_id=epic2.id, prefix="EP-002-F01",
            title="Xử lý nhận hàng tại kho",
            description="Barcode scan, kiểm tra số lượng/chất lượng, báo cáo sự cố",
            status=ItemStatus.draft, priority=Priority.high,
        )
        session.add_all([feat1_1, feat1_2, feat1_3, feat2_1])
        await session.flush()

        # Stories for feat1_1
        story1 = Story(
            feature_id=feat1_1.id, prefix="EP-001-F01-S01",
            title="Tạo đơn đặt hàng mới từ catalog",
            actor_ref="Requester",
            action_text="muốn tạo đơn đặt hàng bằng cách chọn sản phẩm từ catalog và điền số lượng",
            goal_text="để gửi yêu cầu mua hàng nhanh hơn mà không cần nhớ mã sản phẩm",
            status=ItemStatus.in_progress, priority=Priority.high,
            story_points=8, business_value=90,
            labels=["catalog", "order-create"],
        )
        story2 = Story(
            feature_id=feat1_1.id, prefix="EP-001-F01-S02",
            title="Lưu đơn hàng dưới dạng nháp",
            actor_ref="Requester",
            action_text="muốn lưu đơn đang tạo dở làm nháp",
            goal_text="để tiếp tục điền thông tin sau mà không mất dữ liệu",
            status=ItemStatus.draft, priority=Priority.medium,
            story_points=3, business_value=40,
        )
        story3 = Story(
            feature_id=feat1_2.id, prefix="EP-001-F02-S01",
            title="Approver nhận notification và duyệt đơn",
            actor_ref="Approver",
            action_text="muốn nhận thông báo khi có đơn chờ duyệt và duyệt/từ chối trong 1 click",
            goal_text="để không bỏ sót đơn và giảm thời gian xử lý",
            status=ItemStatus.draft, priority=Priority.high,
            story_points=5, business_value=85,
            labels=["approval", "notification"],
        )
        session.add_all([story1, story2, story3])
        await session.flush()

        # Acceptance criteria
        ac_data = [
            (story1.id, 0, "Hiển thị catalog với tìm kiếm theo tên, mã, và danh mục"),
            (story1.id, 1, "Validate số lượng > 0 và không vượt quá giới hạn đặt hàng/lần"),
            (story1.id, 2, "Tự động điền đơn giá tham chiếu từ nhà cung cấp ưu tiên"),
            (story1.id, 3, "Sau submit, đơn xuất hiện trong danh sách 'Chờ duyệt' của Approver"),
            (story2.id, 0, "Nút 'Lưu nháp' hiển thị suốt quá trình điền form"),
            (story2.id, 1, "Đơn nháp hiển thị trong tab 'Nháp' của Requester, có thể tiếp tục chỉnh sửa"),
            (story3.id, 0, "Approver nhận email với link dẫn thẳng đến trang duyệt đơn"),
            (story3.id, 1, "Trang duyệt hiển thị đầy đủ: sản phẩm, số lượng, đơn giá, tổng giá trị, nhà cung cấp"),
            (story3.id, 2, "Có thể duyệt hoặc từ chối kèm ghi chú; ghi chú bắt buộc khi từ chối"),
        ]
        session.add_all([
            AcceptanceCriteria(story_id=sid, order=order, description=desc)
            for sid, order, desc in ac_data
        ])

        # Tasks for story1
        tasks = [
            Task(story_id=story1.id, prefix="EP-001-F01-S01-T01",
                 title="BE: API GET /catalog/products với pagination và filter",
                 status=ItemStatus.done, priority=Priority.high,
                 estimated_hours=4, category="backend"),
            Task(story_id=story1.id, prefix="EP-001-F01-S01-T02",
                 title="BE: API POST /orders — validate + tạo đơn + trigger notification",
                 status=ItemStatus.in_progress, priority=Priority.high,
                 estimated_hours=8, category="backend"),
            Task(story_id=story1.id, prefix="EP-001-F01-S01-T03",
                 title="FE: Form tạo đơn với catalog picker và tính toán tổng giá",
                 status=ItemStatus.draft, priority=Priority.high,
                 estimated_hours=12, category="frontend"),
            Task(story_id=story1.id, prefix="EP-001-F01-S01-T04",
                 title="QA: Test case tạo đơn — catalog search, validate, submit",
                 status=ItemStatus.draft, priority=Priority.medium,
                 estimated_hours=4, category="qa"),
        ]
        session.add_all(tasks)
        await session.flush()

        await session.commit()

        print(f"[seed] Mock project seeded successfully!")
        print(f"       Project: '{project.name}' (slug: {project.slug})")
        print(f"       Org:     {org.name} (slug: {org.slug})")
        print(f"       Data:")
        print(f"         - 5 stakeholders")
        print(f"         - 4 goals + 9 objectives")
        print(f"         - 6 constraints")
        print(f"         - 7 business requirements")
        print(f"         - 7 business rules")
        print(f"         - 4 actors")
        print(f"         - 9 NFRs")
        print(f"         - 2 flows (10 + 8 actions, full swimlane UML notation)")
        print(f"         - 4 epics, 4 features, 3 stories, 4 tasks")


async def add_member(github_login: str) -> None:
    async with async_session_factory() as session:
        # Resolve user
        result = await session.execute(select(User).where(User.github_login == github_login))
        user = result.scalar_one_or_none()
        if not user:
            print(f"[error] No user found with github_login='{github_login}'")
            print("        Login via GitHub OAuth first, then re-run this command.")
            return

        # Resolve org
        result = await session.execute(select(Organization).where(Organization.slug == ORG_SLUG))
        org = result.scalar_one_or_none()
        if not org:
            print(f"[error] Org '{ORG_SLUG}' not found. Run seed first (no flags).")
            return

        # Add to org if not already member
        result = await session.execute(
            select(OrgMember).where(OrgMember.org_id == org.id, OrgMember.user_id == user.id)
        )
        if not result.scalar_one_or_none():
            session.add(OrgMember(org_id=org.id, user_id=user.id, role="member"))
            await session.flush()
            print(f"[seed] Added {github_login} as org member of '{ORG_SLUG}'")
        else:
            print(f"[skip] {github_login} already in org '{ORG_SLUG}'")

        await session.commit()
        print(f"[done] {github_login} can now access the mock project via the app.")
        print(f"       Org slug:     {ORG_SLUG}")
        print(f"       Project slug: {PROJECT_SLUG}")


if __name__ == "__main__":
    if "--add-member" in sys.argv:
        idx = sys.argv.index("--add-member")
        if idx + 1 >= len(sys.argv):
            print("Usage: seed_mock_project.py --add-member <github_login>")
            sys.exit(1)
        asyncio.run(add_member(sys.argv[idx + 1]))
    else:
        asyncio.run(seed())
