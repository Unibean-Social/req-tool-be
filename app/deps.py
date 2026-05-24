import uuid
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.core.security import decode_token
from app.models.user import User
from app.services.sync_service import SyncService
from app.services.github_service import GithubService
from app.services.auth_service import AuthService
from app.services.requirements.epic_service import EpicService
from app.services.requirements.feature_service import FeatureService
from app.services.requirements.story_service import StoryService
from app.services.requirements.task_service import TaskService
from app.services.organization_service import OrgService
from app.services.project_service import ProjectService
from app.services.actor_service import ActorService
from app.services.stakeholder_service import StakeholderService
from app.services.nfr_service import NFRService
from app.services.project_business_service import ProjectBusinessService
from app.services.estimate_service import EstimateService
from app.services.staleness_service import StalenessService
from app.services.brd_export_service import BRDExportService
from app.services.context_diagram_service import ContextDiagramService

bearer = HTTPBearer()


async def current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token không hợp lệ hoặc đã hết hạn")

    user_id = payload.get("sub")
    try:
        uid = uuid.UUID(user_id)
    except (TypeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Subject của token không hợp lệ")
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Không tìm thấy người dùng hoặc tài khoản đã bị vô hiệu hóa")
    return user


async def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Yêu cầu quyền admin")
    return user


def get_sync_service(db: AsyncSession = Depends(get_db)) -> SyncService:
    return SyncService(db)


def get_github_service(db: AsyncSession = Depends(get_db)) -> GithubService:
    return GithubService(db)


def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(db)


def get_epic_service(db: AsyncSession = Depends(get_db)) -> EpicService:
    return EpicService(db)


def get_feature_service(db: AsyncSession = Depends(get_db)) -> FeatureService:
    return FeatureService(db)


def get_story_service(db: AsyncSession = Depends(get_db)) -> StoryService:
    return StoryService(db)


def get_task_service(db: AsyncSession = Depends(get_db)) -> TaskService:
    return TaskService(db)


def get_org_service(db: AsyncSession = Depends(get_db)) -> OrgService:
    return OrgService(db)


def get_project_service(db: AsyncSession = Depends(get_db)) -> ProjectService:
    return ProjectService(db)


def get_actor_service(db: AsyncSession = Depends(get_db)) -> ActorService:
    return ActorService(db)


def get_stakeholder_service(db: AsyncSession = Depends(get_db)) -> StakeholderService:
    return StakeholderService(db)


def get_nfr_service(db: AsyncSession = Depends(get_db)) -> NFRService:
    return NFRService(db)


def get_project_business_service(db: AsyncSession = Depends(get_db)) -> ProjectBusinessService:
    return ProjectBusinessService(db)


def get_estimate_service(db: AsyncSession = Depends(get_db)) -> EstimateService:
    return EstimateService(db)


def get_staleness_service(db: AsyncSession = Depends(get_db)) -> StalenessService:
    return StalenessService(db)


def get_brd_export_service(db: AsyncSession = Depends(get_db)) -> BRDExportService:
    return BRDExportService(db)


def get_context_diagram_service(db: AsyncSession = Depends(get_db)) -> ContextDiagramService:
    return ContextDiagramService(db)
