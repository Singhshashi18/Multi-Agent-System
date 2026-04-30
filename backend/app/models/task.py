from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from app.models.database import Base

JSONType = JSON().with_variant(JSONB, "postgresql")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True, index=True)
    team_id = Column(String(36), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    framework = Column(String(20), nullable=False)
    task_description = Column(Text, nullable=False)
    status = Column(String(40), nullable=False, default="pending")
    current_phase = Column(String(80), nullable=False, default="created")
    final_output = Column(Text, nullable=True)
    metadata_json = Column("metadata", JSONType, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class TaskMessage(Base):
    __tablename__ = "task_messages"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    from_agent = Column(String(120), nullable=False)
    to_agent = Column(String(120), nullable=False)
    message_type = Column(String(40), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TaskTimelineEvent(Base):
    __tablename__ = "task_timeline_events"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_name = Column(String(120), nullable=False)
    event_type = Column(String(40), nullable=False)
    description = Column(Text, nullable=False)
    metadata_json = Column("metadata", JSONType, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
