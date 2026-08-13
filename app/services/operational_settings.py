from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.models import OperationalSetting, User


class RuntimeControls(BaseModel):
    ingestion_enabled: bool = True
    ingestion_interval_minutes: int = Field(default=30, ge=5, le=1440)
    ai_processing_enabled: bool = True
    translations_enabled: bool = True
    analytics_collection_enabled: bool = False
    ongoing_topics_enabled: bool = True
    ongoing_auto_attach_enabled: bool = True
    maintenance_enabled: bool = False
    maintenance_message_ar: str = Field(default="", max_length=500)
    maintenance_message_en: str = Field(default="", max_length=500)


SETTING_KEY = "runtime_controls"


def get_runtime_controls(db: Session) -> RuntimeControls:
    row = db.get(OperationalSetting, SETTING_KEY)
    if row is None:
        return RuntimeControls()
    try:
        return RuntimeControls.model_validate(row.value)
    except ValidationError:
        return RuntimeControls()


def update_runtime_controls(
    db: Session,
    controls: RuntimeControls,
    actor: User,
) -> OperationalSetting:
    row = db.get(OperationalSetting, SETTING_KEY)
    if row is None:
        row = OperationalSetting(key=SETTING_KEY, value={})
        db.add(row)
    row.value = controls.model_dump()
    row.revision = (row.revision or 0) + 1
    row.updated_by_id = actor.id
    db.flush()
    return row


def public_runtime_state(db: Session) -> dict[str, Any]:
    controls = get_runtime_controls(db)
    return {
        "ongoing_topics_enabled": controls.ongoing_topics_enabled,
        "maintenance_enabled": controls.maintenance_enabled,
        "maintenance_message_ar": controls.maintenance_message_ar,
        "maintenance_message_en": controls.maintenance_message_en,
    }
