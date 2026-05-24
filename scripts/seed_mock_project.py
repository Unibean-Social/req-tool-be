"""
Seed a realistic mock project: "Hệ thống Quản lý Đặt hàng Trực tuyến" (Online Order Management).
Full BRD data + 3 flows with swimlanes covering all UML notation types.

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

from sqlalchemy import select, insert as sa_insert

from app.database import async_session_factory
from app.models.user import User
from app.models.organization import Organization, OrgMember
from app.models.project import Project
from app.models.project_business import (
    ProjectGoal, ProjectGoalObjective, ProjectFlow, ProjectFlowAction,
    ProjectRule, ProjectConstraint, ProjectBusinessRequirement,
    ProjectOutOfScope,
    GoalPriority, ConstraintType, ConstraintSeverity, RuleType,
    OutOfScopeCategory,
    project_flow_action_rules,
)
from app.models.stakeholder import ActorType, InfluenceLevel, Stakeholder
from app.models.actor import Actor
from app.models.nfr import NFR, NFRCategory
from app.models.requirements import Priority
from app.utils.activity.layout import calculate_layout, layout_to_activity_dict, review_positions
from app.config import settings


ORG_SLUG = "fpt-software"
PROJECT_SLUG = "online-order-mgmt"


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
            name="Hệ thống Quản lý Đặt hàng Trực tuyến",
            slug=PROJECT_SLUG,
            description=(
                "Nền tảng đặt hàng B2C dành cho chuỗi cửa hàng bán lẻ, "
                "tích hợp quản lý tồn kho và thanh toán trực tuyến."
            ),
            context=(
                "Công ty hiện xử lý đơn hàng thủ công qua Zalo và điện thoại, gây sai sót và chậm trễ. "
                "Cần số hoá toàn bộ quy trình từ đặt hàng đến giao hàng để cạnh tranh với các nền tảng "
                "thương mại điện tử."
            ),
            problems=[
                "Tỷ lệ sai sót đơn hàng thủ công lên đến 12% mỗi tháng",
                "Không có khả năng theo dõi trạng thái đơn theo thời gian thực",
                "Dữ liệu tồn kho không đồng bộ giữa kênh online và offline",
                "Thời gian xử lý trung bình 2 giờ/đơn do phụ thuộc nhân sự",
                "Không có báo cáo tự động — mọi thứ đều làm thủ công trên Excel",
            ],
            proposed_solutions=[
                "Xây dựng portal đặt hàng online với xác thực OTP và guest checkout",
                "Tích hợp realtime inventory từ hệ thống ERP SAP S/4HANA nội bộ",
                "Dashboard theo dõi đơn hàng cho khách hàng và nhân viên kho vận",
                "Tự động hoá thông báo qua SMS và email tại từng milestone đơn hàng",
                "Module báo cáo với export CSV và biểu đồ doanh thu theo thời gian",
            ],
            start_date=date(2026, 6, 1),
            end_date=date(2026, 12, 31),
            budget=Decimal("450000000"),
            executive_summary=(
                "Hệ thống sẽ thay thế toàn bộ quy trình đặt hàng thủ công hiện tại. "
                "Mục tiêu giảm sai sót xuống dưới 1%, rút ngắn thời gian xử lý đơn từ 2 giờ xuống 15 phút, "
                "và tăng tỉ lệ chuyển đổi trực tuyến lên 35% trong 6 tháng đầu vận hành."
            ),
            roi_notes=(
                "Dự kiến tiết kiệm 2 FTE nhân sự xử lý đơn hàng (~180 triệu VND/năm). "
                "Chi phí đầu tư hoàn vốn sau 8 tháng vận hành. "
                "Tăng trưởng doanh thu kỳ vọng 20% nhờ kênh online."
            ),
        )
        session.add(project)
        await session.flush()

        pid = project.id

        # ── Stakeholders ─────────────────────────────────────────────────────
        sh_kh = Stakeholder(
            project_id=pid, name="Khách hàng", role="Người mua hàng cuối",
            impact_area="Trải nghiệm đặt hàng, thanh toán, theo dõi đơn",
            influence_level=InfluenceLevel.high, actor_type=ActorType.business_actor,
            notes="Đối tượng trực tiếp sử dụng hệ thống. Ưu tiên UX đơn giản, hỗ trợ mobile, thời gian checkout nhanh.",
        )
        sh_kv = Stakeholder(
            project_id=pid, name="Bộ phận Kho vận", role="Quản lý tồn kho, đóng gói và xuất hàng",
            impact_area="Kiểm tra tồn kho, xác nhận xuất kho, theo dõi giao hàng",
            influence_level=InfluenceLevel.high, actor_type=ActorType.business_actor,
            notes="Chịu trách nhiệm xác nhận hàng trước khi giao. Cần interface đơn giản, có thể dùng trên tablet.",
        )
        sh_tc = Stakeholder(
            project_id=pid, name="Bộ phận Tài chính", role="Xử lý thanh toán, hoàn tiền và đối soát",
            impact_area="Xác thực giao dịch, báo cáo doanh thu, quản lý hoàn tiền",
            influence_level=InfluenceLevel.medium, actor_type=ActorType.business_actor,
            notes="Cần audit trail đầy đủ cho mọi giao dịch. Yêu cầu báo cáo tài chính tự động theo ngày.",
        )
        sh_ht = Stakeholder(
            project_id=pid, name="Hệ thống", role="Backend tự động hoá — xử lý logic nghiệp vụ",
            impact_area="Tích hợp ERP, xử lý đơn hàng, gửi thông báo tự động",
            influence_level=InfluenceLevel.high, actor_type=ActorType.business_actor,
            notes="Actor ảo đại diện cho các bước tự động không cần can thiệp người dùng.",
        )
        sh_sm = Stakeholder(
            project_id=pid, name="Sale Manager", role="Quản lý đội bán hàng và duyệt đơn đặc biệt",
            impact_area="Phê duyệt đơn giá trị lớn, báo cáo doanh thu, quản lý khuyến mãi",
            influence_level=InfluenceLevel.medium,
            notes="Duyệt thủ công các đơn vượt giới hạn 100 triệu VND hoặc số lượng > 50 sản phẩm.",
        )
        sh_3pl = Stakeholder(
            project_id=pid, name="Đội vận chuyển (3PL)", role="Đối tác giao hàng chặng cuối",
            impact_area="Nhận hàng từ kho, giao đến khách, cập nhật trạng thái giao hàng",
            influence_level=InfluenceLevel.medium,
            notes="Tích hợp API tracking từ Giao Hàng Nhanh và Giao Hàng Tiết Kiệm.",
        )
        sh_it = Stakeholder(
            project_id=pid, name="IT / DevOps", role="Quản trị hệ thống và vận hành hạ tầng",
            impact_area="Uptime, bảo mật, tích hợp SAP ERP, monitoring",
            influence_level=InfluenceLevel.low,
            notes="Không trực tiếp sử dụng sản phẩm nhưng chịu trách nhiệm vận hành.",
        )
        session.add_all([sh_kh, sh_kv, sh_tc, sh_ht, sh_sm, sh_3pl, sh_it])
        await session.flush()

        # ── System Actors ─────────────────────────────────────────────────────
        session.add_all([
            Actor(project_id=pid, name="Khách hàng (Guest)",
                  role_description="Người dùng chưa đăng ký tài khoản — chỉ có quyền đặt hàng và theo dõi đơn bằng mã đơn"),
            Actor(project_id=pid, name="Khách hàng (Registered)",
                  role_description="Người dùng đã có tài khoản — lưu lịch sử đơn hàng, địa chỉ giao hàng, thanh toán nhanh"),
            Actor(project_id=pid, name="Nhân viên Kho vận",
                  role_description="Staff kho — xác nhận tồn kho, đóng gói, cập nhật trạng thái xuất hàng"),
            Actor(project_id=pid, name="Nhân viên Tài chính",
                  role_description="Staff tài chính — xem và đối soát giao dịch, xử lý hoàn tiền"),
            Actor(project_id=pid, name="Sale Manager",
                  role_description="Quản lý bán hàng — phê duyệt đơn đặc biệt, xem toàn bộ báo cáo doanh thu"),
            Actor(project_id=pid, name="System Admin",
                  role_description="Quản trị viên hệ thống — cấu hình danh mục, quản lý user, xem log hệ thống"),
        ])
        await session.flush()

        # ── Goals ─────────────────────────────────────────────────────────────
        goal1 = ProjectGoal(
            project_id=pid, order=1, priority=GoalPriority.high,
            description="Tăng tỉ lệ chuyển đổi đặt hàng trực tuyến lên 35% trong vòng 6 tháng đầu vận hành",
            success_metric="Tỉ lệ chuyển đổi >= 35% đo bằng Google Analytics, đánh giá mỗi tháng",
            target_date=date(2026, 12, 31),
        )
        goal2 = ProjectGoal(
            project_id=pid, order=2, priority=GoalPriority.high,
            description="Giảm tỉ lệ sai sót xử lý đơn hàng từ 12% xuống dưới 1% trong quý đầu tiên",
            success_metric="Số đơn sai / tổng đơn < 1%, đo hàng tuần qua dashboard nội bộ",
            target_date=date(2026, 9, 30),
        )
        goal3 = ProjectGoal(
            project_id=pid, order=3, priority=GoalPriority.high,
            description="Rút ngắn thời gian từ đặt hàng đến xác nhận giao xuống 15 phút cho 90% đơn hàng",
            success_metric="P90 thời gian xử lý <= 15 phút, đo từ timestamp đặt hàng đến xác nhận kho",
            target_date=date(2026, 12, 31),
        )
        goal4 = ProjectGoal(
            project_id=pid, order=4, priority=GoalPriority.medium,
            description="Đạt Net Promoter Score (NPS) >= 50 sau 3 tháng vận hành",
            success_metric="NPS >= 50 dựa trên khảo sát gửi tự động 7 ngày sau khi giao hàng thành công",
            target_date=date(2026, 12, 31),
        )
        goal5 = ProjectGoal(
            project_id=pid, order=5, priority=GoalPriority.medium,
            description="Giảm chi phí vận hành đơn hàng xuống 30% trong năm đầu thông qua tự động hoá",
            success_metric="Chi phí nhân sự xử lý đơn / tổng đơn giảm 30% so với baseline Q1-2026",
            target_date=date(2026, 12, 31),
        )
        session.add_all([goal1, goal2, goal3, goal4, goal5])
        await session.flush()

        session.add_all([
            ProjectGoalObjective(goal_id=goal1.id, description="Rút ngắn luồng đặt hàng xuống tối đa 4 bước từ chọn sản phẩm đến thanh toán"),
            ProjectGoalObjective(goal_id=goal1.id, description="Thời gian tải trang checkout dưới 2 giây trên mạng 4G"),
            ProjectGoalObjective(goal_id=goal1.id, description="Hỗ trợ ít nhất 3 phương thức thanh toán: thẻ ngân hàng, ví điện tử và COD"),
            ProjectGoalObjective(goal_id=goal1.id, description="Tỉ lệ bỏ giỏ hàng giảm xuống dưới 60%"),
            ProjectGoalObjective(goal_id=goal2.id, description="Xác thực tự động tồn kho trước khi xác nhận bất kỳ đơn hàng nào"),
            ProjectGoalObjective(goal_id=goal2.id, description="Thông báo tức thì cho kho vận khi phát sinh đơn mới"),
            ProjectGoalObjective(goal_id=goal2.id, description="Lưu log đầy đủ mọi thay đổi trạng thái đơn với timestamp và user thực hiện"),
            ProjectGoalObjective(goal_id=goal2.id, description="Tự động phát hiện và cảnh báo đơn hàng trùng lặp trong 5 phút"),
            ProjectGoalObjective(goal_id=goal3.id, description="Tự động hoá bước kiểm tra tồn kho và xác thực thanh toán chạy song song"),
            ProjectGoalObjective(goal_id=goal3.id, description="Cảnh báo tự động khi đơn chờ xử lý quá 10 phút"),
            ProjectGoalObjective(goal_id=goal3.id, description="Tích hợp trực tiếp với ERP để lấy dữ liệu tồn kho không qua bước thủ công"),
            ProjectGoalObjective(goal_id=goal4.id, description="Trang theo dõi đơn hàng realtime cho khách hàng"),
            ProjectGoalObjective(goal_id=goal4.id, description="Giao diện mobile-first, hoạt động tốt trên màn hình 375px"),
            ProjectGoalObjective(goal_id=goal4.id, description="Quy trình huỷ đơn và hoàn tiền hoàn toàn tự phục vụ trong app"),
            ProjectGoalObjective(goal_id=goal5.id, description="Tự động hoá 100% các bước xử lý đơn hàng tiêu chuẩn"),
            ProjectGoalObjective(goal_id=goal5.id, description="Giảm từ 3 FTE xuống còn 1 FTE nhân sự xử lý đơn"),
            ProjectGoalObjective(goal_id=goal5.id, description="Tạo báo cáo tự động hàng ngày không cần can thiệp thủ công"),
        ])
        await session.flush()

        # ── Constraints ───────────────────────────────────────────────────────
        session.add_all([
            ProjectConstraint(project_id=pid, type=ConstraintType.budget, severity=ConstraintSeverity.high,
                description="Tổng ngân sách dự án không vượt 450 triệu VND, bao gồm chi phí phát triển, hạ tầng cloud 24 tháng và license phần mềm bên thứ ba"),
            ProjectConstraint(project_id=pid, type=ConstraintType.timeline, severity=ConstraintSeverity.high,
                description="Phiên bản MVP phải go-live trước ngày 01/09/2026 để sẵn sàng cho mùa mua sắm cuối năm Q4-2026"),
            ProjectConstraint(project_id=pid, type=ConstraintType.technical, severity=ConstraintSeverity.high,
                description="Phải tích hợp với ERP SAP S/4HANA hiện tại thông qua REST API được cung cấp bởi đội IT nội bộ — không được thay thế hoặc bypass ERP"),
            ProjectConstraint(project_id=pid, type=ConstraintType.technical, severity=ConstraintSeverity.high,
                description="Database phải là PostgreSQL 15+. Không được dùng NoSQL cho dữ liệu giao dịch chính. Backup tự động hàng ngày và giữ 30 ngày."),
            ProjectConstraint(project_id=pid, type=ConstraintType.regulatory, severity=ConstraintSeverity.high,
                description="Tuân thủ Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân — có cơ chế xin đồng ý, quyền xoá tài khoản và audit log truy cập dữ liệu cá nhân"),
            ProjectConstraint(project_id=pid, type=ConstraintType.regulatory, severity=ConstraintSeverity.medium,
                description="Lưu trữ dữ liệu giao dịch tài chính tối thiểu 5 năm theo quy định thuế của Bộ Tài chính"),
            ProjectConstraint(project_id=pid, type=ConstraintType.resource, severity=ConstraintSeverity.medium,
                description="Đội phát triển tối đa 5 người (3 backend, 1 frontend, 1 QA) — không thể mở rộng trong năm 2026 do hạn chế ngân sách HR"),
            ProjectConstraint(project_id=pid, type=ConstraintType.technical, severity=ConstraintSeverity.medium,
                description="Hệ thống phải đạt uptime 99.5% theo SLA với nhà cung cấp hosting. RTO <= 1 giờ, RPO <= 15 phút."),
            ProjectConstraint(project_id=pid, type=ConstraintType.budget, severity=ConstraintSeverity.low,
                description="Chi phí vận hành hàng tháng (hosting, SMS, email, cổng thanh toán) không vượt 8 triệu VND trong 12 tháng đầu"),
            ProjectConstraint(project_id=pid, type=ConstraintType.risk, severity=ConstraintSeverity.high,
                description="Tích hợp ERP SAP S/4HANA phụ thuộc đội IT nội bộ — nếu API thay đổi hoặc đội IT bận dự án khác sẽ làm trễ tiến độ tối thiểu 2 sprint"),
            ProjectConstraint(project_id=pid, type=ConstraintType.risk, severity=ConstraintSeverity.medium,
                description="Cổng thanh toán VNPay/MoMo có thể thay đổi chính sách phí hoặc API trong thời gian dự án — cần dự phòng chi phí và thời gian tích hợp lại"),
        ])
        await session.flush()

        # ── Out of Scope ───────────────────────────────────────────────────────
        session.add_all([
            ProjectOutOfScope(project_id=pid, order=1, category=OutOfScopeCategory.feature,
                description="Tính năng quản lý nhà cung cấp (vendor management) — đàm phán hợp đồng, đánh giá nhà cung cấp sẽ được xây dựng ở giai đoạn 2"),
            ProjectOutOfScope(project_id=pid, order=2, category=OutOfScopeCategory.integration,
                description="Tích hợp với hệ thống kế toán nội bộ — đội kế toán vẫn xuất CSV và nhập thủ công vào phần mềm kế toán hiện tại"),
            ProjectOutOfScope(project_id=pid, order=3, category=OutOfScopeCategory.integration,
                description="Tích hợp với các sàn thương mại điện tử (Shopee, Lazada, Tiki) — chỉ phục vụ kênh website riêng của công ty"),
            ProjectOutOfScope(project_id=pid, order=4, category=OutOfScopeCategory.user_group,
                description="Khách hàng doanh nghiệp (B2B) với hợp đồng khung và hạn mức tín dụng — giai đoạn 1 chỉ phục vụ khách hàng cá nhân B2C"),
            ProjectOutOfScope(project_id=pid, order=5, category=OutOfScopeCategory.process,
                description="Quy trình đấu thầu mua hàng và phê duyệt nhà cung cấp mới — chỉ hỗ trợ đặt hàng từ danh mục sản phẩm đã được duyệt sẵn"),
            ProjectOutOfScope(project_id=pid, order=6, category=OutOfScopeCategory.technical,
                description="Mobile native app (iOS/Android) — giai đoạn 1 chỉ hỗ trợ responsive web, tối ưu cho màn hình 375px trở lên"),
            ProjectOutOfScope(project_id=pid, order=7, category=OutOfScopeCategory.feature,
                description="Hệ thống quản lý kho nâng cao (WMS) bao gồm sơ đồ kho, vị trí lưu trữ và tối ưu lộ trình picking — nằm ngoài phạm vi đợt này"),
        ])
        await session.flush()

        # ── Business Requirements ──────────────────────────────────────────────
        session.add_all([
            ProjectBusinessRequirement(project_id=pid, priority=GoalPriority.high, is_critical=True,
                description="Khách hàng có thể đặt hàng mà không cần tạo tài khoản thông qua hình thức guest checkout với chỉ email và số điện thoại"),
            ProjectBusinessRequirement(project_id=pid, priority=GoalPriority.high, is_critical=True,
                description="Hệ thống kiểm tra tồn kho theo thời gian thực từ ERP trước khi xác nhận bất kỳ đơn hàng nào"),
            ProjectBusinessRequirement(project_id=pid, priority=GoalPriority.high, is_critical=False,
                description="Khách hàng nhận thông báo tự động qua SMS và email tại các mốc: đặt thành công, kho xác nhận, đang giao, đã giao"),
            ProjectBusinessRequirement(project_id=pid, priority=GoalPriority.high, is_critical=True,
                description="Hỗ trợ thanh toán qua VNPay, MoMo, ZaloPay và hình thức thanh toán khi nhận hàng COD"),
            ProjectBusinessRequirement(project_id=pid, priority=GoalPriority.medium, is_critical=False,
                description="Cho phép khách hàng tự huỷ đơn trong vòng 30 phút kể từ khi đặt nếu kho chưa xác nhận"),
            ProjectBusinessRequirement(project_id=pid, priority=GoalPriority.high, is_critical=False,
                description="Cung cấp trang theo dõi đơn hàng realtime có thể truy cập bằng mã đơn mà không cần đăng nhập"),
            ProjectBusinessRequirement(project_id=pid, priority=GoalPriority.medium, is_critical=False,
                description="Admin có thể xem và xuất báo cáo đơn hàng theo ngày tuần tháng dưới dạng CSV"),
            ProjectBusinessRequirement(project_id=pid, priority=GoalPriority.low, is_critical=False,
                description="Hệ thống tự động đề xuất sản phẩm thay thế khi sản phẩm đã chọn hết hàng"),
            ProjectBusinessRequirement(project_id=pid, priority=GoalPriority.medium, is_critical=True,
                description="Đơn hàng vượt giới hạn 100 triệu VND hoặc 50 sản phẩm phải được sale manager phê duyệt trước khi xử lý"),
            ProjectBusinessRequirement(project_id=pid, priority=GoalPriority.medium, is_critical=False,
                description="Hỗ trợ áp dụng mã giảm giá và voucher tại bước checkout với validation realtime"),
            ProjectBusinessRequirement(project_id=pid, priority=GoalPriority.low, is_critical=False,
                description="Khách hàng đăng ký có thể lưu tối đa 5 địa chỉ giao hàng và chọn nhanh khi đặt hàng"),
            ProjectBusinessRequirement(project_id=pid, priority=GoalPriority.high, is_critical=True,
                description="Hệ thống tự động huỷ đơn và hoàn trả tồn kho nếu thanh toán online không hoàn tất trong 15 phút"),
        ])
        await session.flush()

        # ── Business Rules ─────────────────────────────────────────────────────
        rule_stock = ProjectRule(
            project_id=pid, code="BR-001", type=RuleType.validation, is_dynamic=True,
            rule_def="Đơn hàng chỉ được xác nhận khi số lượng tồn kho trong ERP >= số lượng đặt. Nếu thiếu hàng hệ thống từ chối ngay và thông báo số lượng còn lại cho khách.",
            source="Nghiệp vụ kho vận — tài liệu WH-001 v2.0",
        )
        rule_payment = ProjectRule(
            project_id=pid, code="BR-002", type=RuleType.validation, is_dynamic=False,
            rule_def="Giao dịch thanh toán phải được cổng thanh toán xác nhận thành công (mã trả về 00) trước khi hệ thống gửi lệnh xuất kho. Timeout 30 giây — nếu quá hạn đơn chuyển sang pending_payment và retry tối đa 2 lần.",
            source="Thoả thuận tích hợp VNPay Merchant v2.1",
        )
        rule_cancel = ProjectRule(
            project_id=pid, code="BR-003", type=RuleType.policy, is_dynamic=False,
            rule_def="Khách hàng chỉ được huỷ đơn trong 30 phút kể từ thời điểm đặt và đơn phải chưa được kho xác nhận (status = confirmed). Sau khi kho xác nhận chỉ sale manager hoặc admin mới có quyền huỷ và phải ghi lý do.",
            source="Chính sách bán hàng v1.0 — phòng Kinh doanh",
        )
        rule_order_limit = ProjectRule(
            project_id=pid, code="BR-004", type=RuleType.constraint, is_dynamic=False,
            rule_def="Mỗi đơn hàng không vượt quá 50 sản phẩm (SKU) hoặc tổng giá trị 100 triệu VND. Đơn vượt giới hạn được chuyển sang trạng thái pending_approval và sale manager nhận thông báo trong 5 phút.",
            source="Quy định quản lý rủi ro tín dụng — phòng Tài chính",
        )
        rule_shipping = ProjectRule(
            project_id=pid, code="BR-005", type=RuleType.calculation, is_dynamic=True,
            rule_def="Phí giao hàng = 0 nếu tổng giá trị đơn >= 500.000 VND. Dưới ngưỡng: 30.000 VND nội thành, 50.000 VND ngoại thành và 80.000 VND tỉnh thành khác. Tính theo địa chỉ giao hàng.",
            source="Bảng phí vận chuyển 3PL Q1-2026",
        )
        rule_auto_cancel = ProjectRule(
            project_id=pid, code="BR-006", type=RuleType.process, is_dynamic=False,
            rule_def="Đơn hàng thanh toán online tự động huỷ và hoàn trả tồn kho ERP nếu không nhận được xác nhận thanh toán trong 15 phút kể từ lúc tạo đơn. Khách nhận email thông báo huỷ và có thể đặt lại.",
            source="Quy trình xử lý đơn hàng v2 — phòng Vận hành",
        )
        rule_otp = ProjectRule(
            project_id=pid, code="BR-007", type=RuleType.policy, is_dynamic=False,
            rule_def="Hệ thống cho phép tối đa 3 lần nhập sai OTP xác thực checkout trong 10 phút. Quá giới hạn sẽ khoá session 30 phút và gửi cảnh báo đến email đăng ký.",
            source="Chính sách bảo mật tài khoản — phòng IT",
        )
        rule_voucher = ProjectRule(
            project_id=pid, code="BR-008", type=RuleType.constraint, is_dynamic=True,
            rule_def="Mã giảm giá chỉ được áp dụng một lần mỗi tài khoản. Voucher một lần sử dụng bị vô hiệu hoá ngay sau khi áp dụng thành công. Không áp dụng đồng thời nhiều mã giảm giá cho một đơn.",
            source="Quy định chương trình khuyến mãi — phòng Marketing",
        )
        rule_refund = ProjectRule(
            project_id=pid, code="BR-009", type=RuleType.policy, is_dynamic=False,
            rule_def="Hoàn tiền cho đơn huỷ sau khi thanh toán: hoàn 100% nếu huỷ trong 30 phút và kho chưa xác nhận. Hoàn 90% nếu kho đã xác nhận nhưng chưa xuất hàng. Không hoàn tiền nếu hàng đã xuất kho.",
            source="Chính sách hoàn tiền v1.2 — phòng Tài chính",
        )
        session.add_all([rule_stock, rule_payment, rule_cancel, rule_order_limit,
                         rule_shipping, rule_auto_cancel, rule_otp, rule_voucher, rule_refund])
        await session.flush()

        # ── NFRs ──────────────────────────────────────────────────────────────
        session.add_all([
            NFR(project_id=pid, category=NFRCategory.performance, priority=Priority.high,
                description="Trang checkout và trang danh sách sản phẩm phải load dưới 2 giây với 500 concurrent users trên kết nối 4G (20Mbps)"),
            NFR(project_id=pid, category=NFRCategory.performance, priority=Priority.high,
                description="API xác nhận tồn kho phải phản hồi trong 500ms ở P99 dưới tải 1000 requests/giây"),
            NFR(project_id=pid, category=NFRCategory.performance, priority=Priority.medium,
                description="Hệ thống xử lý được tối thiểu 200 đơn hàng đồng thời mà không degradation hiệu năng"),
            NFR(project_id=pid, category=NFRCategory.security, priority=Priority.high,
                description="Toàn bộ API endpoints phải yêu cầu xác thực JWT. Token hết hạn sau 24 giờ. Refresh token hết hạn sau 30 ngày."),
            NFR(project_id=pid, category=NFRCategory.security, priority=Priority.high,
                description="Thông tin thẻ thanh toán không được lưu trên hệ thống — tokenize qua cổng thanh toán. Tuân thủ PCI DSS Level 2."),
            NFR(project_id=pid, category=NFRCategory.security, priority=Priority.high,
                description="Mã hoá toàn bộ dữ liệu cá nhân nhạy cảm (số điện thoại, địa chỉ) ở trạng thái lưu trữ bằng AES-256"),
            NFR(project_id=pid, category=NFRCategory.security, priority=Priority.medium,
                description="Rate limiting: tối đa 100 requests/phút/IP cho các endpoint công khai. Tối đa 20 requests/phút cho login và OTP."),
            NFR(project_id=pid, category=NFRCategory.usability, priority=Priority.medium,
                description="Giao diện khách hàng phải đạt điểm Lighthouse Accessibility >= 90. Hỗ trợ đầy đủ keyboard navigation."),
            NFR(project_id=pid, category=NFRCategory.usability, priority=Priority.high,
                description="Toàn bộ luồng đặt hàng phải hoạt động trên màn hình 375px (iPhone SE) không có horizontal scroll"),
            NFR(project_id=pid, category=NFRCategory.reliability, priority=Priority.high,
                description="Uptime hệ thống >= 99.5% mỗi tháng. Bảo trì định kỳ phải thực hiện trong khung 02:00–04:00 và thông báo trước 48 giờ."),
            NFR(project_id=pid, category=NFRCategory.reliability, priority=Priority.high,
                description="Recovery Time Objective (RTO) <= 1 giờ. Recovery Point Objective (RPO) <= 15 phút. Backup tự động hàng ngày lúc 02:00."),
            NFR(project_id=pid, category=NFRCategory.compliance, priority=Priority.high,
                description="Ghi audit log đầy đủ cho mọi thao tác tạo, sửa, xoá đơn hàng và thanh toán — bao gồm user_id, timestamp, IP và action. Lưu trữ 5 năm."),
            NFR(project_id=pid, category=NFRCategory.compliance, priority=Priority.medium,
                description="Cung cấp tính năng xuất và xoá dữ liệu cá nhân theo yêu cầu của người dùng trong vòng 72 giờ theo Nghị định 13/2023/NĐ-CP"),
            NFR(project_id=pid, category=NFRCategory.maintainability, priority=Priority.medium,
                description="Unit test coverage >= 80% cho toàn bộ business logic. Integration test tự động chạy trên CI cho mọi PR."),
            NFR(project_id=pid, category=NFRCategory.maintainability, priority=Priority.low,
                description="Thời gian triển khai phiên bản mới <= 15 phút với zero-downtime deployment sử dụng blue-green strategy"),
        ])
        await session.flush()

        # ── Flows ─────────────────────────────────────────────────────────────
        flow1 = ProjectFlow(
            project_id=pid, code="FLOW-001",
            name="Quy trình Đặt hàng",
            description="Luồng chính từ khi khách hàng chọn sản phẩm đến khi đơn hàng được xác nhận và chuyển sang kho vận xử lý",
        )
        flow2 = ProjectFlow(
            project_id=pid, code="FLOW-002",
            name="Quy trình Xử lý Đơn hàng",
            description="Luồng xử lý nội bộ sau khi đơn được đặt thành công — kiểm tra kho và xác thực thanh toán chạy song song để giảm thời gian xử lý",
        )
        flow3 = ProjectFlow(
            project_id=pid, code="FLOW-003",
            name="Quy trình Xử lý Khiếu nại và Hoàn tiền",
            description="Luồng xử lý khi khách hàng có khiếu nại sau giao hàng — giao hàng sai, hàng lỗi hoặc không nhận được hàng",
        )
        session.add_all([flow1, flow2, flow3])
        await session.flush()

        # ── Flow 1 Actions ────────────────────────────────────────────────────
        # Lane mapping: A1-A2,A5-A7,A9 → lane-kh; A3-A4,A8 → lane-ht; A10 → lane-kv
        actions_f1 = [
            ProjectFlowAction(flow_id=flow1.id, order=1,  actor_id=sh_kh.id,
                description="Khách hàng đăng nhập hoặc tiếp tục với tư cách khách"),
            ProjectFlowAction(flow_id=flow1.id, order=2,  actor_id=sh_kh.id,
                description="Khách hàng tìm kiếm và chọn sản phẩm"),
            ProjectFlowAction(flow_id=flow1.id, order=3,  actor_id=sh_ht.id,
                description="Hệ thống kiểm tra tồn kho theo thời gian thực từ ERP"),
            ProjectFlowAction(flow_id=flow1.id, order=4,  actor_id=sh_ht.id,
                description="Hệ thống thông báo hết hàng và gợi ý sản phẩm thay thế"),
            ProjectFlowAction(flow_id=flow1.id, order=5,  actor_id=sh_kh.id,
                description="Khách hàng thêm sản phẩm vào giỏ hàng"),
            ProjectFlowAction(flow_id=flow1.id, order=6,  actor_id=sh_kh.id,
                description="Khách hàng điền địa chỉ giao hàng và chọn phương thức thanh toán"),
            ProjectFlowAction(flow_id=flow1.id, order=7,  actor_id=sh_kh.id,
                description="Hệ thống tính phí giao hàng và hiển thị tổng đơn hàng"),
            ProjectFlowAction(flow_id=flow1.id, order=8,  actor_id=sh_ht.id,
                description="Thông tin đơn hàng tổng hợp trước thanh toán"),
            ProjectFlowAction(flow_id=flow1.id, order=9,  actor_id=sh_kh.id,
                description="Khách hàng xác nhận đặt hàng và hoàn tất thanh toán"),
            ProjectFlowAction(flow_id=flow1.id, order=10, actor_id=sh_kv.id,
                description="Kho vận nhận lệnh xuất kho và bắt đầu chuẩn bị hàng"),
        ]
        session.add_all(actions_f1)
        await session.flush()

        a = actions_f1
        await session.execute(sa_insert(project_flow_action_rules).values(action_id=a[2].id,  rule_id=rule_stock.id))
        await session.execute(sa_insert(project_flow_action_rules).values(action_id=a[4].id,  rule_id=rule_order_limit.id))
        await session.execute(sa_insert(project_flow_action_rules).values(action_id=a[5].id,  rule_id=rule_voucher.id))
        await session.execute(sa_insert(project_flow_action_rules).values(action_id=a[6].id,  rule_id=rule_shipping.id))
        await session.execute(sa_insert(project_flow_action_rules).values(action_id=a[8].id,  rule_id=rule_otp.id))
        await session.execute(sa_insert(project_flow_action_rules).values(action_id=a[8].id,  rule_id=rule_auto_cancel.id))
        await session.execute(sa_insert(project_flow_action_rules).values(action_id=a[9].id,  rule_id=rule_payment.id))
        await session.flush()

        # ── Flow 1 Swimlane ───────────────────────────────────────────────────
        f1_lane_ids = ["lane-kh", "lane-ht", "lane-kv"]
        f1_lane_titles = {
            "lane-kh": "Khách hàng",
            "lane-ht": "Hệ thống",
            "lane-kv": "Kho vận",
        }
        f1_input = [
            {"id": str(a[0].id),  "lane_id": "lane-kh", "notation": "action",     "order": 1,  "label": "Đăng nhập hoặc guest checkout"},
            {"id": str(a[1].id),  "lane_id": "lane-kh", "notation": "action",     "order": 2,  "label": "Tìm kiếm và chọn sản phẩm"},
            {"id": str(a[2].id),  "lane_id": "lane-ht", "notation": "decision",   "order": 3,  "label": None},
            {"id": str(a[3].id),  "lane_id": "lane-ht", "notation": "action",     "order": 4,  "label": "Thông báo hết hàng & gợi ý"},
            {"id": str(a[4].id),  "lane_id": "lane-kh", "notation": "action",     "order": 5,  "label": "Thêm vào giỏ hàng"},
            {"id": str(a[5].id),  "lane_id": "lane-kh", "notation": "merge",      "order": 6,  "label": None},
            {"id": str(a[6].id),  "lane_id": "lane-kh", "notation": "action",     "order": 7,  "label": "Điền địa chỉ và chọn thanh toán"},
            {"id": str(a[7].id),  "lane_id": "lane-ht", "notation": "objectNode", "order": 8,  "label": "Thông tin đơn hàng"},
            {"id": str(a[8].id),  "lane_id": "lane-kh", "notation": "action",     "order": 9,  "label": "Xác nhận và thanh toán"},
            {"id": str(a[9].id),  "lane_id": "lane-kv", "notation": "action",     "order": 10, "label": "Nhận lệnh và chuẩn bị xuất kho"},
        ]
        layout1 = calculate_layout(f1_input, f1_lane_ids)
        layout1 = await review_positions(
            layout1,
            access_key=settings.aws_access_key_id,
            secret_key=settings.aws_secret_access_key,
            region=settings.aws_region,
            model_id=settings.bedrock_notation_model,
        )
        flow1.swimlane = layout_to_activity_dict(layout1, str(flow1.id), flow1.name)
        for lane in flow1.swimlane["lanes"]:
            lane["title"] = f1_lane_titles.get(lane["id"], lane["id"])

        flow1.swimlane["flows"] = [
            {"id": "e01", "source": "start",      "target": str(a[0].id), "flow_type": "control"},
            {"id": "e02", "source": str(a[0].id), "target": str(a[1].id), "flow_type": "control"},
            {"id": "e03", "source": str(a[1].id), "target": str(a[2].id), "flow_type": "control"},
            {"id": "e04", "source": str(a[2].id), "target": str(a[4].id), "flow_type": "control",
             "guard": "[Còn hàng]", "source_handle": "right"},
            {"id": "e05", "source": str(a[2].id), "target": str(a[3].id), "flow_type": "control",
             "guard": "[Hết hàng]", "source_handle": "bottom"},
            {"id": "e06", "source": str(a[4].id), "target": str(a[5].id), "flow_type": "control"},
            {"id": "e07", "source": str(a[3].id), "target": str(a[5].id), "flow_type": "control",
             "source_handle": "bottom"},
            {"id": "e08", "source": str(a[5].id), "target": str(a[6].id), "flow_type": "control"},
            {"id": "e09", "source": str(a[6].id), "target": str(a[7].id), "flow_type": "object",
             "source_handle": "right"},
            {"id": "e10", "source": str(a[7].id), "target": str(a[8].id), "flow_type": "object",
             "source_handle": "left"},
            {"id": "e11", "source": str(a[8].id), "target": str(a[9].id), "flow_type": "control"},
            {"id": "e12", "source": str(a[9].id), "target": "end",        "flow_type": "control"},
        ]

        # ── Flow 2 Actions ────────────────────────────────────────────────────
        # Lane mapping: B1,B2,B5,B6,B8 → lane-ht; B3,B7 → lane-kv; B4 → lane-tc
        actions_f2 = [
            ProjectFlowAction(flow_id=flow2.id, order=1, actor_id=sh_ht.id,
                description="Hệ thống nhận đơn hàng và khởi tạo quy trình xử lý nội bộ"),
            ProjectFlowAction(flow_id=flow2.id, order=2, actor_id=sh_ht.id,
                description="Hệ thống chia xử lý sang hai nhánh song song"),
            ProjectFlowAction(flow_id=flow2.id, order=3, actor_id=sh_kv.id,
                description="Kho vận kiểm tra hàng thực tế và chuẩn bị xuất kho"),
            ProjectFlowAction(flow_id=flow2.id, order=4, actor_id=sh_tc.id,
                description="Tài chính xác thực giao dịch với cổng thanh toán VNPay"),
            ProjectFlowAction(flow_id=flow2.id, order=5, actor_id=sh_ht.id,
                description="Hệ thống tổng hợp kết quả hai nhánh và xác nhận đơn hàng hợp lệ"),
            ProjectFlowAction(flow_id=flow2.id, order=6, actor_id=sh_ht.id,
                description="Hệ thống cập nhật trạng thái đơn thành đang giao hàng"),
            ProjectFlowAction(flow_id=flow2.id, order=7, actor_id=sh_kv.id,
                description="Kho vận bàn giao hàng cho đơn vị vận chuyển và ghi tracking code"),
            ProjectFlowAction(flow_id=flow2.id, order=8, actor_id=sh_ht.id,
                description="Hệ thống gửi thông tin tracking và thời gian giao dự kiến cho khách hàng"),
        ]
        session.add_all(actions_f2)
        await session.flush()

        b = actions_f2
        await session.execute(sa_insert(project_flow_action_rules).values(action_id=b[0].id, rule_id=rule_order_limit.id))
        await session.execute(sa_insert(project_flow_action_rules).values(action_id=b[2].id, rule_id=rule_stock.id))
        await session.execute(sa_insert(project_flow_action_rules).values(action_id=b[3].id, rule_id=rule_payment.id))
        await session.flush()

        # ── Flow 2 Swimlane (fork/join) ───────────────────────────────────────
        f2_lane_ids = ["lane-ht", "lane-kv", "lane-tc"]
        f2_lane_titles = {
            "lane-ht": "Hệ thống",
            "lane-kv": "Kho vận",
            "lane-tc": "Tài chính",
        }
        f2_input = [
            {"id": str(b[0].id), "lane_id": "lane-ht", "notation": "action", "order": 1, "label": "Nhận và khởi tạo đơn hàng"},
            {"id": str(b[1].id), "lane_id": "lane-ht", "notation": "fork",   "order": 2, "label": None},
            {"id": str(b[2].id), "lane_id": "lane-kv", "notation": "action", "order": 3, "label": "Kiểm tra hàng thực tế"},
            {"id": str(b[3].id), "lane_id": "lane-tc", "notation": "action", "order": 4, "label": "Xác thực giao dịch VNPay"},
            {"id": str(b[4].id), "lane_id": "lane-ht", "notation": "join",   "order": 5, "label": None},
            {"id": str(b[5].id), "lane_id": "lane-ht", "notation": "action", "order": 6, "label": "Xác nhận đơn hàng hợp lệ"},
            {"id": str(b[6].id), "lane_id": "lane-kv", "notation": "action", "order": 7, "label": "Bàn giao cho đơn vị vận chuyển"},
            {"id": str(b[7].id), "lane_id": "lane-ht", "notation": "action", "order": 8, "label": "Gửi tracking cho khách hàng"},
        ]
        layout2 = calculate_layout(f2_input, f2_lane_ids)
        layout2 = await review_positions(
            layout2,
            access_key=settings.aws_access_key_id,
            secret_key=settings.aws_secret_access_key,
            region=settings.aws_region,
            model_id=settings.bedrock_notation_model,
        )
        flow2.swimlane = layout_to_activity_dict(layout2, str(flow2.id), flow2.name)
        for lane in flow2.swimlane["lanes"]:
            lane["title"] = f2_lane_titles.get(lane["id"], lane["id"])

        flow2.swimlane["flows"] = [
            {"id": "f01", "source": "start",      "target": str(b[0].id), "flow_type": "control"},
            {"id": "f02", "source": str(b[0].id), "target": str(b[1].id), "flow_type": "control"},
            {"id": "f03", "source": str(b[1].id), "target": str(b[2].id), "flow_type": "control",
             "source_handle": "bottom_left"},
            {"id": "f04", "source": str(b[1].id), "target": str(b[3].id), "flow_type": "control",
             "source_handle": "bottom_right"},
            {"id": "f05", "source": str(b[2].id), "target": str(b[4].id), "flow_type": "control",
             "target_handle": "top_left"},
            {"id": "f06", "source": str(b[3].id), "target": str(b[4].id), "flow_type": "control",
             "target_handle": "top_right"},
            {"id": "f07", "source": str(b[4].id), "target": str(b[5].id), "flow_type": "control"},
            {"id": "f08", "source": str(b[5].id), "target": str(b[6].id), "flow_type": "control"},
            {"id": "f09", "source": str(b[6].id), "target": str(b[7].id), "flow_type": "control"},
            {"id": "f10", "source": str(b[7].id), "target": "end",        "flow_type": "control"},
        ]

        # ── Flow 3 Actions ────────────────────────────────────────────────────
        # Lane mapping: C1 → lane-kh; C2,C3,C7,C8,C9 → lane-ht; C4,C6 → lane-kv; C5 → lane-tc
        actions_f3 = [
            ProjectFlowAction(flow_id=flow3.id, order=1, actor_id=sh_kh.id,
                description="Khách hàng gửi yêu cầu khiếu nại kèm ảnh minh chứng"),
            ProjectFlowAction(flow_id=flow3.id, order=2, actor_id=sh_ht.id,
                description="Hệ thống ghi nhận khiếu nại và tạo ticket hỗ trợ"),
            ProjectFlowAction(flow_id=flow3.id, order=3, actor_id=sh_ht.id,
                description="Hệ thống kiểm tra loại khiếu nại để định tuyến xử lý"),
            ProjectFlowAction(flow_id=flow3.id, order=4, actor_id=sh_kv.id,
                description="Kho vận xác nhận lỗi xuất hàng và chuẩn bị hàng đổi trả"),
            ProjectFlowAction(flow_id=flow3.id, order=5, actor_id=sh_tc.id,
                description="Tài chính xử lý hoàn tiền theo chính sách"),
            ProjectFlowAction(flow_id=flow3.id, order=6, actor_id=sh_kv.id,
                description="Kho vận điều phối lấy hàng lỗi và giao hàng đúng"),
            ProjectFlowAction(flow_id=flow3.id, order=7, actor_id=sh_ht.id,
                description="Hệ thống hợp nhất kết quả xử lý và cập nhật trạng thái ticket"),
            ProjectFlowAction(flow_id=flow3.id, order=8, actor_id=sh_ht.id,
                description="Hệ thống đóng ticket và gửi email xác nhận cho khách hàng"),
            ProjectFlowAction(flow_id=flow3.id, order=9, actor_id=sh_ht.id,
                description="Hệ thống gửi khảo sát đánh giá chất lượng xử lý khiếu nại"),
        ]
        session.add_all(actions_f3)
        await session.flush()

        c = actions_f3
        await session.execute(sa_insert(project_flow_action_rules).values(action_id=c[2].id, rule_id=rule_cancel.id))
        await session.execute(sa_insert(project_flow_action_rules).values(action_id=c[4].id, rule_id=rule_refund.id))
        await session.flush()

        # ── Flow 3 Swimlane (decision → parallel paths → merge) ───────────────
        f3_lane_ids = ["lane-kh", "lane-ht", "lane-kv", "lane-tc"]
        f3_lane_titles = {
            "lane-kh": "Khách hàng",
            "lane-ht": "Hệ thống",
            "lane-kv": "Kho vận",
            "lane-tc": "Tài chính",
        }
        f3_input = [
            {"id": str(c[0].id), "lane_id": "lane-kh", "notation": "action",   "order": 1, "label": "Gửi khiếu nại kèm minh chứng"},
            {"id": str(c[1].id), "lane_id": "lane-ht", "notation": "action",   "order": 2, "label": "Ghi nhận & tạo ticket hỗ trợ"},
            {"id": str(c[2].id), "lane_id": "lane-ht", "notation": "decision", "order": 3, "label": "Loại khiếu nại?"},
            {"id": str(c[3].id), "lane_id": "lane-kv", "notation": "action",   "order": 4, "label": "Xác nhận lỗi & chuẩn bị đổi trả"},
            {"id": str(c[4].id), "lane_id": "lane-tc", "notation": "action",   "order": 5, "label": "Xử lý hoàn tiền"},
            {"id": str(c[5].id), "lane_id": "lane-kv", "notation": "action",   "order": 6, "label": "Lấy hàng lỗi & giao đúng"},
            {"id": str(c[6].id), "lane_id": "lane-ht", "notation": "merge",    "order": 7, "label": None},
            {"id": str(c[7].id), "lane_id": "lane-ht", "notation": "action",   "order": 8, "label": "Đóng ticket & gửi xác nhận"},
            {"id": str(c[8].id), "lane_id": "lane-ht", "notation": "action",   "order": 9, "label": "Gửi khảo sát chất lượng"},
        ]
        layout3 = calculate_layout(f3_input, f3_lane_ids)
        layout3 = await review_positions(
            layout3,
            access_key=settings.aws_access_key_id,
            secret_key=settings.aws_secret_access_key,
            region=settings.aws_region,
            model_id=settings.bedrock_notation_model,
        )
        flow3.swimlane = layout_to_activity_dict(layout3, str(flow3.id), flow3.name)
        for lane in flow3.swimlane["lanes"]:
            lane["title"] = f3_lane_titles.get(lane["id"], lane["id"])

        flow3.swimlane["flows"] = [
            {"id": "g01", "source": "start",      "target": str(c[0].id), "flow_type": "control"},
            {"id": "g02", "source": str(c[0].id), "target": str(c[1].id), "flow_type": "control"},
            {"id": "g03", "source": str(c[1].id), "target": str(c[2].id), "flow_type": "control"},
            {"id": "g04", "source": str(c[2].id), "target": str(c[3].id), "flow_type": "control",
             "guard": "[Lỗi xuất hàng]", "source_handle": "bottom"},
            {"id": "g05", "source": str(c[2].id), "target": str(c[4].id), "flow_type": "control",
             "guard": "[Hoàn tiền]", "source_handle": "right"},
            {"id": "g06", "source": str(c[3].id), "target": str(c[5].id), "flow_type": "control"},
            {"id": "g07", "source": str(c[4].id), "target": str(c[6].id), "flow_type": "control"},
            {"id": "g08", "source": str(c[5].id), "target": str(c[6].id), "flow_type": "control"},
            {"id": "g09", "source": str(c[6].id), "target": str(c[7].id), "flow_type": "control"},
            {"id": "g10", "source": str(c[7].id), "target": str(c[8].id), "flow_type": "control"},
            {"id": "g11", "source": str(c[8].id), "target": "end",        "flow_type": "control"},
        ]
        await session.flush()

        await session.commit()

        print(f"[seed] Mock project seeded successfully!")
        print(f"       Project: '{project.name}' (slug: {project.slug})")
        print(f"       Org:     {org.name} (slug: {org.slug})")
        print(f"       Data:")
        print(f"         - 7 stakeholders (4 business actors, 3 others)")
        print(f"         - 6 system actors")
        print(f"         - 5 goals + 17 objectives")
        print(f"         - 11 constraints")
        print(f"         - 7 out-of-scope items")
        print(f"         - 12 business requirements")
        print(f"         - 9 business rules")
        print(f"         - 15 NFRs")
        print(f"         - 3 flows (10 + 8 + 9 actions, full UML swimlane notation)")


async def add_member(github_login: str) -> None:
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.github_login == github_login))
        user = result.scalar_one_or_none()
        if not user:
            print(f"[error] No user found with github_login='{github_login}'")
            print("        Login via GitHub OAuth first, then re-run this command.")
            return

        result = await session.execute(select(Organization).where(Organization.slug == ORG_SLUG))
        org = result.scalar_one_or_none()
        if not org:
            print(f"[error] Org '{ORG_SLUG}' not found. Run seed first (no flags).")
            return

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
