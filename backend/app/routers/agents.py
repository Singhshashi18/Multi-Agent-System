import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.database import get_db
from app.models.schemas import AgentCreateRequest, AgentResponse, AgentUpdateRequest


router = APIRouter(tags=["agents"])


@router.get("/agents")
async def list_agents(db: Session = Depends(get_db)) -> list[AgentResponse]:
    rows = db.query(Agent).order_by(Agent.created_at.desc()).all()
    return [
        AgentResponse(
            id=row.id,
            name=row.name,
            role=row.role,
            system_prompt=row.system_prompt,
            tools=row.tools or [],
            model=row.model,
            temperature=row.temperature,
            expertise_domain=row.expertise_domain,
            communication_style=row.communication_style,
        )
        for row in rows
    ]


@router.post("/agents")
async def create_agent(payload: AgentCreateRequest, db: Session = Depends(get_db)) -> AgentResponse:
    agent_id = payload.id or str(uuid.uuid4())
    if db.query(Agent).filter(Agent.id == agent_id).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent ID already exists")

    clean_name = payload.name.strip()
    clean_role = payload.role.strip()
    if not clean_name or not clean_role:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent name and role are required")

    row = Agent(
        id=agent_id,
        name=clean_name,
        role=clean_role,
        system_prompt=payload.system_prompt,
        tools=payload.tools,
        model=payload.model,
        temperature=payload.temperature,
        expertise_domain=payload.expertise_domain,
        communication_style=payload.communication_style,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return AgentResponse(
        id=row.id,
        name=row.name,
        role=row.role,
        system_prompt=row.system_prompt,
        tools=row.tools or [],
        model=row.model,
        temperature=row.temperature,
        expertise_domain=row.expertise_domain,
        communication_style=row.communication_style,
    )


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str, db: Session = Depends(get_db)) -> dict[str, str]:
    row = db.query(Agent).filter(Agent.id == agent_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    db.delete(row)
    db.commit()
    return {"message": "Agent deleted"}


@router.put("/agents/{agent_id}")
async def update_agent(agent_id: str, payload: AgentUpdateRequest, db: Session = Depends(get_db)) -> AgentResponse:
    row = db.query(Agent).filter(Agent.id == agent_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"] is not None:
        updates["name"] = updates["name"].strip()
    if "role" in updates and updates["role"] is not None:
        updates["role"] = updates["role"].strip()
    for field_name, field_value in updates.items():
        setattr(row, field_name, field_value)

    db.commit()
    db.refresh(row)
    return AgentResponse(
        id=row.id,
        name=row.name,
        role=row.role,
        system_prompt=row.system_prompt,
        tools=row.tools or [],
        model=row.model,
        temperature=row.temperature,
        expertise_domain=row.expertise_domain,
        communication_style=row.communication_style,
    )
