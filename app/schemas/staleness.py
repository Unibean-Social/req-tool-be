import uuid
from datetime import datetime

from pydantic import BaseModel


class StalenessWarningItem(BaseModel):
    item_type: str
    item_id: uuid.UUID
    title: str
    updated_at: datetime
    stale_days: int
