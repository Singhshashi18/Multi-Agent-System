from sqlalchemy import Column, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from app.models.database import Base

JSONType = JSON().with_variant(JSONB, "postgresql")


class Team(Base):
    __tablename__ = "teams"

    id = Column(String(36), primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    pattern = Column(String(80), nullable=False)
    description = Column(Text, nullable=True)
    config = Column(JSONType, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
