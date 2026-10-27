from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None
    action: str
    entity_type: str | None
    entity_id: int | None
    ip: str | None
    created_at: datetime
