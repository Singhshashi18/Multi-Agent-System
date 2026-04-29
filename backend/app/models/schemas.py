from enum import Enum
from pydantic import BaseModel, Field


class FrameworkType(str, Enum):
    LANGGRAPH = "langgraph"
    CREWAI = "crewai"


class AgentConfig(BaseModel):
    id: str
    name: str
    role: str
    system_prompt: str
    tools: list[str] = Field(default_factory=list)
    model: str = "gpt-4o-mini"
    temperature: float = 0.2
    expertise_domain: str = "general"
    communication_style: str = "professional"


class TeamConfig(BaseModel):
    id: str
    name: str
    pattern: str
    agents: list[AgentConfig]


class TaskCreateRequest(BaseModel):
    team_id: str
    task_description: str
    framework: FrameworkType = FrameworkType.LANGGRAPH


class AgentBase(BaseModel):
    name: str
    role: str
    system_prompt: str
    tools: list[str] = Field(default_factory=list)
    model: str = "gpt-4o-mini"
    temperature: float = 0.2
    expertise_domain: str = "general"
    communication_style: str = "professional"


class AgentCreateRequest(AgentBase):
    id: str | None = None


class AgentUpdateRequest(BaseModel):
    name: str | None = None
    role: str | None = None
    system_prompt: str | None = None
    tools: list[str] | None = None
    model: str | None = None
    temperature: float | None = None
    expertise_domain: str | None = None
    communication_style: str | None = None


class AgentResponse(AgentBase):
    id: str


class TeamBase(BaseModel):
    name: str
    pattern: str
    description: str | None = None
    agent_ids: list[str] = Field(default_factory=list)
    config: dict = Field(default_factory=dict)


class TeamCreateRequest(TeamBase):
    id: str | None = None


class TeamUpdateRequest(BaseModel):
    name: str | None = None
    pattern: str | None = None
    description: str | None = None
    agent_ids: list[str] | None = None
    config: dict | None = None


class TeamResponse(TeamBase):
    id: str


class TaskStatus(str, Enum):
    QUEUED = "queued"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskResponse(BaseModel):
    id: str
    team_id: str
    framework: FrameworkType
    task_description: str
    status: TaskStatus
    current_phase: str
    final_output: str | None = None
    metadata: dict = Field(default_factory=dict)


class TaskMessageResponse(BaseModel):
    id: int
    task_id: str
    from_agent: str
    to_agent: str
    message_type: str
    content: str
    created_at: str


class TaskTimelineResponse(BaseModel):
    id: int
    task_id: str
    agent_name: str
    event_type: str
    description: str
    metadata: dict = Field(default_factory=dict)
    created_at: str


class TaskCompareRequest(BaseModel):
    task_description: str | None = None


class DebateRunRequest(BaseModel):
    team_id: str
    task_description: str
    rounds: int = 3
    framework: FrameworkType = FrameworkType.LANGGRAPH


class SignupRequest(BaseModel):
    full_name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, str]
