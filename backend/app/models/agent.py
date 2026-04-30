from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Table, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from app.models.database import Base

JSONType = JSON().with_variant(JSONB, "postgresql")


team_agents = Table(
    "team_agents",
    Base.metadata,
    Column("team_id", String(36), ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True),
    Column("agent_id", String(36), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
)


class Agent(Base):
    __tablename__ = "agents"

    id = Column(String(36), primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    role = Column(String(255), nullable=False)
    system_prompt = Column(Text, nullable=False)
    tools = Column(JSONType, nullable=False, default=list)
    model = Column(String(120), nullable=False, default="gpt-4o-mini")
    temperature = Column(Float, nullable=False, default=0.2)
    expertise_domain = Column(String(120), nullable=False, default="general")
    communication_style = Column(String(120), nullable=False, default="professional")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AgentPerformance(Base):
    __tablename__ = "agent_performance"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True)
    quality_score = Column(Float, nullable=False, default=0.0)
    response_time_ms = Column(Integer, nullable=False, default=0)
    revision_rate = Column(Float, nullable=False, default=0.0)
    contribution_score = Column(Float, nullable=False, default=0.0)
    token_usage = Column(Integer, nullable=False, default=0)
    error_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
